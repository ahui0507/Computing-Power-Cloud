"""Fixed, bounded environment checks executed inside the user's instance."""

import importlib
import importlib.util
import json
import platform
import shutil
import urllib.request

checks = []


def record(name, ok, detail, advice=""):
    checks.append(dict(name=name, ok=bool(ok), detail=str(detail), advice=advice if not ok else ""))


def check_framework(record):
    """Check the installed framework without requiring PyTorch in TensorFlow images."""
    framework = next((name for name in ("torch", "tensorflow") if importlib.util.find_spec(name)), None)
    if framework is None:
        record("CUDA", False, "未安装支持的深度学习框架", "选择 PyTorch 或 TensorFlow 基础镜像。")
        return None
    try:
        module = importlib.import_module(framework)
        record(framework, True, module.__version__)
        if framework == "tensorflow":
            devices = module.config.list_physical_devices("GPU")
            for device in devices:
                module.config.experimental.set_memory_growth(device, True)
            module.config.set_soft_device_placement(False)
            build = module.sysconfig.get_build_info()
            record("CUDA", bool(devices), f"{len(devices)} 张 GPU / CUDA {build.get('cuda_version', '未知')}", "确认已申请 GPU，并使用匹配的 TensorFlow GPU 镜像。")
            for index, device in enumerate(devices):
                try:
                    with module.device(f"/GPU:{index}"):
                        matrix = module.ones((32, 32))
                        result = module.reduce_sum(module.linalg.matmul(matrix, matrix))
                    ok = f"GPU:{index}" in result.device and result.numpy() == 32768
                    name = module.config.experimental.get_device_details(device).get("device_name", device.name)
                    record(f"GPU {index}", ok, name, "检查 CUDA/cuDNN 版本和剩余显存。")
                except Exception as error:
                    record(f"GPU {index}", False, type(error).__name__, "检查 CUDA/cuDNN 版本和剩余显存。")
        else:
            count = module.cuda.device_count()
            record("CUDA", module.cuda.is_available() and count > 0, f"{count} 张 GPU / CUDA {module.version.cuda}", "确认已申请 GPU，并使用匹配的 PyTorch GPU 镜像。")
            for index in range(count):
                try:
                    tensor = module.ones((32, 32), device=f"cuda:{index}")
                    result = (tensor @ tensor).sum().item()
                    record(f"GPU {index}", result == 32768, module.cuda.get_device_name(index), "联系管理员检查 GPU 运行状态。")
                    del tensor
                except Exception as error:
                    record(f"GPU {index}", False, type(error).__name__, "检查 CUDA 版本和剩余显存。")
    except Exception as error:
        record("CUDA", False, f"{framework}: {type(error).__name__}", "使用平台推荐的兼容基础镜像。")
    return framework


def main():
    checks.clear()
    record("Python", True, platform.python_version())
    try:
        numpy = importlib.import_module("numpy")
        record("numpy", True, numpy.__version__)
    except Exception as error:
        record("numpy", False, type(error).__name__, "使用推荐基础镜像或安装 NumPy。")
    framework = check_framework(record)
    tools = ("bash", "git", "curl", "wget", "ssh", "tar", "unzip")
    missing = [tool for tool in tools if not shutil.which(tool)]
    record("Linux 工具", not missing, "缺少：" + ", ".join(missing) if missing else "基础工具齐全", "使用平台推荐的工作镜像。")
    sources = [("Python 软件源", "https://pypi.org/simple/pip/")]
    if framework == "tensorflow":
        sources.append(("TensorFlow 软件源", "https://pypi.org/simple/tensorflow/"))
    elif framework == "torch":
        sources.append(("PyTorch 软件源", "https://download.pytorch.org/whl/"))
    for name, url in sources:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                record(name, response.status == 200, f"HTTP {response.status}", "检查联网状态，或配置校内可达的软件镜像源。")
        except Exception as error:
            record(name, False, type(error).__name__, "稍后重试，或配置校内可达的软件镜像源。")
    print("PLATFORM_CHECK_RESULT=" + json.dumps({"checks": checks}, ensure_ascii=False))


if __name__ == "__main__":
    main()
