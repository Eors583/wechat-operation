<script setup lang="ts">
import AppIcon from '@/components/base/AppIcon.vue'
defineProps<{
  label: string
  value: string
  delta?: string
  tone: string
  icon: string
  to: string
}>()
</script>

<template>
  <el-card
    shadow="never"
    class="surface-card metric-card"
    role="link"
    tabindex="0"
    :aria-label="`${label}：${value}`"
    @click="$router.push(to)"
    @keydown.enter="$router.push(to)"
  >
    <div class="metric-card__top">
      <admin-avatar :class="`tone-${tone}`" :size="40"><AppIcon :name="icon" /></admin-avatar>
      <AppIcon name="arrow_forward" />
    </div>
    <div class="metric-card__body">
      <div class="metric-card__label">{{ label }}</div>
      <div class="metric-card__value">{{ value }}</div>
      <div v-if="delta" class="metric-card__delta">{{ delta }}</div>
    </div>
  </el-card>
</template>

<style scoped lang="scss">
.metric-card {
  min-width: 0;
  cursor: pointer;
  transition:
    transform 140ms ease,
    box-shadow 140ms ease;
}
.metric-card:hover {
  transform: translateY(-2px);
}
.metric-card__top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.metric-card__body {
  padding-top: var(--space-4);
}
.tone-primary {
  background: var(--app-action-primary);
}
.tone-positive {
  background: var(--app-action-success);
}
.tone-warning {
  background: var(--app-action-warning);
}
.tone-negative {
  background: var(--app-action-danger);
}
.metric-card__label {
  color: var(--app-text-secondary);
}
.metric-card__value {
  margin-top: 4px;
  font-size: 30px;
  font-weight: 750;
  line-height: 1.2;
  overflow-wrap: anywhere;
}
.metric-card__delta {
  margin-top: 8px;
  color: var(--app-text-secondary);
  font-size: 13px;
  overflow-wrap: anywhere;
}
</style>
