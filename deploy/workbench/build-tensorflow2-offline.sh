#!/bin/sh
set -eu
export DOCKER_BUILDKIT=1
context=${1:?Usage: build-tensorflow2-offline.sh CONTEXT [IMAGE_TAG]}
tag=${2:-campus-workbench:tensorflow2-devel-20261017}
base=ubuntu:22.04
expected=sha256:cee13550f97b8a595506e8e4ca74263ba44924248779a4ba4f942e197652acff
actual=$(docker image inspect "$base" --format '{{.Id}}')
test "$actual" = "$expected" || { printf 'Ubuntu base digest mismatch\n' >&2; exit 1; }
if docker image inspect "$tag" >/dev/null 2>&1; then
    printf 'Target tag exists; use a new release tag\n' >&2
    exit 1
fi
docker build --pull=false --network none --build-arg BASE_IMAGE="$base" -f "$context/Dockerfile" -t "$tag" "$context"
docker run --rm --network none --env NVIDIA_VISIBLE_DEVICES=void --cpus 2 --memory 6g "$tag" campus-check --compile-cuda
docker run --rm -i --network none --env NVIDIA_VISIBLE_DEVICES=void --cpus 1 --memory 512m "$tag" python - <<'PY'
from pathlib import Path
import importlib.util
import json
assert importlib.util.find_spec('torch') is None, 'Unexpected PyTorch installation'
assert not list(Path('/etc/ssh').glob('ssh_host_*'))
assert not Path('/root/.bash_history').exists()
for name in ('/workspace', '/data'):
    assert not any(Path(name).iterdir()), name
assert not list(Path('/opt/offline').rglob('*.deb'))
assert not list(Path('/opt/offline').rglob('*.whl'))
installer = Path('/opt/offline/miniconda.sh')
assert not installer.exists() or installer.stat().st_size == 0
print(json.dumps({'public_image_clean': True, 'offline_payload_excluded': True, 'framework': 'tensorflow'}))
PY
