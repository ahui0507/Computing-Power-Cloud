<template>
  <PageHeader
    title="使用指南"
    eyebrow="GET STARTED"
    description="从创建第一台实例，到保存工作成果。"
  />
  <div class="two-columns">
    <section class="panel">
      <h2 class="panel-title">快速开始</h2>
      <div class="guide-steps">
        <div class="guide-step">
          <h3>选择算力</h3>
          <p>
            进入资源市场，选择 GPU
            型号与可用数量。创建页会显示完整配置，可选择按小时、包日或包周。
          </p>
          <el-button link type="primary" @click="router.push('/compute/pools')"
            >浏览资源市场 →</el-button
          >
        </div>
        <div class="guide-step">
          <h3>准备开发环境</h3>
          <p>
            选择包含 Jupyter
            的镜像并确认创建。在我的实例中等待状态变为运行中，然后打开
            JupyterLab 或浏览器终端。
          </p>
        </div>
        <div class="guide-step">
          <h3>上传代码并运行</h3>
          <p>
            在我的文件中上传 Python 脚本。文件会出现在实例的 /data
            中。打开终端执行以下命令，或在运行任务中提交后台命令。
          </p>
          <p>
            也可点击「我的文件 →
            创建训练示例」，使用生成的单卡或多卡命令开始训练。实例详情中的「环境自检」可检查
            GPU 运算与下载源连接。
          </p>
          <pre class="hint-box mono" style="margin-top: 12px">
cd /workspace
python -u /data/hello.py</pre>
        </div>
        <div class="guide-step">
          <h3>保存结果并释放实例</h3>
          <p>
            实例临时磁盘按申请的 GPU 数量分配，限额在创建页和实例列表显示；系统盘可写层、/tmp、/workspace 和日志合并计量。超额可能终止实例。将需要保留的结果主动保存到 /data。实例系统盘和 /workspace
            为临时空间，释放后会删除；/data
            文件继续保留。使用结束后释放实例，费用会结算并进入历史订单。下次申请实例可接着使用。
          </p>
        </div>
      </div>
    </section>
    <div class="stack">
      <section class="panel">
        <h2 class="panel-title">使用前了解这些</h2>
        <el-collapse
          ><el-collapse-item title="个人存储有额度吗？" name="storage-quota"
            ><p class="caption">
              申请 GPU 算力时自动附带个人持久存储，默认300 GiB，实际额度以创建页和「我的文件」显示为准。同一账号的实例共享 /data，重复申请不叠加额度，释放实例后文件继续保留。个人文件与保存的镜像共用额度，接近上限时提醒；达到额度后需要清理或联系管理员扩容，原文件继续保留。请将模型定期保存到
              /data，释放实例会终止正在运行的进程。
            </p></el-collapse-item
          ><el-collapse-item title="关闭网页会停止计费吗？" name="billing"
            ><p class="caption">
              不会。关闭网页或退出登录不会停止实例。请在我的实例中释放不再使用的资源。
            </p></el-collapse-item
          ><el-collapse-item title="释放后哪些内容会保留？" name="files"
            ><p class="caption">
              /data
              中的代码、数据和结果会保留，所有个人实例共享此目录。系统盘环境可在释放前保存为个人镜像，之后用该镜像重新申请。
            </p></el-collapse-item
          ><el-collapse-item title="如何运行后台任务？" name="jobs"
            ><p class="caption">
              进入运行任务，选择运行中的实例，输入命令。命令以临时 /workspace
              为工作目录执行，日志可在线查看。释放实例会终止任务，取消任务不会释放实例。
            </p></el-collapse-item
          ><el-collapse-item title="训练中断后如何继续？" name="resume">
            <p class="caption">新生成的训练示例每个epoch保存模型、优化器及进度到脚本旁的checkpoint.pt。将示例放在个人存储目录；释放后从历史订单再次申请，选择原镜像或已保存的个人镜像，再运行：</p>
            <pre class="hint-box mono">python /data/示例目录/train.py --resume /data/示例目录/checkpoint.pt --epochs 10</pre>
            <p class="caption">epochs表示目标总轮数；多卡使用torchrun并追加相同参数。中断时从最近完成的epoch恢复。镜像保存不包含训练进程，恢复后仍需手动启动命令；自行编写的训练代码需实现自己的checkpoint逻辑。</p>
          </el-collapse-item
          ><el-collapse-item title="资源不足时可以排队吗？" name="queue">
            <p class="caption">创建页可选择排队申请，等待期间不占卡、不计费，可在我的实例取消。资源可用后自动申请并通知，分配时重新校验价格、余额和配额。每账号最多3个未完成申请，默认24小时过期。较小申请可能先于暂不能满足的大申请启动。</p>
          </el-collapse-item
          ><el-collapse-item title="可以定时释放吗？" name="schedule">
            <p class="caption">创建时可设置首次就绪后多少小时释放，或在我的实例设置具体时间、修改或取消。到期前60分钟和10分钟发出站内提醒。到期会终止所有程序，个人存储文件保留；包时订单提前释放不退费。若镜像正在保存，回收等待保存完成或超时，计费截止仍保留原计划时间。</p>
          </el-collapse-item
          ><el-collapse-item title="SSH 与镜像快照支持吗？" name="access"
            ><p class="caption">
              公共工作环境支持 JupyterLab、SSH 和 SFTP。从我的实例打开 SSH
              连接信息，复制命令和密码即可登录，也可在账户设置中添加公钥。
              点击保存镜像可保存已安装的软件；镜像不包含运行中的进程或 /data
              文件。
            </p></el-collapse-item
          ><el-collapse-item title="CPU 和内存如何分配？" name="compute"
            ><p class="caption">
              默认每个节点先预留 20% 的 CPU 和内存给系统，其余按申请 GPU
              数占节点 GPU 总数的比例分配。 页面显示 CPU
              和内存份额，实际限制由节点硬件容量计算，并在创建时锁定。CPU
              限制可使用的计算时间，内存为实例上限，共享内存也计入其中。
              GPU、CPU
              和内存一起预留，资源不足时无法申请。旧订单保留原配额，不追溯改成新的比例规则。
            </p></el-collapse-item
          ><el-collapse-item title="包日、包周如何计费？" name="packages"
            ><p class="caption">
              包日按 24 小时费用的 8 折，包周按 168 小时费用的 6
              折。下单时一次扣除余额，实例就绪后开始计时，到期自动释放。
              提前释放不退费；实例未就绪即创建失败会全额退回。请在到期前将成果保存到
              /data，或完成个人镜像保存。
            </p></el-collapse-item
          ><el-collapse-item title="如何增加余额？欠费后会怎样？" name="payment"
            ><p class="caption">
              校内平台余额由管理员统一增加。可用余额不超过 10
              元时预警；欠费后现有按小时实例保留 6
              小时，用于保存文件和个人镜像，期间可联系管理员补充余额。到期自动释放实例，个人存储继续保留；保存期内仍按实例原费率计费。已付款的包日、包周实例按套餐到期时间释放。
            </p></el-collapse-item
          ></el-collapse
        >
      </section>
      <div class="hint-box">
        多人同时申请时，空闲数量可能变化。若资源不足，刷新资源市场并重新选择；遇到网络超时，先检查我的实例再重试，避免重复申请。
      </div>
    </div>
  </div>
</template>
<script setup lang="ts">
import { useRouter } from 'vue-router'
import PageHeader from '@/components/PageHeader.vue'
const router = useRouter()
</script>
