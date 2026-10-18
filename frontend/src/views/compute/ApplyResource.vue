<template>
  <PageHeader
    title="创建实例"
    eyebrow="DEPLOY INSTANCE"
    description="申请 GPU 算力并附带个人持久存储，配置环境后即可开始使用。"
    ><el-button @click="router.push('/compute/pools')"
      ><el-icon><ArrowLeft /></el-icon>返回资源市场</el-button
    ></PageHeader
  >
  <div v-if="loadError" class="request-error section-gap">
    {{ loadError
    }}<el-button link type="primary" @click="load">重新加载</el-button>
  </div>
  <div class="form-grid">
    <el-alert
      v-if="
        !initialLoading &&
        budget.summary &&
        (budget.summary.remaining_instances === 0 ||
          budget.summary.remaining_gpus === 0)
      "
      title="资源配额已用满，释放不再使用的实例后重试，或联系管理员调整配额。"
      type="warning"
      :closable="false"
      style="grid-column: 1/-1"
    />
    <div class="panel" v-loading="initialLoading">
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-position="top"
        :disabled="submitting || ambiguous"
        @submit.prevent="submit"
      >
        <section class="form-section">
          <el-form-item label="申请内容"><el-tag>GPU 算力＋个人持久存储</el-tag></el-form-item>
          <el-form-item label="分配方式"><el-switch v-model="queueMode" active-text="排队申请（可取消，不占卡、不计费）" @change="clampCount(); form.accepted = false" /></el-form-item>
          <p v-if="queueMode" class="caption">资源可用后自动申请，按分配时价格、余额和配额校验。最多保留3个排队申请，默认24小时过期，以提交后显示的时间为准。</p>
          <h2 class="form-section-title">
            <span class="step-number">1</span>选择算力
          </h2>
          <el-form-item label="GPU 资源池" prop="pool_id"
            ><el-select
              v-model="form.pool_id"
              placeholder="请选择 GPU 资源池"
              style="width: 100%"
              @change="clampCount"
              ><el-option
                v-for="pool in resources.pools"
                :key="pool.pool_id"
                :value="pool.pool_id"
                :label="`${pool.gpu_type} · ${pool.name} · 可用 ${pool.free_gpus} 张`"
                :disabled="queueMode ? !pool.queue_max_gpus_per_instance : pool.free_gpus === 0" /></el-select></el-form-item
          ><el-form-item label="GPU 数量" prop="gpu_count"
            ><el-input-number
              :key="`${form.pool_id}-${maximum > 0}`"
              v-model="form.gpu_count"
              :min="1"
              :max="Math.max(1, maximum)"
              :disabled="!selectedPool || maximum === 0"
              controls-position="right"
            /><span class="caption" style="margin-left: 16px">{{
              selectedPool
                ? `资源池可用 ${selectedPool.free_gpus} 张 · 配额剩余 ${budget.summary?.remaining_gpus ?? '—'} 张`
                : '先选择资源池'
            }}</span></el-form-item
          >
        </section>
        <section class="form-section">
          <h2 class="form-section-title">
            <span class="step-number">2</span>选择开发环境
          </h2>
          <el-form-item label="容器镜像" prop="image_id"
            ><el-select
              v-model="form.image_id"
              filterable
              placeholder="选择镜像或搜索名称"
              style="width: 100%"
              ><el-option-group label="公共镜像"
                ><el-option
                  v-for="image in images.publicImages"
                  :key="image.image_id"
                  :value="image.image_id"
                  :disabled="!images.isAvailable(image.image_id, form.pool_id)"
                  :label="image.display_name || `${image.name}:${image.tag}`" /></el-option-group
              ><el-option-group v-if="images.myImages.length" label="我的镜像"
                ><el-option
                  v-for="image in images.myImages"
                  :key="image.image_id"
                  :value="image.image_id"
                  :disabled="!images.isAvailable(image.image_id, form.pool_id)"
                  :label="`${image.name}:${image.tag}`" /></el-option-group></el-select
          ></el-form-item>
          <p class="caption">
            {{
              selectedImage?.desc ||
              '选择包含 Jupyter 的开发镜像，创建后可直接打开 Notebook 和终端。'
            }}
          </p>
        </section>
        <section class="form-section">
          <h2 class="form-section-title">
            <span class="step-number">3</span>存储与计费
          </h2>
          <div class="hint-box" style="margin-bottom: 20px">
            <strong>附带个人持久存储：{{ personalStorageLimit }}</strong>
            <p v-if="storage.data.value?.limit_bytes != null">已用 {{ storageUsed }} · 额度内剩余 {{ storageRemaining }}</p>
            <p>自动挂载到 /data，同一账号的实例共享。重复申请不会叠加额度，释放实例后文件继续保留；个人文件与保存的镜像共用这份额度，无额外存储费用。需要扩容时联系管理员。</p>
          </div>
          <el-alert v-if="storage.data.value?.warning === 'full'" title="个人存储已满，写入新文件前请清理或联系管理员扩容。" type="warning" :closable="false" style="margin-bottom: 20px" />
          <el-form-item label="计费方式">
            <el-radio-group
              v-model="form.billing_mode"
              class="billing-plan-options"
              @change="form.accepted = false"
            >
              <el-radio-button label="on_demand"
                >按时<span>实际用量结算</span></el-radio-button
              >
              <el-radio-button label="day"
                >包日<span>24 小时 · 8 折</span></el-radio-button
              >
              <el-radio-button label="week"
                >包周<span>7 天 · 6 折</span></el-radio-button
              >
            </el-radio-group>
          </el-form-item>
          <el-form-item label="定时释放（可选）"><el-switch v-model="timedRelease" active-text="首次就绪后自动释放" /><el-input-number v-if="timedRelease" v-model="durationHours" :min="1" :max="720" style="margin-left:12px" /><span v-if="timedRelease" class="caption">小时</span></el-form-item>
          <p v-if="timedRelease" class="caption">到期会终止所有程序，请提前保存checkpoint；可在我的实例中修改或取消。包时订单提前释放不退费。</p>
          <div class="hint-box">
            <strong>临时工作 /workspace · 个人存储 /data</strong
            ><br />每个实例的 /workspace 独立且临时，释放后删除。主动保存到
            /data
            的个人文件长期保留，并由同一账号的实例共享；需要保留系统环境和临时工作文件时请保存个人镜像。<br /><template
              v-if="form.billing_mode === 'on_demand'"
              >按时计费：实例运行后产生费用，使用结束请及时释放。</template
            ><template v-else
              >包时下单扣余额，就绪后起算，到期自动释放；提前释放不退费，创建失败退回余额。</template
            >
          </div>
          <el-form-item prop="accepted" style="margin: 20px 0 0"
            ><el-checkbox v-model="form.accepted"
              >我已了解计费方式与文件保留规则</el-checkbox
            ></el-form-item
          >
        </section>
      </el-form>
    </div>
    <aside class="panel order-summary">
      <div class="panel-heading">
        <h2 class="panel-title">配置清单</h2>
        <el-tag size="small">{{ planLabel }}</el-tag>
      </div>
      <div class="summary-row">
        <span>GPU 型号</span
        ><strong>{{ selectedPool?.gpu_type || '尚未选择' }}</strong>
      </div>
      <div class="summary-row">
        <span>GPU 数量</span><strong>{{ form.gpu_count }} 张</strong>
      </div>
      <div class="summary-row">
        <span>CPU 份额</span><strong>{{ configurationShare }}</strong>
      </div>
      <div class="summary-row">
        <span>内存份额</span><strong>{{ configurationShare }}</strong>
      </div>
      <p class="caption">CPU 与内存在系统预留后，按申请 GPU 占节点 GPU 总数的比例分配，创建时锁定，费用已包含在算力价格中。</p>
      <div v-if="selectedPool?.ephemeral_storage_gib_per_gpu" class="summary-row">
        <span>临时磁盘限额</span><strong>{{ selectedPool.ephemeral_storage_gib_per_gpu * form.gpu_count }} GiB</strong>
      </div>
      <p v-if="selectedPool?.ephemeral_storage_gib_per_gpu" class="caption">临时目录、软件安装和容器日志合并计量。超额可能终止实例；重要文件请保存到 /data。</p>
      <div class="summary-row">
        <span>个人持久存储</span><strong>{{ personalStorageLimit }}</strong>
      </div>
      <p class="caption">账号共享额度，挂载到 /data；申请多卡或多个实例不叠加。</p>
      <div class="summary-row">
        <span>开发镜像</span
        ><strong>{{
          selectedImage
            ? selectedImage.display_name || `${selectedImage.name}:${selectedImage.tag}`
            : '尚未选择'
        }}</strong>
      </div>
      <div class="summary-row">
        <span>文件目录</span><strong>/workspace 临时 · /data 持久</strong>
      </div>
      <div class="summary-row">
        <span>可用余额</span
        ><strong
          >¥{{ budget.summary?.available_balance.toFixed(4) ?? '—' }}</strong
        >
      </div>
      <p class="caption section-gap">
        {{
          form.billing_mode === 'on_demand' ? '预估小时费用' : '本次预付费用'
        }}
      </p>
      <p class="price-display">
        {{ totalCost == null ? '—' : `¥${totalCost.toFixed(4)}` }}
        <small>{{
          form.billing_mode === 'on_demand'
            ? '/ 小时'
            : form.billing_mode === 'day'
              ? '/ 24 小时'
              : '/ 7 天'
        }}</small>
      </p>
      <p class="caption" style="margin: 10px 0 22px">
        {{
          form.billing_mode === 'on_demand'
            ? '按实际运行时长结算，最终金额以账单为准。'
            : '就绪后开始计时，到期释放，不自动续费。请在到期前保存工作。'
        }}
      </p>
      <el-alert
        v-if="packageInsufficient"
        title="可用余额不足，请联系管理员增加余额后再购买此套餐。"
        type="warning"
        :closable="false"
        style="margin-bottom: 16px"
      />
      <el-alert
        v-if="ambiguous"
        title="上次请求结果尚未确认，请先到我的实例检查；重试会沿用原申请标识。"
        type="warning"
        :closable="false"
        style="margin-bottom: 16px"
      /><el-button
        type="primary"
        style="width: 100%; height: 42px"
        :loading="submitting"
        :disabled="
          initialLoading ||
          !!loadError ||
          maximum === 0 ||
          hourlyCost == null ||
          (!queueMode && packageInsufficient)
        "
        @click="submit"
        >{{ ambiguous ? '重试原申请' : queueMode ? '确认并加入排队' : '申请算力与存储'
        }}<el-icon v-if="!submitting"><ArrowRight /></el-icon></el-button
      ><el-button
        v-if="ambiguous"
        link
        type="primary"
        style="width: 100%; margin: 12px 0 0"
        @click="router.push('/compute/instances')"
        >查看我的实例</el-button
      >
    </aside>
  </div>
</template>
<script setup lang="ts">
import { computed, reactive, ref, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { useResourceStore } from '@/stores/resource'
import { useImageStore } from '@/stores/image'
import { useBillingStore } from '@/stores/billing'
import { useBudgetStore } from '@/stores/budget'
import { useAutoRefresh } from '@/composables/useAutoRefresh'
import { useRemoteData } from '@/composables/useRemoteData'
import { storageApi, type StorageUsage } from '@/api/storage'
import { reportError } from '@/utils/feedback'
import PageHeader from '@/components/PageHeader.vue'
import { packageUnitPrice } from '@/utils/instance'
import { maximumCards, shareText } from '@/utils/compute'
import { resourceApi } from '@/api/resource'
import { applicationKey, finishApplication } from '@/utils/resource-request'
import { sessionRevision } from '@/utils/session'
import type { ApplyResourceRequest } from '@/types'
const queueMode = ref(false), timedRelease = ref(false), durationHours = ref(1)
const resources = useResourceStore(),
  images = useImageStore(),
  billing = useBillingStore()
const budget = useBudgetStore()
const storage = useRemoteData<StorageUsage | null>(async () => {
  const result = await storageApi.usage()
  if (!result.data) throw new Error('个人存储额度暂不可查询，请重试')
  return result.data
}, null)
const gibText = (bytes: number) => `${Number((bytes / 1024 ** 3).toFixed(2))} GiB`
const personalStorageLimit = computed(() => storage.data.value?.limit_bytes != null
  ? `${gibText(storage.data.value.limit_bytes)}（账号共享）`
  : storage.data.value?.enforcement === 'disabled' ? '未启用额度限制' : '正在查询')
const storageUsed = computed(() => storage.data.value?.used_bytes != null
  ? storage.data.value.used_bytes < 1024 ** 3 ? `${Number((storage.data.value.used_bytes / 1024 ** 2).toFixed(2))} MiB` : gibText(storage.data.value.used_bytes)
  : '—')
const storageRemaining = computed(() => storage.data.value?.limit_bytes != null && storage.data.value?.used_bytes != null
  ? gibText(Math.max(0, storage.data.value.limit_bytes - storage.data.value.used_bytes)) : '—')
const route = useRoute(),
  router = useRouter()
const formRef = ref<FormInstance>(),
  initialLoading = ref(true),
  submitting = ref(false),
  ambiguous = ref(false)
const form = reactive({
  pool_id: undefined as number | undefined,
  image_id: undefined as number | undefined,
  gpu_count: 1,
  accepted: false,
  billing_mode: 'on_demand' as 'on_demand' | 'day' | 'week',
})
const selectedPool = computed(() =>
  resources.pools.find((pool) => pool.pool_id === form.pool_id),
)
const selectedImage = computed(() =>
  images.getAllImages().find((image) => image.image_id === form.image_id),
)
const maximum = computed(() =>
  budget.summary && budget.summary.remaining_instances > 0
    ? queueMode.value ? Math.min(selectedPool.value?.queue_max_gpus_per_instance || 0, budget.summary.remaining_gpus) : maximumCards(selectedPool.value, budget.summary.remaining_gpus)
    : 0,
)
const configurationShare = computed(() =>
  shareText(form.gpu_count, selectedPool.value?.node_gpu_count),
)
const hourlyCost = computed(() => {
  const type = selectedPool.value?.gpu_type.toLowerCase()
  const price = type ? billing.prices?.[type] : undefined
  return price == null ? null : price * form.gpu_count
})
const loadError = computed(
  () =>
    resources.poolsError || images.error || billing.pricesError || budget.error || storage.error.value,
)
const planLabel = computed(() =>
  form.billing_mode === 'day'
    ? '包日 · 8 折'
    : form.billing_mode === 'week'
      ? '包周 · 6 折'
      : '按时计费',
)
const totalCost = computed(() => {
  if (hourlyCost.value == null) return null
  if (form.billing_mode === 'on_demand') return hourlyCost.value
  const frozen =
    form.billing_mode === 'day'
      ? selectedPool.value?.daily_price
      : selectedPool.value?.weekly_price
  return (
    (frozen ??
      packageUnitPrice(hourlyCost.value / form.gpu_count, form.billing_mode)) *
    form.gpu_count
  )
})
const packageInsufficient = computed(
  () =>
    form.billing_mode !== 'on_demand' &&
    totalCost.value != null &&
    !!budget.summary &&
    budget.summary.available_balance <
      totalCost.value +
        (budget.summary.hourly_cost * budget.summary.minimum_balance_minutes) /
          60,
)
const rules: FormRules = {
  pool_id: [
    {
      validator: (_rule, value, callback) =>
        callback(
          resources.pools.some(
            (pool) => pool.pool_id === value && (queueMode.value ? (pool.queue_max_gpus_per_instance || 0) > 0 : pool.free_gpus > 0),
          )
            ? undefined
            : new Error('请选择可申请的资源池'),
        ),
      trigger: 'change',
    },
  ],
  image_id: [
    {
      validator: (_rule, _value, callback) =>
        callback(
          selectedImage.value &&
            images.isAvailable(selectedImage.value.image_id, form.pool_id)
            ? undefined
            : new Error('请选择当前资源池已准备的镜像'),
        ),
      trigger: 'change',
    },
  ],
  gpu_count: [
    {
      validator: (_rule, value, callback) =>
        callback(
          Number.isInteger(value) && value >= 1 && value <= maximum.value
            ? undefined
            : new Error(`请输入1至${maximum.value}之间的整数`),
        ),
      trigger: 'change',
    },
  ],
  accepted: [
    {
      validator: (_rule, value, callback) =>
        callback(value ? undefined : new Error('请先确认计费和文件保留规则')),
      trigger: 'change',
    },
  ],
}
function clampCount() {
  if (maximum.value > 0)
    form.gpu_count = Math.min(Math.max(1, form.gpu_count || 1), maximum.value)
}
function prefill() {
  queueMode.value = route.query.queue === '1'
  const pool = Number(route.query.pool_id),
    image = Number(route.query.image_id),
    count = Number(route.query.gpu_count)
  form.billing_mode =
    route.query.billing_mode === 'day' || route.query.billing_mode === 'week'
      ? route.query.billing_mode
      : 'on_demand'
  form.accepted = false
  form.pool_id =
    resources.pools.find((item) => item.pool_id === pool && (queueMode.value ? (item.queue_max_gpus_per_instance || 0) > 0 : item.free_gpus > 0))
      ?.pool_id ||
    (route.query.pool_id
      ? undefined
      : resources.pools.find((item) => queueMode.value ? (item.queue_max_gpus_per_instance || 0) > 0 : item.free_gpus > 0)?.pool_id)
  form.image_id =
    images.getAllImages().find((item) => item.image_id === image)?.image_id ||
    (route.query.image_id
      ? undefined
      : images.publicImages.find((item) =>
          images.isAvailable(item.image_id, form.pool_id),
        )?.image_id)
  if (Number.isInteger(count) && count > 0) form.gpu_count = count
  clampCount()
}
async function load() {
  initialLoading.value = true
  await Promise.allSettled([
    resources.fetchPools(),
    images.fetchPublicImages(),
    images.fetchAvailability(),
    images.fetchMyImages(),
    billing.fetchPrices(),
    budget.refresh(),
    storage.refresh(),
  ])
  initialLoading.value = false
}
onMounted(async () => {
  await load()
  prefill()
})
watch(
  () => route.query,
  () => {
    if (!initialLoading.value) prefill()
  },
)
useAutoRefresh(async () => {
  if (!initialLoading.value && !submitting.value)
    await Promise.allSettled([resources.fetchPools(), budget.refresh(), storage.refresh()])
})
async function submit() {
  if (submitting.value || !formRef.value) return
  submitting.value = true
  const scope = sessionRevision()
  let submittedParameters: ApplyResourceRequest | undefined
  try {
    if (!(await formRef.value.validate().catch(() => false))) return
    const parameters = {
      pool_id: form.pool_id!,
      image_id: form.image_id!,
      gpu_count: form.gpu_count,
      billing_mode: form.billing_mode,
      ...(timedRelease.value ? {duration: durationHours.value} : {}),
    }
    submittedParameters = parameters
    if (queueMode.value) {
      const result = await resourceApi.enqueue(parameters, 'queue-' + applicationKey(parameters))
      if (scope !== sessionRevision()) return
      if (!result.data) return
      finishApplication(parameters)
      ambiguous.value = false
      ElMessage.success('已加入排队，等待期间不占卡、不计费')
      void router.push('/compute/instances')
      return
    }
    const created = await resources.applyResource(parameters)
    if (!created) return
    void budget.refresh().catch(() => {})
    ambiguous.value = false
    ElMessage.success('实例创建已提交，正在准备开发环境')
    void router.push({
      path: '/compute/instances',
      query: { id: created.container_id },
    })
  } catch (error) {
    if (scope !== sessionRevision()) return
    const code = (error as { code?: number }).code
    if (queueMode.value && submittedParameters && code && [400, 401, 403, 409, 422, 501].includes(code)) finishApplication(submittedParameters)
    ambiguous.value = (error as { code?: number }).code === 0
    if ((error as { code?: number }).code === 409)
      await Promise.allSettled([resources.fetchPools(), budget.refresh()])
    reportError(error)
  } finally {
    submitting.value = false
  }
}
</script>
