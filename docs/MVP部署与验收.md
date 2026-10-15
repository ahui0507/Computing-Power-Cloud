> 历史 demo 设计参考：本文描述旧环境，不是新节点验收记录。旧地址已替换为占位项；新环境以新环境部署记录.md为准。

# MVP 部署与验收

当前实现覆盖登录和邮箱注册、GPU 申请、Jupyter 独立访问凭证、用户共享工作目录、释放回收和按时结算。部署前需要接入真实 K3s、NVIDIA 驱动及共享文件服务；代码中的本地测试不替代这些环境验证。

## 工作目录

后端和 GPU Pod 共用 `platform-workspaces` 这个 ReadWriteMany PVC。后端挂载整个目录，计算实例只挂载所属用户的 `user_<id>` 子目录到 `/workspace`。释放实例删除 Pod、Service、Ingress 和鉴权 Secret，保留用户目录。

在控制或存储节点准备 `/data/workspaces`，为 NFS 客户端提供目录读写权限。默认工作目录组为 1000。采用 `root_squash` 时，可将匿名 UID/GID 映射到 1000，并让导出目录属于这个用户和组；后端需能创建子目录及持久化密钥。所有计算节点安装 NFS 客户端。

编辑 `deploy/kubernetes/cluster/workspaces.yaml` 中的 `NFS_SERVER_IP`、导出路径和容量，然后应用并检查 PVC 绑定状态：

```bash
kubectl apply -f deploy/kubernetes/cluster/workspaces.yaml
kubectl get pvc platform-workspaces -n default
```

使用 Compose 运行后端时，`WORKSPACE_ROOT_HOST` 必须指向上述同一份 NFS 数据目录。配置成另一个本地目录会导致后端和计算节点看到不同的数据；现场验收脚本会检查这种错误。

## GPU 运行环境与镜像

计算节点先安装驱动及 NVIDIA Container Toolkit，再重启 `k3s-agent` 让 K3s 探测 NVIDIA runtime。确认运行时 handler 为 `nvidia`，为计算节点添加标签；以下 `worker1` 替换成实际节点名：

```bash
kubectl label node worker1 nvidia.com/gpu.present=true --overwrite
kubectl apply -f deploy/kubernetes/cluster/nvidia-runtimeclass.yaml
kubectl apply -f deploy/kubernetes/cluster/nvidia-device-plugin.yaml
kubectl get nodes -o custom-columns=NAME:.metadata.name,GPU:.status.allocatable.nvidia\.com/gpu
```

GPU Pod 默认使用 `runtimeClassName: nvidia`。若集群的运行时名称不同，可配置 `K8S_GPU_RUNTIME_CLASS`；创建 RuntimeClass 对象本身不会安装运行时。插件只调度到带 GPU 标签的节点。

默认镜像包含 JupyterLab 4.2.5 与 Jupyter Server 2.14.2，不预装特定训练框架。GPU 驱动库由 NVIDIA runtime 注入，CUDA 验收程序仅依赖 Python 和驱动库。

```bash
docker build -t jupyter-test:latest test-images/jupyter-test
docker save jupyter-test:latest -o jupyter-test.tar
```

把 tar 文件传到每个计算节点，在节点上执行：

```bash
sudo k3s ctr -n k8s.io images import jupyter-test.tar
sudo k3s ctr -n k8s.io images list
```

目录中登记的名称是 `docker.io/library/jupyter-test:latest`，需与导入名称一致。默认拉取策略是 `Never`，每个候选节点都必须有该镜像；也可使用私有仓库并将策略改为 `IfNotPresent`。其他镜像需提供兼容的 Jupyter Server，`images.startup_command` 可配置特定启动路径；旧 Conda 环境的登记脚本已保留其原启动路径。

## 后端启动

### Compose

先从 `.env.example` 创建 `backend/.env`，填写 SMTP、Ingress 和集群连接配置。在 `backend/` 目录运行：

```bash
docker compose -f docker-compose.yml -f docker-compose.k3s.yml up --build -d
```

配置至少包含 `WORKSPACE_ROOT_HOST=/data/workspaces` 和控制节点 kubeconfig 路径。若 kubeconfig 中 API 地址是 `127.0.0.1`，容器无法通过该地址连接控制节点，应设置 `K8S_API_SERVER` 为容器可达且被 API 证书覆盖的控制节点地址，例如 `https://REPLACE_NODE_INTERNAL_IP:6443`。

基础 Compose 文件提供 MySQL、Redis 和 API。`init-db` 等待数据库账户就绪后执行迁移和种子初始化，API 等待该服务成功退出再启动。已有数据库需先按 [数据库迁移](数据库迁移.md) 接入基线，初始化不会自动标记未知旧库。

### K3s

先创建数据库和 JWT 配置所需的 Secret，使用共享 PVC，再部署后端：

```bash
kubectl apply -f deploy/kubernetes/backend/backend-deployment.yaml
```

初始化容器执行迁移和种子数据操作。MySQL 初始化使用命名锁，多个副本启动时不会同时重复建表和种子数据。主服务启动前检查数据库版本与角色数据；`/health` 用于就绪检查，`/live` 用于进程存活检查。

### 主机

在 Python 3.10 环境安装 `backend/requirements.txt`，配置 `backend/.env`，将 `STORAGE_ROOT` 指向共享目录，然后运行：

```bash
cd backend
python scripts/start_backend.py
```

这个入口等待数据库并执行初始化。原有主机安装脚本的 systemd 服务也使用同一启动入口。

## 首次账号及节点登记

默认管理员邮箱为 `REPLACE_ADMIN_EMAIL`。新数据库可通过 `INITIAL_ADMIN_PASSWORD` 指定首次密码；留空时，随机密码保存在工作目录的 `.initial-admin-password` 文件中。读取该文件获取登录密码，应用不会把它写入启动日志。已有管理员账户不会被重置。

`SECRET_KEY` 留空时，应用在共享目录的 `.platform-secret` 保存随机密钥。所有后端副本需使用同一显式密钥或同一共享目录，否则 JWT 和实例令牌将不一致。

GPU 节点、GPU 类型及资源池仍由管理员登记。可在控制节点使用既有同步工具，再在管理员页面创建资源池：

```bash
cd backend
python scripts/sync_nodes_from_k8s.py
python scripts/init_resource_pools.py
```

核对节点主机名与 `kubernetes.io/hostname` 标签、GPU 型号和数量。数据库中的 GPU 条目预留逻辑名额，实际物理设备由 NVIDIA device plugin 分配。

邮箱注册需正确配置 Redis 与 SMTP。邮件发送失败返回 503，并清除未发送验证码；本地测试使用替代邮件服务，没有向真实用户发送测试邮件。

## 操作恢复与状态核对

默认后台任务每轮结束后等待 15 秒，分批处理 50 个操作及 50 个实例。每个后端副本均可运行，数据库租约协调创建和释放；实例普通查询读取数据库，状态更新不依赖用户打开页面。`RECONCILIATION_ENABLED=false` 可关闭内置任务，但需要由外部运维任务持续运行核对脚本。

```bash
cd backend
python scripts/reconcile_resources.py
```

该脚本执行一轮恢复和核对，输出处理、观测及错误数量。创建结果未提交时，恢复会核对并接续同名资源；释放失败按 10、20、40 秒等退避重试，间隔上限 300 秒。集群网络错误不等同于 Pod 消失，不会直接腾出 GPU。工作负载首次就绪超时默认 900 秒；从未 Ready 的启动失败或超时会安排不计费清理。

`OPERATION_LEASE_SECONDS` 默认 300 秒，必须大于 `10 * K8S_REQUEST_TIMEOUT_SECONDS + K8S_DELETE_TIMEOUT_SECONDS`，配置加载会检查这个关系。它给有界集群调用留下执行时间；进程退出后的未完成操作在租约过期后可被其他执行器接管。

创建 API 支持 `Idempotency-Key` 请求头，长度为 1–128，仅允许字母、数字、下划线和连字符。相同用户、标识与参数返回原申请；改变参数返回 409。浏览器在请求超时或服务器错误时保留标识，确认成功或明确拒绝后清除；点击重置可开始新的申请。释放返回 `released` 或 `releasing`，后者表示操作仍需恢复，不能仅凭 HTTP 成功认为物理资源已回收。

## 本地与现场验收

```bash
cd backend
python -m pip install -r requirements-test.txt
python -m pytest
```

后端测试包含真实本地 Jupyter 的启动、匿名和错误令牌拒绝、平台文件读写，以及 WebSocket 内核执行；业务数据库使用 SQLite，集群调用使用替代客户端。Windows 未授权创建符号链接时，对应测试会跳过，该项在 Linux CI 中运行。

```bash
cd frontend
npm ci
npm test
npm run build
```

真实集群可用后，从完整仓库运行验收脚本。先将登录密码设置到 `PLATFORM_ACCEPT_PASSWORD` 环境变量，再选择实际资源池和镜像 ID：

```bash
python backend/scripts/verify_mvp.py --api-url http://127.0.0.1:8000 --email REPLACE_ADMIN_EMAIL --pool-id 1 --image-id 1 --report mvp-report.json
```

脚本会创建一个 GPU 实例并复用标识申请一次，确认返回同一实例，检查上传文件能被 Jupyter 读取、匿名访问被拒绝，并在容器中通过 CUDA Driver API 执行 `41 + 1 = 42`。之后释放实例两次，等待状态变成 `released`，验证只有一笔结算、文件仍存在，并删除测试文件。启动/释放等待时间可分别用 `--startup-timeout`、`--release-timeout` 调整。此验收会产生少量按时使用费用，报告不包含密码或访问令牌。`passed: true` 才表示本次现场流程成功。

## 计费与现阶段边界

释放后重新申请、同一用户多个独立实例、多卡及多人争抢剩余名额的重复验收入口是 `backend/scripts/verify_resource_scenarios.py`。2026-10-10 的 8 用户、43 实例现场结果、运行方式及机器报告见[资源并发验收](资源并发验收-2026-10-10.md)。

申请时确定单卡小时价格，后续改价不改变已有申请。结算使用 Decimal，费用为单卡小时价乘 GPU 数量乘运行秒数除以 3600，保留四位小数。容器未启动时不计费，运行起点来自 Pod 容器时间。用户释放时，计费在释放请求成功落库的时间截止，已知更早的终止时间优先；清理延迟和结算重试时间不向用户收费。若 Pod 被外部删除且无终止时间，使用最后成功观测时间作为保守截止点。账单与余额修改、实例终态、GPU 回收在一个数据库事务中提交，重复释放不会重复扣费。

当前余额是内部演示记账，允许余额为负数表示欠款；充值接口不代表外部支付确认。预付费、配额审批、定时释放、暂停恢复、镜像保存和多机训练仍属后续功能。

旧运行实例没有新增卷和鉴权配置，需要先保存原容器中的数据，再释放并重新申请。更新后端代码不会自动改写已有 Pod。2026-10-10 已在 control/worker1 完成真实 MySQL 并发、NFS、GPU 和 Jupyter WebSocket 验收，环境与报告见[现场部署记录](现场部署记录-2026-10-10.md)。自主邮箱注册及 SMTP 按用户要求暂不验收。
