"""Single/multi-GPU example with atomic per-epoch checkpoint and resume."""

import argparse
from contextlib import suppress
import os
import json
from pathlib import Path

import torch
import torch.distributed as dist
from torch import nn
from torch.nn.parallel import DistributedDataParallel
from torch.utils.data import DataLoader, TensorDataset, DistributedSampler


def checkpoint_payload(checkpoint):
    """Keep pickle restricted to tensors and strings for PyTorch 1.13 safe loading."""
    tensors = {}

    def encode(value):
        if isinstance(value, torch.Tensor):
            key = str(len(tensors))
            tensors[key] = value
            return {"tensor": key}
        if isinstance(value, dict):
            return {"dict": [[encode(key), encode(item)] for key, item in value.items()]}
        if isinstance(value, tuple):
            return {"tuple": [encode(item) for item in value]}
        if isinstance(value, list):
            return [encode(item) for item in value]
        if value is None or isinstance(value, (str, bool, int, float)):
            return value
        raise TypeError(f"Unsupported checkpoint value: {type(value).__name__}")

    return {"metadata": json.dumps(encode(checkpoint), allow_nan=False), "tensors": tensors}


def load_checkpoint(path):
    payload = torch.load(path, map_location="cpu", weights_only=True)
    if not isinstance(payload, dict) or set(payload) != {"metadata", "tensors"}:
        raise RuntimeError("Resume requires a checkpoint created by the new training example")

    def decode(value):
        if isinstance(value, list):
            return [decode(item) for item in value]
        if isinstance(value, dict):
            if set(value) == {"tensor"}:
                return payload["tensors"][value["tensor"]]
            if set(value) == {"dict"}:
                return {decode(key): decode(item) for key, item in value["dict"]}
            if set(value) == {"tuple"}:
                return tuple(decode(item) for item in value["tuple"])
            raise ValueError("Invalid checkpoint metadata")
        return value

    return decode(json.loads(payload["metadata"]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=Path(__file__).resolve().parent / "checkpoint.pt",
    )
    parser.add_argument("--resume", type=Path, help="Load a checkpoint created by this example")
    parser.add_argument(
        "--device",
        choices=("cuda", "cpu"),
        default="cuda",
        help="CPU is for a small functional check",
    )
    args = parser.parse_args()
    local_rank = int(os.environ.get("LOCAL_RANK", 0))
    world_size = int(os.environ.get("WORLD_SIZE", 1))
    if args.epochs < 1:
        parser.error("--epochs must be positive")
    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("No CUDA GPU found. Select a compatible platform image.")
    device = torch.device("cuda", local_rank) if args.device == "cuda" else torch.device("cpu")
    if args.device == "cuda":
        torch.cuda.set_device(local_rank)
    if world_size > 1:
        dist.init_process_group("nccl" if args.device == "cuda" else "gloo")
    rank = dist.get_rank() if world_size > 1 else 0
    try:
        torch.manual_seed(42)
        dataset = TensorDataset(torch.randn(4096, 128), torch.randint(0, 10, (4096,)))
        sampler = DistributedSampler(dataset) if world_size > 1 else None
        loader = DataLoader(dataset, batch_size=128, sampler=sampler, shuffle=sampler is None)
        model = nn.Sequential(nn.Linear(128, 256), nn.ReLU(), nn.Linear(256, 10)).to(device)
        if world_size > 1:
            model = DistributedDataParallel(
                model, device_ids=[local_rank] if args.device == "cuda" else None
            )
        optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
        raw_model = model.module if world_size > 1 else model
        start_epoch = 0
        if args.resume:
            checkpoint = load_checkpoint(args.resume)
            if not isinstance(checkpoint, dict) or checkpoint.get("format") != 1:
                raise RuntimeError(
                    "Resume requires a checkpoint from the new example, including model and optimizer"
                )
            raw_model.load_state_dict(checkpoint["model"])
            optimizer.load_state_dict(checkpoint["optimizer"])
            start_epoch = int(checkpoint["epoch"])
            if checkpoint["world_size"] == world_size and checkpoint["device"] == args.device:
                state = checkpoint["rank_states"][rank]
                torch.set_rng_state(state["cpu"])
                if args.device == "cuda":
                    torch.cuda.set_rng_state(state["cuda"], device)
            if rank == 0:
                print(
                    f"Resuming after epoch {start_epoch}; target total epochs={args.epochs}",
                    flush=True,
                )
        for epoch in range(start_epoch, args.epochs):
            if sampler:
                sampler.set_epoch(epoch)
            total = 0
            for inputs, labels in loader:
                optimizer.zero_grad()
                loss = nn.functional.cross_entropy(model(inputs.to(device)), labels.to(device))
                loss.backward()
                optimizer.step()
                total += loss.detach().item()
            if rank == 0:
                print(
                    f"epoch={epoch + 1} mean_loss={total / len(loader):.4f} gpus={world_size}",
                    flush=True,
                )
            state = {
                "cpu": torch.get_rng_state(),
                "cuda": torch.cuda.get_rng_state(device) if args.device == "cuda" else None,
            }
            states = [None] * world_size
            if world_size > 1:
                dist.all_gather_object(states, state)
            else:
                states[0] = state
            # All ranks agree that saving succeeded before entering another DDP epoch.
            saved = torch.ones(1, device=device, dtype=torch.int32)
            if rank == 0:
                target = args.checkpoint.resolve()
                temporary = target.with_name(target.name + f".{os.getpid()}.tmp")
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with temporary.open("wb") as stream:
                        torch.save(
                            checkpoint_payload(
                                {
                                    "format": 1,
                                    "model": raw_model.state_dict(),
                                    "optimizer": optimizer.state_dict(),
                                    "epoch": epoch + 1,
                                    "world_size": world_size,
                                    "device": args.device,
                                    "rank_states": states,
                                }
                            ),
                            stream,
                        )
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temporary, target)
                    print(f"Saved epoch {epoch + 1} to {target}", flush=True)
                except (OSError, RuntimeError):
                    saved.zero_()
                finally:
                    with suppress(OSError):
                        temporary.unlink(missing_ok=True)
            if world_size > 1:
                dist.broadcast(saved, src=0)
            if not saved.item():
                raise RuntimeError(
                    "Checkpoint save failed; check persistent storage capacity and permissions"
                )
    finally:
        if world_size > 1:
            dist.destroy_process_group()


if __name__ == "__main__":
    main()
