<script setup lang="ts">
import { computed } from 'vue'
import type { OfficialAccount } from '@/api/types'
import AppButton from '@/components/base/AppButton.vue'

const props = defineProps<{ account: OfficialAccount }>()
defineEmits<{ detail: []; templates: []; reconnect: [] }>()

const status = computed(
  () =>
    ({
      connected: { label: '连接正常', color: 'positive' },
      reconnect: { label: '需要重新连接', color: 'warning' },
      unsupported: { label: '当前公众号不支持该功能', color: 'negative' },
    })[props.account.status],
)
</script>

<template>
  <q-card class="account-card surface-card" flat>
    <q-card-section class="account-card__identity">
      <q-avatar :style="{ background: account.avatarColor, color: '#fff' }">{{
        account.avatarText
      }}</q-avatar>
      <div>
        <h2>{{ account.name }}</h2>
        <q-badge :color="status.color" outline>{{ status.label }}</q-badge>
      </div>
    </q-card-section>
    <q-card-section class="account-card__sync">
      <span>最近同步</span
      ><strong>{{
        new Date(account.lastSyncedAt).toLocaleString('zh-CN', {
          month: '2-digit',
          day: '2-digit',
          hour: '2-digit',
          minute: '2-digit',
        })
      }}</strong>
    </q-card-section>
    <q-card-actions class="account-card__actions">
      <AppButton
        v-if="account.status === 'reconnect'"
        variant="outline"
        label="重新连接"
        @click="$emit('reconnect')"
      />
      <AppButton variant="ghost" label="查看详情" @click="$emit('detail')" />
      <AppButton variant="outline" label="模板管理" @click="$emit('templates')" />
    </q-card-actions>
  </q-card>
</template>

<style scoped lang="scss">
.account-card {
  min-width: 0;

  &__identity {
    display: flex;
    align-items: center;
    gap: 12px;
    min-width: 0;

    > div {
      min-width: 0;
    }
    h2 {
      margin: 0 0 6px;
      font-size: 18px;
      overflow-wrap: anywhere;
    }
  }

  &__sync {
    display: flex;
    justify-content: space-between;
    gap: 12px;
    color: var(--app-text-secondary);
    border-block: 1px solid var(--app-border-default);

    strong {
      color: var(--app-text-primary);
      overflow-wrap: anywhere;
    }
  }

  &__actions {
    flex-wrap: wrap;
    justify-content: flex-end;
  }
}
</style>
