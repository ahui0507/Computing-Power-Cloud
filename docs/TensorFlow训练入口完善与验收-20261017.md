# TensorFlow 训练入口完善与验收（2026-10-17）

“我的文件 → 创建训练示例”支持选择 PyTorch 或 TensorFlow，生成对应框架的程序和命令。TensorFlow 示例支持单卡、多卡、逐轮 checkpoint 和重新启动进程后的断点恢复。

## 使用方法

1. 创建实例时选择 TensorFlow 2.18 / CUDA 12.5 开发镜像，申请需要的 GPU 数量。
2. 进入“我的文件”，点击“创建训练示例”，选择 TensorFlow，再点击“创建并保存”。
3. 在实例 SSH 或 JupyterLab 终端执行对话框中的命令。多卡数量选择当前实例实际申请的数量。
4. 需要继续训练时，执行对应的单卡或多卡恢复命令。`--epochs 10` 表示累计完成十轮，不是额外增加十轮。

程序保存到唯一的 `/data/training-tensorflow-时间-随机值/train.py`，不会覆盖已有文件。默认每轮保存到同目录的 `checkpoint-tensorflow`，保留最近两个 checkpoint，包括模型参数、Adam 优化器、训练轮数与原 GPU 数量。`training-state.json` 记录权重及优化器摘要和进度，便于核验恢复结果。

示例使用合成回归数据，每轮 16 次更新，每卡 batch size 为 32，无需下载数据集。默认运行三轮。GPU 不足时明确报错；仅在主动指定 `--device cpu` 时执行 CPU 功能检查。更改恢复时的 GPU 数量会改变全局 batch size 和数据序列，脚本会提示数值轨迹可能不同。

## 多卡实现与兼容范围

实机检查发现，当前 PCIe 环境的 TensorFlow 单进程 GPU 间复制会出现次卡变量值异常；只设置 `NCCL_P2P_DISABLE=1` 无法覆盖 TensorFlow 自身的复制路径。因此网站示例采用每卡一个进程的 `MultiWorkerMirroredStrategy`，自动设置实例内的本地通信端口与 `CUDA_VISIBLE_DEVICES`，使用 RING 通信。用户仍只执行一条 `python ... --gpus N` 命令。

各进程只初始化一张 GPU，计算在 GPU 上执行。所有进程参与 checkpoint 保存，主进程保留个人持久目录中的 checkpoint，其余进程使用并清理临时目录。恢复时各进程从同一个持久 checkpoint 加载，严格核对模型、优化器和进度；训练结束后父进程比较所有 worker 的模型与优化器摘要。任一 worker 失败会停止其他 worker，并返回失败。

这一实现保证了示例在当前环境中的正确训练与恢复，没有修复宿主机的通用 GPU P2P 问题。自行编写单进程 MirroredStrategy 程序仍需验证各卡参数一致性；该问题与八卡性能优化保留为后续专项工作。短时功能验收不能代表长期稳定性、八卡效率或真实模型性能。

## 接口与兼容

- `POST /api/storage/examples/training` 接受 `{"framework":"tensorflow"}` 或 `{"framework":"pytorch"}`。
- 旧客户端不传请求体时继续生成 PyTorch 示例。
- 返回框架、目录、单卡/多卡训练命令和对应恢复命令；网页将 GPU 数量替换为可执行的数字。
- 非法框架返回 422，不创建目录或文件。个人目录、配额与文件写入检查继续生效。
- 训练命令是供用户在已申请实例中执行的入口；创建示例本身不申请 GPU、不启动训练。

## 验证

- Linux 服务器完整后端测试：330 项通过。
- 独立前端构建、类型检查通过，前端现有 43 项测试通过。
- CPU 连续两轮与一轮后恢复至两轮的模型权重 SHA256 完全一致，优化器均更新 32 次。
- 线上 API 验证 TensorFlow 文件内容、PyTorch 显式选择、旧请求体兼容和非法框架无写入。
- 真实浏览器验证两种框架创建流程、TensorFlow checkpoint 说明、GPU 数量修改同时更新训练及恢复命令，浏览器无错误。
- A100 单卡、双卡通过线上接口生成的脚本训练一轮，再分别启动新进程恢复至第二轮；最终 epoch=2、optimizer_iterations=32、restored=true，多卡 worker 的模型与优化器摘要一致。
- 验收订单使用进程内零费率设置，测试后释放实例并核对零费用与资源回收；未修改网站全局计费配置。

本轮仅发布训练入口相关文件及独立构建的前端产物，无数据库迁移。发布前比较线上源码基线，保留旧前端资源，切换 release 链接并验证健康状态，失败可回退 release。验收中生成的个人测试目录通过所属用户的文件接口清理。

最终 release：`20261017-tf-training-eb187b5829a2`。实机订单 `container-24-49358359` 已释放并结算为 `0.0000`，资源恢复为 8/8 GPU 可用；本轮 11 个测试目录、48 个文件或目录路径已清理，原有个人目录保留。线上 API 与浏览器下载的 TensorFlow 程序 SHA256 均为 `eb187b5829a24215d89b4ad4b6e9b5bb3e52a2016c79eb04ac13c8cac6cc929e`。

本地验证记录与发布材料位于 `.ops/tensorflow-training-entry-20261017/`；网页截图位于 `output/playwright/tensorflow-training-entry.png`。服务器记录位于 `/home/system/cpcloud-operations/tf-training-entry-20261017/`。归档采用明确文件清单，不包含登录凭据或浏览器认证状态。

实现入口：[生成服务](../backend/app/services/environment_service.py)、[TensorFlow 程序](../backend/app/assets/train_tensorflow.py)、[网页组件](../frontend/src/components/TrainingExample.vue)。
