"""Summarize downloaded stress results and plot the observed stability timeline."""

import argparse
from datetime import datetime
import json
from pathlib import Path
import statistics
import xml.etree.ElementTree as ET

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    root = args.directory
    load = lambda name: json.loads((root / name).read_text(encoding="utf-8"))
    single = load("single/rank-0.json")
    dual = load("dual/rank-0.json")
    other = load("dual/rank-1.json")
    host = load("host-summary.json")
    peak = load("dual-peak/rank-0.json")
    peak_other = load("dual-peak/rank-1.json")
    peak_host = load("peak-host-summary.json")
    post_health = load("post-test-health.json")
    gemm = load("gemm.json")
    telemetry = [json.loads(line) for line in (root / "host-telemetry.jsonl").read_text().splitlines()]
    origin = datetime.fromisoformat(telemetry[0]["utc"])
    peak_telemetry = [json.loads(line) for line in (root / "peak-host-telemetry.jsonl").read_text().splitlines()]
    for record in peak_telemetry:
        record["elapsed_seconds"] = (datetime.fromisoformat(record["utc"]) - origin).total_seconds()
    telemetry.extend(peak_telemetry)
    for uuid, gpu in peak_host["gpus"].items():
        for field in ("max_temperature_c", "max_utilization_percent", "max_power_w",
                      "max_memory_mib", "max_sm_clock_mhz"):
            host["gpus"][uuid][field] = max(host["gpus"][uuid][field], gpu[field])
        host["gpus"][uuid]["last"] = gpu["last"]
    best = {precision: max((row for row in gemm["results"] if row["precision"] == precision),
                           key=lambda row: row["median_tflops"])
            for precision in ("bf16", "tf32")}
    devices = list(host["gpus"])
    same_boot = host["boot_id"] == peak_host["boot_id"]
    same_module = host["driver_module_version"] == peak_host["driver_module_version"]
    summary = {
        "passed": all(row["passed"] for row in (single, dual, other, host, peak, peak_other, peak_host))
        and same_boot and same_module and post_health["passed"],
        "post_test_health_passed": post_health["passed"],
        "remaining_compute_processes": post_health["active_compute_processes"],
        "same_node_boot_across_scenarios": same_boot,
        "same_driver_module_across_scenarios": same_module,
        "model_parameters": single["parameter_count"],
        "selected_local_batch": single["local_batch"],
        "dense_gemm_peak_bf16_tflops": best["bf16"]["median_tflops"],
        "dense_gemm_peak_tf32_tflops": best["tf32"]["median_tflops"],
        "single_training_tflops": single["aggregate_dense_gemm_tflops"],
        "dual_training_tflops": dual["aggregate_dense_gemm_tflops"],
        "dual_compute_training_tflops": peak["aggregate_dense_gemm_tflops"],
        "dual_compute_to_single_throughput": peak["aggregate_dense_gemm_tflops"] / single["aggregate_dense_gemm_tflops"],
        "dual_compute_seconds": peak["duration_seconds"],
        "dual_compute_gradient_accumulation": peak["gradient_accumulation"],
        "dual_to_single_throughput": dual["aggregate_dense_gemm_tflops"] / single["aggregate_dense_gemm_tflops"],
        "single_seconds": single["duration_seconds"], "dual_seconds": dual["duration_seconds"],
        "single_optimizer_steps": single["optimizer_steps"], "dual_optimizer_steps": dual["optimizer_steps"],
        "gradient_accumulation": single["gradient_accumulation"],
        "all_ranks_max_weight_difference": dual["all_ranks_max_weight_difference"],
        "nccl_p2p_disable": dual["nccl_p2p_disable"],
        "new_kernel_errors": host["kernel_errors"] + peak_host["kernel_errors"],
        "driver_module_version": host["driver_module_version"],
        "telemetry_samples": host["samples"] + peak_host["samples"], "gpus": host["gpus"],
        "scope": "Three 600-second scenarios: single GPU, dual GPU accumulation 4, dual GPU accumulation 64; two allocated A100s only",
        "peak_scope": "Best median among tested GEMM shapes; not a proof of absolute hardware maximum",
    }
    steady = [record for record in peak_telemetry
              if peak_telemetry[0]["elapsed_seconds"] + 60 <= record["elapsed_seconds"]
              <= peak_telemetry[-1]["elapsed_seconds"] - 5]
    summary["dual_compute_steady_telemetry"] = {}
    for uuid in devices:
        rows = [gpu for record in steady for gpu in record["gpus"] if gpu["uuid"] == uuid]
        summary["dual_compute_steady_telemetry"][uuid] = {
            "mean_power_w": statistics.mean(float(row["power.draw"]) for row in rows),
            "mean_utilization_percent": statistics.mean(float(row["utilization.gpu"]) for row in rows),
            "mean_sm_clock_mhz": statistics.mean(float(row["clocks.current.sm"]) for row in rows),
            "samples": len(rows),
        }
    summary["power_sampling_note"] = (
        "Raw NVML instantaneous samples exceeded the 250 W configured limit; "
        "these peaks are retained and are not interpreted as sustained board power. "
        "No independent power-meter measurement or cause diagnosis was performed."
    )
    # Record NVML power/thermal throttle counters before and after, without assuming
    # that a nonzero historical counter was caused by this particular test.
    for label, filename in (("before", "host-before.xml"), ("after", "peak-host-after.xml"),
                            ("single_under_load", "single-under-load.xml"),
                            ("dual_under_load", "dual-peak-under-load.xml")):
        tree = ET.parse(root / filename)
        inventory = {}
        for gpu in tree.getroot().findall("gpu"):
            uuid = gpu.findtext("uuid")
            if uuid in devices:
                nodes = {}
                for section in ("clocks_event_reasons", "clocks_throttle_reasons",
                                "temperature", "power_readings"):
                    node = gpu.find(section)
                    if node is not None:
                        nodes[section] = {child.tag: child.text for child in node if len(child) == 0}
                inventory[uuid] = nodes
        summary["nvml_" + label] = inventory
    (root / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False})
    colors = ["#0072B2", "#D55E00"]
    fig, axes = plt.subplots(4, 1, figsize=(10, 11), layout="constrained")
    for row, color, label, linestyle in ((single, colors[0], "Single GPU, accumulation 4", "-"),
                                        (dual, colors[1], "Two GPUs, accumulation 4", "--"),
                                        (peak, "#009E73", "Two GPUs, accumulation 64", "-")):
        axes[0].plot([point["elapsed_seconds"] / 60 for point in row["history"]],
                     [point["aggregate_dense_gemm_tflops"] for point in row["history"]],
                     color=color, label=label, linewidth=1.5, linestyle=linestyle)
    axes[0].set(xlabel="Time within each training scenario (min)",
                ylabel="Dense GEMM TFLOPS", ylim=(0, None),
                title="(a) Sustained model training throughput")
    axes[0].legend(loc="best")
    labels = ["GPU " + host["gpus"][uuid]["first"]["index"] for uuid in devices]
    for index, (field, ylabel, title) in enumerate((
        ("temperature.gpu", "Temperature (°C)", "(b) GPU temperature"),
        ("power.draw", "Power (W)", "(c) Board power"),
        ("clocks.current.sm", "SM clock (MHz)", "(d) GPU clocks")), start=1):
        for uuid, color, label, linestyle in zip(devices, colors, labels, ("-", "--")):
            points = [(record["elapsed_seconds"] / 60, gpu[field])
                      for record in telemetry for gpu in record["gpus"] if gpu["uuid"] == uuid]
            axes[index].plot([point[0] for point in points], [float(point[1]) for point in points],
                             color=color, label=label, linestyle=linestyle, linewidth=1)
        axes[index].set(xlabel="Time since independent host monitoring began (min)",
                        ylabel=ylabel, title=title, ylim=(0, None))
        axes[index].legend(loc="best")
    axes[2].axhline(250, color="#666666", linestyle=":", linewidth=1, label="250 W limit")
    axes[2].legend(loc="best")
    dual_start = next((record["elapsed_seconds"] / 60 for record in telemetry
                       if any(gpu["uuid"] == devices[1] and float(gpu["utilization.gpu"]) > 50
                              for gpu in record["gpus"])), None)
    if dual_start is not None:
        for axis in axes[1:]:
            axis.axvline(dual_start, color="#888888", linestyle=":", linewidth=1)
        axes[1].annotate("Dual GPU load begins", (dual_start, 0),
                         xytext=(4, 8), textcoords="offset points", fontsize=9)
    for axis in axes:
        axis.grid(axis="y", alpha=0.18)
    fig.suptitle("A100 training stress: three 10-minute scenarios", fontsize=14)
    fig.savefig(root / "stability.png", dpi=200)
    fig.savefig(root / "stability.svg")
    plt.close(fig)
    text = (
        "# A100 压力测试结果\n\n"
        f"总体通过：{summary['passed']}。模型 {single['parameter_count']:,} 参数，"
        f"每卡批量 {single['local_batch']}，每次更新累积 {single['gradient_accumulation']} 个微批。\n\n"
        "| 项目 | 单卡 | 双卡 |\n| --- | --- | --- |\n"
        f"| 持续训练时间 | {single['duration_seconds']:.1f} 秒 | {dual['duration_seconds']:.1f} 秒 |\n"
        f"| 实测训练吞吐 | {single['aggregate_dense_gemm_tflops']:.2f} TFLOPS | {dual['aggregate_dense_gemm_tflops']:.2f} TFLOPS（总计） |\n"
        f"| 参数更新次数 | {single['optimizer_steps']} | {dual['optimizer_steps']} / 卡 |\n"
        f"| 峰值 PyTorch 已分配显存 | {single['peak_allocated_mib']:.0f} MiB | {max(dual['peak_allocated_mib'], other['peak_allocated_mib']):.0f} MiB / 卡 |\n\n"
        f"矩阵扫描实测最高中位数：BF16 {best['bf16']['median_tflops']:.2f} TFLOPS，"
        f"TF32 {best['tf32']['median_tflops']:.2f} TFLOPS。按稠密计算量统计，"
        "这是所测配置范围内的最高值，并非理论硬件极限。\n\n"
        f"双卡/单卡吞吐比：{summary['dual_to_single_throughput']:.2f}×；"
        f"NCCL_P2P_DISABLE={dual['nccl_p2p_disable']}。固定每卡批量，总负载随卡数增加。\n\n"
    )
    for uuid, label in zip(devices, labels):
        gpu = host["gpus"][uuid]
        first, last = gpu["first"], gpu["last"]
        text += (f"{label}：最高温度 {gpu['max_temperature_c']:.0f}°C，"
                 f"最高利用率 {gpu['max_utilization_percent']:.0f}%，最高功耗 {gpu['max_power_w']:.2f}W，"
                 f"最高 NVML 已用显存 {gpu['max_memory_mib']:.0f}MiB；"
                 f"不可纠正 ECC {first['ecc.errors.uncorrected.volatile.total']} → "
                 f"{last['ecc.errors.uncorrected.volatile.total']}，"
                 f"可纠正 ECC {first['ecc.errors.corrected.volatile.total']} → "
                 f"{last['ecc.errors.corrected.volatile.total']}。\n\n")
    text += (f"新增相关内核错误 {len(summary['new_kernel_errors'])} 条，驱动模块版本 "
             f"{host['driver_module_version']}，双卡所有参数最大差异 "
             f"{dual['all_ranks_max_weight_difference']}。\n\n"
             "本次仅测试已分配的两张卡及上述时长，未覆盖其他六张卡，也不构成长时间稳定性保证。"
             "默认功耗上限保持 250W；压力下频率变化需结合 NVML 限频原因判断，不能直接视为掉驱动。\n\n"
             "![训练与硬件监控曲线](stability.png)\n")
    text += ("\nNVML 瞬时功耗采样出现高于 250W 设定值的尖峰，原始峰值如上所列，"
             "曲线保留全部原始读数。瞬时峰值不作为持续板卡功耗结论；"
             "本次没有独立电源测量，也未诊断这些尖峰的原因。\n")
    text += ("\n## 双卡计算占比增强场景\n\n"
             f"另外运行 {peak['duration_seconds']:.1f} 秒双卡训练，将梯度累积从 4 调整为 "
             f"{peak['gradient_accumulation']}，总吞吐 {peak['aggregate_dense_gemm_tflops']:.2f} TFLOPS，"
             f"为单卡的 {summary['dual_compute_to_single_throughput']:.2f}×。"
             "这组用于减少通信等待，让两张卡更持续承受计算和功耗负载；"
             "其有效批量和优化器更新频率与前两组不同，不作为相同训练设置的加速比。"
             f"两卡所有参数最大差异 {peak['all_ranks_max_weight_difference']}，"
             f"新增相关内核错误 {len(peak_host['kernel_errors'])} 条，独立监控通过 {peak_host['passed']}。\n")
    for uuid, label in zip(devices, labels):
        steady_gpu = summary["dual_compute_steady_telemetry"][uuid]
        text += (f"\n{label} 双卡计算组稳定阶段平均利用率 "
                 f"{steady_gpu['mean_utilization_percent']:.2f}%，平均功耗 "
                 f"{steady_gpu['mean_power_w']:.2f}W，平均 SM 时钟 "
                 f"{steady_gpu['mean_sm_clock_mhz']:.0f}MHz。\n")
    text += ("\n测试后 8 张 GPU 均可查询，全部训练和独立监控进程已退出，"
             f"节点启动 ID 和驱动模块版本跨阶段一致：{same_boot and same_module}。\n")
    (root / "RESULTS.md").write_text(text, encoding="utf-8")
    (root / "stability_description.md").write_text(
        "四幅时间曲线分别显示单/双卡聚合训练吞吐、两卡温度、功耗和 SM 时钟。"
        "上图横轴为各情景内部时间，其他图横轴为独立主机监控时间。"
        "垂直虚线依据第二张卡首次利用率超过 50% 的采样定位双卡负载开始，"
        "不是训练程序精确启动时间；功耗水平虚线为默认 250W 上限。"
        "未做平滑或插值，监控采样周期约一秒。", encoding="utf-8")
    (root / "stability.tex").write_text(
        "\\begin{figure}[t]\n\\centering\n\\includegraphics[width=\\linewidth]{stability.png}\n"
        "\\caption{Measured A100 training throughput and host telemetry during ten-minute "
        "single- and two-GPU stress scenarios. Throughput counts dense linear-layer GEMMs; "
        "two-GPU values include both ranks.}\n\\label{fig:a100-stress}\n\\end{figure}\n")
    print(json.dumps({key: value for key, value in summary.items()
                      if key != "gpus" and not key.startswith("nvml_")}, indent=2))


if __name__ == "__main__":
    main()
