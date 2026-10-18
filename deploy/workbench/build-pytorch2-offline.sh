#!/bin/sh
# Context contains offline-debs/, wheels/, the hash lock, SHA256SUMS and the verifier.
set -eu
context=${1:?Usage: build-pytorch2-offline.sh CONTEXT [IMAGE_TAG]}
tag=${2:-campus-workbench:pytorch2-20261016}
base=pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime
expected=sha256:946241f40f56c5ac17b12be451a9ff6bf7163acaac37d1f15bbc7404f4394e57
actual=$(docker image inspect "$base" --format '{{.Id}}')
test "$actual" = "$expected" || { printf 'Base image config digest does not match the verified download\n' >&2; exit 1; }
docker build --pull=false --network none --build-arg BASE_IMAGE="$base" -f "$context/Dockerfile" -t "$tag" "$context"
docker run --rm --network none --env NVIDIA_VISIBLE_DEVICES=void --cpus 2 --memory 3g "$tag" python /usr/local/share/campus-workbench/verify_pytorch2.py
