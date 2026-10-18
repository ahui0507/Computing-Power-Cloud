"""Run with torchrun --standalone --nproc_per_node=N; fail on silent corruption.

Use --checkpoint /tmp/... on the first run and --resume on a new invocation.
Test with NCCL_P2P_DISABLE unset or 0 to exercise the native NCCL path.
"""
import argparse
import copy
from datetime import timedelta
import json
import os
from pathlib import Path
import time

import torch
import torch.distributed as dist
from torch.nn.parallel import DistributedDataParallel


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--steps', type=int, default=12)
    parser.add_argument('--stress-iterations', type=int, default=100)
    parser.add_argument('--stress-seconds', type=float, default=0)
    args = parser.parse_args()
    if os.environ.get('NCCL_P2P_DISABLE', '0') != '0':
        raise RuntimeError('Native NCCL acceptance requires P2P enabled')
    rank = int(os.environ['RANK'])
    local_rank = int(os.environ['LOCAL_RANK'])
    size = int(os.environ['WORLD_SIZE'])
    if size < 2 or args.steps < 1 or args.stress_iterations < 1:
        raise RuntimeError('At least two GPUs and positive iteration counts required')
    torch.cuda.set_device(local_rank)
    torch.set_num_threads(2)
    dist.init_process_group('nccl', timeout=timedelta(seconds=90))
    try:
        torch.manual_seed(20261017)
        model = torch.nn.Sequential(torch.nn.Linear(16, 32), torch.nn.Tanh(), torch.nn.Linear(32, 4)).cuda()
        reference = torch.nn.Sequential(torch.nn.Linear(16, 32), torch.nn.Tanh(), torch.nn.Linear(32, 4)).cuda()
        reference.load_state_dict(model.state_dict())
        optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
        reference_optimizer = torch.optim.Adam(reference.parameters(), lr=0.001)
        start = 0
        if args.resume:
            saved = torch.load(args.checkpoint, map_location='cpu', weights_only=True)
            if saved['world_size'] != size:
                raise RuntimeError('Checkpoint world size changed')
            for target in (model, reference):
                target.load_state_dict(saved['model'])
            for target in (optimizer, reference_optimizer):
                # load_state_dict can retain CPU scalar tensors such as Adam's
                # step counter. Each optimizer needs its own checkpoint copy.
                target.load_state_dict(copy.deepcopy(saved['optimizer']))
            for actual, expected in zip(model.parameters(), reference.parameters()):
                for key, value in optimizer.state[actual].items():
                    other = reference_optimizer.state[expected][key]
                    if isinstance(value, torch.Tensor) and value.data_ptr() == other.data_ptr():
                        raise RuntimeError('Reference optimizer shares checkpoint storage')
            start = saved['completed_steps']
        ddp = DistributedDataParallel(model, device_ids=[local_rank])

        def same_replicas(value):
            tensors = [torch.empty_like(value) for _ in range(size)]
            dist.all_gather(tensors, value.contiguous())
            for other in tensors:
                torch.testing.assert_close(value, other, rtol=0, atol=0)

        for step in range(start, start + args.steps):
            # Different input on each rank; a local-only update cannot pass.
            x = torch.arange(size * 8 * 16, device='cuda', dtype=torch.float32).reshape(size * 8, 16)
            x = ((x + step * 13) % 97) / 97
            y = x[:, :4] * 0.75 + 0.1
            optimizer.zero_grad(set_to_none=True)
            reference_optimizer.zero_grad(set_to_none=True)
            loss = (ddp(x[rank*8:(rank+1)*8]) - y[rank*8:(rank+1)*8]).square().mean()
            loss.backward()
            reference_loss = (reference(x) - y).square().mean()
            reference_loss.backward()
            for parameter, expected in zip(model.parameters(), reference.parameters()):
                if not torch.isfinite(parameter.grad).all():
                    raise RuntimeError('Non-finite gradient')
                torch.testing.assert_close(parameter.grad, expected.grad, rtol=2e-4, atol=2e-6)
            optimizer.step()
            reference_optimizer.step()
            for parameter, expected in zip(model.parameters(), reference.parameters()):
                torch.testing.assert_close(parameter, expected, rtol=2e-4, atol=2e-6)
                same_replicas(parameter.detach())
                for key, value in optimizer.state[parameter].items():
                    if isinstance(value, torch.Tensor):
                        torch.testing.assert_close(value, reference_optimizer.state[expected][key], rtol=3e-4, atol=2e-6)
                        same_replicas(value.detach().cuda())

        deadline = time.monotonic() + args.stress_seconds
        stress_started = time.monotonic()
        iteration = 0
        continue_flag = torch.zeros((), dtype=torch.int32, device='cuda')
        base = torch.arange(2 * 1024 * 1024, device='cuda', dtype=torch.float32).remainder_(31)
        while True:
            # A single rank decides when to stop so every rank executes the
            # same number of collectives even when their clocks differ.
            if rank == 0:
                continue_flag.fill_(iteration < args.stress_iterations or time.monotonic() < deadline)
            dist.broadcast(continue_flag, src=0)
            if not continue_flag.item():
                break
            # 8 MiB patterned tensors catch incorrect copies beyond scalar checks.
            tensor = base + rank + iteration % 7
            expected = base * size + size * (size - 1) // 2 + (iteration % 7) * size
            dist.all_reduce(tensor)
            torch.testing.assert_close(tensor, expected, rtol=0, atol=0)
            iteration += 1
            if rank == 0 and iteration % 1000 == 0:
                print(json.dumps({'progress':'stress', 'iterations':iteration,
                                  'elapsed_seconds':round(time.monotonic()-stress_started, 2)}), flush=True)
        if rank == 0:
            args.checkpoint.parent.mkdir(parents=True, exist_ok=True)
            torch.save({'model':model.state_dict(), 'optimizer':optimizer.state_dict(),
                        'completed_steps':start + args.steps, 'world_size':size}, args.checkpoint)
        dist.barrier()
        torch.cuda.synchronize()
        if rank == 0:
            print(json.dumps({'framework':'pytorch', 'version':torch.__version__,
                              'gpu_count':size, 'native_nccl':True,
                              'gradient_reference_match':True, 'replicas_and_optimizer_identical':True,
                              'completed_steps':start + args.steps, 'resumed':args.resume,
                              'stress_iterations':iteration,
                              'stress_seconds':round(time.monotonic()-stress_started, 2)}), flush=True)
    finally:
        dist.destroy_process_group()


if __name__ == '__main__':
    main()
