#!/bin/sh
set -eu
IMAGE_TAG=${1:-campus-workbench:20261012}
BASE_IMAGE=${2:-campus-workbench:20261011}
SOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
docker image inspect "$BASE_IMAGE" >/dev/null
BUILD_CONTEXT=$(mktemp -d /tmp/campus-clean-build.XXXXXXXX)
cleanup() {
    case "$BUILD_CONTEXT" in /tmp/campus-clean-build.*) rm -rf "$BUILD_CONTEXT";; esac
}
trap cleanup EXIT HUP INT TERM
cp "$SOURCE_DIR/Dockerfile.clean" "$BUILD_CONTEXT/Dockerfile"
cp "$SOURCE_DIR/clean-public-image.sh" "$BUILD_CONTEXT/"
docker build --network none --build-arg BASE_IMAGE="$BASE_IMAGE" -t "$IMAGE_TAG" "$BUILD_CONTEXT"
