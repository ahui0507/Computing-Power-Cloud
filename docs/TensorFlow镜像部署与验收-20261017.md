# TensorFlow 镜像部署与验收（2026-10-17）

已发布镜像：`docker.io/library/campus-workbench:tensorflow2-devel-20261017`。

当前状态：构建、GPU 与平台入口验收通过并已公开，目录显示 **TensorFlow 2.18 · CUDA 12.5 · 开发版**，镜像 ID 为 **6**。最终 API 确认镜像可选，平台为 healthy，环境检查全部通过。两个零费率测试实例均已释放并结算为 0，8 张 GPU 全部可用。

## 环境

| 组件 | 版本或能力 |
| --- | --- |
| 系统 / Python | Ubuntu 22.04 / Python 3.11.10 |
| 环境管理 | Conda，支持交互 Bash 激活；pip |
| TensorFlow / Keras | 2.18.1 / 3.8.0 |
| CUDA | 12.5.1，nvcc 12.5.82，包含运行库、头文件和开发库 |
| cuDNN / NCCL | 9.3.0.75 / 2.21.5 |
| JupyterLab | 4.2.5，Python Kernel |
| NumPy / pandas | 1.26.4 / 2.2.3 |
| SciPy / scikit-learn | 1.14.1 / 1.5.2 |
| Matplotlib / Pillow | 3.9.2 / 10.2.0 |
| h5py / ml-dtypes | 3.12.1 / 0.4.1 |
| tqdm / TensorBoard | 4.66.5 / 2.18.0 |
| 开发工具 | GCC/G++、make、CMake、Ninja 1.13.0、Git、curl、wget、tmux 等 |
| 访问 | JupyterLab、SSH、SFTP、sudo |
| 工作目录 | `/workspace` 临时目录；平台挂载 `/data` 个人持久目录 |

TensorFlow 2.18 的官方 GPU 构建组合为 CUDA 12.5 / cuDNN 9.3，来源为 [TensorFlow tested build configurations](https://www.tensorflow.org/install/source#gpu)。2.18.1 的官方 PyPI CUDA extra 也固定相应 CUDA 12.5 与 cuDNN 9.3 组件。本镜像由 NVIDIA 签名 DEB 提供这些库和开发工具链。

镜像针对本平台 A100 验收，不适用于 K80；驱动由宿主机 NVIDIA runtime 提供。镜像采用独立 Ubuntu / Miniconda 环境，无 PyTorch 安装。

## 材料与校验

- [基础环境锁文件](../deploy/workbench/tensorflow2-base.lock.json)：Ubuntu 官方 linux/amd64 清单 `sha256:98510ac07bb4545e389be502a8918b385c018bfe4ceeb5ac7e0375c782268b04`，config `sha256:cee13550f97b8a595506e8e4ca74263ba44924248779a4ba4f942e197652acff`。
- Miniconda 官方 `Miniconda3-py311_24.9.2-0-Linux-x86_64.sh`，SHA256 `62ef806265659c47e37e22e8f9adce29e75c4ea0497e619c280f54c823887c4f`，与 Anaconda 官方下载索引核对。
- [CUDA/cuDNN/NCCL DEB 锁文件](../deploy/workbench/cuda-tensorflow2-debs.lock.json)：48 个 NVIDIA 包，官方 Release 签名和 Packages SHA256 校验；公钥指纹 `EB693B3035CD5710E231E123A4B469963BF863CC`。
- Ubuntu 系统依赖由已核验签名的 Jammy/updates/security 索引解析，127 个 DEB；与 NVIDIA 包合计 175 个 DEB。
- [Python 直接依赖](../deploy/workbench/requirements-tensorflow2.in)及[完整 hash 锁文件](../deploy/workbench/requirements-tensorflow2.lock)：134 个 Linux/Python 3.11 wheel。下载可使用国内镜像传输，均对照官方 PyPI 和锁文件摘要核验。
- [离线 Dockerfile](../deploy/workbench/Dockerfile.tensorflow2-offline)、[上下文打包器](../deploy/workbench/prepare-tensorflow2-context.py)、[构建入口](../deploy/workbench/build-tensorflow2-offline.sh)、[验收器](../deploy/workbench/verify_tensorflow2.py)。

构建使用 `--pull=false --network none` 和 pip `--no-index --require-hashes`。安装包、wheel 和 Miniconda 安装器使用 BuildKit 只读挂载，成品不保留离线载荷。构建末尾清理临时工作区、root 历史和缓存、临时文件及 SSH 主机密钥，保存软件版本清单到 `/usr/local/share/campus-workbench/`。独立容器检查确认 `/workspace` 和镜像内的 `/data` 初始为空。

| 成品信息 | 实际值 |
| --- | --- |
| 镜像 config | `sha256:6d61c259b4ca931ca7c32f20d3487ec0fa591cae5df24be47d5e3f4c5399665a` |
| K3s 清单 | `sha256:97004930db04396037c67d9c9363d5bf531497adfa3b318984ade53aebf33150` |
| 逻辑大小 | 9,663,126,260 字节，约 9.66 GB |
| 验证硬件 | NVIDIA A100-PCIE-40GB，双卡 |

计算节点的完整构建上下文、软件清单、构建与导入日志位于 `/home/lvzhiqiang/cpcloud-operations/tensorflow-devel-20261017/`。官方签名索引、安装程序与已校验依赖位于 `/home/lvzhiqiang/cpcloud-stage/tensorflow-devel-20261017/`。控制节点验收、发布与环境检查部署备份位于 `/home/system/cpcloud-operations/tensorflow2-acceptance-20261017/`，包含已归档的首次尝试状态。对应本地材料位于 `.ops/tensorflow-devel-20261017/`。

## 实际验收

- 上下文打包器 5 项测试通过：DEB 损坏、缺失 CUDA 包、未锁定 wheel、已有目录保护、Miniconda 摘要校验。
- 平台环境检查 4 项回归通过：TensorFlow 双 GPU 识别、CPU 回退拒绝、PyTorch 兼容、缺少框架的中性提示。更新的检查脚本已部署，按请求读取，无需重启服务。
- 禁网构建和独立容器复检通过；依赖一致性、全部固定版本、CPU 运算、科学计算、绘图、TensorBoard event 读写、Jupyter Kernel 实际执行与 Conda 激活通过。
- CUDA SDK 头文件编译以及 TensorFlow GPU 自定义算子的编译/动态加载通过；当前阶段不分配 GPU。
- 公共镜像清理检查通过：无历史工作文件、共享 SSH 主机密钥、离线 DEB/wheel/安装器载荷；未安装 PyTorch。
- GPU 运算通过：cuBLAS 矩阵运算、cuDNN 卷积与反向传播、梯度有限性和 Keras 优化器参数更新均在显式 GPU 设备上完成。
- XLA GPU JIT 编译、TensorFlow CUDA 自定义算子编译/动态加载及 GPU 运算结果通过；验收器报告 `gpu_verified`、`xla_gpu`、`tensorflow_cuda_op`、`tensorflow_op_compilation`、`cuda_compilation` 和 `jupyter_kernel` 均为 true，GPU 数量为 2。
- 双卡 MirroredStrategy / NCCL 训练通过：第一进程保存 step=1 checkpoint，第二进程恢复后核对权重 SHA256、训练步数与优化器进度，再训练至 step=2；最终 replicas=2、optimizer_iterations=2、restored=true。
- 真实 Jupyter 认证入口、专用跳板与实例 SSH、sudo、nvcc 远端路径以及 SFTP 个人目录读写均通过；测试文件已删除。
- 网站 `/resource/{container_id}/diagnostics` 实测 Python、NumPy、TensorFlow、CUDA、两张 A100、Linux 工具与两个软件源检查全部通过，无缺少 PyTorch 的误报。
- 测试实例 `container-12-ebfc1107` 和 `container-13-6f343d8d` 均为 released、结算 0；最终资源汇总为 8/8 GPU 可用。最后一个验收实例释放后才将候选镜像公开；PyTorch 开发版仍可选。

网站的框架选择、单卡/多卡训练及恢复入口已补齐，使用方法和后续加强的各卡状态验收见 [TensorFlow 训练入口记录](TensorFlow训练入口完善与验收-20261017.md)。该验收进一步发现了当前环境中单进程 GPU 间复制的问题，网站示例使用每卡独立进程避开；上文早期双卡检查未核对每卡完整状态，不能据此推断任意 MirroredStrategy 程序均正确。

早期双卡验收脚本见 [examples/tensorflow_smoke](../examples/tensorflow_smoke/README.md)，实际训练建议优先使用网站生成的新示例。本轮为功能验收，不代表八卡长期稳定性或性能基准。模型权重和数据集由用户按需准备。
