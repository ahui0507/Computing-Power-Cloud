# 租户隔离部署

当前站点已部署专用 `platform-workloads` namespace、默认拒绝的 NetworkPolicy、受限 ServiceAccount、容器权限与节点 IPv6 guard。数据继续使用现有 NFS 用户子目录，公开镜像无需重建。

[完整实施与验收记录](../../docs/租户隔离加固与验收-20261017.md)。

清单中的节点地址、控制节点转发源、NFS 路径和 `cni0` 对应当前现场实测。迁移环境前应重新核对，不能直接假设地址相同。当前集群仅支持 IPv4 Pod 网络，IPv6 guard 封堵链路本地旁路。

部署顺序：先在每个节点安装并验证 [pod_ipv6_guard.py](pod_ipv6_guard.py) 与 service；为节点服务添加启动依赖；验证业务 namespace、SA、Retain PV/PVC 与 NetworkPolicy；设置已验证节点的 `cpcloud.io/tenant-isolation=v1` 标签；最后启用后端隔离开关与对应策略摘要。仅复制源码而不启用配置，不代表完成隔离。

NetworkPolicy spec 的 SHA256 使用 `app.infrastructure.kubernetes.isolation.policy_digest` 计算。额外网络策略具有叠加放行语义，后端会拒绝接管存在未知策略的 namespace。白名单应在经过审核的基准策略内调整，并同步摘要。

已安装的 guard 脚本位于 `/usr/local/sbin/cpcloud-pod-ipv6-guard`。常规 apply 幂等，不清理其他防火墙规则。`--remove` 只用于受控回退；不能在仍有租户实例时撤除边界。
