<script setup lang="ts">
import { computed } from 'vue'
import AppIcon from './AppIcon.vue'

const props = defineProps<{ status: string; label?: string }>()

type TagTone = 'primary' | 'success' | 'warning' | 'danger' | 'info'
const dictionary: Record<string, { label: string; type: TagTone; icon: string }> = {
  draft: { label: '草稿', type: 'info', icon: 'edit_note' },
  testing: { label: '测试中', type: 'warning', icon: 'science' },
  published: { label: '已发布', type: 'success', icon: 'check_circle' },
  available: { label: '已发布', type: 'success', icon: 'check_circle' },
  disabled: { label: '已停用', type: 'info', icon: 'pause_circle' },
  healthy: { label: '正常', type: 'success', icon: 'check_circle' },
  degraded: { label: '需关注', type: 'warning', icon: 'warning' },
  down: { label: '异常', type: 'danger', icon: 'error' },
  active: { label: '正常', type: 'success', icon: 'check_circle' },
  ai_suspended: { label: 'AI 已限制', type: 'warning', icon: 'smart_toy' },
  wechat_suspended: { label: '公众号已限制', type: 'warning', icon: 'forum' },
  connected: { label: '连接正常', type: 'success', icon: 'link' },
  reconnect_required: { label: '需重新连接', type: 'danger', icon: 'link_off' },
  limited: { label: '能力受限', type: 'warning', icon: 'gpp_maybe' },
  queued: { label: '排队中', type: 'info', icon: 'schedule' },
  running: { label: '执行中', type: 'primary', icon: 'sync' },
  failed: { label: '失败', type: 'danger', icon: 'error' },
  unknown: { label: '结果待核对', type: 'warning', icon: 'help' },
  completed: { label: '已完成', type: 'success', icon: 'check_circle' },
  cancelled: { label: '已取消', type: 'info', icon: 'close' },
}

const config = computed(
  () => dictionary[props.status] ?? { label: props.status, type: 'info' as const, icon: 'info' },
)
</script>

<template>
  <el-tag round effect="plain" :type="config.type" class="status-badge">
    <AppIcon :name="config.icon" :size="14" />
    <span>{{ label ?? config.label }}</span>
  </el-tag>
</template>

<style scoped lang="scss">
.status-badge {
  max-width: 100%;
  gap: 4px;
  padding: 5px 8px;
  font-weight: 600;
  white-space: normal;
  overflow-wrap: anywhere;
}
</style>
