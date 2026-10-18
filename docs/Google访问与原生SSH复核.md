# Google 访问与原生 SSH 复核（2026-10-16）

用户明确要求：外网验收包含 Google；SSH 使用 Windows PowerShell 自带的 OpenSSH 命令，不以 Python 本地连接工具作为必需条件。

## Google 访问实测

从计算节点和当前实例分别测试 `https://www.google.com/`、`https://www.google.com.hk/`，均在 TCP 连接阶段超时，HTTP 状态 000。同轮百度和 PyPI 返回 200。因此此前普通下载站点的可达性不能代表 Google 可达。

系统 DNS 对 Google 返回异常地址。计算节点另经 Cloudflare HTTPS DNS 获得 Google 地址 `142.251.156.119`、`142.251.155.119` 等，使用 `curl --resolve` 保持 Google 域名及正常 TLS 验证，连接这些地址仍超时。仅更换 DNS 没有解决当前出口的连接问题。

两处实例进程均未配置 HTTP_PROXY、HTTPS_PROXY 或 ALL_PROXY。没有擅自修改主机 DNS、默认路由或实例网络。后续需要服务器能够访问的有效代理/VPN 出口，再验证 Google HTTPS、命令行与实例环境；代理地址及认证信息尚待用户提供。

## 当前管理员可用的 PowerShell 原生命令

```powershell
ssh -J system@10.72.63.42:64022 -p 31256 root@127.0.0.1
```

首次连接按提示核对主机密钥。先认证控制节点的 `system` SSH 账号，再认证实例的 `root` 账号，实例密码见网页“我的实例 → SSH”。这里的 127.0.0.1 是跳板机所连接的实例 NodePort。

已通过固定控制节点主机密钥、实例主机密钥、两段真实 SSH 认证及 `id -u`、`hostname`、`pwd` 验证该链路；本机 Windows OpenSSH 的 `ssh -G` 确认支持此 ProxyJump 参数。该方案使用原生 SSH，无需下载或启动 Python 工具。控制节点账号属于管理员运维凭据，不作为普通平台用户的共用账号。

## 仅使用外部 IP 和端口的直连方式

当前实例的完整映射规则为：

| 协议 | 校园网访问地址 | 目标服务器 | 目标端口 |
|---|---|---|---|
| TCP | 10.72.63.42:31256 | 192.168.24.64 | 31256 |

映射建立后，应从用户电脑实际验证 SSH banner 和登录，成功后才将页面切换为普通命令：

```powershell
ssh -p 31256 root@10.72.63.42
```

当前外部 31256 返回 Connection refused；用户电脑到 192.168.24.64:31256 和 192.168.24.63:31256 均超时；服务器内 NodePort 和实例 SSH 正常。现有凭据覆盖控制节点和计算节点，未提供网关的管理入口或访问方式，因此没有声称映射已经完成。

现有 64022、63022 分别用于控制节点和计算节点 SSH；64022 同时承载网站。不能直接把它们改指向一个实例，否则会影响当前管理和网站入口。

实例 NodePort 随创建动态分配。单独映射 31256 只覆盖当前实例；要让所有新实例都提供这类原生命令，需要网关同时映射平台使用的 NodePort 范围，或约定专用 SSH 端口段并同步平台分配逻辑。最终采用的范围和网关配置尚待用户提供管理方式后落实。

已有网站转发工具仍可使用，当前没有提前关闭有效入口或显示未经验证的直接连接命令。


## Windows PowerShell 实机复测

按用户“测试一下，是否都可用”的要求，使用本机 Windows PowerShell 5.1 启动系统自带 OpenSSH 9.5p2，实际验证如下。测试认证使用既有凭据及严格主机密钥核验，未修改服务器账号、公钥或网关。

| 项目 | 实测结果 |
|---|---|
| 控制节点 SSH，64022 | 登录成功，hostname=dell，工作目录 /home/system |
| 计算节点 SSH，63022 | 登录成功，hostname=ubuntu，工作目录 /home/lvzhiqiang |
| 原生 ssh.exe 经 -J 进入实例 | 登录成功，root，/workspace，sudo 返回 UID 0 |
| 原生 ssh.exe 分配 PTY | 成功分配 /dev/pts 终端，登录 Bash 载入 Ubuntu 提示符 |
| 原生 sftp.exe 经 -J 访问实例 | 成功读取工作目录并列出 /data、/workspace，未上传或删除用户文件 |
| Google、Google 香港 | 计算节点和实例均连接超时，HTTP 000；同轮百度、PyPI 为 HTTP 200 |
| 外部 10.72.63.42:31256 不经跳板 | Connection refused，仍未建立该端口映射 |

当前可用的原生命令保持 `ssh -J system@10.72.63.42:64022 -p 31256 root@127.0.0.1`。控制节点和实例分别认证，需要先后输入两处密码。此结论针对管理员拥有节点 SSH 凭据的使用场景。

脱敏实机测试结果保存于本地忽略目录 `.ops/native-powershell-test-result.json`；自动输入测试密码的临时辅助程序已删除。没有重启节点或实例。
