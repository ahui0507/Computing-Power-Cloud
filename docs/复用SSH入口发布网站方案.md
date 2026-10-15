# 控制节点统一网站入口（2026-10-15 实施记录）

用户已确认实施“复用 SSH 入口”的方案，现已上线。统一网址：**http://10.72.63.42:64022/**。允许用户网段为 **10.240.0.0/16**；用户使用管理员开通的独立平台账号登录，不需要个人隧道，不需要修改网关。

## 实际连接关系

```text
浏览器 HTTP / 原 SSH 命令
          |
10.72.63.42:64022（原网关 TCP 入口）
          |
控制节点 HAProxy 3.2.9，TCP 22
          |                         |
       HTTP                       SSH
          |                         |
Nginx 127.0.0.1:8081         OpenSSH 127.0.0.1:2222
          |
前端静态文件、/api/ → 原 FastAPI
```

控制节点外部 SSH 命令保持 `ssh -p 64022 system@10.72.63.42`；计算节点仍为原 63022 入口。所有已确认用户名、密码和 SSH 主机密钥保持原值。当前页面版本链接指向 `/opt/computing-platform/releases/20261015-shared-web`，旧版本保留。

## 访问控制与日志

HAProxy 按真实 TCP 来源只允许 10.240.0.0/16 的 HTTP 请求，其他来源的 HTTP 连接直接拒绝。仅 HTTP 应用该网段限制，SSH 保持原有可达范围。

HAProxy 使用 PROXY v2 将真实客户端地址传给仅监听 loopback 的专用 Nginx 入口；该入口仅信任本机代理元数据，并再次执行网段限制。用户提供的 X-Forwarded-For 不影响权限判断。原 127.0.0.1:8080 保留节点健康检查和管理员运维；内网 192.168.24.64:8080 保留来源限制。

SSH 后端看到代理的 127.0.0.1 地址，真实连接来源由 HAProxy TCP 日志保留。OpenSSH 的默认 PerSourcePenalties 会把所有代理会话计作同一来源，现仅对 127.0.0.1 设置 PerSourcePenaltyExemptList，避免一次失败处罚影响其他管理员。MaxAuthTries=6、MaxStartups=10:30:100、原密码/公钥认证设置保留。这意味着原生 SSH 按单个客户端来源处罚不能在代理后的 SSH 后端直接执行，维护时应结合代理日志核对来源。

专用网页日志位于 `/var/log/nginx/cpcloud-shared-access.log`，记录真实 IP、方法、路径和状态，不记录查询参数、请求体或认证头。登录页和账户页遗留的初始密码明文提示已删除，复制的旧静态缓存中相应提示文件也已清理。

## 实际验证

- 原 SSH 22 仍工作时，在私有 18081/18082 端口预演 HTTP/SSH 分流；测试来源元数据、网段内其他地址、网段外拒绝、伪造头拒绝，以及原账户/固定主机密钥认证。
- 切换前启动独立 5 分钟自动回退 timer；切换通过 detached systemd 任务执行，不依赖当前 SSH 命令存活。
- 当前电脑 10.240.52.192 直接访问正式网址：首页、JS/CSS、API 健康、管理员登录和鉴权接口全部通过。
- 普通验收用户经正式网址登录、访问自己的 100 GiB 存储成功，管理员接口返回 403；验收后恢复其禁用状态，保留目录、额度及数据。
- 使用 Playwright/Firefox 从正式网址填写登录表单，成功进入 `/dashboard`；页面没有应用错误，前端 42 项测试及生产构建通过。
- 计算节点 192.168.24.63 作为实际非允许来源请求正式协议入口被拒绝，伪造允许网段的 X-Forwarded-For 也无效。
- 从当前电脑新建 SSH 会话成功，固定 host key 验证通过；切换前保留的测试 SSH 会话继续可用。
- 独立检查通过后取消自动回退。HAProxy、SSH service/socket、Nginx、API 当前正常，原 GPU 容器和存储没有调整；没有重启节点。

浏览器测试只使用本轮独立上下文，已关闭；认证输入及浏览器产物在本地私有忽略目录内，未放入源码包。当前仅使用 HTTP，HTTPS 不属于本次已实施范围。

## 配置及维护

实际配置：

- `/etc/haproxy/haproxy.cfg`
- `/etc/ssh/sshd_config.d/90-cpcloud-shared-entry.conf`
- `/etc/systemd/system/ssh.socket.d/zz-cpcloud-shared-entry.conf`
- `/etc/systemd/system/haproxy.service.d/cpcloud-shared-entry.conf`
- `/etc/nginx/conf.d/cpcloud-published.conf`
- `/etc/cpcloud/backend.env`：追加正式网址到 CORS，原凭据保留。

对应模板在 `deploy/new-environment`。HAProxy 包创建的进程账号为 haproxy，锁定且无交互 shell，没有登录密码；已在本地凭据文件记录。

```bash
sudo systemctl status haproxy ssh.socket ssh.service nginx computing-platform-backend --no-pager
sudo haproxy -c -f /etc/haproxy/haproxy.cfg
sudo sshd -t
sudo nginx -t
sudo ss -lnt
curl -fsS http://127.0.0.1:8080/api/health
```

原配置、启用状态、私有后端配置备份和回退脚本在 `/home/system/cpcloud-operations/shared-entry-20261015`，root 受限权限。该目录含真实服务凭据备份，不能分享或提交 Git。

手工恢复原 SSH 22 入口时执行该目录的 `rollback.py`；这会关闭新网站入口、恢复原 SSH/Nginx/后端来源配置，并可能中断通过代理建立的新 SSH 会话，应使用已保持的管理连接或具备恢复条件后操作。回退脚本不会删除平台持久数据或修改账户密码。

日常不要直接停止 HAProxy，因为 SSH 和网站共用它；先校验配置再 reload，重大入口调整沿用独立自动回退流程。未对主机重启后的启动顺序进行实机重启验收，但 SSH socket/service、HAProxy 的启用状态和依赖已配置并检查。

HAProxy 的 client/server 空闲超时当前为 0，以保留原 SSH 长连接无额外空闲超时的语义；其配置检查会对此产生已知 warning，校验返回成功。HTTP 连接的请求与 keepalive 超时仍由 Nginx 控制。后续如需要统一空闲时长，应明确运维策略后调整。

GPU 驱动修复、真实 GPU 实例及其 Jupyter/实例 SSH 对外链接仍属原先待维护范围，不能把统一网站验证通过视为这些功能已经可用。
