<script setup lang="ts">
withDefaults(defineProps<{ icon?: string; title: string; description?: string }>(), {
  icon: 'inbox',
})
</script>

<template>
  <div class="empty-state" role="status">
    <q-icon :name="icon" size="42px" />
    <strong>{{ title }}</strong>
    <p v-if="description">{{ description }}</p>
    <slot />
  </div>
</template>

<style scoped lang="scss">
.empty-state {
  display: grid;
  place-items: center;
  min-width: 0;
  padding: clamp(32px, 7vw, 72px) 20px;
  color: var(--app-text-secondary);
  text-align: center;

  strong {
    margin-top: 12px;
    color: var(--app-text-primary);
    font-size: 18px;
  }

  p {
    max-width: 520px;
    margin: 8px 0 18px;
    overflow-wrap: anywhere;
  }
}
</style>
