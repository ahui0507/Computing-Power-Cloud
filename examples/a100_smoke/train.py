"""Train a small CNN on synthetic images and verify real A100 CUDA execution."""

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import subprocess
import threading
import time

import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset


class SmallCNN(nn.Module):
    def __init__(self):
        super().__init__()
        self.network = nn.Sequential(
            nn.Conv2d(1, 32, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
            nn.Conv2d(32, 64, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
            nn.Conv2d(64, 128, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
            nn.Flatten(), nn.Linear(128 * 4 * 4, 128), nn.ReLU(),
            nn.Linear(128, 10),
        )

    def forward(self, inputs):
        return self.network(inputs)


def images(count, device):
    """Ten classes indicate the position of a bright patch; add random noise."""
    labels = torch.randint(0, 10, (count,), device=device)
    inputs = torch.randn(count, 1, 32, 32, device=device) * 0.15
    for label in range(10):
        row, column = divmod(label, 5)
        inputs[labels == label, :, 5 + row * 16:11 + row * 16,
               2 + column * 6:7 + column * 6] += 1.5
    return inputs, labels


def nvidia_query(fields, kind="gpu"):
    result = subprocess.run(
        ["nvidia-smi", "--query-" + kind + "=" + fields,
         "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=5, check=True,
    )
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--output-dir", type=Path, default=Path("a100-results"))
    args = parser.parse_args()
    if args.epochs < 1 or args.batch_size < 1:
        raise ValueError("epochs and batch-size must be positive")
    # Avoid sharing the existing instance with an already running compute job.
    active = nvidia_query("pid,gpu_uuid,used_memory", "compute-apps")
    if active:
        raise RuntimeError("GPU compute processes already exist; training not started")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable; CPU fallback is deliberately disabled")
    torch.cuda.set_device(0)
    device = torch.device("cuda:0")
    name = torch.cuda.get_device_name(device)
    if "A100" not in name:
        raise RuntimeError("Expected A100, found " + name)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    torch.manual_seed(42)
    torch.cuda.manual_seed_all(42)
    torch.set_num_threads(2)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    report = {
        "passed": False, "started_at": datetime.now(timezone.utc).isoformat(),
        "torch_version": torch.__version__, "cuda_version": torch.version.cuda,
        "gpu_name": name, "device": str(device),
        "compute_capability": list(torch.cuda.get_device_capability(device)),
        "visible_cuda_devices": torch.cuda.device_count(),
        "gpu_inventory": nvidia_query("index,uuid,name,driver_version,memory.total"),
        "model": "SmallCNN", "dataset": "synthetic noisy patch-position images",
        "training_samples": 8192, "validation_samples": 2048,
        "epochs": args.epochs, "batch_size": args.batch_size, "precision": "FP32",
    }
    print(json.dumps(report), flush=True)
    training = TensorDataset(*images(8192, device))
    validation_x, validation_y = images(2048, device)
    loader = DataLoader(training, batch_size=args.batch_size, shuffle=True, num_workers=0)
    model = SmallCNN().to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
    criterion = nn.CrossEntropyLoss()
    original_weight = next(model.parameters()).detach().clone()

    def evaluate(network):
        network.eval()
        with torch.no_grad():
            logits = torch.cat([
                network(batch) for batch in validation_x.split(args.batch_size)
            ])
            return (criterion(logits, validation_y).item(),
                    (logits.argmax(1) == validation_y).float().mean().item(), logits)

    initial_loss, initial_accuracy, _ = evaluate(model)
    samples = []
    stop = threading.Event()

    def monitor():
        while not stop.is_set():
            try:
                samples.append({
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "gpus": nvidia_query("uuid,utilization.gpu,memory.used"),
                })
            except (subprocess.SubprocessError, OSError):
                pass
            stop.wait(0.2)

    torch.cuda.reset_peak_memory_stats(device)
    torch.cuda.synchronize()
    started = time.monotonic()
    worker = threading.Thread(target=monitor, daemon=True)
    worker.start()
    history = []
    try:
        for epoch in range(args.epochs):
            model.train()
            total_loss = torch.zeros((), device=device)
            for inputs, labels in loader:
                optimizer.zero_grad(set_to_none=True)
                loss = criterion(model(inputs), labels)
                loss.backward()
                optimizer.step()
                total_loss += loss.detach() * inputs.shape[0]
            validation_loss, accuracy, _ = evaluate(model)
            record = {
                "epoch": epoch + 1,
                "train_loss": total_loss.item() / len(training),
                "validation_loss": validation_loss, "validation_accuracy": accuracy,
            }
            if not all(math.isfinite(record[key]) for key in ("train_loss", "validation_loss")):
                raise RuntimeError("Nonfinite training loss")
            history.append(record)
            print(json.dumps(record), flush=True)
        torch.cuda.synchronize()
        elapsed = time.monotonic() - started
    finally:
        stop.set()
        worker.join(timeout=6)

    gradients_finite = all(
        parameter.grad is not None and torch.isfinite(parameter.grad).all().item()
        for parameter in model.parameters()
    )
    weight_change = (next(model.parameters()).detach() - original_weight).abs().max().item()
    # Profile one inference batch to independently confirm CUDA kernels executed.
    with torch.no_grad(), torch.autograd.profiler.profile(use_cuda=True) as profile:
        model(validation_x[:args.batch_size])
    cuda_event_count = sum(event.cuda_time_total > 0 for event in profile.function_events)
    final_loss, final_accuracy, reference = evaluate(model)
    checkpoint = args.output_dir / "checkpoint.pt"
    torch.save({"model_state_dict": model.state_dict(), "model": "SmallCNN"}, checkpoint)
    restored = SmallCNN().to(device)
    restored.load_state_dict(torch.load(checkpoint, map_location=device)["model_state_dict"])
    _, _, reloaded = evaluate(restored)
    reload_difference = (reference - reloaded).abs().max().item()
    report.update({
        "parameter_count": sum(p.numel() for p in model.parameters()),
        "model_device": str(next(model.parameters()).device),
        "data_device": str(training.tensors[0].device),
        "initial_validation_loss": initial_loss,
        "initial_validation_accuracy": initial_accuracy,
        "final_validation_loss": final_loss, "final_validation_accuracy": final_accuracy,
        "training_seconds": elapsed,
        "training_samples_per_second": len(training) * args.epochs / elapsed,
        "peak_allocated_mib": torch.cuda.max_memory_allocated(device) / 1024 ** 2,
        "gradients_finite": gradients_finite, "max_weight_change": weight_change,
        "profile_events_with_cuda_time": cuda_event_count,
        "checkpoint_reload_max_difference": reload_difference,
        "checkpoint": checkpoint.name, "history": history, "gpu_samples": samples,
    })
    report["passed"] = bool(
        gradients_finite and weight_change > 0 and cuda_event_count > 0
        and final_loss < initial_loss and final_accuracy >= 0.95
        and reload_difference < 1e-5
    )
    (args.output_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("RESULT " + json.dumps({k: v for k, v in report.items()
                                 if k not in ("history", "gpu_samples")}), flush=True)
    if not report["passed"]:
        raise RuntimeError("A100 training verification failed; inspect report.json")


if __name__ == "__main__":
    main()
