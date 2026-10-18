# 持久存储与固定配额

本轮新环境使用控制节点两块现有 ext4 分区，保留历史数据。完整 UUID、容量、批准范围、执行结果见 `docs/新环境实施确认方案.md` 和 `docs/新环境部署记录.md`。不要运行旧环境的 `prepare_volumes.py`，它面向 LVM 卷准备，与本次现有 sdb1/sdc1 不符。

## 实际目录与限制

- `/srv/platform-system`：sdb1；MySQL、Redis、K3s 公共镜像缓存和独立 Python 运行环境。
- `/srv/platform-users`：sdc1；原 `source/software/docker/minio/llm` 保持原位。
- 新平台个人文件在 `CPCloud/workspaces/user_ID`，bind 为 `/srv/platform-workspaces/user_ID`。
- 新平台个人镜像在 `CPCloud/images/user_ID`，bind 为 `/srv/platform-images/user_ID`；与个人文件共用 project quota。
- 计算节点 NFS 路径分别为 `/srv/platform-workspaces`、`/mnt/platform-images`。仅导出新平台逻辑目录给实际内网计算节点，使用 root_squash 和数值 UID/GID 20000。

用户默认 300 GiB；首次分配值持久化在 `users.storage_default_bytes`，管理员覆盖值在 `quotas.storage_limit_bytes`。2026-10-18 已把两个使用原默认 100 GiB 的有效账号向上调整为 300 GiB，未修改自定义额度。申请 GPU 时自动挂载账号的 `/data`，多卡、多实例及重复申请不叠加持久存储额度。平台默认值改变、新增用户和用户数量变化不会缩减已有额度。管理员入口用 GiB 调整，原百分比字段仅为兼容旧环境保留；新环境按固定字节值调用 helper。

原生 helper 为 root 所有的 `/usr/local/sbin/platform-storage`；配置 `/etc/platform-storage.json` 为 root:root 600，调用者不能传入任意路径。每用户 project ID 为 `100000 + user_id`，目录启用 project ID 继承；同用户文件和镜像归档继承同一 project。块硬限制限制直接 shell、SFTP、NFS 和 API 写入，不仅是界面数值。另有可配置的默认每用户 200000 inode 上限。

用户卷启用 `project,quota` 特性和 `usrquota,prjquota` 挂载参数。新平台所有持久数据使用独立 UID 20000 的全局硬限制，避免计入历史 UID 1000 数据。配置把既有数据、ext4 保留块和 20% 可用空闲预留扣除后，冻结池容量约 3.08 TiB。这个预留是新平台容量规划；管理员若在旧目录继续大量写入，需要重新评估可用容量，不能假设池容量自动扩张。

helper 用卷内 `.platform-quota.lock` 串行化分配，用 `.platform-quota-ledger.json` 保存已承诺额度。超额、容量不足或拟缩减到已用空间以下时拒绝；不会创建半个新用户目录或删除现有文件。删除/禁用平台用户不自动删除目录或释放已承诺额度，存量数据和额度处理需人工审查。根目录账本由 root 管理，不得清空以“修复”容量问题。

## 维护

```bash
sudo /usr/local/sbin/platform-storage health
sudo /usr/local/sbin/platform-storage status 1
sudo exportfs -v
findmnt /srv/platform-users
```

日常调整用户额度使用平台管理员界面，保持数据库与内核一致。直接执行 helper `ensure ID --limit-bytes BYTES` 仅用于受控运维或诊断，不会自动更新平台数据库。全局池容量或 inode 策略由 root 在配置中修改；变更后核验全部已承诺限额，不得缩小到已有承诺或实际用量以下。

实例内部 `/data` 持久化；容器系统盘与 `/workspace` 为临时工作区。实例释放回收临时盘，用户目录和个人镜像继续保留。用户主动在文件管理中删除文件与系统自动删除用户数据是不同操作；本轮未对历史数据执行清理。

当前仅承诺可信校内用户的 API 鉴权、路径校验和实例 subPath 隔离。共享数值 UID/NFS AUTH_SYS 不提供恶意租户强隔离；需更强隔离时另行设计和批准。

用户已明确排除异机备份与恢复演练，后续不再提醒，遵循 [用户确认的运行策略](../../docs/运行策略与用户偏好.md)。
