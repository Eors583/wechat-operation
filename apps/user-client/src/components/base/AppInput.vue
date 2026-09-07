<script setup lang="ts">
withDefaults(
  defineProps<{
    modelValue: string
    label?: string
    placeholder?: string
    type?: 'text' | 'password' | 'tel' | 'email' | 'textarea'
    icon?: string
    errorMessage?: string
    autocomplete?: string
    maxlength?: number
  }>(),
  { type: 'text' },
)

defineEmits<{ 'update:modelValue': [value: string] }>()
</script>

<template>
  <div class="app-input">
    <label v-if="label" class="app-input__label">{{ label }}</label>
    <q-input
      :model-value="modelValue"
      :aria-label="label"
      :placeholder="placeholder"
      :type="type"
      :error="Boolean(errorMessage)"
      :error-message="errorMessage"
      :autocomplete="autocomplete"
      :maxlength="maxlength"
      outlined
      hide-bottom-space
      @update:model-value="$emit('update:modelValue', String($event ?? ''))"
    >
      <template v-if="icon" #prepend><q-icon :name="icon" /></template>
      <template v-if="$slots.append" #append><slot name="append" /></template>
    </q-input>
  </div>
</template>

<style scoped lang="scss">
.app-input {
  display: grid;
  gap: 9px;
  width: 100%;
  min-width: 0;
  max-width: 100%;

  &__label {
    color: var(--app-text-primary);
    font-size: 15px;
    font-weight: 600;
  }

  :deep(.q-field__control) {
    min-height: 56px;
    color: var(--app-text-primary);
    background: var(--app-bg-surface);
    border-radius: 8px;
  }

  :deep(.q-field__native) {
    padding-block: 15px;
  }
}
</style>
