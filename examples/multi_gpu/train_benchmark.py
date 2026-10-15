"""Validate synchronous GPU training and time the same global batch on 1+ GPUs.

Run directly for one GPU, or with torchrun --standalone --nproc_per_node=2.
Synthetic data stays on the GPUs so the benchmark measures training and
communication rather than storage/download performance. Requires only PyTorch.
"""
import argparse
from datetime import timedelta
import json
import os
from pathlib import Path
import statistics
import time

import torch
from torch import distributed as dist, nn
from torch.nn.parallel import DistributedDataParallel


class ConvClassifier(nn.Module):
    def __init__(self, width):
        super().__init__()
        layers = []
        previous = 3
        for channels in (width, width * 2, width * 4):
            layers.extend([
                nn.Conv2d(previous, channels, 3, padding=1), nn.ReLU(),
                nn.Conv2d(channels, channels, 3, padding=1), nn.ReLU(),
                nn.MaxPool2d(2),
            ])
            previous = channels
        self.features = nn.Sequential(*layers, nn.AdaptiveAvgPool2d(1))
        self.classifier = nn.Linear(previous, 10)

    def forward(self, inputs):
        return self.classifier(self.features(inputs).flatten(1))


def verify_collectives_and_gradients(device, world, rank, distributed):
    total = torch.tensor(float(rank + 1), device=device)
    if distributed:
        dist.all_reduce(total)
    assert total.item() == world * (world + 1) / 2
    model = nn.Linear(4, 1, bias=False).to(device)
    nn.init.zeros_(model.weight)
    if distributed:
        model = DistributedDataParallel(model, device_ids=[device.index])
    inputs = torch.full((8, 4), float(rank + 1), device=device)
    loss = (model(inputs) - 1).square().mean()
    loss.backward()
    parameter = next(model.parameters())
    expected_gradient = -(world + 1)
    assert torch.allclose(parameter.grad, torch.full_like(parameter.grad, expected_gradient))
    torch.optim.SGD(model.parameters(), lr=0.1).step()
    expected_weight = (world + 1) * 0.1
    assert torch.allclose(parameter, torch.full_like(parameter, expected_weight))
    return {"all_reduce_sum": total.item(), "averaged_gradient": parameter.grad[0, 0].item(),
            "weight_after_step": parameter[0, 0].item(), "passed": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--global-batch", type=int, default=64)
    parser.add_argument("--image-size", type=int, default=64)
    parser.add_argument("--width", type=int, default=32)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--backend", choices=("nccl", "gloo"), default="nccl")
    parser.add_argument("--output", type=Path, default=Path("training-result.json"))
    parser.add_argument("--checkpoint", type=Path)
    args = parser.parse_args()
    world = int(os.environ.get("WORLD_SIZE", "1"))
    rank = int(os.environ.get("RANK", "0"))
    local_rank = int(os.environ.get("LOCAL_RANK", "0"))
    distributed = world > 1
    assert torch.cuda.is_available(), "CUDA is required"
    assert torch.cuda.device_count() >= world, "Request all GPUs in one instance"
    assert args.global_batch > 0 and args.global_batch % world == 0
    assert min(args.image_size, args.width, args.warmup, args.steps, args.trials) > 0
    torch.set_num_threads(2)
    torch.cuda.set_device(local_rank)
    device = torch.device("cuda", local_rank)
    if distributed:
        dist.init_process_group(args.backend, timeout=timedelta(seconds=120))
    try:
        collective = verify_collectives_and_gradients(device, world, rank, distributed)
        print(json.dumps({"event": "rank_ready", "rank": rank, "device": local_rank,
                          "gpu": torch.cuda.get_device_name(local_rank), "collectives": collective}), flush=True)
        torch.manual_seed(20261011)
        torch.backends.cudnn.benchmark = True
        model = ConvClassifier(args.width).to(device)
        if distributed:
            model = DistributedDataParallel(model, device_ids=[local_rank])
        # Identical global data and labels, partitioned without overlap by rank.
        generator = torch.Generator().manual_seed(1011)
        all_inputs = torch.randn(args.global_batch, 3, args.image_size, args.image_size, generator=generator)
        all_targets = torch.randint(0, 10, (args.global_batch,), generator=generator)
        local_batch = args.global_batch // world
        start = rank * local_batch
        inputs = all_inputs[start:start + local_batch].to(device)
        targets = all_targets[start:start + local_batch].to(device)
        del all_inputs, all_targets
        optimizer = torch.optim.SGD(model.parameters(), lr=0.05, momentum=0.9)
        criterion = nn.CrossEntropyLoss()

        def mean_loss():
            with torch.no_grad():
                value = criterion(model(inputs), targets)
                if distributed:
                    dist.all_reduce(value)
                    value /= world
                return value.item()

        def step():
            optimizer.zero_grad(set_to_none=True)
            loss = criterion(model(inputs), targets)
            loss.backward()
            optimizer.step()

        initial_loss = mean_loss()
        for _ in range(args.warmup):
            step()
        durations = []
        for trial in range(args.trials):
            torch.cuda.synchronize()
            if distributed:
                dist.barrier()
            started = time.perf_counter()
            for _ in range(args.steps):
                step()
            torch.cuda.synchronize()
            elapsed = torch.tensor(time.perf_counter() - started, device=device, dtype=torch.float64)
            if distributed:
                dist.all_reduce(elapsed, op=dist.ReduceOp.MAX)
            durations.append(elapsed.item())
            if rank == 0:
                print(json.dumps({"event": "trial_finished", "trial": trial + 1, "seconds": durations[-1]}), flush=True)
        final_loss = mean_loss()
        assert torch.isfinite(torch.tensor(final_loss)), "Training produced a nonfinite loss"
        assert final_loss < initial_loss, "Expected loss to decrease on the fixed synthetic batch"
        module = model.module if distributed else model
        flat = torch.cat([parameter.detach().flatten() for parameter in module.parameters()])
        difference = torch.zeros((), device=device)
        if distributed:
            reference = flat.clone()
            dist.broadcast(reference, src=0)
            difference = (flat - reference).abs().max()
            dist.all_reduce(difference, op=dist.ReduceOp.MAX)
            assert difference.item() == 0, "Ranks have different trained weights"
        if rank == 0:
            median = statistics.median(durations)
            result = {
                "world_size": world, "visible_gpus": torch.cuda.device_count(),
                "gpu_names": [torch.cuda.get_device_name(index) for index in range(torch.cuda.device_count())],
                "pytorch": torch.__version__, "cuda_runtime": torch.version.cuda,
                "nccl_version": list(torch.cuda.nccl.version()),
                "backend": args.backend if distributed else "single", "precision": "float32",
                "global_batch": args.global_batch, "batch_per_gpu": local_batch,
                "image_size": args.image_size, "width": args.width,
                "parameter_count": sum(parameter.numel() for parameter in module.parameters()),
                "steps_per_trial": args.steps, "warmup_steps": args.warmup,
                "trial_seconds": durations, "median_seconds": median,
                "median_step_ms": median / args.steps * 1000,
                "samples_per_second": args.global_batch * args.steps / median,
                "initial_loss": initial_loss, "final_loss": final_loss,
                "all_ranks_weight_max_difference": difference.item(),
                "collective_and_gradient_check": collective,
                "max_allocated_mb_rank0": torch.cuda.max_memory_allocated() / 1024**2,
                "synthetic_gpu_resident_data": True,
            }
            if args.checkpoint:
                args.checkpoint.parent.mkdir(parents=True, exist_ok=True)
                state = {name: value.cpu() for name, value in module.state_dict().items()}
                torch.save(state, args.checkpoint)
                restored = ConvClassifier(args.width)
                restored.load_state_dict(torch.load(args.checkpoint, map_location="cpu"))
                result["checkpoint_saved_and_reloaded"] = True
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(result), flush=True)
    finally:
        if distributed:
            dist.destroy_process_group()


if __name__ == "__main__":
    main()
