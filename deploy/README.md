# 部署配置与入口

Kubernetes 配置统一放在本目录，主机安装脚本位于仓库根目录的 `scripts/`，后端排障脚本保留在 `backend/scripts/`。

迁移及新站点部署优先使用 `scripts/platform_ops.py` 与 `deploy/migration/site.example.json`，覆盖配置生成、发布包、镜像搬运、停机备份恢复、控制节点及代理安装、原节点 ID 重绑和只读验收。完整流程与前置条件见 [平台迁移与部署手册](../docs/平台迁移与部署手册.md)。旧 `scripts/deploy.sh` 保留为历史安装参考，不覆盖当前所有功能。

| 路径 | 用途 |
|---|---|
| scripts/install_k3s_control_node.sh | 控制节点安装 |
| scripts/install_k3s_worker_node.sh | 计算节点安装 |
| scripts/deploy.sh | 主机上的平台服务部署 |
| kubernetes/cluster/nvidia-device-plugin.yaml | GPU 插件配置 |
| kubernetes/cluster/namespace.yaml | 命名空间配置 |
| kubernetes/cluster/storage-class.yaml | 存储类配置 |
| kubernetes/cluster/workspaces.yaml | 共享工作目录 PV 和 PVC |
| kubernetes/cluster/nvidia-runtimeclass.yaml | NVIDIA runtime handler |
| kubernetes/backend/backend-deployment.yaml | 后端工作负载、服务及 RBAC |
| kubernetes/backend/secrets.yaml.example | 配置示例 |
| nginx/computing-platform.conf.example | 主机网页、API 与 Jupyter WebSocket 反向代理 |
| systemd/computing-platform-backend.service.example | 主机后端自启动服务 |
| storage/ | 数据卷、用户配额 helper、在线快照备份及定时器 |

表中的 `scripts/` 路径从仓库根目录计算，`kubernetes/` 路径相对本目录。后端可选择主机部署或集群部署，两者共用业务代码和迁移。

集群部署使用 ServiceAccount 自动加载连接配置，不把 ServiceAccount 目录当作 kubeconfig 文件。主机部署则设置 `K8S_CONFIG_PATH` 指向 kubeconfig 文件。

```bash
kubectl apply -f deploy/kubernetes/cluster/nvidia-runtimeclass.yaml
kubectl apply -f deploy/kubernetes/cluster/nvidia-device-plugin.yaml
kubectl apply -f deploy/kubernetes/backend/backend-deployment.yaml
```

集群目录中的其他 `fixed` 配置是既有排障方案。部署前选定适合节点驱动的插件配置，避免同时运行多套 GPU 插件。

工作负载配置通过后端环境变量管理：`K8S_NAMESPACE`、`K8S_IMAGE_PULL_POLICY`、`K8S_GPU_RUNTIME_CLASS`、`WORKSPACE_PVC_NAME`、`JUPYTER_COMMAND` 和 Ingress 配置。默认使用本地导入镜像和 `jupyter-lab` 启动程序，可按镜像设置特定路径。GPU 插件只调度到 `nvidia.com/gpu.present=true` 的节点。

实例的 `/dev/shm` 使用独立、按需占用的内存型 emptyDir，默认上限 `1Gi`，避免容器默认 64 MiB 导致多卡 NCCL 或多进程 DataLoader 失败。可通过 `WORKLOAD_SHM_SIZE_LIMIT` 配置正整数 `Mi`/`Gi`；该值在下单时冻结到创建操作，调整配置只影响后续申请。已有实例需保存文件、释放并重新申请才能获得新挂载。

计算配额采用比例规则，`NODE_RESERVED_CPU_PERCENT` 和 `NODE_RESERVED_RAM_PERCENT` 默认均为 20。先按节点容量预留系统份额，再按申请 GPU 数占该节点全部登记 GPU 数的比例分配，CPU 以毫核、内存以 MiB 向下取整；不再使用旧的每卡固定数量或固定系统预留数量。采集服务更新节点硬件容量，容量未知或监控准入不满足时停止新分配。

GPU 总数按整个节点计算，跨用户、跨资源池共用预算。每次申请冻结实际配额和分母；异构节点的创建页不会承诺一个统一份额，实例详情以实际分配节点为准。已有固定配额记录保留原限制和历史，不改写为比例订单。申请使用用户、资源池、节点、GPU 的一致锁顺序，实例 CPU/内存 requests 与 limits 相同，CPU 为时间配额而非独占物理核心。共享内存计入实例内存上限，CPU/内存不另收费。

数据库升级入口及已有数据库接入方式见 [数据库迁移](../docs/数据库迁移.md)。目录职责和本地检查见 [项目代码结构](../docs/项目目录说明.md)。

v0.7 的独立数据卷、原生存储配额、镜像日志位置及备份恢复见 [存储部署说明](storage/README.md)。`STORAGE_QUOTA_ENABLED` 只在 helper 与数据卷准备完成后启用。日常备份使用 `scripts/backup_snapshot.py`，原迁移入口的备份命令仍要求停机。

共享目录、初始化、镜像准备及现场验证以 [MVP 部署与验收](../docs/MVP部署与验收.md) 为准。
