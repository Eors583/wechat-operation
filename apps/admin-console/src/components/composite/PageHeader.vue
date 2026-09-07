<script setup lang="ts">
defineProps<{ title: string; description: string; eyebrow?: string }>()
</script>

<template>
  <header class="page-header">
    <div class="page-header__copy">
      <div v-if="eyebrow" class="page-header__eyebrow">{{ eyebrow }}</div>
      <h1>{{ title }}</h1>
      <p>{{ description }}</p>
    </div>
    <div v-if="$slots.actions" class="page-header__actions">
      <slot name="actions" />
    </div>
  </header>
</template>

<style scoped lang="scss">
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  min-width: 0;
  margin-bottom: 24px;
}

.page-header__copy {
  min-width: 0;
}
.page-header__eyebrow {
  color: var(--app-action-primary);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
h1 {
  margin: 2px 0 6px;
  font-size: clamp(24px, 3vw, 34px);
  line-height: 1.2;
}
p {
  max-width: 780px;
  margin: 0;
  color: var(--app-text-secondary);
  overflow-wrap: anywhere;
}
.page-header__actions {
  display: flex;
  flex: 0 1 auto;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
  min-width: 0;
}

@media (max-width: 599px) {
  .page-header {
    flex-direction: column;
  }
  .page-header__actions {
    width: 100%;
    justify-content: stretch;
  }
  .page-header__actions :deep(.el-button) {
    flex: 1 1 auto;
  }
}
</style>
