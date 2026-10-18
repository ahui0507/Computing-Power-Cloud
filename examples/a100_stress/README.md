# A100 单卡 / 双卡训练压力测试

通过扫描稠密矩阵乘和大模型训练负载，测量当前软硬件环境可达到的吞吐，并检查持续训练期间的驱动、ECC、温度及多卡通信状态。

## 负载

- 矩阵乘扫描：BF16 / TF32，方阵边长 4096、8192、12288、16384。预热后用 CUDA Event 测三次，每次十个矩阵乘，报告三次吞吐中位数。
- 模型：四层 8192 → 8192 的全连接网络，268,435,456 个参数，BF16 自动混合精度，FP32 权重和梯度，SGD 优化器。
- 批量扫描：每卡 2048、4096、8192、16384，按实测训练吞吐选出配置。
- 持续单卡训练：600 秒；持续双卡 DDP 训练：600 秒。
- 每次优化器更新累积四个微批，双卡在最后一个微批同步梯度。每个时间窗口检查所有梯度是否有限；结束时广播并逐参数核对两卡权重。

合成输入常驻 GPU，测量重点是计算、优化器和通信。用于驱动压力测试的回归目标不代表真实任务质量。

## 运行

在已分配至少两张 A100 的同一实例里运行完整流程：

```bash
OMP_NUM_THREADS=2 NCCL_DEBUG=WARN python -u stress.py suite \
  --seconds 600 --output stress-results
```

输出目录必须为新目录。单独运行指定配置：

```bash
mkdir single-results
python -u stress.py train --seconds 600 --batch 8192 --output single-results

mkdir dual-results
python -m torch.distributed.run --standalone --nproc_per_node=2 \
  stress.py train --seconds 600 --batch 8192 --output dual-results

# 额外的双卡计算压力组：减少同步频率，提高持续计算占比。
mkdir dual-peak-results
python -m torch.distributed.run --standalone --nproc_per_node=2 \
  stress.py train --seconds 600 --batch 8192 --accumulation 64 \
  --window-steps 2 --output dual-peak-results
```

当前站点由平台注入 `NCCL_P2P_DISABLE=1`，双卡测试会沿用并记录该配置。此处测试的是当前已部署通信路径，不是硬件 P2P 性能。

现场额外执行了上面的双卡计算压力组，因而实际包含三组各十分钟的训练。标准 `suite` 包含单卡和双卡同步组；第三组单独运行。第三组累积 64 个微批，其有效批量及参数更新频率与标准组不同。

## 独立监控

在计算节点、容器之外运行 `host_monitor.py`，需要读取内核日志的权限。UUID 由实例分配结果确定：

```bash
sudo python3 host_monitor.py --output /tmp/a100-monitor \
  --uuid GPU-REPLACE-FIRST --uuid GPU-REPLACE-SECOND --seconds 1800
```

每秒采集 NVML 温度、利用率、功耗、时钟、显存和 ECC；保存测试前后的完整 `nvidia-smi -q -x`；记录测试开始后新增的内核 GPU / PCIe / IOMMU 错误，以及启动 ID 和 NVIDIA 模块版本。默认温度退出阈值为 88°C。

监控发现温度达到阈值、GPU 消失、新增不可纠正 ECC、NVML 查询失败或新增相关内核错误时写入 `fault.json`。现场本地编排器每十秒读取该标记并取消本次平台训练任务。监控本身只读，不改变功耗上限、时钟、驱动或节点配置。

`stress.py suite` 对每个阶段设置超时；退出码和分阶段日志保存在平台任务及结果目录。独立监控通过输出目录内的 `stop` 文件结束，也有总时长上限。手动运行监控时，应由外部编排器负责读取故障标记并停止训练。

## 吞吐口径与结论边界

GEMM 每次计算量为 `2*N^3`，报告稠密吞吐，不计稀疏加速。训练每个微批的 GEMM 计算量为 `(6*depth-2)*batch*width^2`：包含所有线性层前向、权重梯度，以及第一层以外的输入梯度。训练时间包含通信、优化器、数值检查和 Python 调度开销，排除进程启动和预热；吞吐是两卡总和。

扫描所得最高值是本次配置范围内的实测峰值，不能等同于理论硬件极限。双卡使用固定每卡批量，属于随卡数增加总负载的吞吐对比；不能解释为相同总批量的延迟加速。十分钟未观察到驱动故障只能说明本次负载和时长通过，不能保证长时间运行或所有八张卡都稳定。

现场最终数据与曲线由 `summarize.py` 从下载的原始结果生成。
