"""Candidate image checks; GPU verification must run in an isolated allocated workload."""
import argparse
import json
import shutil
import subprocess
import sys
import torch
import numpy


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-gpu", action="store_true")
    args = parser.parse_args()
    assert torch.__version__.split("+")[0] == "2.5.1", torch.__version__
    assert torch.version.cuda == "12.4", torch.version.cuda
    assert numpy.__version__ == "1.26.4", numpy.__version__
    for tool in ("sshd", "sudo", "git", "gcc", "ninja", "jupyter-lab", "torchrun"):
        assert shutil.which(tool), tool
    subprocess.run(["ninja", "--version"], check=True)
    subprocess.run(["python", "-m", "pip", "check"], check=True)
    cpu = torch.arange(10).sum().item()
    assert cpu == 45
    assert torch.from_numpy(numpy.arange(10, dtype=numpy.float32)).sum().item() == 45
    report = {
        "torch": torch.__version__,
        "cuda_runtime": torch.version.cuda,
        "numpy": numpy.__version__,
        "python": sys.version.split()[0],
        "cpu_check": True,
        "gpu_verified": False,
    }
    if args.require_gpu:
        assert torch.cuda.is_available(), "GPU unavailable"
        assert torch.arange(10, device="cuda").sum().item() == 45
        model = torch.nn.Linear(16, 4).cuda()
        optimizer = torch.optim.SGD(model.parameters(), lr=0.01)
        loss = model(torch.ones(8, 16, device="cuda")).square().mean()
        loss.backward()
        assert all(torch.isfinite(p.grad).all().item() for p in model.parameters())
        optimizer.step()
        torch.cuda.synchronize()
        report.update(
            gpu_verified=True,
            gpu_name=torch.cuda.get_device_name(0),
            capability=torch.cuda.get_device_capability(0),
            cuda_forward_backward=True,
        )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
