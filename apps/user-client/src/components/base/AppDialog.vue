<script setup lang="ts">
import { useQuasar } from 'quasar'

withDefaults(
  defineProps<{
    modelValue: boolean
    title: string
    width?: string
    persistent?: boolean
    fullScreenMobile?: boolean
    compact?: boolean
  }>(),
  { width: '720px', persistent: false, fullScreenMobile: true, compact: false },
)

defineEmits<{ 'update:modelValue': [value: boolean] }>()
const $q = useQuasar()
</script>

<template>
  <q-dialog
    :model-value="modelValue"
    :persistent="persistent"
    :maximized="fullScreenMobile && $q.screen.lt.sm"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <q-card
      :class="['app-dialog', { 'app-dialog--compact': compact }]"
      :style="{ '--dialog-width': width }"
    >
      <q-card-section class="app-dialog__header">
        <h2>{{ title }}</h2>
        <q-btn
          flat
          round
          dense
          icon="close"
          aria-label="关闭"
          @click="$emit('update:modelValue', false)"
        />
      </q-card-section>
      <q-separator />
      <div class="app-dialog__body"><slot /></div>
      <q-separator v-if="$slots.actions" />
      <q-card-actions v-if="$slots.actions" class="app-dialog__actions"
        ><slot name="actions"
      /></q-card-actions>
    </q-card>
  </q-dialog>
</template>

<style scoped lang="scss">
.app-dialog {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  width: min(var(--dialog-width), calc(100vw - 32px));
  max-width: 100%;
  max-height: min(92vh, 1040px);
  color: var(--app-text-primary);
  background: var(--app-bg-elevated);
  border-radius: 10px;
  box-shadow: var(--app-shadow-md);

  &__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    padding: 20px 24px;

    h2 {
      min-width: 0;
      margin: 0;
      overflow-wrap: anywhere;
      font-size: 22px;
    }
  }

  &__body {
    min-width: 0;
    min-height: 0;
    overflow: auto;
  }

  &__actions {
    justify-content: flex-end;
    gap: 10px;
    padding: 16px 24px max(16px, env(safe-area-inset-bottom));
  }

  &--compact &__header {
    padding: 14px 20px;

    h2 {
      font-size: 17px;
    }
  }

  &--compact &__actions {
    padding: 12px 20px max(12px, env(safe-area-inset-bottom));
  }
}

@media (max-width: 599px) {
  .app-dialog {
    width: 100%;
    height: 100%;
    max-height: none;
    border-radius: 0;
  }
}
</style>
