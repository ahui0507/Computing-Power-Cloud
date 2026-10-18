"""Assemble an offline context from verified Ubuntu packages and hash-locked wheels."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil


SOURCE = Path(__file__).resolve().parent


def digest(path):
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(4 * 1024**2):
            checksum.update(chunk)
    return checksum.hexdigest()


def prepare(debs, manifest, wheels, output, miniconda):
    lock = SOURCE / "requirements-tensorflow2.lock"
    wheel_hashes = set(re.findall(r"--hash=sha256:([0-9a-f]{64})", lock.read_text()))
    records = json.loads(manifest.read_text(encoding="utf-8-sig"))
    cuda_lock = json.loads((SOURCE / "cuda-tensorflow2-debs.lock.json").read_text())
    provided = {Path(row["Filename"]).name: row["SHA256"] for row in records}
    for row in cuda_lock["packages"]:
        name = Path(row["Filename"]).name
        if provided.get(name) != row["SHA256"]:
            raise ValueError(f"Missing or mismatched locked CUDA package: {name}")
    deb_paths = []
    seen = set()
    for record in records:
        name = Path(record["Filename"]).name
        if name in seen or not name.endswith(".deb"):
            raise ValueError(f"Invalid or duplicated Ubuntu package: {name}")
        seen.add(name)
        path = debs / name
        if path.stat().st_size != int(record["Size"]) or digest(path) != record["SHA256"]:
            raise ValueError(f"Ubuntu package checksum mismatch: {name}")
        deb_paths.append(path)
    wheel_paths = sorted(wheels.glob("*.whl"))
    if not deb_paths or not wheel_paths:
        raise ValueError("Both verified Ubuntu packages and Python wheels are required")
    # Ignore cached wheels outside this lock, but never copy them into the context.
    wheel_paths = [path for path in wheel_paths if digest(path) in wheel_hashes]
    if not wheel_paths:
        raise ValueError("No wheels match the development lock")
    base = json.loads((SOURCE / "tensorflow2-base.lock.json").read_text())
    installer = base["miniconda"]
    if miniconda.stat().st_size != installer["bytes"] or digest(miniconda) != installer["sha256"]:
        raise ValueError("Miniconda installer checksum mismatch")
    output.mkdir(parents=True, exist_ok=False)
    checksums = []
    for label, paths in (("offline-debs", deb_paths), ("wheels", wheel_paths)):
        (output / label).mkdir()
        for path in paths:
            target = output / label / path.name
            shutil.copy2(path, target)
            checksum_label = "debs" if label == "offline-debs" else label
            checksums.append(f"{digest(target)}  {checksum_label}/{path.name}")
    for name, target_name in (
        ("Dockerfile.tensorflow2-offline", "Dockerfile"),
        ("requirements-tensorflow2.lock", "requirements-tensorflow2.lock"),
        ("cuda-tensorflow2-debs.lock.json", "cuda-tensorflow2-debs.lock.json"),
        ("tensorflow2-base.lock.json", "tensorflow2-base.lock.json"),
        ("verify_tensorflow2.py", "verify_tensorflow2.py"),
        ("clean-public-image.sh", "clean-public-image.sh"),
        ("build-tensorflow2-offline.sh", "build-tensorflow2-offline.sh"),
    ):
        target = output / target_name
        target.write_bytes((SOURCE / name).read_bytes().replace(b"\r\n", b"\n"))
        if target_name.endswith(".lock"):
            checksums.append(f"{digest(target)}  {target_name}")
    shutil.copy2(miniconda, output / "miniconda.sh")
    checksums.append(f"{digest(output / 'miniconda.sh')}  miniconda.sh")
    (output / "SHA256SUMS").write_bytes(("\n".join(checksums) + "\n").encode())
    return {"context": str(output.resolve()), "debs": len(deb_paths), "wheels": len(wheel_paths)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--debs", required=True, type=Path)
    parser.add_argument("--deb-manifest", required=True, type=Path)
    parser.add_argument("--wheels", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--miniconda", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.debs, args.deb_manifest, args.wheels, args.output, args.miniconda)))


if __name__ == "__main__":
    main()
