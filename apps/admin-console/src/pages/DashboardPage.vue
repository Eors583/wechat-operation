<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import type { DashboardSummary, JobRecord } from '@/api/contracts'
import { adminRepository } from '@/api/repository'
import AppIcon from '@/components/base/AppIcon.vue'
import StatusBadge from '@/components/base/StatusBadge.vue'
import MetricCard from '@/components/composite/MetricCard.vue'
import PageHeader from '@/components/composite/PageHeader.vue'

const loading = ref(false)
const dashboard = ref<DashboardSummary>({
  metrics: [],
  ai_success_rate: 100,
  ai_average_latency_ms: 0,
  current_abnormal_models: 0,
  account_health: { healthy: 0, degraded: 0, down: 0 },
  failed_tasks: {},
  recent_changes: [],
})
const jobs = ref<JobRecord[]>([])
const lastRefreshed = ref('刚刚')
const metricIcons = ['group', 'smart_toy', 'forum', 'error']
const toneMap: Record<string, string> = {
  primary: 'primary',
  positive: 'positive',
  warning: 'warning',
  negative: 'negative',
}
const failedJobs = computed(() =>
  jobs.value.filter((job) => ['failed', 'unknown'].includes(job.status)).slice(0, 4),
)

async function refresh(): Promise<void> {
  loading.value = true
  try {
    ;({ summary: dashboard.value, jobs: jobs.value } = await adminRepository.dashboard())
    lastRefreshed.value = new Intl.DateTimeFormat('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    }).format(new Date())
  } finally {
    loading.value = false
  }
}

onMounted(() => void refresh())
</script>

<template>
  <section class="admin-page">
    <PageHeader
      title="管理首页"
      description="快速确认 AI、公众号连接和后台任务是否正常；指标仅用于定位问题，不展示用户正文。"
      eyebrow="运行总览"
    >
      <template #actions>
        <el-button :loading="loading" @click="refresh"
          ><AppIcon name="refresh" />刷新状态</el-button
        >
      </template>
    </PageHeader>

    <div class="dashboard-meta"><AppIcon name="schedule" /> 数据更新：{{ lastRefreshed }}</div>
    <section class="metric-grid" aria-label="核心指标">
      <MetricCard
        v-for="(metric, index) in dashboard.metrics"
        :key="metric.label"
        :label="metric.label"
        :value="metric.value"
        :delta="metric.delta"
        :to="metric.route"
        :tone="toneMap[metric.tone] ?? 'primary'"
        :icon="metricIcons[index] ?? 'monitoring'"
      />
    </section>

    <section class="dashboard-grid">
      <el-card shadow="never" class="surface-card health-card">
        <template #header
          ><h2>AI 运行质量</h2>
          <p>今日所有生成任务的聚合状态</p></template
        >
        <div class="health-card__body">
          <div class="success-ring" :style="{ '--rate': `${dashboard.ai_success_rate * 3.6}deg` }">
            <div>
              <strong>{{ dashboard.ai_success_rate }}%</strong><span>成功率</span>
            </div>
          </div>
          <div class="health-stats">
            <div>
              <span>平均耗时</span
              ><strong>{{ (dashboard.ai_average_latency_ms / 1000).toFixed(1) }} 秒</strong>
            </div>
            <div>
              <span>当前异常模型</span
              ><strong :class="dashboard.current_abnormal_models ? 'tone-danger' : 'tone-success'"
                >{{ dashboard.current_abnormal_models }} 个</strong
              >
            </div>
            <el-button link type="primary" @click="$router.push('/ai/config')"
              >查看模型与积分</el-button
            >
          </div>
        </div>
      </el-card>

      <el-card shadow="never" class="surface-card connection-card">
        <template #header
          ><h2>公众号连接</h2>
          <p>授权与 Token 状态聚合</p></template
        >
        <div class="connection-list">
          <div class="connection-row">
            <admin-avatar class="connection-success"><AppIcon name="link" /></admin-avatar>
            <div><strong>连接正常</strong><span>可以执行草稿和发布操作</span></div>
            <strong>{{ dashboard.account_health.healthy }}</strong>
          </div>
          <div class="connection-row">
            <admin-avatar class="connection-warning"><AppIcon name="sync_problem" /></admin-avatar>
            <div><strong>需要重新连接</strong><span>用户下次发送时收到重新授权提示</span></div>
            <strong>{{ dashboard.account_health.degraded }}</strong>
          </div>
          <div class="connection-row">
            <admin-avatar class="connection-danger"><AppIcon name="link_off" /></admin-avatar>
            <div><strong>平台或权限异常</strong><span>可能影响新增绑定、草稿或发布</span></div>
            <strong>{{ dashboard.account_health.down }}</strong>
          </div>
        </div>
        <div class="card-actions">
          <el-button link type="primary" @click="$router.push('/wechat/accounts')"
            >检查公众号连接</el-button
          >
        </div>
      </el-card>

      <el-card shadow="never" class="surface-card failed-card" :body-style="{ padding: '0' }">
        <template #header
          ><div class="card-heading">
            <div>
              <h2>最近失败与待核对任务</h2>
              <p>结果不确定的微信任务必须先对账</p>
            </div>
            <el-button link type="primary" @click="$router.push('/tasks')">全部任务</el-button>
          </div></template
        >
        <div class="failed-list">
          <button
            v-for="job in failedJobs"
            :key="job.id"
            class="failed-row"
            @click="$router.push({ path: '/tasks', query: { job: job.id } })"
          >
            <AppIcon :name="job.status === 'unknown' ? 'help' : 'error'" />
            <span class="min-width-zero"
              ><strong>{{ job.resource_label }}</strong
              ><small class="long-text">{{ job.error_code }} · {{ job.stage }}</small></span
            >
            <StatusBadge :status="job.status" />
          </button>
        </div>
      </el-card>

      <el-card shadow="never" class="surface-card recent-card">
        <template #header
          ><h2>最近发布配置</h2>
          <p>仅影响发布后的新任务</p></template
        >
        <el-timeline v-if="dashboard.recent_changes.length">
          <el-timeline-item
            v-for="change in dashboard.recent_changes"
            :key="change.id"
            :timestamp="change.published_at"
            type="primary"
          >
            <strong>{{ change.type }} · {{ change.name }}</strong>
            <div class="text-secondary">{{ change.version }} 已发布</div>
          </el-timeline-item>
        </el-timeline>
        <div v-else class="text-secondary">尚无已发布的模型配置、提示词或官方技能。</div>
      </el-card>
    </section>
  </section>
</template>

<style scoped lang="scss">
.dashboard-meta {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 6px;
  margin: -14px 0 16px;
  color: var(--app-text-secondary);
  font-size: 12px;
}
.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 18px;
  min-width: 0;
}
.dashboard-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20px;
  min-width: 0;
  margin-top: 20px;
}
.dashboard-grid > * {
  min-width: 0;
}
h2 {
  margin: 0;
  font-size: 18px;
}
p {
  margin: 4px 0 0;
  color: var(--app-text-secondary);
  overflow-wrap: anywhere;
}
.health-card__body {
  display: flex;
  align-items: center;
  gap: clamp(22px, 4vw, 52px);
  min-width: 0;
}
.success-ring {
  display: grid;
  place-items: center;
  flex: 0 0 150px;
  aspect-ratio: 1;
  border-radius: 50%;
  background: conic-gradient(var(--app-action-success) var(--rate), var(--app-bg-subtle) 0);
}
.success-ring::before {
  content: '';
  grid-area: 1 / 1;
  width: 118px;
  aspect-ratio: 1;
  border-radius: 50%;
  background: var(--app-bg-surface);
}
.success-ring > div {
  display: flex;
  z-index: 1;
  grid-area: 1 / 1;
  flex-direction: column;
  align-items: center;
}
.success-ring strong {
  font-size: 25px;
}
.success-ring span {
  color: var(--app-text-secondary);
}
.health-stats {
  display: grid;
  flex: 1;
  gap: 12px;
  min-width: 0;
}
.health-stats > div {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
}
.health-stats span,
.health-stats strong {
  min-width: 0;
  overflow-wrap: anywhere;
}
.card-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
}
.card-heading > div,
.min-width-zero {
  min-width: 0;
}
.connection-list,
.failed-list {
  min-width: 0;
}
.connection-row {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  min-width: 0;
  padding: 14px 0;
  border-bottom: 1px solid var(--app-border-default);
}
.connection-row > div {
  display: flex;
  min-width: 0;
  flex-direction: column;
}
.connection-row span {
  color: var(--app-text-secondary);
  font-size: 12px;
  overflow-wrap: anywhere;
}
.connection-success {
  background: color-mix(in srgb, var(--app-action-success) 16%, transparent);
  color: var(--app-action-success);
}
.connection-warning {
  background: color-mix(in srgb, var(--app-action-warning) 16%, transparent);
  color: var(--app-action-warning);
}
.connection-danger {
  background: color-mix(in srgb, var(--app-action-danger) 16%, transparent);
  color: var(--app-action-danger);
}
.card-actions {
  display: flex;
  justify-content: flex-end;
  padding-top: 12px;
}
.failed-row {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  width: 100%;
  min-width: 0;
  padding: 14px 20px;
  border: 0;
  border-bottom: 1px solid var(--app-border-default);
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
}
.failed-row:hover {
  background: var(--app-bg-subtle);
}
.failed-row span {
  display: flex;
  flex-direction: column;
}
.failed-row small {
  color: var(--app-text-secondary);
}
.recent-card :deep(.el-timeline) {
  padding: 4px 0 0 8px;
}

@media (max-width: 1199px) {
  .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (max-width: 899px) {
  .dashboard-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
@media (max-width: 599px) {
  .metric-grid {
    grid-template-columns: minmax(0, 1fr);
    gap: 12px;
  }
  .health-card__body {
    align-items: stretch;
    flex-direction: column;
  }
  .success-ring {
    align-self: center;
  }
  .card-heading {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
