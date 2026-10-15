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
            将需要保留的结果主动保存到 /data。实例系统盘和 /workspace
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
              个人文件与保存的镜像共用存储额度，由管理员按用户存储池的份额分配。「我的文件」显示占用比例，接近上限时会提醒；达到额度后需要清理文件、镜像或联系管理员调整份额，原文件继续保留。请将模型定期保存到
              /data，备份无法保存训练进程的内存状态。
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
