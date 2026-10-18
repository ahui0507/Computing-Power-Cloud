# 独立运行监测

`watchdog.py` 只使用 Python 标准库、systemd、节点工具和受限 SSH，不依赖应用、数据库或 Kubernetes API 客户端。每个节点以 oneshot service 加 30 秒 timer 运行，状态持久化到 `/var/lib/cpcloud-watchdog`。连续三次异常形成故障记录，连续两次恢复结束该次故障；已结束记录保留七天，最多 200 条。

控制节点检测 API、HTTPS 入口、资源对账心跳、本地磁盘和计算节点状态；计算节点检测 API、控制节点监测进度、节点服务、GPU 数量/域/温度、近期内核错误和本地磁盘。磁盘占用 85% 告警，95% 升级；GPU 温度阈值 85℃。计算节点只测本地根文件系统，避免远端 NFS 卡住检测。节点服务列表和八卡身份域检查适用于当前双节点 A100 部署，扩容时需要同步配置。

部署文件：

- `/usr/local/lib/cpcloud-watchdog/watchdog.py`：root 所有，0644。
- `/etc/cpcloud-watchdog/config.json`：root 所有，0600。
- 控制节点私钥 `/etc/cpcloud-watchdog/compute_key`、固定主机密钥文件 `known_hosts`：root 所有，0600。不得写入管理员口令。
- 计算节点用户 `cpwatchdog` 仅接受固定来源的密钥认证。root 管理的 authorized_keys 使用 `restrict`、`from`、固定 command；sshd Match 再固定 `ForceCommand ... watchdog.py status`，禁用密码、转发、TTY 和用户 RC。
- `state.json` 私有 0600；`status.json` 0644，仅供受限 SSH 读取；`public/` 下只有清理后的 `status.json` 和静态 `index.html`。
- systemd 单元启用 `StateDirectory`、`RuntimeDirectory`、空 capabilities、只读系统路径及资源限制。`/run/cpcloud-watchdog` 用于独立进程锁。

配置示意（替换节点 IP、CA 和固定主机名；两个节点不得使用无法回流的公网映射做内部健康检查）：

```json
{
  "role": "control",
  "state_directory": "/var/lib/cpcloud-watchdog",
  "site_url": "http://CONTROL_LAN_IP:8080",
  "ca_file": "/etc/cpcloud-watchdog/ca.pem",
  "tls_server_name": "CERTIFICATE_IP_OR_DNS",
  "local_disks": ["/", "/srv/platform-workspaces"],
  "heartbeat_file": "/run/cpcloud-backend/reconciliation.json",
  "heartbeat_ttl": 120,
  "ssh_key": "/etc/cpcloud-watchdog/compute_key",
  "known_hosts": "/etc/cpcloud-watchdog/known_hosts",
  "compute_target": "cpwatchdog@COMPUTE_LAN_IP",
  "confirm_failures": 3
}
```

计算节点 `role=compute`、`local_disks=["/"]`，不需要 SSH 私钥。控制节点 HTTPS 检测连接本机 8443 PROXY listener，发送受信任代理头，再验证服务器证书和静态状态的新鲜度。当前此 listener 仅绑定 loopback，真实站点仍由原入口转发。

Nginx `/ops-alerts/` 直接 alias `/var/lib/cpcloud-watchdog/public/`，禁止目录列表并禁用缓存。内部 8080 仅对两个节点的固定地址开放精确 `/api/health` 和 `/ops-alerts/`，其他路由保持原访问限制；HTTPS 入口继续原校内网限制。不要把整个状态目录或 `/etc/cpcloud-watchdog` 作为 alias，不要扩大全站 IP allow-list。

后端配置 `RECONCILIATION_HEARTBEAT_FILE=/run/cpcloud-backend/reconciliation.json`，后端 service 的 RuntimeDirectory 为 `cpcloud-backend`，所有者由其 `User=CPCloud` 确定。生产 `BACKUP_ALERTS_ENABLED=false`；此监测程序无相关检查，也没有外发渠道。

```bash
python3 deploy/watchdog/test_watchdog.py
systemctl daemon-reload
systemctl enable --now cpcloud-watchdog.timer
systemctl start cpcloud-watchdog.service
systemctl status cpcloud-watchdog.timer
journalctl -u cpcloud-watchdog.service
```

管理员弹窗单独轮询静态记录，不依赖业务通知接口；浏览器根据已验证的管理员身份启用。已阅标记按管理员账号存于当前浏览器 localStorage，其他设备独立确认。未关闭的记录即使恢复也保留。网站整体不可达时页面无法弹出，但节点仍记录故障，入口恢复后可查；后端不可用导致新登录不能验证管理员时，可直接查看只含通用故障说明的静态记录页。
