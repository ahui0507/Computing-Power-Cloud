# TensorFlow 双卡训练与恢复

在平台申请两张 A100，选择 TensorFlow 2.18 / CUDA 12.5 开发版，将本目录的 `train.py` 保存到个人 `/data` 目录后执行：

```bash
python /data/train.py --steps 3 --checkpoint /data/tensorflow-checkpoint
python /data/train.py --steps 6 --checkpoint /data/tensorflow-checkpoint --resume
```

示例使用合成数据和 MirroredStrategy / NCCL 进行双卡训练，逐步检查梯度、参数更新和有限性。每步保存模型、优化器与训练步数；重新启动进程后核对恢复的权重摘要及优化器进度，再继续训练到目标总步数。`--steps` 是累计目标步数。

脚本明确使用两张 GPU，关闭设备自动回退，并启用显存按需增长。用于功能验证；训练速度不代表真实模型性能。

平台网站也提供 TensorFlow 示例：在“我的文件 → 创建训练示例”选择 TensorFlow，然后点击“创建并保存”。网站会生成个人 `/data` 目录下的 `train.py`，提供单卡、多卡及断点恢复命令；多卡数量应与实例申请数量一致。网站示例使用 `--epochs` 表示目标总轮数，与本目录独立验收脚本的 `--steps` 参数不同。

网站入口的实现与验收见 [TensorFlow 训练入口记录](../../docs/TensorFlow训练入口完善与验收-20261017.md)。
