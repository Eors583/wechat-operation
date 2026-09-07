<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    label?: string
    icon?: string
    variant?: 'primary' | 'outline' | 'ghost' | 'danger'
    loading?: boolean
    disabled?: boolean
    fullWidth?: boolean
    type?: 'button' | 'submit' | 'reset'
  }>(),
  {
    variant: 'primary',
    loading: false,
    disabled: false,
    fullWidth: false,
    type: 'button',
  },
)

defineEmits<{ click: [event: Event] }>()

const buttonProps = computed(() => ({
  color: props.variant === 'danger' ? 'negative' : 'primary',
  unelevated: props.variant === 'primary' || props.variant === 'danger',
  outline: props.variant === 'outline',
  flat: props.variant === 'ghost',
}))
</script>

<template>
  <q-btn
    v-bind="buttonProps"
    :class="['app-button', { 'app-button--full': fullWidth }]"
    :label="label"
    :icon="icon"
    :loading="loading"
    :disable="disabled"
    :type="type"
    no-caps
    @click="$emit('click', $event)"
  >
    <slot />
  </q-btn>
</template>

<style scoped lang="scss">
.app-button {
  min-height: 44px;
  padding-inline: 16px;
  border-radius: 8px;
  font-weight: 600;
  letter-spacing: 0;

  &--full {
    width: 100%;
  }
}
</style>
