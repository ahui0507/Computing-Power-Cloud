#!/bin/sh
# Run before initramfs udev coldplug. Fail closed for workloads, not host boot.
case "${1:-}" in prereqs) exit 0 ;; esac
umask 077
gpu_sysfs=${CPCLOUD_GPU_SYSFS:-/sys/bus/pci/devices}
gpu_config=${CPCLOUD_GPU_CONFIG:-/conf/cpcloud-gpu-domains.conf}
gpu_state=${CPCLOUD_GPU_STATE:-/run/cpcloud-gpu-domains-early}
gpu_before="${gpu_state}.before"
gpu_expected="${gpu_state}.expected"
gpu_changed=no

fail() {
    if [ "$gpu_changed" = yes ] && [ -f "$gpu_before" ]; then
        while read -r address original; do
            [ -n "$address" ] || continue
            printf '%s\n' "$original" > "$gpu_sysfs/$address/iommu_group/type" || true
        done < "$gpu_before"
    fi
    printf 'failed:%s\n' "$1" > "$gpu_state"
    # The systemd guard prevents k3s startup; allow SSH and host recovery.
    exit 0
}

[ -f "$gpu_config" ] || fail missing-config
: > "$gpu_before"
: > "$gpu_expected"
count=0
while read -r address device pci_class extra; do
    case "$address" in ''|'#'*) continue ;; esac
    case "$address" in ????\:??\:??.?) ;; *) fail invalid-address ;; esac
    case "$address$device$pci_class" in *[!0-9a-fx:.]*) fail invalid-manifest ;; esac
    [ -z "$extra" ] || fail extra-fields
    [ "$pci_class" = 0x030200 ] || fail unapproved-class
    pci="$gpu_sysfs/$address"
    [ -d "$pci" ] || fail missing-gpu
    [ "$(cat "$pci/vendor")" = 0x10de ] || fail unapproved-vendor
    [ "$(cat "$pci/device")" = "$device" ] || fail changed-device
    [ "$(cat "$pci/class")" = "$pci_class" ] || fail changed-class
    [ ! -e "$pci/driver" ] || fail driver-already-bound
    set -- "$pci"/iommu_group/devices/*
    [ "$#" -eq 1 ] && [ "${1##*/}" = "$address" ] || fail shared-iommu-group
    [ -w "$pci/iommu_group/type" ] || fail domain-not-writable
    original=$(cat "$pci/iommu_group/type")
    case "$original" in DMA-FQ|identity) ;; *) fail unexpected-domain ;; esac
    # Duplicate lines must not let an omitted GPU pass a count check.
    while read -r previous; do
        [ "$previous" != "$address" ] || fail duplicate-gpu
    done < "$gpu_expected"
    printf '%s\n' "$address" >> "$gpu_expected"
    printf '%s %s\n' "$address" "$original" >> "$gpu_before"
    count=$((count + 1))
done < "$gpu_config"
[ "$count" -gt 0 ] || fail empty-manifest

# Refuse additional NVIDIA display/compute devices outside the approved list.
seen=0
for pci in "$gpu_sysfs"/*; do
    [ -f "$pci/vendor" ] && [ "$(cat "$pci/vendor")" = 0x10de ] || continue
    case "$(cat "$pci/class")" in 0x03*) ;; *) continue ;; esac
    found=no
    while read -r address; do
        [ "${pci##*/}" != "$address" ] || found=yes
    done < "$gpu_expected"
    [ "$found" = yes ] || fail unapproved-gpu
    seen=$((seen + 1))
done
[ "$seen" -eq "$count" ] || fail gpu-count-changed

while read -r address original; do
    pci="$gpu_sysfs/$address"
    [ ! -e "$pci/driver" ] || fail driver-bound-during-change
    gpu_changed=yes
    printf 'identity\n' > "$pci/iommu_group/type" || fail write-domain
    [ "$(cat "$pci/iommu_group/type")" = identity ] || fail verify-domain
done < "$gpu_before"
printf 'applied:identity:%s\n' "$count" > "$gpu_state"
exit 0
