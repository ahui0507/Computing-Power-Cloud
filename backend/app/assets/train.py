"""Small single/multi-GPU example; saves a checkpoint beside this script."""

import argparse
import os
from pathlib import Path

import torch
import torch.distributed as dist
from torch import nn
from torch.nn.parallel import DistributedDataParallel
from torch.utils.data import DataLoader, TensorDataset, DistributedSampler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs", type=int, default=3)
    args = parser.parse_args()
    local_rank = int(os.environ.get("LOCAL_RANK", 0))
    world_size = int(os.environ.get("WORLD_SIZE", 1))
    if not torch.cuda.is_available():
        raise RuntimeError("No CUDA GPU found. Select a compatible platform image.")
    torch.cuda.set_device(local_rank)
    if world_size > 1:
        dist.init_process_group("nccl")
    rank = dist.get_rank() if world_size > 1 else 0
    try:
        torch.manual_seed(42)
        dataset = TensorDataset(torch.randn(4096, 128), torch.randint(0, 10, (4096,)))
        sampler = DistributedSampler(dataset) if world_size > 1 else None
        loader = DataLoader(dataset, batch_size=128, sampler=sampler, shuffle=sampler is None)
        model = nn.Sequential(nn.Linear(128, 256), nn.ReLU(), nn.Linear(256, 10)).cuda()
        if world_size > 1:
            model = DistributedDataParallel(model, device_ids=[local_rank])
        optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
        for epoch in range(args.epochs):
            if sampler:
                sampler.set_epoch(epoch)
            total = 0
            for inputs, labels in loader:
                optimizer.zero_grad()
                loss = nn.functional.cross_entropy(model(inputs.cuda()), labels.cuda())
                loss.backward()
                optimizer.step()
                total += loss.detach().item()
            if rank == 0:
                print(
                    f"epoch={epoch + 1} mean_loss={total / len(loader):.4f} gpus={world_size}",
                    flush=True,
                )
        if rank == 0:
            target = Path(__file__).resolve().parent / "checkpoint.pt"
            torch.save((model.module if world_size > 1 else model).state_dict(), target)
            print(f"Saved {target}", flush=True)
    finally:
        if world_size > 1:
            dist.destroy_process_group()


if __name__ == "__main__":
    main()
