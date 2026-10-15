#!/bin/sh
set -eu
PYTHON_SOURCE=${1:-/opt/platform-python310}
WHEEL_SOURCE=${2:-/home/REPLACE_SERVICE_USER/platform-wheels}
IMAGE_TAG=${3:-campus-workbench:20261010}
SOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
test -x "$PYTHON_SOURCE/bin/python3"
test -d "$WHEEL_SOURCE"
BUILD_CONTEXT=$(mktemp -d /tmp/campus-build.XXXXXXXX)
cleanup() {
    case "$BUILD_CONTEXT" in /tmp/campus-build.*) rm -rf "$BUILD_CONTEXT";; esac
}
trap cleanup EXIT HUP INT TERM
cp "$SOURCE_DIR/Dockerfile" "$BUILD_CONTEXT/Dockerfile"
cp "$SOURCE_DIR/clean-public-image.sh" "$BUILD_CONTEXT/"
cp -a "$PYTHON_SOURCE" "$BUILD_CONTEXT/python"
cp -a "$WHEEL_SOURCE" "$BUILD_CONTEXT/wheels"
docker build --network host -t "$IMAGE_TAG" "$BUILD_CONTEXT"
