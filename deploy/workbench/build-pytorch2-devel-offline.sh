#!/bin/sh
# Verify the official base before building a new, immutable development release.
set -eu
export DOCKER_BUILDKIT=1
context=${1:?Usage: build-pytorch2-devel-offline.sh CONTEXT [IMAGE_TAG]}
tag=${2:-campus-workbench:pytorch2-devel-20261017}
base=pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime
expected=sha256:946241f40f56c5ac17b12be451a9ff6bf7163acaac37d1f15bbc7404f4394e57
actual=$(docker image inspect "$base" --format '{{.Id}}')
test "$actual" = "$expected" || { printf 'Base image config digest does not match the verified download\n' >&2; exit 1; }
if docker image inspect "$tag" >/dev/null 2>&1; then
    printf 'Target tag already exists; use a new release tag\n' >&2
    exit 1
fi
docker build --pull=false --network none --build-arg BASE_IMAGE="$base" \
    -f "$context/Dockerfile" -t "$tag" "$context"
docker run --rm --network none --env NVIDIA_VISIBLE_DEVICES=void --cpus 2 --memory 4g \
    "$tag" campus-check --compile-cuda
docker run --rm -i --network none --env NVIDIA_VISIBLE_DEVICES=void --cpus 1 --memory 512m \
    "$tag" python - <<'PY'
from pathlib import Path
import json
assert not list(Path('/etc/ssh').glob('ssh_host_*')), 'Shared SSH host keys in image'
assert not Path('/root/.bash_history').exists(), 'Shell history in image'
for name in ('/workspace', '/data'):
    assert not any(Path(name).iterdir()), f'Files in public {name}'
assert not list(Path('/opt/offline').rglob('*.deb')), 'DEB payload retained in image'
assert not list(Path('/opt/offline').rglob('*.whl')), 'Wheel payload retained in image'
print(json.dumps({'public_image_clean': True, 'offline_payload_excluded': True}))
PY
