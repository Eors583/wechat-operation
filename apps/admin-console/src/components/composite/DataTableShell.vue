<script setup lang="ts">
defineProps<{ title?: string; description?: string }>()
</script>

<template>
  <el-card shadow="never" class="surface-card table-shell" :body-style="{ padding: '0' }">
    <template v-if="title || description || $slots.actions" #header>
      <div class="table-shell__head">
        <div class="table-shell__copy">
          <h2 v-if="title">{{ title }}</h2>
          <p v-if="description">{{ description }}</p>
        </div>
        <div v-if="$slots.actions" class="table-shell__actions"><slot name="actions" /></div>
      </div>
    </template>
    <div class="table-shell__scroll" data-testid="table-scroll-region">
      <slot />
    </div>
  </el-card>
</template>

<style scoped lang="scss">
.table-shell {
  min-width: 0;
  max-width: 100%;
  overflow: clip;
}
.table-shell__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  min-width: 0;
}
.table-shell__copy {
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
.table-shell__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  min-width: 0;
}
.table-shell__scroll {
  width: 100%;
  max-width: 100%;
  overflow-x: auto;
  overscroll-behavior-inline: contain;
}
.table-shell__scroll :deep(.el-table) {
  min-width: 720px;
  box-shadow: none;
  background: transparent;
}
.table-shell__scroll :deep(.el-table td),
.table-shell__scroll :deep(.el-table th) {
  max-width: 320px;
  white-space: normal;
  overflow-wrap: anywhere;
}

@media (max-width: 599px) {
  .table-shell__head {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
