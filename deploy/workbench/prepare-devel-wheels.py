#!/usr/bin/env python3
"""下载 Linux/Python 3.10 wheel，逐个核对 PyPI 或 PyTorch 官方索引的 SHA256。"""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import time
import urllib.parse
import urllib.request


def sha256(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for data in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            result.update(data)
    return result.hexdigest()


def download(url, target, expected, workers):
    if target.is_file() and sha256(target) == expected:
        print(target.name + ": cached and verified", flush=True)
        return
    with urllib.request.urlopen(urllib.request.Request(url, headers={"Range": "bytes=0-0"}), timeout=30) as response:
        if response.status != 206:
            raise RuntimeError("Download server must support byte ranges")
        total = int(response.headers["Content-Range"].rsplit("/", 1)[1])
    temporary = target.with_suffix(".partial")
    resume = temporary.is_file() and temporary.stat().st_size == total and hasattr(os, "SEEK_HOLE")
    descriptor = os.open(temporary, os.O_CREAT | os.O_RDWR, 0o644)
    os.ftruncate(descriptor, total)
    step = 4 * 1024 * 1024
    bounds = [(start, min(total - 1, start + step - 1)) for start in range(0, total, step)]
    retained = []
    if resume:
        # Linux 稀疏文件中的完整数据区可复用；最终仍校验整个官方 wheel 摘要。
        for pair in bounds:
            try:
                if os.lseek(descriptor, pair[0], os.SEEK_HOLE) > pair[1]:
                    retained.append(pair)
            except OSError:
                break
    bounds = [pair for pair in bounds if pair not in retained]
    if retained:
        print(f"{target.name}: resuming {sum(end-start+1 for start,end in retained)/total:.1%} downloaded ranges", flush=True)
    def piece(pair):
        start, end = pair
        for attempt in range(4):
            try:
                request = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}"})
                with urllib.request.urlopen(request, timeout=60) as response:
                    if response.status != 206 or not response.headers["Content-Range"].startswith(f"bytes {start}-{end}/"):
                        raise RuntimeError("Unexpected range response")
                    offset = start
                    for data in iter(lambda: response.read(256 * 1024), b""):
                        os.pwrite(descriptor, data, offset)
                        offset += len(data)
                    if offset != end + 1:
                        raise RuntimeError("Incomplete range response")
                return end - start + 1
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(1)
    try:
        completed, last_print = sum(end-start+1 for start,end in retained), time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(piece, pair) for pair in bounds]
            for future in concurrent.futures.as_completed(futures):
                completed += future.result()
                if time.monotonic() - last_print > 10 or completed == total:
                    print(f"{target.name}: {completed / total:.1%}", flush=True)
                    last_print = time.monotonic()
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    if sha256(temporary) != expected:
        temporary.unlink()
        raise RuntimeError("Official wheel SHA256 mismatch")
    temporary.replace(target)
    print(target.name + ": official SHA256 verified", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--workers", type=int, default=32, choices=range(1, 33))
    parser.add_argument("--torch-mirror", choices=["aliyun", "sjtu", "nju", "official"], default="aliyun")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen("https://pypi.org/pypi/numpy/1.26.4/json", timeout=30) as response:
        package = json.load(response)
    numpy = next(row for row in package["urls"] if row["filename"] == "numpy-1.26.4-cp310-cp310-manylinux_2_17_x86_64.manylinux2014_x86_64.whl")
    index_url = "https://download.pytorch.org/whl/cu117/torch/"
    torch_name = "torch-1.13.1+cu117-cp310-cp310-linux_x86_64.whl"
    with urllib.request.urlopen(index_url, timeout=30) as response:
        index = response.read().decode()
    link = next(urllib.parse.urljoin(index_url, value) for value in re.findall(r'href="([^"]+)"', index) if torch_name in urllib.parse.unquote(value))
    torch_hash = urllib.parse.parse_qs(urllib.parse.urlsplit(link).fragment)["sha256"][0]
    mirror = {"aliyun": "https://mirrors.aliyun.com/pytorch-wheels/cu117/",
              "sjtu": "https://mirror.sjtu.edu.cn/pytorch-wheels/cu117/",
              "nju": "https://mirrors.nju.edu.cn/pytorch/whl/cu117/",
              "official": "https://download.pytorch.org/whl/cu117/"}[args.torch_mirror]
    packages = [(numpy["filename"], numpy["digests"]["sha256"],
                 numpy["url"].replace("https://files.pythonhosted.org/", "https://pypi.tuna.tsinghua.edu.cn/")),
                (torch_name, torch_hash, mirror + urllib.parse.quote(torch_name))]
    for name, expected, url in packages:
        download(url, output / name, expected, args.workers)
    (output / "SHA256SUMS").write_text("".join(f"{expected}  {name}\n" for name, expected, _ in packages))


if __name__ == "__main__":
    main()
