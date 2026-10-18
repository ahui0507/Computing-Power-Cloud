# GPU 专用 IOMMU 配置

生产部署与实际验收见 [GPU IOMMU 正式修复记录](../../docs/GPU-IOMMU正式修复与验收-20261018.md)。当前方案只对白名单中的八张 A100 PCIe 设置 identity，不修改全局 IOMMU 参数或 ACS。identity 取消这些 GPU 的 DMA 地址翻译保护；网卡、存储等其他设备保持原域。

## 启动顺序

`initramfs-gpu-domains.sh` 安装为 `/etc/initramfs-tools/scripts/init-top/00-cpcloud-gpu-domains`。构建 initramfs 后必须检查实际 `scripts/init-top/ORDER`，确认它在 `udev` 冷插拔之前执行；当前部署已检查并完成重启验证。

`initramfs-hook.sh` 将 `/etc/cpcloud/gpu-domains-early.conf` 复制到 initramfs `/conf/cpcloud-gpu-domains.conf`。每行格式为 `PCI地址 设备ID PCI类别`，例如 `0000:3d:00.0 0x20f1 0x030200`。脚本先验证完整白名单、厂商/设备/类别、驱动未绑定及单设备 IOMMU 组，再设置 identity；不依赖重启后可能变化的 group 编号。

`verify_boot_domains.py` 安装为 `/usr/local/sbin/cpcloud-verify-gpu-domains`，读取 `/etc/cpcloud/gpu-domains.json`，核对全部 GPU 的 PCI/UUID/索引、驱动、identity 域和全部非 GPU 域。`cpcloud-gpu-domains.service` 是只读启动门禁，k3s-agent、worker、monitor 都通过 `Requires` 和 `After` 依赖它。失败时不启动执行与监控服务，主机仍可通过 SSH 恢复。

更新白名单属于硬件配置变更，应在维护状态下核对实际 PCI 和 NVML 清单。不要绕过启动检查以接纳未知设备。

## 验证工具

- `inspect_gpu_domains.py`：原 DMA-FQ 基线核验。
- `verify_boot_domains.py`：生产 identity 配置只读核验。
- `switch_gpu_domains.py`：需要新鲜维护证明、批准的 GPU 索引与无客户端检查，默认只输出计划；用于受控运行时切换及恢复。
- `test_boot_domains.py`：使用合成 PCI 树验证拒绝路径，不写真实 GPU sysfs；在 Linux 上执行 `python3 -I test_boot_domains.py -v`。
- `verify_torch_collectives.py`、`verify_tensorflow_mirrored.py`：原生 NCCL 数值训练、优化器副本、独立进程恢复及图案张量持续归约；TensorFlow 严格参考比较关闭 TF32。

## 回退

先暂停数据库调度并 cordon 节点，等待用户实例释放，暂停 GPU 插件与 GPU 客户端。控制节点恢复 `WORKLOAD_NCCL_P2P_DISABLE=true` 并重启后端，确保后续实例使用软件兼容路径。

然后以 root 执行 `rollback_boot.py --record <installed.json绝对路径>`。该工具只删除部署记录中允许的准确文件，校验原 initramfs 备份后恢复它；不会删除用户数据、修改 ACS 或启动参数。运行时 GPU 仍可能处于 identity，需要在客户端关闭且维护证明有效时，以原 inventory 调用 `switch_gpu_domains.py --restore --execute ...`，或在维护窗口重启并核对恢复结果。

确认八卡 UUID/索引、原域、现有 IPv6 guard、NetworkPolicy 与服务恢复后，再开放调度。不要在旧 DMA-FQ 域下保持原生 P2P 作为站点默认配置。
