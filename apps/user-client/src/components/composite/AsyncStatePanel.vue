<script setup lang="ts">
import AppEmptyState from '@/components/base/AppEmptyState.vue'

withDefaults(
  defineProps<{
    loading?: boolean
    error?: string | null
    empty?: boolean
    emptyTitle?: string
    emptyDescription?: string
  }>(),
  {
    loading: false,
    error: null,
    empty: false,
    emptyTitle: '暂无内容',
  },
)

defineEmits<{ retry: [] }>()
</script>

<template>
  <div v-if="loading" class="async-panel" aria-live="polite">
    <q-skeleton v-for="index in 4" :key="index" type="rect" height="82px" animation="wave" />
  </div>
  <q-banner v-else-if="error" class="async-panel__error" rounded>
    <template #avatar><q-icon name="error_outline" color="negative" /></template>
    <span class="wrap-anywhere">{{ error }}</span>
    <template #action><q-btn flat color="primary" label="重试" @click="$emit('retry')" /></template>
  </q-banner>
  <AppEmptyState v-else-if="empty" :title="emptyTitle" :description="emptyDescription"
    ><slot name="empty-action"
  /></AppEmptyState>
  <slot v-else />
</template>

<style scoped lang="scss">
.async-panel {
  display: grid;
  gap: 12px;

  &__error {
    color: var(--app-text-primary);
    background: color-mix(in srgb, var(--app-danger) 9%, var(--app-bg-surface));
    border: 1px solid color-mix(in srgb, var(--app-danger) 28%, transparent);
  }
}
</style>
