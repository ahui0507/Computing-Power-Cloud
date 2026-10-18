"""Dense Tensor Core calibration and bounded single/multi-GPU training stress."""

import argparse
from contextlib import nullcontext
from datetime import timedelta, datetime, timezone
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

import torch
from torch import distributed as dist, nn
from torch.nn.parallel import DistributedDataParallel as DDP


def emit(**record):
    print(json.dumps(record), flush=True)


def save(path, value):
    path = Path(path)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(path)


class DenseModel(nn.Module):
    def __init__(self, width, depth):
        super().__init__()
        layers = []
        for index in range(depth):
            layers.append(nn.Linear(width, width, bias=False))
            if index != depth - 1:
                layers.append(nn.ReLU())
        self.layers = nn.Sequential(*layers)

    def forward(self, inputs):
        return self.layers(inputs)


def initialize():
    rank = int(os.environ.get("RANK", "0"))
    local_rank = int(os.environ.get("LOCAL_RANK", "0"))
    world = int(os.environ.get("WORLD_SIZE", "1"))
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA required")
    torch.cuda.set_device(local_rank)
    torch.set_num_threads(2)
    if "A100" not in torch.cuda.get_device_name(local_rank):
        raise RuntimeError("This benchmark expects A100")
    if world > 1:
        dist.init_process_group("nccl", timeout=timedelta(seconds=90))
    return rank, world, torch.device("cuda", local_rank)


def calibrate(output):
    _, _, device = initialize()
    results = []
    for precision in ("bf16", "tf32"):
        torch.backends.cuda.matmul.allow_tf32 = precision == "tf32"
        dtype = torch.bfloat16 if precision == "bf16" else torch.float32
        for size in (4096, 8192, 12288, 16384):
            inputs = torch.randn(size, size, device=device, dtype=dtype)
            weights = torch.randn_like(inputs)
            product = torch.empty_like(inputs)
            for _ in range(5):
                torch.mm(inputs, weights, out=product)
            torch.cuda.synchronize()
            trials = []
            for _ in range(3):
                start, end = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
                start.record()
                for _ in range(10):
                    torch.mm(inputs, weights, out=product)
                end.record()
                end.synchronize()
                seconds = start.elapsed_time(end) / 1000
                trials.append(2 * size ** 3 * 10 / seconds / 1e12)
            if not torch.isfinite(product).all().item():
                raise RuntimeError("Nonfinite GEMM result")
            record = {"precision": precision, "size": size, "trials_tflops": trials,
                      "median_tflops": statistics.median(trials)}
            results.append(record)
            emit(event="gemm", **record)
            del inputs, weights, product
            torch.cuda.empty_cache()
    save(output, {"gpu": torch.cuda.get_device_name(device), "results": results,
                  "flop_convention": "dense GEMM: 2*N^3; excludes sparsity",
                  "timing": "CUDA events, warmup excluded, median of 3 trials"})


def collective_check(device, world):
    rank = dist.get_rank() if world > 1 else 0
    probe = torch.tensor(float(rank + 1), device=device)
    if world > 1:
        dist.all_reduce(probe)
    expected = world * (world + 1) / 2
    if probe.item() != expected:
        raise RuntimeError("Collective numerical check failed")
    tiny = nn.Linear(4, 1, bias=False).to(device)
    nn.init.zeros_(tiny.weight)
    model = DDP(tiny, device_ids=[device.index]) if world > 1 else tiny
    loss = (model(torch.full((8, 4), float(rank + 1), device=device)) - 1).square().mean()
    loss.backward()
    gradient = tiny.weight.grad
    if not torch.allclose(gradient, torch.full_like(gradient, -(world + 1))):
        raise RuntimeError("DDP gradient averaging failed")
    return {"all_reduce_sum": probe.item(), "expected_sum": expected,
            "averaged_gradient": gradient[0, 0].item(), "passed": True}


def train(args):
    rank, world, device = initialize()
    torch.manual_seed(1234)
    torch.backends.cuda.matmul.allow_tf32 = False
    collective = collective_check(device, world)
    base = DenseModel(args.width, args.depth).to(device)
    model = DDP(base, device_ids=[device.index], bucket_cap_mb=64,
                gradient_as_bucket_view=True) if world > 1 else base
    optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
    generator = torch.Generator(device=device).manual_seed(9000 + rank)
    inputs = torch.randn(args.batch, args.width, device=device, dtype=torch.bfloat16,
                         generator=generator)
    target = torch.randn_like(inputs) * 0.1
    initial = next(base.parameters()).detach().clone()
    flops_per_microstep = (6 * args.depth - 2) * args.batch * args.width ** 2
    count = sum(parameter.numel() for parameter in base.parameters())

    def step():
        optimizer.zero_grad(set_to_none=True)
        for micro in range(args.accumulation):
            synchronize = micro == args.accumulation - 1
            context = model.no_sync() if world > 1 and not synchronize else nullcontext()
            with context:
                with torch.autocast("cuda", dtype=torch.bfloat16):
                    outputs = model(inputs)
                    loss = (outputs.float() - target.float()).square().mean()
                (loss / args.accumulation).backward()
        optimizer.step()
        return loss.detach()

    for _ in range(4):
        step()
    torch.cuda.synchronize()
    if world > 1:
        dist.barrier()
    torch.cuda.reset_peak_memory_stats()
    started = time.monotonic()
    elapsed = 0.0
    steps = 0
    history = []
    initial_loss = None
    emit(event="training_started", rank=rank, world=world, width=args.width,
         depth=args.depth, local_batch=args.batch, accumulation=args.accumulation,
         parameter_count=count, precision="BF16 autocast / FP32 parameters and gradients",
         nccl_p2p_disable=os.environ.get("NCCL_P2P_DISABLE"), collective=collective)
    while True:
        window_start = time.monotonic()
        window_steps = 0
        for _ in range(args.window_steps):
            loss = step()
            window_steps += 1
        torch.cuda.synchronize()
        window_seconds = time.monotonic() - window_start
        seconds = torch.tensor(time.monotonic() - started, device=device)
        if world > 1:
            dist.all_reduce(seconds, op=dist.ReduceOp.MAX)
        elapsed = seconds.item()
        steps += window_steps
        value = loss.item()
        if not math.isfinite(value):
            raise RuntimeError("Nonfinite loss")
        if initial_loss is None:
            initial_loss = value
        # Every window checks every gradient, including nonsampled layers.
        gradients_finite = all(
            p.grad is not None and torch.isfinite(p.grad).all().item()
            for p in base.parameters()
        )
        if not gradients_finite:
            raise RuntimeError("Nonfinite gradient")
        record = {"elapsed_seconds": elapsed, "optimizer_steps": steps, "loss": value,
                  "window_seconds": window_seconds, "rank": rank,
                  "aggregate_dense_gemm_tflops": flops_per_microstep * args.accumulation
                  * window_steps * world / window_seconds / 1e12}
        history.append(record)
        emit(event="training_window", **record)
        if elapsed >= args.seconds:
            break
    maximum_difference = torch.zeros((), device=device)
    if world > 1:
        for parameter in base.parameters():
            reference = parameter.detach().clone()
            dist.broadcast(reference, src=0)
            maximum_difference = torch.maximum(
                maximum_difference, (parameter.detach() - reference).abs().max())
        dist.all_reduce(maximum_difference, op=dist.ReduceOp.MAX)
    changed = (next(base.parameters()).detach() - initial).abs().max().item()
    report = {
        "passed": gradients_finite and changed > 0 and maximum_difference.item() == 0,
        "rank": rank, "world_size": world, "gpu": torch.cuda.get_device_name(device),
        "torch_version": torch.__version__, "cuda_version": torch.version.cuda,
        "local_batch": args.batch, "width": args.width, "depth": args.depth,
        "gradient_accumulation": args.accumulation, "parameter_count": count,
        "duration_seconds": elapsed, "optimizer_steps": steps,
        "microsteps": steps * args.accumulation,
        "aggregate_dense_gemm_tflops": flops_per_microstep * args.accumulation * steps
        * world / elapsed / 1e12,
        "peak_allocated_mib": torch.cuda.max_memory_allocated() / 1024 ** 2,
        "initial_observed_loss": initial_loss, "final_loss": value,
        "max_weight_change": changed, "gradients_finite": gradients_finite,
        "all_ranks_max_weight_difference": maximum_difference.item(),
        "collectives": collective, "history": history,
        "flop_convention": "(6*depth-2)*batch*width^2 per microstep, dense GEMMs only; wall time includes optimizer/communication/checks",
        "nccl_p2p_disable": os.environ.get("NCCL_P2P_DISABLE"),
    }
    save(Path(args.output) / ("rank-" + str(rank) + ".json"), report)
    emit(event="training_finished", **{k: v for k, v in report.items() if k != "history"})
    if world > 1:
        dist.destroy_process_group()
    if not report["passed"]:
        raise RuntimeError("Training numerical verification failed")


def suite(args):
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    active = subprocess.check_output(
        ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader"], text=True).strip()
    if active:
        raise RuntimeError("Existing GPU compute process; refusing concurrent stress")
    script = str(Path(__file__).resolve())
    stages = [("gemm", [sys.executable, "-u", script, "gemm", "--output", str(output / "gemm.json")])]
    for batch in (2048, 4096, 8192, 16384):
        folder = output / ("scan-" + str(batch))
        folder.mkdir()
        stages.append(("scan-" + str(batch), [sys.executable, "-u", script, "train",
                       "--seconds", "5", "--batch", str(batch), "--window-steps", "8",
                       "--output", str(folder)]))

    def run(name, command, timeout):
        emit(event="stage_started", stage=name)
        save(output / "status.json", {"stage": name, "state": "running"})
        with (output / (name + ".log")).open("w", buffering=1) as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
            try:
                code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    process.kill()
                raise RuntimeError("Stage timeout: " + name)
        if code:
            raise RuntimeError("Stage failed: " + name + "; inspect stage log")
        emit(event="stage_finished", stage=name, exit_code=code)

    try:
        for name, command in stages:
            run(name, command, 180)
        scans = [json.loads((output / ("scan-" + str(batch)) / "rank-0.json").read_text())
                 for batch in (2048, 4096, 8192, 16384)]
        best = max(scans, key=lambda row: row["aggregate_dense_gemm_tflops"])
        save(output / "chosen.json", {"selected_local_batch": best["local_batch"],
                                     "scans": [{k: v for k, v in row.items() if k != "history"}
                                               for row in scans]})
        emit(event="configuration_selected", batch=best["local_batch"],
             scan_tflops=best["aggregate_dense_gemm_tflops"])
        for world, name in ((1, "single"), (2, "dual")):
            folder = output / name
            folder.mkdir()
            command = [sys.executable, "-u"]
            if world > 1:
                command += ["-m", "torch.distributed.run", "--standalone", "--nproc_per_node=2"]
            command += [script, "train", "--seconds", str(args.seconds),
                        "--batch", str(best["local_batch"]), "--output", str(folder)]
            run(name, command, args.seconds + 180)
        save(output / "status.json", {"stage": "finished", "state": "completed",
                                     "finished_at": datetime.now(timezone.utc).isoformat()})
    except BaseException as error:
        save(output / "status.json", {"stage": "failed", "state": "failed",
                                     "error": str(error)})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("suite", "gemm", "train"))
    parser.add_argument("--seconds", type=float, default=600)
    parser.add_argument("--width", type=int, default=8192)
    parser.add_argument("--depth", type=int, default=4)
    parser.add_argument("--batch", type=int, default=8192)
    parser.add_argument("--accumulation", type=int, default=4)
    parser.add_argument("--window-steps", type=int, default=32)
    parser.add_argument("--output", default="stress-results")
    args = parser.parse_args()
    if min(args.seconds, args.width, args.depth, args.batch, args.accumulation, args.window_steps) <= 0:
        parser.error("All sizes and durations must be positive")
    {"suite": suite, "gemm": lambda a: calibrate(a.output), "train": train}[args.mode](args)


if __name__ == "__main__":
    main()
