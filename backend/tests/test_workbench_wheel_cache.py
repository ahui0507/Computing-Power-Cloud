import hashlib
import base64
import csv
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile
import threading

import pytest


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("workbench_wheels", ROOT / "deploy/workbench/prepare-devel-wheels.py")
wheels = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wheels)
cache_spec = importlib.util.spec_from_file_location("installed_cache", ROOT / "deploy/workbench/prepare-installed-cache.py")
installed_cache = importlib.util.module_from_spec(cache_spec)
cache_spec.loader.exec_module(installed_cache)


def test_range_download_resumes_and_verifies_final_content(tmp_path):
    data = os.urandom(9 * 1024 * 1024)
    ranges = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            start, end = map(int, self.headers["Range"].removeprefix("bytes=").split("-"))
            ranges.append((start, end))
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
            self.send_header("Content-Length", str(end - start + 1))
            self.end_headers()
            self.wfile.write(data[start:end + 1])
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    target = tmp_path / "fixture.whl"
    partial = target.with_suffix(".partial")
    with partial.open("wb") as stream:
        stream.truncate(len(data))
        stream.write(data[:4 * 1024 * 1024])
        stream.flush()
        os.fsync(stream.fileno())
    try:
        wheels.download(f"http://127.0.0.1:{server.server_port}/wheel", target, hashlib.sha256(data).hexdigest(), 2)
        assert target.read_bytes() == data
        assert not partial.exists()
        before = len(ranges)
        wheels.download(f"http://127.0.0.1:{server.server_port}/wheel", target, hashlib.sha256(data).hexdigest(), 2)
        assert len(ranges) == before
        if hasattr(os, "SEEK_HOLE"):
            assert (0, 4 * 1024 * 1024 - 1) not in ranges
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("problem", ["none", "corrupt", "unexpected"])
def test_installed_cache_copies_only_named_packages_and_checks_records(tmp_path, problem):
    contents = {"root/.ssh/private": b"not-for-public-image", "workspace/private.py": b"not-for-public-image"}
    if problem == "unexpected":
        contents[installed_cache.SITE + "torch/personal-secret.txt"] = b"not-a-distribution-file"
    for name, version in (("numpy", "1.26.4"), ("torch", "1.13.1+cu117")):
        package_file = name + "/__init__.py"
        data = b"public software package"
        record_file = f"{name}-{version}.dist-info/RECORD"
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip("=")
        if problem == "corrupt" and name == "torch":
            digest = "incorrect"
        rows = io.StringIO()
        writer = csv.writer(rows)
        writer.writerow([package_file, "sha256=" + digest, len(data)])
        writer.writerow([record_file, "", ""])
        contents[installed_cache.SITE + package_file] = data
        contents[installed_cache.SITE + record_file] = rows.getvalue().encode()
    packed = io.BytesIO()
    with tarfile.open(fileobj=packed, mode="w:gz") as archive:
        for name, data in contents.items():
            member = tarfile.TarInfo(name)
            member.size = len(data)
            member.mode = 0o644
            archive.addfile(member, io.BytesIO(data))
    layer = packed.getvalue()
    layer_digest = hashlib.sha256(layer).hexdigest()
    manifest = json.dumps({"layers": [{"digest": "sha256:" + layer_digest}]}).encode()
    manifest_digest = hashlib.sha256(manifest).hexdigest()
    entries = {"index.json": json.dumps({"manifests": [{"digest": "sha256:" + manifest_digest}]}).encode(),
               "blobs/sha256/" + manifest_digest: manifest, "blobs/sha256/" + layer_digest: layer}
    archive_path = tmp_path / "fixture.oci.tar"
    with tarfile.open(archive_path, "w") as archive:
        for name, data in entries.items():
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    output = tmp_path / "cache"
    if problem == "corrupt":
        with pytest.raises(ValueError, match="RECORD 摘要"):
            installed_cache.prepare(archive_path, output)
    elif problem == "unexpected":
        with pytest.raises(ValueError, match="未记录"):
            installed_cache.prepare(archive_path, output)
    else:
        installed_cache.prepare(archive_path, output)
        manifest = json.loads((output / "manifest.json").read_text())
        assert manifest["verified_record_files"] == 2
        assert not (output / "content/root").exists()
        assert not (output / "content/workspace").exists()
        assert (output / "content/lib/python3.10/site-packages/torch/__init__.py").read_bytes() == b"public software package"
