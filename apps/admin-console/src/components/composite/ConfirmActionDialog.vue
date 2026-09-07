<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import AppIcon from '@/components/base/AppIcon.vue'

const props = withDefaults(
  defineProps<{
    modelValue: boolean
    title: string
    description: string
    confirmLabel?: string
    tone?: 'primary' | 'negative' | 'warning'
    requireReason?: boolean
  }>(),
  { confirmLabel: '确认', tone: 'primary', requireReason: false },
)

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  confirm: [reason: string]
}>()

const reason = ref('')
const canConfirm = computed(() => !props.requireReason || reason.value.trim().length >= 4)
const confirmType = computed(() => (props.tone === 'negative' ? 'danger' : props.tone))

watch(
  () => props.modelValue,
  (open) => {
    if (!open) reason.value = ''
  },
)

function confirm(): void {
  if (!canConfirm.value) return
  emit('confirm', reason.value.trim())
  emit('update:modelValue', false)
}
</script>

<template>
  <el-dialog
    :close-on-click-modal="false"
    :model-value="modelValue"
    :title="title"
    width="min(520px, calc(100vw - 24px))"
    align-center
    class="confirm-dialog"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="confirm-dialog__message">
      <admin-avatar :class="`tone-${tone}`">
        <AppIcon :name="tone === 'negative' ? 'warning' : 'verified_user'" />
      </admin-avatar>
      <p class="long-text">{{ description }}</p>
    </div>
    <el-form v-if="requireReason" label-position="top" class="confirm-dialog__form">
      <el-form-item label="操作原因（至少 4 个字符）">
        <el-input
          v-model="reason"
          type="textarea"
          :autosize="{ minRows: 3, maxRows: 6 }"
          show-word-limit
          :maxlength="300"
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <div class="confirm-dialog__actions">
        <el-button @click="emit('update:modelValue', false)">取消</el-button>
        <el-button :type="confirmType" :disabled="!canConfirm" @click="confirm">{{
          confirmLabel
        }}</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped lang="scss">
.confirm-dialog__message {
  display: flex;
  align-items: flex-start;
  gap: var(--space-4);
  min-width: 0;
}
.confirm-dialog__message p {
  flex: 1 1 auto;
  margin: 0;
}
.tone-primary {
  background: var(--app-action-primary);
}
.tone-warning {
  background: var(--app-action-warning);
}
.tone-negative {
  background: var(--app-action-danger);
}
.confirm-dialog__form {
  margin-top: var(--space-5);
}
.confirm-dialog__form :deep(.el-form-item) {
  margin-bottom: 0;
}
.confirm-dialog__actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: var(--space-2);
}
@media (max-width: 599px) {
  :global(.confirm-dialog.el-dialog) {
    width: calc(100vw - 24px) !important;
    margin: 12px auto;
  }
}
</style>
