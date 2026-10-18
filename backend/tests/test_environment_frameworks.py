"""The platform checker must accept TensorFlow GPUs and reject CPU fallback."""
from contextlib import contextmanager
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace


SOURCE = Path(__file__).resolve().parents[1] / "app/assets/environment_check.py"
spec = importlib.util.spec_from_file_location("workbench_environment_checker", SOURCE)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def collect():
    rows = []

    def record(name, ok, detail, advice=""):
        rows.append({"name": name, "ok": bool(ok), "detail": detail})

    return rows, record


def tensorflow(monkeypatch, fallback=False):
    tf = ModuleType("tensorflow")
    tf.__version__ = "2.18.1"
    tf.current_device = "/CPU:0"
    tf.growth = []
    tf.placements = []
    devices = [SimpleNamespace(name=f"GPU:{i}") for i in range(2)]
    tf.config = SimpleNamespace(
        list_physical_devices=lambda name: devices,
        set_soft_device_placement=tf.placements.append,
        experimental=SimpleNamespace(
            set_memory_growth=lambda device, enabled: tf.growth.append((device.name, enabled)),
            get_device_details=lambda device: {"device_name": "A100"},
        ),
    )
    tf.sysconfig = SimpleNamespace(get_build_info=lambda: {"cuda_version": "12.5.1"})

    @contextmanager
    def device(name):
        previous = tf.current_device
        tf.current_device = name
        try:
            yield
        finally:
            tf.current_device = previous

    tf.device = device
    tf.ones = lambda shape: SimpleNamespace(device="/CPU:0" if fallback else tf.current_device, numpy=lambda: 32768)
    tf.linalg = SimpleNamespace(matmul=lambda left, right: left)
    tf.reduce_sum = lambda tensor: tensor
    monkeypatch.setitem(sys.modules, "tensorflow", tf)
    monkeypatch.setattr(checker.importlib.util, "find_spec", lambda name: object() if name == "tensorflow" else None)
    return tf


def test_tensorflow_only_image_checks_both_allocated_gpus(monkeypatch):
    tf = tensorflow(monkeypatch)
    rows, record = collect()
    assert checker.check_framework(record) == "tensorflow"
    assert [row["name"] for row in rows] == ["tensorflow", "CUDA", "GPU 0", "GPU 1"]
    assert all(row["ok"] for row in rows)
    assert tf.growth == [("GPU:0", True), ("GPU:1", True)]
    assert tf.placements == [False]


def test_tensorflow_cpu_fallback_is_not_reported_as_gpu_success(monkeypatch):
    tensorflow(monkeypatch, fallback=True)
    rows, record = collect()
    checker.check_framework(record)
    gpu_rows = [row for row in rows if row["name"].startswith("GPU ")]
    assert len(gpu_rows) == 2 and all(not row["ok"] for row in gpu_rows)


def test_existing_pytorch_gpu_check_remains_supported(monkeypatch):
    class Tensor:
        def __matmul__(self, other):
            return self

        def sum(self):
            return SimpleNamespace(item=lambda: 32768)

    torch = ModuleType("torch")
    torch.__version__ = "2.5.1"
    torch.version = SimpleNamespace(cuda="12.4")
    torch.cuda = SimpleNamespace(device_count=lambda: 1, is_available=lambda: True, get_device_name=lambda index: "A100")
    torch.ones = lambda shape, device: Tensor()
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setattr(checker.importlib.util, "find_spec", lambda name: object() if name == "torch" else None)
    rows, record = collect()
    assert checker.check_framework(record) == "torch"
    assert [row["name"] for row in rows] == ["torch", "CUDA", "GPU 0"]
    assert all(row["ok"] for row in rows)


def test_missing_framework_reports_a_framework_neutral_failure(monkeypatch):
    monkeypatch.setattr(checker.importlib.util, "find_spec", lambda name: None)
    rows, record = collect()
    assert checker.check_framework(record) is None
    assert len(rows) == 1 and rows[0]["name"] == "CUDA" and not rows[0]["ok"]
