#!/bin/sh
set -eu
WHEEL_SOURCE=${1:?Usage: build-devel.sh WHEEL_DIRECTORY [IMAGE_TAG] [BASE_IMAGE]}
IMAGE_TAG=${2:-campus-workbench:20261012}
BASE_IMAGE=${3:-campus-workbench:20261010}
PACKAGE_CACHE=${4:-}
SOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
docker image inspect "$BASE_IMAGE" >/dev/null
BUILD_CONTEXT=$(mktemp -d /tmp/campus-devel-build.XXXXXXXX)
cleanup() {
    case "$BUILD_CONTEXT" in /tmp/campus-devel-build.*) rm -rf "$BUILD_CONTEXT";; esac
}
trap cleanup EXIT HUP INT TERM
cp "$SOURCE_DIR/Dockerfile.devel" "$BUILD_CONTEXT/Dockerfile"
cp "$SOURCE_DIR/requirements-devel.txt" "$SOURCE_DIR/verify_environment.py" "$SOURCE_DIR/shell-tools.sh" "$BUILD_CONTEXT/"
cp "$SOURCE_DIR/clean-public-image.sh" "$BUILD_CONTEXT/"
if [ -n "$PACKAGE_CACHE" ]; then
    python3 - "$PACKAGE_CACHE" "$BUILD_CONTEXT" "$SOURCE_DIR" <<'PY'
import hashlib,importlib.util,json,shutil,sys
from pathlib import Path
cache,context,source_dir=map(Path,sys.argv[1:])
spec=importlib.util.spec_from_file_location('installed_cache',source_dir/'prepare-installed-cache.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
module.validate_records(cache/'content')
manifest=json.loads((cache/'manifest.json').read_text())
actual_files={str(path.relative_to(cache/'content')) for path in (cache/'content').rglob('*') if path.is_file()}
if actual_files!=set(manifest['files']):raise ValueError('Unexpected package cache files')
for name,expected in manifest['files'].items():
    if Path(name).is_absolute() or '..' in Path(name).parts:raise ValueError('Invalid cache path')
    path=cache/'content'/name
    if path.is_symlink():raise ValueError('Package cache must contain regular files')
    actual=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(4*1024*1024),b''):actual.update(chunk)
    if actual.hexdigest()!=expected:raise ValueError('Package cache checksum mismatch')
shutil.copytree(cache/'content',context/'package-cache')
source=(context/'Dockerfile').read_text()
marker='FROM ${BASE_IMAGE}\n'
assert source.count(marker)==1
runtime=source.split(marker,1)[1].replace('COPY --from=python-environment /opt/campus-python /opt/campus-python',
    'COPY package-cache/ /opt/campus-python/')
(context/'Dockerfile').write_text('ARG BASE_IMAGE=campus-workbench:20261010\n'+marker+runtime)
PY
else
    test -f "$WHEEL_SOURCE/numpy-1.26.4-cp310-cp310-manylinux_2_17_x86_64.manylinux2014_x86_64.whl"
    test -f "$WHEEL_SOURCE/torch-1.13.1+cu117-cp310-cp310-linux_x86_64.whl"
    mkdir "$BUILD_CONTEXT/wheels"
    cp "$WHEEL_SOURCE/numpy-1.26.4-cp310-cp310-manylinux_2_17_x86_64.manylinux2014_x86_64.whl" "$BUILD_CONTEXT/wheels/"
    cp "$WHEEL_SOURCE/torch-1.13.1+cu117-cp310-cp310-linux_x86_64.whl" "$BUILD_CONTEXT/wheels/"
fi
docker build --network host --build-arg BASE_IMAGE="$BASE_IMAGE" -t "$IMAGE_TAG" "$BUILD_CONTEXT"
