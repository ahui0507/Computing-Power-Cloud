#!/usr/bin/env python3
"""从管理员验收 OCI 中提取指定公开软件包缓存，核对层摘要及 RECORD；不复制其他目录。"""
import argparse
import base64
import csv
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import posixpath
import shutil
import tarfile
import tempfile

PREFIX = "opt/campus-python/"
SITE = PREFIX + "lib/python3.10/site-packages/"
PACKAGES = {"numpy", "numpy.libs", "numpy-1.26.4.dist-info", "torch", "torchgen", "functorch", "caffe2", "torch-1.13.1+cu117.dist-info"}
SCRIPTS = {"torchrun", "convert-caffe2-to-onnx", "convert-onnx-to-caffe2", "f2py", "f2py3", "f2py3.10"}


def allowed(name):
    name = name[2:] if name.startswith("./") else name
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or name.endswith(".pyc") or "__pycache__" in path.parts:
        return False
    if name.startswith(SITE):
        relative = name[len(SITE):]
        return relative.split("/", 1)[0] in PACKAGES and not name.endswith("/direct_url.json")
    return name.startswith(PREFIX + "bin/") and name.rsplit("/", 1)[1] in SCRIPTS


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def validate_records(content):
    verified = 0
    included = set()
    package_root = content / "lib/python3.10/site-packages"
    for distribution in ("numpy-1.26.4.dist-info", "torch-1.13.1+cu117.dist-info"):
        record = package_root / distribution / "RECORD"
        rows = list(csv.reader(io.StringIO(record.read_text())))
        kept = []
        for relative, expected, size in rows:
            absolute = posixpath.normpath(SITE + relative)
            if not allowed(absolute):
                continue
            path = content / absolute[len(PREFIX):]
            included.add(path)
            if not path.is_file():
                raise ValueError("缓存缺少 RECORD 文件: " + relative)
            if expected:
                method, encoded = expected.split("=", 1)
                if method != "sha256" or base64.urlsafe_b64encode(bytes.fromhex(digest(path))).decode().rstrip("=") != encoded:
                    raise ValueError("软件包 RECORD 摘要不匹配: " + relative)
                if size and path.stat().st_size != int(size):
                    raise ValueError("软件包 RECORD 文件长度不匹配")
                verified += 1
            elif not relative.endswith("/RECORD"):
                raise ValueError("软件包文件缺少摘要")
            kept.append([relative, expected, size])
        with record.open("w", newline="") as output:
            csv.writer(output).writerows(kept)
    if any(path not in included for path in content.rglob("*") if path.is_file()):
        raise ValueError("缓存含未记录的软件包文件，不能用于公共镜像")
    return verified


def prepare(archive_path, output):
    output = Path(output)
    if output.exists():
        raise ValueError("缓存目标已存在，请使用空的新目录")
    output.mkdir(parents=True, mode=0o700)
    content = output / "content"
    content.mkdir()
    with tarfile.open(archive_path) as archive:
        index = json.load(archive.extractfile("index.json"))
        descriptor = index["manifests"][0]
        manifest_bytes = archive.extractfile("blobs/sha256/" + descriptor["digest"].split(":")[1]).read()
        if "sha256:" + hashlib.sha256(manifest_bytes).hexdigest() != descriptor["digest"]:
            raise ValueError("镜像清单摘要不匹配")
        manifest = json.loads(manifest_bytes)
        layer = manifest["layers"][-1]
        with tempfile.TemporaryFile() as packed:
            blob = archive.extractfile("blobs/sha256/" + layer["digest"].split(":")[1])
            expected = hashlib.sha256()
            for chunk in iter(lambda: blob.read(4 * 1024 * 1024), b""):
                packed.write(chunk)
                expected.update(chunk)
            if "sha256:" + expected.hexdigest() != layer["digest"]:
                raise ValueError("软件缓存层摘要不匹配")
            packed.seek(0)
            with tarfile.open(fileobj=packed, mode="r|*") as delta:
                for member in delta:
                    name = member.name[2:] if member.name.startswith("./") else member.name
                    if not allowed(name) or member.isdir():
                        continue
                    if not member.isfile():
                        raise ValueError("软件包缓存中不接受链接或特殊文件")
                    target = content / name[len(PREFIX):]
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with delta.extractfile(member) as source, target.open("wb") as destination:
                        shutil.copyfileobj(source, destination)
                    target.chmod(member.mode & 0o755)
    count = validate_records(content)
    files = {str(path.relative_to(content)): digest(path) for path in content.rglob("*") if path.is_file()}
    result = {"format": 1, "source_manifest": descriptor["digest"], "source_layer": layer["digest"],
              "verified_record_files": count, "files": files}
    (output / "manifest.json").write_text(json.dumps(result, indent=2))
    print(f"Verified installed public package cache: {count} RECORD hashes, {len(files)} files")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    prepare(args.archive, args.output)


if __name__ == "__main__":
    main()
