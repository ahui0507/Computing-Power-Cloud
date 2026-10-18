"""Exercise the public development environment; GPU checks need an allocated instance."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


VERSIONS = {
    "torch": "2.5.1",
    "torchvision": "0.20.1",
    "torchaudio": "2.5.1",
    "jupyterlab": "4.2.5",
    "numpy": "1.26.4",
    "ninja": "1.13.0",
    "pandas": "2.2.3",
    "scipy": "1.14.1",
    "scikit-learn": "1.5.2",
    "matplotlib": "3.9.2",
    "tqdm": "4.66.5",
    "tensorboard": "2.18.0",
    "pillow": "10.2.0",
    "setuptools": "75.1.0",
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def compile_cuda(directory):
    """Compile without accessing a GPU, including runtime and CUDA template headers."""
    source = directory / "toolkit.cu"
    source.write_text(
        "#include <cuda_runtime.h>\n#include <curand_kernel.h>\n"
        "#include <thrust/device_ptr.h>\n"
        "#include <cublas_v2.h>\n#include <cufft.h>\n"
        "#include <cusolverDn.h>\n#include <cusparse.h>\n"
        "__global__ void kernel(float* x) { x[threadIdx.x] += 1.0f; }\n"
        "int main() { return 0; }\n"
    )
    subprocess.run(
        ["nvcc", "-arch=sm_80", str(source), "-o", str(directory / "toolkit")],
        check=True, timeout=120,
    )


def cuda_extension(directory):
    """Compile and run a real PyTorch CUDA extension using the current CUDA stream."""
    import torch
    from torch.utils.cpp_extension import load

    binding = directory / "binding.cpp"
    binding.write_text(
        "#include <torch/extension.h>\n"
        "at::Tensor add_one(const at::Tensor& x);\n"
        "PYBIND11_MODULE(TORCH_EXTENSION_NAME, m) { m.def(\"add_one\", &add_one); }\n"
    )
    kernel = directory / "kernel.cu"
    kernel.write_text(
        "#include <ATen/ATen.h>\n"
        "#include <c10/cuda/CUDAStream.h>\n"
        "#include <c10/cuda/CUDAException.h>\n"
        "__global__ void increment(const float* x, float* y, int64_t n) {\n"
        "  int64_t i = blockIdx.x * blockDim.x + threadIdx.x;\n"
        "  if (i < n) y[i] = x[i] + 1.0f;\n}\n"
        "at::Tensor add_one(const at::Tensor& x) {\n"
        "  TORCH_CHECK(x.is_cuda() && x.is_contiguous() && x.scalar_type() == at::kFloat);\n"
        "  auto y = at::empty_like(x);\n"
        "  if (x.numel()) increment<<<(x.numel()+255)/256, 256, 0,\n"
        "      c10::cuda::getCurrentCUDAStream().stream()>>>(\n"
        "      x.data_ptr<float>(), y.data_ptr<float>(), x.numel());\n"
        "  C10_CUDA_KERNEL_LAUNCH_CHECK();\n"
        "  return y;\n}\n"
    )
    os.environ["MAX_JOBS"] = "1"
    module = load(
        name="campus_cuda_acceptance", sources=[str(binding), str(kernel)],
        build_directory=str(directory), extra_cflags=["-O0"],
        extra_cuda_cflags=["-O0"], with_cuda=True,
    )
    x = torch.arange(1024, device="cuda", dtype=torch.float32)
    require(torch.equal(module.add_one(x), x + 1), "CUDA extension returned wrong values")
    torch.cuda.synchronize()


def check_kernel(directory):
    from jupyter_client import KernelManager

    manager = KernelManager(kernel_name="python3")
    client = None
    try:
        manager.start_kernel(cwd=str(directory), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        client = manager.blocking_client()
        client.start_channels()
        client.wait_for_ready(timeout=30)
        message_id = client.execute(
            "import sys, torch\n"
            "assert sys.version_info[:2] == (3, 11)\n"
            "assert torch.__version__ == '2.5.1+cu124'\n"
        )
        reply = client.get_shell_msg(timeout=30)
        require(reply["parent_header"].get("msg_id") == message_id, "Unexpected kernel reply")
        require(reply["content"]["status"] == "ok", f"Jupyter kernel failed: {reply['content']}")
    finally:
        if client:
            client.stop_channels()
        if manager.has_kernel:
            manager.shutdown_kernel(now=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-gpu", action="store_true")
    parser.add_argument("--compile-cuda", action="store_true")
    parser.add_argument("--cuda-extension", action="store_true")
    args = parser.parse_args()
    if args.cuda_extension and not args.require_gpu:
        parser.error("--cuda-extension requires --require-gpu")
    installed = {name: importlib.metadata.version(name) for name in VERSIONS}
    for name, expected in VERSIONS.items():
        require(installed[name].split("+")[0] == expected, f"{name}: {installed[name]} != {expected}")
    for name in ("torch", "torchvision", "torchaudio"):
        require(installed[name].endswith("+cu124"), f"{name} must use CUDA 12.4 wheels")
    require(sys.version_info[:2] == (3, 11), "Python 3.11 required")
    for tool in (
        "conda", "pip", "sshd", "sudo", "git", "curl", "wget", "rsync", "unzip",
        "tmux", "gcc", "g++", "make", "cmake", "ninja", "nvcc", "jupyter-lab",
        "torchrun", "tensorboard",
    ):
        require(shutil.which(tool), f"Missing tool: {tool}")
    subprocess.run([sys.executable, "-m", "pip", "check"], check=True, timeout=60)
    nvcc = subprocess.check_output(["nvcc", "--version"], text=True, timeout=15)
    require("release 12.4," in nvcc, "CUDA compiler must match CUDA 12.4")
    cuda_lock = json.loads(Path(__file__).with_name("cuda-pytorch2-devel-debs.lock.json").read_text())
    cuda_versions = {row["Package"]: row["Version"] for row in cuda_lock["packages"]}
    installed_cuda = dict(line.split("=", 1) for line in subprocess.check_output(
        ["dpkg-query", "-W", "-f=${Package}=${Version}\n", *cuda_versions], text=True, timeout=30,
    ).splitlines())
    require(installed_cuda == cuda_versions, "CUDA development packages differ from the lock")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    import scipy.linalg
    from sklearn.linear_model import LinearRegression
    from tqdm import tqdm
    import torch
    import torchvision
    import torchaudio
    from torch.utils.tensorboard import SummaryWriter
    from tensorboard.backend.event_processing.event_accumulator import EventAccumulator
    from PIL import Image
    import jupyterlab
    import ipykernel

    require(torch.version.cuda == "12.4", "Unexpected PyTorch CUDA runtime")
    require(torch.backends.cudnn.is_available(), "cuDNN unavailable")
    require(torch.from_numpy(np.arange(10, dtype=np.float32)).sum().item() == 45, "NumPy interop failed")
    frame = pd.DataFrame({"x": [1, 2, 3], "y": [2, 4, 6]})
    model = LinearRegression().fit(frame[["x"]], frame["y"])
    require(np.allclose(model.predict(pd.DataFrame({"x": [4]})), [8]), "scikit-learn failed")
    require(np.allclose(scipy.linalg.solve(np.eye(2), [1, 2]), [1, 2]), "SciPy failed")
    require(list(tqdm(range(2), disable=True)) == [0, 1], "tqdm failed")
    boxes = torch.tensor([[0., 0., 10., 10.], [0., 0., 10., 10.]])
    scores = torch.tensor([0.9, 0.8])
    require(torchvision.ops.nms(boxes, scores, 0.5).tolist() == [0], "torchvision NMS failed")
    audio = torchaudio.functional.resample(torch.ones(1, 160), 16000, 8000)
    require(audio.shape == (1, 80) and torch.isfinite(audio).all().item(), "torchaudio failed")
    report = {
        "python": sys.version.split()[0], "packages": installed,
        "cuda_runtime": torch.version.cuda, "cudnn": torch.backends.cudnn.version(),
        "nvcc": "12.4", "cpu_checks": True, "gpu_verified": False,
        "cuda_compilation": False, "pytorch_cuda_extension": False, "jupyter_kernel": False,
    }
    with tempfile.TemporaryDirectory(prefix="campus-devel-check-") as temporary:
        directory = Path(temporary)
        fig, ax = plt.subplots()
        ax.plot(frame["x"], frame["y"])
        fig.savefig(directory / "plot.png")
        plt.close(fig)
        with Image.open(directory / "plot.png") as image:
            image.verify()
        with SummaryWriter(str(directory / "events")) as writer:
            writer.add_scalar("acceptance/loss", 0.5, 1)
        events = EventAccumulator(str(directory / "events")).Reload()
        require(events.Scalars("acceptance/loss")[0].value == 0.5, "TensorBoard events failed")
        check_kernel(directory)
        report["jupyter_kernel"] = True
        if args.compile_cuda:
            compile_cuda(directory)
            report["cuda_compilation"] = True
        if args.require_gpu:
            require(torch.cuda.is_available(), "GPU unavailable")
            require(torch.arange(10, device="cuda").sum().item() == 45, "CUDA arithmetic failed")
            require(torchvision.ops.nms(boxes.cuda(), scores.cuda(), 0.5).tolist() == [0], "CUDA NMS failed")
            network = torch.nn.Linear(16, 4).cuda()
            optimizer = torch.optim.SGD(network.parameters(), lr=0.01)
            before = network.weight.detach().clone()
            loss = network(torch.ones(8, 16, device="cuda")).square().mean()
            loss.backward()
            require(all(p.grad is not None and torch.isfinite(p.grad).all().item() for p in network.parameters()), "Invalid gradients")
            optimizer.step()
            require(not torch.equal(before, network.weight), "Optimizer did not update weights")
            torch.cuda.synchronize()
            report.update(gpu_verified=True, gpu_name=torch.cuda.get_device_name(0), gpu_count=torch.cuda.device_count())
            if args.cuda_extension:
                # Run in a child so a stuck compiler cannot hold the acceptance indefinitely.
                subprocess.run(
                    [sys.executable, str(Path(__file__).resolve()), "--extension-worker", str(directory)],
                    check=True, timeout=300,
                )
                report["pytorch_cuda_extension"] = True
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--extension-worker":
        cuda_extension(Path(sys.argv[2]))
    else:
        main()
