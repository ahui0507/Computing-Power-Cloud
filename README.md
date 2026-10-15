# 算力云平台（新环境迁移工作区）

源 demo 保留在 `D:\Users\72760\Desktop\云平台`，本工作区迁移 Vue 3、FastAPI、MySQL、Redis、K3s 架构及现有功能。历史业务数据、截图、镜像归档、依赖缓存和构建产物未从源复制。初始化脚本和 Alembic 为新空库准备，不能直接指向已有业务库。

本轮授权：可信校内用户的 NFS 共享、固定 100 GiB 默认配额、20% 预留及局部代码适配；旧磁盘数据原位保留。计算节点不重启、不停止现有 GPU 容器。当前实际进度和访问方法见 [部署记录](docs/新环境部署记录.md)，原始只读检查与实施方案见 [确认方案](docs/新环境实施确认方案.md)。

目录：`backend/` API、模型和数据库迁移；`frontend/` 控制台；`database/` 历史结构参考和初始化入口；`deploy/` Kubernetes、systemd、Nginx、NFS/配额与镜像配置；`scripts/` 发布、备份和运维；`examples/` GPU 示例；`docs/` 文档。旧 demo 文档仅作设计参考，不能当作新节点验收结果。

全部真实凭据见本地“账号密码.txt”，该文件及实际环境配置已排除 Git、Docker 构建和源码分享包。模板只含占位项；新建服务凭据不得写入源码。

本机网页访问已提供后台 SSH 转发工具。在项目目录的 PowerShell 执行 `./启动本地访问.ps1`，打开 `http://127.0.0.1:18080`；关闭转发使用 `./停止本地访问.ps1`。工具读取本地凭据文件并核对已保存的 SSH 主机密钥，不把密码放入命令行或日志。依赖为 Python 3.13 和 `scripts/requirements-local-access.txt`。当前电脑无法直达控制节点内网；需要固定远程网址时，网关须单独转发 Web 端口到 `192.168.24.64:8080`。SSH 端口可用不代表 Web 端口已映射。

统一网站的目标用户网段已按本机实际掩码确认为 `10.240.0.0/16`，Nginx 已执行来源限制；共享网址尚待网关 Web 端口映射。具体映射要求和验收步骤见 [校园网统一访问配置](docs/校园网统一访问配置.md)。本机隧道工具仅用于运维，不作为所有用户的正式访问方式。

本地验证（Python 3.10、Node 20 或已验证的 Node 24）：

```powershell
cd frontend
npm ci
npm test
npm run build
```

```bash
cd backend
python -m pip install -r requirements-test.txt
python -m pytest
```

后端完整测试需 Linux，Windows 结果不代表 Linux 部署验收。仅测试环境使用隔离数据库、测试凭据及替代集群。真实 GPU/NFS/配额和持久化另做现场验证。

安全导出源码：`python scripts/create_source_bundle.py /安全路径/source.tar.gz`。它使用明确白名单，排除真实凭据、业务数据、虚拟环境、node_modules 和历史验收截图；前端 dist 如需部署单独打包。不要将整个工作目录直接压缩分享。
