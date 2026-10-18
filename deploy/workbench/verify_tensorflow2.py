"""Exercise the TensorFlow workbench; GPU checks require a platform allocation."""
import argparse
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


VERSIONS = {
    "tensorflow": "2.18.1", "keras": "3.8.0", "numpy": "1.26.4",
    "ml-dtypes": "0.4.1", "h5py": "3.12.1", "jupyterlab": "4.2.5",
    "pandas": "2.2.3", "scipy": "1.14.1", "scikit-learn": "1.5.2",
    "matplotlib": "3.9.2", "tensorboard": "2.18.0", "tqdm": "4.66.5",
    "pillow": "10.2.0", "ninja": "1.13.0", "setuptools": "75.1.0",
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def configure_tensorflow(require_gpu):
    import tensorflow as tf

    tf.config.threading.set_intra_op_parallelism_threads(2)
    tf.config.threading.set_inter_op_parallelism_threads(2)
    devices = tf.config.list_physical_devices("GPU")
    if require_gpu:
        require(bool(devices), "GPU unavailable")
        for device in devices:
            tf.config.experimental.set_memory_growth(device, True)
        tf.config.set_soft_device_placement(False)
    else:
        tf.config.set_visible_devices([], "GPU")
    return tf, devices


def compile_cuda(directory):
    source = directory / "toolkit.cu"
    source.write_text(
        "#include <cuda_runtime.h>\n#include <curand_kernel.h>\n"
        "#include <thrust/device_ptr.h>\n#include <cublas_v2.h>\n"
        "#include <cufft.h>\n#include <cusolverDn.h>\n#include <cusparse.h>\n"
        "#include <cudnn.h>\n#include <nccl.h>\n"
        "__global__ void kernel(float* x) { x[threadIdx.x] += 1.0f; }\n"
        "int main() { return 0; }\n"
    )
    subprocess.run(["nvcc", "-arch=sm_80", str(source), "-o", str(directory / "toolkit")], check=True, timeout=120)


def cuda_op(directory, run=True):
    tf, _ = configure_tensorflow(run)
    binding = directory / "op.cc"
    binding.write_text(
        "#define EIGEN_USE_GPU\n#define GOOGLE_CUDA 1\n"
        "#include <tensorflow/core/framework/op.h>\n"
        "#include <tensorflow/core/framework/op_kernel.h>\n"
        "#include <tensorflow/core/framework/shape_inference.h>\n"
        "#include <tensorflow/core/lib/core/errors.h>\n"
        "#include <cuda_runtime.h>\nusing namespace tensorflow;\n"
        "using GPUDevice = Eigen::GpuDevice;\n"
        "void Launch(const float*, float*, int64_t, cudaStream_t);\n"
        "REGISTER_OP(\"CampusAddOne\").Input(\"input: float\").Output(\"output: float\")\n"
        ".SetShapeFn([](shape_inference::InferenceContext* c) {\n"
        "c->set_output(0,c->input(0)); return absl::OkStatus(); });\n"
        "class AddOneOp : public OpKernel { public:\n"
        "explicit AddOneOp(OpKernelConstruction* c):OpKernel(c) {}\n"
        "void Compute(OpKernelContext* c) override {\n"
        "const Tensor& x=c->input(0); Tensor* y=nullptr;\n"
        "OP_REQUIRES_OK(c,c->allocate_output(0,x.shape(),&y));\n"
        "if(x.NumElements()) Launch(x.flat<float>().data(),y->flat<float>().data(),\n"
        "x.NumElements(),c->eigen_device<GPUDevice>().stream());\n"
        "OP_REQUIRES(c,cudaGetLastError()==cudaSuccess,errors::Internal(\"CUDA launch failed\"));\n"
        "}};\nREGISTER_KERNEL_BUILDER(Name(\"CampusAddOne\").Device(DEVICE_GPU),AddOneOp);\n"
    )
    kernel = directory / "kernel.cu"
    kernel.write_text(
        "#include <cuda_runtime.h>\n#include <cstdint>\n"
        "__global__ void increment(const float* x,float* y,int64_t n) {\n"
        "int64_t i=blockIdx.x*blockDim.x+threadIdx.x; if(i<n) y[i]=x[i]+1.0f; }\n"
        "void Launch(const float* x,float* y,int64_t n,cudaStream_t s) {\n"
        "increment<<<(n+255)/256,256,0,s>>>(x,y,n); }\n"
    )
    obj = directory / "kernel.o"
    library = directory / "campus_tf_op.so"
    subprocess.run(["nvcc", "-std=c++17", "-arch=sm_80", "-Xcompiler", "-fPIC", "-c", str(kernel), "-o", str(obj)], check=True, timeout=120)
    subprocess.run(
        ["g++", "-shared", "-fPIC", "-O0", str(binding), str(obj), "-o", str(library),
         "-I/usr/local/cuda/include", "-L/usr/local/cuda/lib64", "-lcudart",
         *tf.sysconfig.get_compile_flags(), *tf.sysconfig.get_link_flags()],
        check=True, timeout=180,
    )
    module = tf.load_op_library(str(library))
    if run:
        with tf.device("/GPU:0"):
            x = tf.cast(tf.range(1024), tf.float32)
            y = module.campus_add_one(x)
            require("GPU:0" in y.device and (y.numpy() == x.numpy() + 1).all(), "Custom CUDA op failed")


def check_kernel(directory):
    from jupyter_client import KernelManager

    manager = KernelManager(kernel_name="python3")
    client = None
    try:
        manager.start_kernel(cwd=str(directory), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        client = manager.blocking_client()
        client.start_channels()
        client.wait_for_ready(timeout=45)
        message = client.execute("import tensorflow as tf, sys\nassert tf.__version__ == '2.18.1'\nassert sys.version_info[:2] == (3,11)")
        for _ in range(10):
            reply = client.get_shell_msg(timeout=45)
            if reply["parent_header"].get("msg_id") == message:
                require(reply["content"]["status"] == "ok", f"Kernel failed: {reply['content']}")
                break
        else:
            raise RuntimeError("No Jupyter execution reply")
    finally:
        if client:
            client.stop_channels()
        if manager.has_kernel:
            manager.shutdown_kernel(now=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-gpu", action="store_true")
    parser.add_argument("--compile-cuda", action="store_true")
    parser.add_argument("--cuda-op", action="store_true")
    args = parser.parse_args()
    if args.cuda_op and not args.require_gpu:
        parser.error("--cuda-op requires --require-gpu")
    installed = {name: importlib.metadata.version(name) for name in VERSIONS}
    require(installed == VERSIONS, f"Package versions differ: {installed}")
    require(sys.version_info[:2] == (3, 11), "Python 3.11 required")
    for name in ("conda", "pip", "sshd", "sudo", "git", "curl", "wget", "rsync", "tmux", "gcc", "g++", "make", "cmake", "ninja", "nvcc", "jupyter-lab", "tensorboard"):
        require(shutil.which(name), f"Missing tool: {name}")
    subprocess.run([sys.executable, "-m", "pip", "check"], check=True, timeout=60)
    require("release 12.5," in subprocess.check_output(["nvcc", "--version"], text=True), "Unexpected CUDA compiler")
    sdk = json.loads(Path(__file__).with_name("cuda-tensorflow2-debs.lock.json").read_text())
    expected = {row["Package"]: row["Version"] for row in sdk["packages"]}
    actual = dict(line.split("=", 1) for line in subprocess.check_output(
        ["dpkg-query", "-W", "-f=${Package}=${Version}\n", *expected], text=True, timeout=30,
    ).splitlines())
    require(actual == expected, "CUDA/cuDNN/NCCL packages differ from the lock")
    tf, devices = configure_tensorflow(args.require_gpu)
    build = tf.sysconfig.get_build_info()
    require(build["is_cuda_build"] and str(build["cuda_version"]).startswith("12.5"), f"Unexpected TensorFlow build: {build}")
    import numpy as np
    import pandas as pd
    import scipy.linalg
    from sklearn.linear_model import LinearRegression
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from PIL import Image
    from tensorboard.backend.event_processing.event_accumulator import EventAccumulator
    with tf.device("/CPU:0"):
        require(tf.reduce_sum(tf.range(10)).numpy() == 45, "TensorFlow CPU calculation failed")
        require(np.array_equal(tf.convert_to_tensor(np.arange(10)).numpy(), np.arange(10)), "NumPy interop failed")
    frame = pd.DataFrame({"x": [1, 2, 3], "y": [2, 4, 6]})
    model = LinearRegression().fit(frame[["x"]], frame["y"])
    require(np.allclose(model.predict(pd.DataFrame({"x": [4]})), [8]), "scikit-learn failed")
    require(np.allclose(scipy.linalg.solve(np.eye(2), [1, 2]), [1, 2]), "SciPy failed")
    subprocess.run(["bash", "-ic", "conda activate base && python -c 'import sys; assert sys.version_info[:2] == (3,11)'"], check=True, timeout=30, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    report = {
        "python": sys.version.split()[0], "packages": installed,
        "cuda_runtime": build["cuda_version"], "cudnn_build": build["cudnn_version"],
        "cpu_checks": True, "jupyter_kernel": False, "cuda_compilation": False,
        "gpu_verified": False, "tensorflow_cuda_op": False, "xla_gpu": False,
        "tensorflow_op_compilation": False,
    }
    with tempfile.TemporaryDirectory(prefix="campus-tf-check-") as temporary:
        directory = Path(temporary)
        fig, ax = plt.subplots()
        ax.plot(frame["x"], frame["y"])
        fig.savefig(directory / "plot.png")
        plt.close(fig)
        with Image.open(directory / "plot.png") as image:
            image.verify()
        writer = tf.summary.create_file_writer(str(directory / "events"))
        with writer.as_default():
            tf.summary.scalar("acceptance/loss", 0.5, step=1)
        writer.close()
        events = EventAccumulator(str(directory / "events")).Reload()
        event = events.Tensors("acceptance/loss")[0]
        require(event.step == 1 and float(tf.make_ndarray(event.tensor_proto)) == 0.5, "TensorBoard event readback failed")
        check_kernel(directory)
        report["jupyter_kernel"] = True
        if args.compile_cuda:
            compile_cuda(directory)
            subprocess.run([sys.executable, str(Path(__file__).resolve()), "--compile-op-worker", str(directory)], check=True, timeout=360)
            report["cuda_compilation"] = True
            report["tensorflow_op_compilation"] = True
        if args.require_gpu:
            with tf.device("/GPU:0"):
                result = tf.linalg.matmul(tf.ones((4, 4)), tf.ones((4, 4)))
                require("GPU:0" in result.device and np.allclose(result.numpy(), 4), "GPU matmul failed")
                weights = tf.Variable(tf.random.normal((3, 3, 3, 8)))
                before = weights.numpy().copy()
                with tf.GradientTape() as tape:
                    output = tf.nn.conv2d(tf.ones((2, 16, 16, 3)), weights, 1, "SAME")
                    loss = tf.reduce_mean(tf.square(output))
                gradient = tape.gradient(loss, weights)
                require(gradient is not None and np.isfinite(gradient.numpy()).all(), "Invalid GPU gradients")
                tf.keras.optimizers.SGD(0.01).apply_gradients([(gradient, weights)])
                require(not np.array_equal(before, weights.numpy()), "Optimizer did not update weights")
                @tf.function(jit_compile=True)
                def compiled(x):
                    return tf.math.sin(x) + 1
                x = tf.ones((8,))
                require(np.allclose(compiled(x).numpy(), np.sin(1) + 1), "XLA GPU failed")
            report.update(gpu_verified=True, gpu_count=len(devices), xla_gpu=True)
            if args.cuda_op:
                subprocess.run([sys.executable, str(Path(__file__).resolve()), "--op-worker", str(directory)], check=True, timeout=360)
                report["tensorflow_cuda_op"] = True
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--op-worker":
        cuda_op(Path(sys.argv[2]))
    elif len(sys.argv) == 3 and sys.argv[1] == "--compile-op-worker":
        cuda_op(Path(sys.argv[2]), run=False)
    else:
        main()
