# 当前内网 HTTPS 部署

网站入口为 `https://10.72.63.42:64022/`。HAProxy 在既有入口分流 HTTP、TLS 与 SSH，Nginx 终止 TLS，集群 Ingress 保持 HTTP。访问链接使用后端 `PUBLIC_HTTPS_ENABLED=true`。

首次使用需要安装内部 CA 信任包；Windows 根证书导入必须在交互式系统弹窗确认，不能后台静默安装。公开包只有 CA 与安装/撤销脚本，私钥只保存在控制节点 root 专有目录。

[完整部署、客户端安装、续期和验收记录](../../docs/HTTPS部署与验收-20261017.md)。

[renew_certificate.py](renew_certificate.py) 已安装到控制节点 `/usr/local/sbin/cpcloud-tls-renew`，由每日 systemd timer 运行；支持 `--force` 手动续期，默认只在剩余不足 45 天时续期。部署路径、IP、CA 和运维目录均对应当前站点，迁移环境时应调整并重新验收。
