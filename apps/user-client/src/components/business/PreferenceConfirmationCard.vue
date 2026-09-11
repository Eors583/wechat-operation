<script setup lang="ts">
import type { Message } from '@/api/types'
import AppButton from '@/components/base/AppButton.vue'

defineProps<{
  proposal: NonNullable<Message['preferenceProposal']>
  disabled: boolean
}>()
defineEmits<{ decide: [decision: 'confirmed' | 'dismissed'] }>()
</script>

<template>
  <q-card flat bordered class="preference-confirmation q-mt-sm">
    <q-card-section>
      <strong>{{ proposal.previousValue ? '更新用户偏好？' : '保存为用户偏好？' }}</strong>
      <p v-if="proposal.previousValue" class="preference-confirmation__previous q-mt-sm q-mb-sm">
        原偏好：{{ proposal.previousValue }}
      </p>
      <p class="q-mt-sm q-mb-none">{{ proposal.value }}</p>
    </q-card-section>
    <q-card-actions class="preference-confirmation__actions">
      <AppButton label="保存" :disabled="disabled" @click="$emit('decide', 'confirmed')" />
      <AppButton
        label="仅本次"
        variant="outline"
        :disabled="disabled"
        @click="$emit('decide', 'dismissed')"
      />
    </q-card-actions>
  </q-card>
</template>

<style scoped lang="scss">
.preference-confirmation {
  min-width: 0;
  max-width: 100%;
  overflow-wrap: anywhere;

  &__previous {
    color: var(--app-text-secondary);
  }

  &__actions {
    flex-wrap: wrap;

    > * {
      min-width: 0;
      max-width: 100%;
    }
  }
}
</style>
