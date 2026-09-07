<script setup lang="ts">
defineProps<{ title: string; subtitle?: string }>()
</script>

<template>
  <header class="page-header">
    <div class="page-header__copy">
      <h1>{{ title }}</h1>
      <p v-if="subtitle">{{ subtitle }}</p>
    </div>
    <div v-if="$slots.actions" class="page-header__actions"><slot name="actions" /></div>
  </header>
</template>

<style scoped lang="scss">
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  min-width: 0;
  margin-bottom: clamp(24px, 3vw, 34px);

  &__copy {
    min-width: 0;
  }

  h1 {
    margin: 0;
    overflow-wrap: anywhere;
    font-size: clamp(28px, 2.5vw, 38px);
    font-weight: 650;
    letter-spacing: -0.025em;
    line-height: 1.2;
  }

  p {
    max-width: 720px;
    margin: 10px 0 0;
    color: var(--app-text-secondary);
    overflow-wrap: anywhere;
  }

  &__actions {
    display: flex;
    flex: 0 1 auto;
    flex-wrap: wrap;
    justify-content: flex-end;
    gap: 10px;
    min-width: 0;
  }
}

@media (max-width: 599px) {
  .page-header {
    align-items: stretch;
    flex-direction: column;

    &__actions > :deep(*) {
      flex: 1 1 auto;
    }
  }
}
</style>
