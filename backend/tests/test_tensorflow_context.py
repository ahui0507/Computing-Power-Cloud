"""Offline builds must reject corrupted packages and exclude unrelated cached wheels."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "tensorflow_context", ROOT / "deploy/workbench/prepare-tensorflow2-context.py"
)
context = importlib.util.module_from_spec(spec)
spec.loader.exec_module(context)


@pytest.fixture
def packages(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    debs = tmp_path / "debs"
    debs.mkdir()
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    deb = debs / "tool_1_amd64.deb"
    deb.write_bytes(b"verified Ubuntu package")
    wheel = wheels / "library-1-py3-none-any.whl"
    wheel.write_bytes(b"verified Python wheel")
    (wheels / "unrelated-1-py3-none-any.whl").write_bytes(b"unrelated cache")
    lock = source / "requirements-tensorflow2.lock"
    lock.write_text("library==1 --hash=sha256:" + hashlib.sha256(wheel.read_bytes()).hexdigest() + "\n")
    for name in (
        "Dockerfile.tensorflow2-offline", "verify_tensorflow2.py",
        "clean-public-image.sh", "build-tensorflow2-offline.sh",
        "cuda-tensorflow2-debs.lock.json",
    ):
        (source / name).write_bytes(b"fixture\r\n")
    (source / "cuda-tensorflow2-debs.lock.json").write_text(json.dumps({"packages": []}))
    manifest = tmp_path / "deb-manifest.json"
    manifest.write_text(json.dumps([{
        "Filename": "pool/main/tool_1_amd64.deb", "Size": deb.stat().st_size,
        "SHA256": hashlib.sha256(deb.read_bytes()).hexdigest(),
    }]))
    installer = tmp_path / "miniconda.sh"
    installer.write_bytes(b"public installer")
    (source / "tensorflow2-base.lock.json").write_text(json.dumps({"miniconda": {"sha256": hashlib.sha256(installer.read_bytes()).hexdigest(), "bytes": installer.stat().st_size}}))
    monkeypatch.setattr(context, "SOURCE", source)
    return debs, manifest, wheels, tmp_path / "context", installer


def test_context_excludes_unlocked_wheels_and_uses_linux_line_endings(packages):
    debs, manifest, wheels, output, installer = packages
    result = context.prepare(debs, manifest, wheels, output, installer)
    assert result["debs"] == result["wheels"] == 1
    assert [p.name for p in (output / "wheels").iterdir()] == ["library-1-py3-none-any.whl"]
    assert (output / "Dockerfile").read_bytes() == b"fixture\n"
    checksums = (output / "SHA256SUMS").read_bytes()
    assert b"\r" not in checksums
    assert b"  debs/tool_1_amd64.deb\n" in checksums
    assert b"  requirements-tensorflow2.lock\n" in checksums


def test_corrupted_ubuntu_package_fails_before_context_creation(packages):
    debs, manifest, wheels, output, installer = packages
    (debs / "tool_1_amd64.deb").write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="checksum mismatch"):
        context.prepare(debs, manifest, wheels, output, installer)
    assert not output.exists()


def test_existing_context_is_not_overwritten(packages):
    debs, manifest, wheels, output, installer = packages
    output.mkdir()
    (output / "important.txt").write_text("keep")
    with pytest.raises(FileExistsError):
        context.prepare(debs, manifest, wheels, output, installer)
    assert (output / "important.txt").read_text() == "keep"


def test_missing_locked_cuda_package_fails_before_context_creation(packages):
    debs, manifest, wheels, output, installer = packages
    (context.SOURCE / "cuda-tensorflow2-debs.lock.json").write_text(json.dumps({
        "packages": [{"Filename": "cuda_missing.deb", "SHA256": "0" * 64}],
    }))
    with pytest.raises(ValueError, match="locked CUDA package"):
        context.prepare(debs, manifest, wheels, output, installer)
    assert not output.exists()


def test_corrupted_python_installer_fails_before_context_creation(packages):
    debs, manifest, wheels, output, installer = packages
    installer.write_bytes(b"corrupted installer")
    with pytest.raises(ValueError, match="Miniconda installer checksum mismatch"):
        context.prepare(debs, manifest, wheels, output, installer)
    assert not output.exists()
