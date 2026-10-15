# 单实例多卡训练与测速

在资源申请页为**同一个实例选择 2 张或 4 张卡**，使用 `campus-workbench:20261011` 公共环境。将本目录的 `train_benchmark.py` 上传到 `/workspace`，从 SSH 或 Jupyter 终端执行。无需额外安装依赖。

脚本包含一个六层卷积分类模型，使用 FP32、PyTorch DistributedDataParallel 和 NCCL。总批量固定为 64，分别在 1 / 2 / 4 张卡上使用每卡 64 / 32 / 16 个样本；每个进程绑定一张卡并处理互不重叠的数据。脚本同时检查通信、梯度平均、各进程权重一致、损失下降和模型保存/加载。

```bash
cd /workspace

# 单卡基准
python train_benchmark.py --warmup 10 --steps 200 --trials 3 \
  --output single.json --checkpoint single.pt

# 双卡同步训练
python -m torch.distributed.run --standalone --nproc_per_node=2 \
  train_benchmark.py --warmup 10 --steps 200 --trials 3 \
  --output dual.json --checkpoint dual.pt

# 仅在已申请四张卡的实例中运行
python -m torch.distributed.run --standalone --nproc_per_node=4 \
  train_benchmark.py --warmup 10 --steps 200 --trials 3 \
  --output four.json --checkpoint four.pt
```

每次独立执行并等待结束，避免测速任务相互竞争 GPU。输出 `median_seconds` 是三轮中位数，`samples_per_second` 是整个实例的训练吞吐，`all_ranks_weight_max_difference` 应为 0。单卡时间除以多卡时间即本次负载的加速比；文件和模型保存在 `/workspace`，释放实例后继续保留。

这里使用 GPU 内的合成数据，排除了下载、磁盘读取和数据加载时间；计时也排除了进程启动、模型构建和预热。因此该结果用于确认多卡同步训练能力及计算吞吐，不代表所有真实模型都能取得相同加速。数据加载、模型大小、总批量、GPU 间通信和 CPU 都会影响实际速度。小任务可能因同步开销而变慢，多卡显存也不会自动合并为一块显存。

自己的训练代码需要适配 DistributedDataParallel，并为实际数据集配置 DistributedSampler 等分片方式；`torchrun` 负责启动进程，不会自动改写一个单卡训练脚本。分别租多个独立实例用于同一次训练，还需要跨实例网络与分布式初始化配置，本示例针对同一节点上的单实例多卡。

平台从 v0.5.1 起为新实例提供独立的 `/dev/shm` 内存挂载，默认上限 1 GiB，供 NCCL 与多进程数据加载使用。旧实例保留容器原有共享内存，遇到 SIGBUS 或共享内存不足时，先保存文件与环境，再释放重新申请。

现场结果见 [多卡训练验收](../../docs/多卡并行训练验收-2026-10-11.md)。
