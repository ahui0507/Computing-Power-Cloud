<template>
  <PageHeader
    class="compute-page-heading"
    title="资源市场"
    eyebrow="COMPUTE MARKET"
    description="选择 GPU 和开发环境，支持按时、包日八折、包周六折。"
    ><el-button :loading="store.poolsLoading" @click="refresh"
      ><el-icon><Refresh /></el-icon>刷新资源</el-button
    ><el-button type="primary" @click="router.push('/compute/instances')"
      >我的实例</el-button
    ></PageHeader
  >
  <div class="toolbar">
    <div class="toolbar-filters">
      <el-input
        v-model="search"
        placeholder="搜索 GPU 型号或资源池"
        clearable
        aria-label="搜索资源"
        ><template #prefix
          ><el-icon><Search /></el-icon></template></el-input
      ><el-switch v-model="availableOnly" active-text="仅看可申请" />
    </div>
    <span class="caption"
      >{{ available }} 张 GPU 当前可申请 · 每 15 秒更新</span
    >
  </div>
  <AsyncState
    :loading="store.poolsLoading"
    :error="store.poolsError"
    :empty="filtered.length === 0"
    empty-text="暂无符合条件的资源，可以刷新或调整筛选"
    @retry="refresh"
    ><div
      class="gpu-card-grid"
      :class="{ 'single-pool': filtered.length === 1 }"
    >
      <article v-for="pool in filtered" :key="pool.pool_id" class="gpu-card">
        <div class="gpu-card-top">
          <div class="gpu-symbol">
            <el-icon><Cpu /></el-icon>
          </div>
          <el-tag
            :type="pool.free_gpus > 0 ? 'success' : 'info'"
            effect="light"
            >{{ pool.free_gpus > 0 ? '可立即申请' : '暂时满载' }}</el-tag
          >
        </div>
        <div class="gpu-card-content">
          <div class="gpu-technical">
            <h2>{{ pool.gpu_type }}</h2>
            <p class="caption">{{ pool.name }}</p>
            <dl class="gpu-compatibility">
              <div>
                <dt>显存</dt>
                <dd>
                  {{
                    pool.memory_mb
                      ? `${(pool.memory_mb / 1024).toFixed(1)} GiB`
                      : '待登记'
                  }}
                </dd>
              </div>
              <div>
                <dt>计算能力</dt>
                <dd>{{ pool.compute_capability || '待登记' }}</dd>
              </div>
              <div>
                <dt>NVIDIA 驱动</dt>
                <dd>{{ pool.driver_versions?.join(' / ') || '待采集' }}</dd>
              </div>
              <div>
                <dt>最高 CUDA（架构）</dt>
                <dd>{{ pool.cuda_arch_max || '待核验' }}</dd>
              </div>
              <div>
                <dt>驱动报告 CUDA</dt>
                <dd>
                  {{ pool.driver_cuda_versions?.join(' / ') || '待采集' }}
                </dd>
              </div>
              <div>
                <dt>每卡 CPU 份额</dt>
                <dd>{{ shareText(1, pool.node_gpu_count) }}</dd>
              </div>
              <div>
                <dt>每卡内存份额</dt>
                <dd>{{ shareText(1, pool.node_gpu_count) }}</dd>
              </div>
            </dl>
            <p v-if="pool.recommended_environment" class="gpu-runtime-note">
              推荐 {{ pool.recommended_environment }}
            </p>
            <p class="caption">
              驱动报告值与镜像 CUDA 运行时版本不同，请优先选择已验证的推荐环境。
            </p>
            <div class="gpu-specs">
              <span
                >总量 <strong>{{ pool.total_gpus }}</strong> 张</span
              ><span
                >可用 <strong>{{ pool.free_gpus }}</strong> 张</span
              ><span
                >单实例最多
                {{ pool.max_gpus_per_instance ?? pool.free_gpus }} 张</span
              >
            </div>
            <p class="caption">
              节点为系统预留 {{ pool.system_cpu_percent ?? 20 }}% CPU、{{
                pool.system_ram_percent ?? 20
              }}% 内存，剩余额度按 GPU 占比分配，创建后锁定。
            </p>
            <p
              v-if="
                (pool.physical_free_gpus ?? pool.free_gpus) > pool.free_gpus
              "
              class="caption"
            >
              GPU 空闲 {{ pool.physical_free_gpus }} 张；可申请数量还受
              CPU、内存和节点状态限制。
            </p>
          </div>
          <div class="gpu-purchase">
            <el-progress
              :percentage="
                pool.total_gpus
                  ? Math.round(
                      ((pool.total_gpus - pool.free_gpus) / pool.total_gpus) *
                        100,
                    )
                  : 0
              "
              :show-text="false"
              :stroke-width="4"
              color="#87a8e8"
              class="section-gap"
            />
            <div class="gpu-card-bottom">
              <div class="gpu-price">
                {{ price(pool.gpu_type) }}<small> / 卡·小时</small>
              </div>
              <el-button
                type="primary"
                :disabled="pool.free_gpus < 1"
                @click="
                  router.push({
                    path: '/compute/apply',
                    query: { pool_id: pool.pool_id },
                  })
                "
                >创建实例<el-icon><ArrowRight /></el-icon
              ></el-button>
            </div>
            <div class="package-offers">
              <button
                type="button"
                :disabled="pool.free_gpus < 1"
                @click="
                  router.push({
                    path: '/compute/apply',
                    query: { pool_id: pool.pool_id, billing_mode: 'day' },
                  })
                "
                aria-label="选择包日八折"
              >
                <span>包日 <em>8 折</em></span
                ><strong
                  >¥{{ pool.daily_price?.toFixed(2) ?? '—'
                  }}<small> / 卡·天</small></strong
                >
              </button>
              <button
                type="button"
                :disabled="pool.free_gpus < 1"
                @click="
                  router.push({
                    path: '/compute/apply',
                    query: { pool_id: pool.pool_id, billing_mode: 'week' },
                  })
                "
                aria-label="选择包周六折"
              >
                <span>包周 <em>6 折</em></span
                ><strong
                  >¥{{ pool.weekly_price?.toFixed(2) ?? '—'
                  }}<small> / 卡·周</small></strong
                >
              </button>
            </div>
          </div>
        </div>
      </article>
    </div></AsyncState
  >
  <div class="hint-box section-gap">
    <strong>使用提示</strong
    >　资源数量会随其他用户申请实时变化，最终以提交时分配结果为准。实例运行后可通过
    JupyterLab 或浏览器终端使用；文件请保存到 /data。
  </div>
</template>
<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useResourceStore } from '@/stores/resource'
import { useBillingStore } from '@/stores/billing'
import { useAutoRefresh } from '@/composables/useAutoRefresh'
import PageHeader from '@/components/PageHeader.vue'
import AsyncState from '@/components/AsyncState.vue'
import { shareText } from '@/utils/compute'
const router = useRouter(),
  store = useResourceStore(),
  billing = useBillingStore()
const search = ref(''),
  availableOnly = ref(false)
const filtered = computed(() =>
  store.pools.filter(
    (pool) =>
      (!availableOnly.value || pool.free_gpus > 0) &&
      `${pool.name} ${pool.gpu_type}`
        .toLowerCase()
        .includes(search.value.toLowerCase()),
  ),
)
const available = computed(() =>
  store.pools.reduce((sum, pool) => sum + pool.free_gpus, 0),
)
function price(type: string) {
  const value = billing.prices?.[type.toLowerCase()]
  return value == null ? '价格加载中' : `¥${value.toFixed(2)}`
}
const refresh = useAutoRefresh(async () => {
  await Promise.allSettled([store.fetchPools(), billing.fetchPrices()])
})
</script>
