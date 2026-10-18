#!/bin/sh
set -eu
case "${1:-}" in prereqs) exit 0 ;; esac
mkdir -p "${DESTDIR}/conf"
cp /etc/cpcloud/gpu-domains-early.conf "${DESTDIR}/conf/cpcloud-gpu-domains.conf"
