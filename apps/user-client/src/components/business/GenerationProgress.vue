<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import type { RunStage } from '@/api/types'

const props = defineProps<{ stage: RunStage | null; history: RunStage[]; modelName: string }>()
const labels: Record<RunStage, string> = {
  submitting: '正在提交要求与准备参考资料',
  queued: '任务已接收，等待开始处理',
  validating: '正在核对要求并识别任务类型',
  clarifying: '正在整理需要确认的问题',
  reading: '正在整理参考资料与创作上下文',
  planning: '正在规划文章结构与引用安排',
  generating: '正在生成正文内容',
  checking: '正在检查输出结构与内容',
  saving: '正在保存文章版本',
  ready: '文章已就绪，正在完成任务收尾',
  reconnecting: '连接中断，正在恢复进度同步',
  completed: '本次生成已完成',
  failed: '本次生成未完成',
  cancelled: '本次生成已停止',
}
const recentSteps = computed(() => props.history.slice(0, -1).slice(-3))
const startedAt = Date.now()
const elapsed = ref(0)
const timer = setInterval(() => {
  elapsed.value = Math.floor((Date.now() - startedAt) / 1000)
}, 1000)
onBeforeUnmount(() => clearInterval(timer))
const waitTime = computed(() =>
  elapsed.value < 60
    ? `${elapsed.value} 秒`
    : `${Math.floor(elapsed.value / 60)} 分 ${elapsed.value % 60} 秒`,
)
</script>

<template>
  <div class="generation-progress" aria-label="生成进度">
    <div class="generation-progress__meta">
      <span class="generation-progress__model">{{ modelName }}</span>
      <span class="generation-progress__time">已等待 {{ waitTime }}</span>
    </div>
    <ol v-if="recentSteps.length" class="generation-progress__history" aria-label="最近经过的步骤">
      <li v-for="step in recentSteps" :key="step">
        <q-icon name="check" aria-hidden="true" />
        <span>{{ labels[step].replace(/^正在/, '') }}</span>
      </li>
    </ol>
    <div class="generation-progress__current" role="status" aria-live="polite" aria-atomic="true">
      <q-spinner-dots size="18px" color="primary" aria-hidden="true" />
      <span>{{ labels[stage ?? 'submitting'] }}</span>
    </div>
    <p v-if="elapsed >= 30 && stage === 'generating'" class="generation-progress__note">
      仍在等待模型返回正文，收到结果后会继续更新进度。
    </p>
  </div>
</template>

<style scoped lang="scss">
.generation-progress {
  display: grid;
  gap: 6px;
  width: 100%;
  min-width: 0;
  max-width: 100%;
  color: var(--app-text-secondary);
  font-size: 12px;
  line-height: 1.65;
  overflow-wrap: anywhere;

  &__meta,
  &__current,
  &__history li {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    min-width: 0;
  }

  &__meta {
    flex-wrap: wrap;
  }
  &__model,
  &__current span,
  &__history span {
    min-width: 0;
  }
  &__time {
    white-space: nowrap;
  }
  &__history {
    display: grid;
    gap: 3px;
    min-width: 0;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  &__history .q-icon,
  &__current .q-spinner {
    flex: 0 0 18px;
    margin-top: 2px;
  }
  &__current {
    color: var(--app-text-primary);
    font-size: 13px;
  }
  &__note {
    margin: 0;
  }
}
</style>
