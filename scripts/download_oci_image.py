"""Download a public Docker Hub linux/amd64 image as a verified, resumable OCI archive."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import re
import tarfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme != "https":
            raise ValueError("Image downloads require HTTPS")
        redirected = super().redirect_request(request, fp, code, msg, headers, newurl)
        if (
            urllib.parse.urlsplit(request.full_url).netloc
            != urllib.parse.urlsplit(newurl).netloc
        ):
            redirected.remove_header("Authorization")
        return redirected


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(4 * 1024**2):
            digest.update(chunk)
    return digest.hexdigest()


def download(repository, reference, output, workers=6):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    blobs = output / "blobs/sha256"
    blobs.mkdir(parents=True, exist_ok=True)
    opener = urllib.request.build_opener(SafeRedirect())
    bearer = None
    lock = threading.Lock()
    accept = ",".join(
        [
            "application/vnd.oci.image.index.v1+json",
            "application/vnd.docker.distribution.manifest.list.v2+json",
            "application/vnd.oci.image.manifest.v1+json",
            "application/vnd.docker.distribution.manifest.v2+json",
        ]
    )

    def get(path, extra=None):
        nonlocal bearer
        for attempt in range(2):
            with lock:
                if bearer is None:
                    query = urllib.parse.urlencode(
                        {
                            "service": "registry.docker.io",
                            "scope": f"repository:{repository}:pull",
                        }
                    )
                    with opener.open(
                        "https://auth.docker.io/token?" + query, timeout=30
                    ) as response:
                        bearer = json.load(response)["token"]
                token = bearer
            try:
                return opener.open(
                    urllib.request.Request(
                        f"https://registry-1.docker.io/v2/{repository}/{path}",
                        headers={
                            "Authorization": "Bearer " + token,
                            "Accept": accept,
                            **(extra or {}),
                        },
                    ),
                    timeout=90,
                )
            except urllib.error.HTTPError as error:
                if error.code != 401 or attempt:
                    raise
                with lock:
                    if bearer == token:
                        bearer = None

    with get("manifests/" + reference) as response:
        raw = response.read()
        advertised = response.headers.get("Docker-Content-Digest")
    if advertised and advertised != "sha256:" + hashlib.sha256(raw).hexdigest():
        raise ValueError("Registry manifest digest mismatch")
    manifest = json.loads(raw)
    if "manifests" in manifest:
        selected = next(
            d
            for d in manifest["manifests"]
            if d.get("platform", {}).get("architecture") == "amd64"
            and d.get("platform", {}).get("os") == "linux"
        )
        with get("manifests/" + selected["digest"]) as response:
            raw = response.read()
        if "sha256:" + hashlib.sha256(raw).hexdigest() != selected["digest"]:
            raise ValueError("Platform manifest digest mismatch")
        manifest = json.loads(raw)
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    (blobs / digest.split(":")[1]).write_bytes(raw)
    descriptors = [manifest["config"], *manifest["layers"]]
    total = sum(d["size"] for d in descriptors)
    print(
        f"Manifest {digest}; {len(manifest['layers'])} layers; {total / 1024**3:.2f} GiB",
        flush=True,
    )
    (output / "download-manifest.json").write_text(
        json.dumps(
            {
                "repository": repository,
                "reference": reference,
                "digest": digest,
                "bytes": total,
                "descriptors": descriptors,
            },
            indent=2,
        )
    )
    completed = 0

    for desc in descriptors:
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", desc["digest"]):
            raise ValueError("Unsupported digest")
        target = blobs / desc["digest"].split(":")[1]
        if (
            target.is_file()
            and target.stat().st_size == desc["size"]
            and sha256(target) == desc["digest"].split(":")[1]
        ):
            completed += desc["size"]
            print(f"Verified cached layer; total {completed / total:.1%}", flush=True)
            continue
        parts = output / ".parts" / target.name
        parts.mkdir(parents=True, exist_ok=True)
        chunk_size = 32 * 1024**2
        ranges = [
            (i, start, min(desc["size"], start + chunk_size))
            for i, start in enumerate(range(0, desc["size"], chunk_size))
        ]

        def piece(spec):
            index, start, end = spec
            path = parts / str(index)
            if path.exists() and path.stat().st_size == end - start:
                return end - start
            for attempt in range(5):
                try:
                    with get(
                        "blobs/" + desc["digest"], {"Range": f"bytes={start}-{end - 1}"}
                    ) as response, path.with_suffix(".partial").open("wb") as stream:
                        if desc["size"] > chunk_size and (
                            response.status != 206
                            or not response.headers.get("Content-Range", "").startswith(
                                f"bytes {start}-{end - 1}/"
                            )
                        ):
                            raise ValueError(
                                "Registry blob server does not support exact ranges"
                            )
                        received = 0
                        while chunk := response.read(1024**2):
                            received += len(chunk)
                            if received > end - start:
                                raise ValueError("Unexpected blob response length")
                            stream.write(chunk)
                    if received != end - start:
                        raise ValueError("Incomplete blob range")
                    path.with_suffix(".partial").replace(path)
                    return received
                except Exception:
                    if attempt == 4:
                        raise
                    time.sleep(min(2**attempt, 8))

        last = time.monotonic()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for future in as_completed([pool.submit(piece, spec) for spec in ranges]):
                completed += future.result()
                if time.monotonic() - last >= 10:
                    print(
                        f"Image download: {completed / total:.1%} ({completed / 1024**3:.2f}/{total / 1024**3:.2f} GiB)",
                        flush=True,
                    )
                    last = time.monotonic()
        temporary = target.with_suffix(".partial")
        with temporary.open("wb") as stream:
            for index, _, _ in ranges:
                with (parts / str(index)).open("rb") as part:
                    while chunk := part.read(4 * 1024**2):
                        stream.write(chunk)
        if (
            temporary.stat().st_size != desc["size"]
            or sha256(temporary) != desc["digest"].split(":")[1]
        ):
            raise ValueError(
                "Blob SHA256 mismatch; discard this blob's .parts directory before retrying"
            )
        temporary.replace(target)
        print(f"Verified {desc['digest']}; total {completed / total:.1%}", flush=True)

    with (blobs / manifest["config"]["digest"].split(":")[1]).open() as stream:
        config = json.load(stream)
    if config.get("os") != "linux" or config.get("architecture") != "amd64":
        raise ValueError("Unexpected image platform")
    name = f"docker.io/{repository}:{reference}"
    index = {
        "schemaVersion": 2,
        "manifests": [
            {
                "mediaType": manifest.get(
                    "mediaType", "application/vnd.docker.distribution.manifest.v2+json"
                ),
                "digest": digest,
                "size": len(raw),
                "platform": {"os": "linux", "architecture": "amd64"},
                "annotations": {
                    "io.containerd.image.name": name,
                    "org.opencontainers.image.ref.name": name,
                },
            }
        ],
    }
    (output / "index.json").write_text(json.dumps(index))
    (output / "oci-layout").write_text('{"imageLayoutVersion":"1.0.0"}')
    archive = output.with_suffix(".tar")
    with tarfile.open(archive.with_suffix(".partial"), "w") as tar:
        for path in [output / "oci-layout", output / "index.json", *blobs.iterdir()]:
            if path.is_file() and path.suffix != ".partial":
                tar.add(path, arcname=path.relative_to(output).as_posix())
    archive.with_suffix(".partial").replace(archive)
    report = {
        "image": name,
        "manifest_digest": digest,
        "archive": str(archive),
        "bytes": archive.stat().st_size,
        "sha256": sha256(archive),
    }
    archive.with_suffix(".json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository")
    parser.add_argument("reference")
    parser.add_argument("output")
    parser.add_argument("--workers", type=int, default=6, choices=range(1, 17))
    args = parser.parse_args()
    download(args.repository, args.reference, args.output, args.workers)
