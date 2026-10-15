<template>
  <section class="hint-box section-gap">
    <template v-if="separate">
      <strong>临时工作目录 /workspace · 个人存储 /data</strong>
      <p class="caption">
        SSH 和 Jupyter Terminal 默认进入
        /workspace。实例释放后，系统盘与临时工作文件会删除；需要保留的代码、数据和模型请主动复制到
        /data，或保存为个人镜像。
      </p>
      <p class="caption">例如保存一个项目目录：</p>
      <code>cp -a /workspace/my-project /data/</code>
      <el-button
        link
        type="primary"
        @click="copyText('cp -a /workspace/my-project /data/')"
        >复制示例</el-button
      >
    </template>
    <template v-else
      ><strong>旧实例的个人存储目录：/workspace</strong>
      <p class="caption">
        此实例沿用创建时的持久目录。新版实例使用临时 /workspace 与持久
        /data；原个人文件继续保留。
      </p></template
    >
  </section>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import type { Container } from '@/types'
import { copyText } from '@/utils/feedback'
const props = defineProps<{ instance: Container }>()
const separate = computed(() => props.instance.storage_layout === 'separate-v1')
</script>
