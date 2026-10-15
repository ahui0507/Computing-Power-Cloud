#!/bin/bash
# Current-site offline worker installation. Never installs/removes GPU drivers or reboots.
set -euo pipefail
test "$(id -u)" = 0
stage=${1:?Provide the staged official K3s assets directory}
test -f "$stage/k3s"
test -s "$stage/k3s-token"
test ! -e /usr/local/bin/k3s
test ! -e /etc/rancher/k3s/config.yaml
test ! -e /etc/systemd/system/k3s-agent.service
test ! -e /var/lib/rancher/k3s
test ! -e /var/lib/kubelet
test "$(hostname)" = ubuntu
test "$(uname -r)" = 7.0.0-38-generic
test "$(cat /sys/module/nvidia/version)" = 595.99.02
test "$(nvidia-smi --query-gpu=uuid --format=csv,noheader | wc -l)" = 8
test -z "$(docker ps -q)"
systemctl is-active --quiet ssh.socket
mountpoint -q /srv/platform-workspaces
# Trigger the already configured NFS automount; require the actual remote filesystem.
stat /mnt/platform-images/. >/dev/null
findmnt -n -T /mnt/platform-images -o FSTYPE | grep -q '^nfs'
(cd "$stage" && sha256sum -c sha256sum-amd64.txt --ignore-missing)
install -m 755 "$stage/k3s" /usr/local/bin/k3s
install -d -m 700 /etc/rancher/k3s
install -m 600 "$stage/k3s-token" /etc/rancher/k3s/token
install -d -m 755 /var/lib/rancher/k3s/agent/images
install -m 600 "$stage/k3s-airgap-images-amd64.tar.zst" /var/lib/rancher/k3s/agent/images/
cat > /etc/rancher/k3s/config.yaml <<'EOF'
server: https://192.168.24.64:6443
token-file: /etc/rancher/k3s/token
node-name: ubuntu
node-ip: 192.168.24.63
flannel-iface: ens12f0
node-label:
  - nvidia.com/gpu.present=true
node-taint:
  - cpcloud-maintenance=true:NoSchedule
EOF
chmod 600 /etc/rancher/k3s/config.yaml
cat > /etc/systemd/system/k3s-agent.service <<'EOF'
[Unit]
Description=K3s compute agent (CPCloud)
After=network-online.target
Wants=network-online.target
RequiresMountsFor=/srv/platform-workspaces /mnt/platform-images
[Service]
Type=notify
ExecStart=/usr/local/bin/k3s agent
KillMode=process
Delegate=yes
LimitNOFILE=1048576
LimitNPROC=infinity
LimitCORE=infinity
TasksMax=infinity
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now k3s-agent
echo 'Compute agent started with a maintenance taint; platform GPU allocation remains disabled.'
