"""Fixed, bounded environment checks executed inside the user's instance."""

import importlib
import json
import platform
import shutil
import urllib.request

checks = []


def record(name, ok, detail, advice=""):
    checks.append(dict(name=name, ok=bool(ok), detail=str(detail), advice=advice if not ok else ""))


record("Python", True, platform.python_version())
for name in ("numpy", "torch"):
    try:
        module = importlib.import_module(name)
        record(name, True, module.__version__)
    except Exception as error:
        record(
            name,
            False,
            type(error).__name__,
            "使用推荐的基础镜像，或通过 pip 安装与 GPU 兼容的版本。",
        )
try:
    import torch

    count = torch.cuda.device_count()
    record(
        "CUDA",
        torch.cuda.is_available() and count > 0,
        f"{count} 张 GPU / CUDA {torch.version.cuda}",
        "确认已申请 GPU，K80 推荐使用 PyTorch 1.13.1 + CUDA 11.7；持续异常请联系管理员。",
    )
    for index in range(count):
        try:
            tensor = torch.ones((32, 32), device=f"cuda:{index}")
            result = (tensor @ tensor).sum().item()
            record(
                f"GPU {index}",
                result == 32768,
                torch.cuda.get_device_name(index),
                "联系管理员检查 GPU 运行状态。",
            )
            del tensor
        except Exception as error:
            record(
                f"GPU {index}",
                False,
                type(error).__name__,
                "检查 CUDA 版本和剩余显存。",
            )
except ImportError:
    record("CUDA", False, "未安装 PyTorch", "先安装兼容的 PyTorch。")
tools = ("bash", "git", "curl", "wget", "ssh", "tar", "unzip")
missing = [tool for tool in tools if not shutil.which(tool)]
record(
    "Linux 工具",
    not missing,
    "缺少：" + ", ".join(missing) if missing else "基础工具齐全",
    "使用平台推荐的工作镜像。",
)
for name, url in (
    ("Python 软件源", "https://pypi.org/simple/pip/"),
    ("PyTorch 软件源", "https://download.pytorch.org/whl/"),
):
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            record(
                name,
                response.status == 200,
                f"HTTP {response.status}",
                "检查联网状态，或配置校内可达的软件镜像源。",
            )
    except Exception as error:
        record(name, False, type(error).__name__, "稍后重试，或配置校内可达的软件镜像源。")
print("PLATFORM_CHECK_RESULT=" + json.dumps({"checks": checks}, ensure_ascii=False))
