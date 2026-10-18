# 实例专用 SSH 转发

按用户最新要求，本站已恢复本目录的带认证跳板，两次密码提示均输入同一个实例密码。[一次密码 SSH 连接](../../docs/一次密码SSH连接.md) 已停用并保留为历史记录。

复用控制节点既有 SSH 入口，为每个运行中的实例配置一个只能进行 TCP 转发的账号。普通用户使用自己的实例密码，不需要控制节点管理账号或密码。控制节点、计算节点原 SSH 账号及主机密钥保留。

本站命令示例：

```powershell
ssh -J cpjump-9@10.72.63.42:64022 -p 31256 root@127.0.0.1
```

两次密码提示均输入网页中的实例密码。SSH/SFTP/VS Code Remote SSH 使用同一条转发路径。此方案使用 PowerShell 自带的 OpenSSH，无需 Python 连接工具或新增网关端口映射。

## 配置与安装

后端设置：

```dotenv
SSH_GATEWAY_ENABLED=true
SSH_GATEWAY_ENDPOINT=10.72.63.42:64022
SSH_GATEWAY_HELPER=/usr/local/sbin/platform-ssh-gateway
SSH_JUMP_HOST=
SSH_TUNNEL_ENABLED=false
```

安装 `platform_ssh_gateway.py` 到 `/usr/local/sbin/platform-ssh-gateway`，root 所有、0755。脚本使用当前发布目录的 Python 环境。创建专用系统组 `cpcloud-ssh-jump`，安装并验证本目录的 sudoers 模板，安装两个 systemd 单元。应用服务账号只获准调用 `ensure`；同步和回收由 root timer 执行。

`/etc/ssh/sshd_config` **末尾**包含 `Include /etc/ssh/platform-instance-gateway.conf`。不要把含 Match 的策略任意放在后面还有全局指令的位置。安装时先生成 `render_policy([])` 的默认拒绝策略、运行 `sshd -t` 并 reload，之后才允许创建账号。策略由 helper 维护。

启动前备份原 sshd 配置、后端配置及发布指针；沿用独立的自动回退计时器，完成独立管理 SSH 和实例访问测试后取消。本站实施脚本与备份记录位于 `/home/system/cpcloud-operations/feedback-20261016/instance-ssh-gateway/`。

```bash
sudo /usr/local/sbin/platform-ssh-gateway sync
sudo systemctl enable --now platform-ssh-gateway-sync.timer
sudo systemctl status platform-ssh-gateway-sync.timer
sudo journalctl -u platform-ssh-gateway-sync.service -n 20 --no-pager
```

## 权限与生命周期

- `cpjump-ID` 对应全局唯一的实例分配 ID。密码散列通过 stdin 设置为该实例凭据的散列，密码不进入命令参数、策略、状态文件或日志。
- 账号无 home，shell 为 nologin；`MaxSessions 0` 禁止控制节点 shell、exec、SFTP 等会话。
- `PermitOpen` 只允许 `127.0.0.1:本实例SSH NodePort`，限制在本站 Kubernetes 默认的 30000–32767 范围，拒绝主机服务和其他实例端口。远程监听、Unix socket 转发、代理转发、X11、隧道和用户 rc 均禁用。
- API 在核对实例归属、Pod/Secret 所属标签、运行状态后调用 helper。helper 从数据库读取真实运行中、启用 SSH、所属用户有效且未删除的实例，不接受调用者传入目标 IP、端口或密码。
- root timer 每轮结束 15 秒后重新同步。释放、停用或删除用户后撤销转发目标、锁定账号并终止该账号已有连接。回收受下一轮同步时间影响。锁定账号保留，避免复用 UID；不删除用户数据。
- 现有控制节点 `system` 账号和其他管理账号不属于此组，不由 helper 修改。Linux 同名账号若未在 root 私有账本登记，helper 拒绝接管。
- 账本 `/var/lib/cpcloud-ssh-gateway/accounts.json` 为 root 私有文件，保存 UID、所属用户、状态和端口，不保存密码或散列。

## 2026-10-16 验证

Linux 后端完整 309 项测试通过；前端 43 项测试和生产构建通过。Windows 原生 SSH、PTY、SFTP 均使用实例密码通过，测试客户端未获得控制节点密码。控制节点 shell、其他目标端口、远程监听被拒绝；独立临时转发账号的连接在回收后断开，旧凭据和其他实例凭据均被拒绝，临时账号及监听已清理。控制节点原 SSH 和主机密钥再次验证通过。

当前发布：`/opt/computing-platform/releases/20261016-instance-ssh-f32e8069db80`。
