# 公共工作环境构建

`Dockerfile` 和 `build.sh` 构建 Python 3.10、JupyterLab、SSH 的基础环境。`Dockerfile.devel` 在该基础上构建 `campus-workbench:20261012`，增加常用 Linux 工具、编译环境及适配现有 K80 的 NumPy/PyTorch。

| 类别 | 内容 |
| --- | --- |
| 终端与编辑 | Bash、补全、Vim、Nano、less、tmux |
| 文件与下载 | curl、wget、Git、OpenSSH、rsync、zip/unzip、tar、gzip/bzip2/xz、file |
| 进程与网络 | ps/pgrep、htop、ip/ss、ping、dig、ifconfig、lsof、traceroute、nc |
| 编译 | GCC/G++、make、CMake、pkg-config |
| Python 与开发入口 | Python 3.10.15、JupyterLab 4.2.5、SSH/SFTP |
| GPU 环境 | PyTorch 1.13.1+cu117、CUDA 11.7 用户态库、NumPy 1.26.4 |

CUDA 驱动仍由宿主机 NVIDIA runtime 注入；镜像不安装宿主机驱动。PyTorch 版本针对 K80 固定，其他 GPU/框架版本应制作独立镜像。

## 构建

需要 Linux amd64、Docker、可用的基础镜像以及 Debian 软件仓库网络。若基础镜像尚不存在，先按原构建入口准备 standalone Python 3.10 与 Jupyter 的 Linux wheel 缓存：

```bash
sh deploy/workbench/build.sh /opt/platform-python310 /home/REPLACE_SERVICE_USER/platform-wheels campus-workbench:20261010
```

准备新版所需 wheel，再构建开发环境：

```bash
python3 deploy/workbench/prepare-devel-wheels.py --output /home/REPLACE_SERVICE_USER/campus-devel-wheels
sh deploy/workbench/build-devel.sh /home/REPLACE_SERVICE_USER/campus-devel-wheels campus-workbench:20261012
docker run --rm --network none campus-workbench:20261012 campus-check
```

下载程序使用公开镜像站传输，并核对 PyPI/PyTorch 官方索引提供的 SHA256；已校验的缓存可重复使用。镜像采用多阶段构建，最终镜像保留已安装环境，不包含构建时的两份大型 wheel。软件版本清单位于 `/usr/local/share/campus-workbench/`。

下载站较慢时，也可复用管理员专用验收环境中已验证的安装缓存。`prepare-installed-cache.py` 只提取指定版本 NumPy/PyTorch 的包文件和命令，核对 OCI 清单、增量层及每个 RECORD 摘要，拒绝未记录文件；不提取用户工作目录、SSH 配置或其他系统文件。此入口要求目标软件完整存在于验收快照最后的增量层中，缺失时停止；不要将真实用户镜像整张公开。

```bash
python3 deploy/workbench/prepare-installed-cache.py --archive ADMIN_ACCEPTANCE.oci.tar --output /home/REPLACE_SERVICE_USER/verified-devel-cache
sh deploy/workbench/build-devel.sh - campus-workbench:20261012 campus-workbench:20261010 /home/REPLACE_SERVICE_USER/verified-devel-cache
```

缓存构建同样从原公共基础镜像开始，仅覆盖已校验的软件包。缓存清单记录源层摘要及所有复制文件的 SHA256，构建时再次核对。

镜像的 PATH 指向 `/opt/campus-python/bin`，SSH、Jupyter、网页终端共用 Python 环境。交互 Bash 载入补全和 `ll`/`la`；非交互任务不输出启动提示。

所有公共镜像构建最后执行 `clean-public-image.sh`：清空临时工作区、root 的历史与缓存、Jupyter 运行记录及临时目录，并恢复发行版默认 Shell 配置。已有完整开发镜像可直接生成新的干净版本，无需重装软件：

```bash
sh deploy/workbench/build-clean.sh campus-workbench:20261012 campus-workbench:20261011
docker run --rm --network none campus-workbench:20261012 campus-check
```

此清理只用于管理员构建公共镜像，不在实例启动时清空目录。个人镜像保留用户明确保存的环境；个人持久存储 `/data` 不参与清理。

## 导入与上线

使用固定版本标签，避免覆盖仍被旧实例或个人镜像引用的基础环境。导出后向每个候选计算节点的 `k8s.io` 镜像缓存导入：

```bash
docker save campus-workbench:20261012 > /srv/platform-images/.bootstrap/campus-workbench-20261012.tar
# 在挂载了镜像共享目录的计算节点执行：
sudo k3s ctr -n k8s.io images import --local --platform linux/amd64 --label io.cri-containerd.image=managed /mnt/platform-images/.bootstrap/campus-workbench-20261012.tar
```

后端 `scripts/publish_workbench.py` 先把镜像登记为指定验收用户的私有环境，完成真实实例测试后再公开。以下管理员和验收用户 ID 仅为当前现场示例，其他部署使用自己的 ID；`--size-bytes` 填 Docker inspect 的实际值：

```bash
cd backend
.venv/bin/python scripts/publish_workbench.py --admin-id 9 --staging-owner-id 17 --size-bytes IMAGE_SIZE --apply
# 在实例中验收：
campus-check --require-gpu --check-network
# 验收后公开同一条登记：
.venv/bin/python scripts/publish_workbench.py --admin-id 9 --size-bytes IMAGE_SIZE --apply
```

普通用户不能运行登记脚本。省略 `--apply` 时只预览；重复发布相同配置不重复写审计。先验收再公开，不把个人已保存的镜像改为公共镜像。

新版公开后运行 `scripts/retire_unusable_images.py --admin-id 9 --apply` 下架带旧测试文件的公共版本。下架只禁止新的申请，保留订单关联、已有实例及个人镜像所需的基础缓存；不要删除或覆盖旧标签。

## 用户使用

选择 `docker.io/library/campus-workbench:20261012` 创建实例，标准工具和 GPU PyTorch 已预装。实例中运行 `campus-check --require-gpu --check-network` 可检查工具、C 编译、CUDA 张量结果和外部下载站。

同一实例申请多张 GPU 后，可使用预装的 PyTorch DistributedDataParallel / NCCL 并行训练，运行方式见 [多卡训练示例](../../examples/multi_gpu/README.md)。v0.5.1 的实例模板提供默认 1 GiB 的独立共享内存挂载，镜像本身无需重建；此前创建的旧实例需保存后重新申请以使用新挂载。

新实例的 `/workspace` 是临时工作区，持久文件请主动保存到 `/data`。平台在实例启动时统一 Bash、SSH/SFTP 和 Jupyter Terminal 的工作目录及环境，已有基础镜像无需重建。自行安装的其他系统/Python 软件仍需通过「保存镜像」保留，释放后再次申请时选择该个人镜像。已创建的旧实例和旧个人镜像继续使用其原环境，不会自动增加新版工具。
