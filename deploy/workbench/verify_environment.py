#!/opt/campus-python/bin/python3
"""检查公共开发环境；构建时核对工具和编译器，实例中可追加 GPU 与联网实测。"""
import argparse
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.request

COMMANDS = "bash ls find grep sed awk less nano vim curl wget git ssh sshd rsync zip unzip tar gzip bzip2 xz file ps pgrep htop tmux ip ping dig ifconfig lsof traceroute nc gcc g++ make cmake pkg-config jupyter-lab".split()


def verify(require_gpu=False, check_network=False):
    missing = [name for name in COMMANDS if shutil.which(name) is None]
    if missing:
        raise RuntimeError("Missing tools: " + ", ".join(missing))
    if sys.version_info[:2] != (3, 10):
        raise RuntimeError("Expected Python 3.10")
    import numpy
    import torch
    if numpy.__version__ != "1.26.4" or torch.__version__ != "1.13.1+cu117" or torch.version.cuda != "11.7":
        raise RuntimeError("Unexpected NumPy / PyTorch / CUDA version")
    with tempfile.TemporaryDirectory(prefix="campus-compiler-") as temporary:
        source = Path(temporary) / "hello.c"
        executable = Path(temporary) / "hello"
        source.write_text('#include <stdio.h>\nint main(void) { puts("compiler-42"); return 0; }\n')
        subprocess.run(["gcc", str(source), "-o", str(executable)], check=True, capture_output=True)
        if subprocess.check_output([str(executable)]).decode().strip() != "compiler-42":
            raise RuntimeError("C compiler execution failed")
    result = {"python": sys.version.split()[0], "numpy": numpy.__version__, "torch": torch.__version__,
              "cuda_runtime": torch.version.cuda, "tool_count": len(COMMANDS), "tools": COMMANDS,
              "c_compile_and_execute": True}
    if require_gpu:
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA GPU unavailable")
        answer = torch.arange(10, device="cuda").sum().item()
        if answer != 45:
            raise RuntimeError("CUDA result mismatch")
        result.update(gpu=torch.cuda.get_device_name(0), cuda_result=answer)
    if check_network:
        network = {}
        for host, url in [("pypi.org", "https://pypi.org/simple/packaging/"),
                          ("download.pytorch.org", "https://download.pytorch.org/whl/cu117/torch/")]:
            socket.getaddrinfo(host, 443)
            with urllib.request.urlopen(url, timeout=30) as response:
                if response.status != 200:
                    raise RuntimeError("Download site unavailable")
                network[host] = response.status
        result["network"] = network
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-gpu", action="store_true")
    parser.add_argument("--check-network", action="store_true")
    parser.add_argument("--report")
    args = parser.parse_args()
    result = verify(args.require_gpu, args.check_network)
    serialized = json.dumps(result, ensure_ascii=False, indent=2)
    if args.report:
        Path(args.report).write_text(serialized, encoding="utf-8")
    print(serialized)


if __name__ == "__main__":
    main()
