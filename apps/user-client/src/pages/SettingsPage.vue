<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useInfiniteQuery } from '@tanstack/vue-query'
import { useQuasar } from 'quasar'
import { api } from '@/api/client'
import type { Preference, ThemePreference } from '@/api/types'
import { queryClient } from '@/boot/query'
import AppButton from '@/components/base/AppButton.vue'
import AppDialog from '@/components/base/AppDialog.vue'
import AsyncStatePanel from '@/components/composite/AsyncStatePanel.vue'
import PageHeader from '@/components/composite/PageHeader.vue'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'

const auth = useAuthStore()
const theme = useThemeStore()
const router = useRouter()
const $q = useQuasar()
const preferencesQuery = useInfiniteQuery({
  queryKey: ['preferences'],
  queryFn: ({ pageParam }) => api.listPreferencesPage(pageParam),
  initialPageParam: undefined as string | undefined,
  getNextPageParam: (lastPage) => lastPage.nextCursor,
})
const preferences = computed(() => [
  ...new Map(
    (preferencesQuery.data.value?.pages.flatMap((page) => page.items) ?? []).map((preference) => [
      preference.id,
      preference,
    ]),
  ).values(),
])
const preferenceDialog = ref(false)
const editing = ref<Preference | null>(null)
const preferenceText = ref('')
const preferenceTitle = ref('')
const preferenceValue = computed(
  () => `# ${preferenceTitle.value.trim()}\n\n${preferenceText.value.trim()}`,
)
const preferenceValid = computed(
  () =>
    Boolean(preferenceTitle.value.trim() && preferenceText.value.trim()) &&
    [...preferenceTitle.value.trim()].length <= 80 &&
    [...preferenceValue.value].length <= 2000,
)
const saving = ref(false)
const confirmingId = ref('')
const themeSaving = ref(false)
const deletionDialog = ref(false)
const deletionPassword = ref('')
const deletionConfirmation = ref('')
const deletingAccount = ref(false)

const themes: { value: ThemePreference; label: string; icon: string; description: string }[] = [
  { value: 'light', label: '浅色', icon: 'light_mode', description: '始终使用明亮界面' },
  { value: 'dark', label: '深色', icon: 'dark_mode', description: '始终使用深色界面' },
  { value: 'system', label: '跟随系统', icon: 'contrast', description: '随设备外观自动切换' },
]

const openPreference = (preference?: Preference) => {
  editing.value = preference ?? null
  preferenceTitle.value = preference?.title ?? ''
  preferenceText.value = preference?.text ?? ''
  preferenceDialog.value = true
}

const savePreference = async () => {
  if (!preferenceValid.value || saving.value) return
  saving.value = true
  try {
    await api.savePreference(preferenceValue.value, editing.value?.id, 'confirmed')
    await queryClient.invalidateQueries({ queryKey: ['preferences'] })
    preferenceDialog.value = false
    $q.notify({
      type: 'positive',
      message:
        editing.value?.status === 'candidate'
          ? '候选偏好已确认，之后的新创作会使用它。'
          : '写作偏好已保存，之后的新创作会使用它。',
    })
  } finally {
    saving.value = false
  }
}

const confirmPreference = async (preference: Preference) => {
  confirmingId.value = preference.id
  try {
    await api.confirmPreference(preference.id)
    await queryClient.invalidateQueries({ queryKey: ['preferences'] })
    $q.notify({ type: 'positive', message: '候选偏好已确认，之后的新创作会使用它。' })
  } finally {
    confirmingId.value = ''
  }
}

const setTheme = async (preference: ThemePreference) => {
  if (preference === theme.preference || themeSaving.value) return
  themeSaving.value = true
  try {
    await theme.setPreference(preference)
  } catch (error) {
    $q.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '主题偏好没有保存，请重试。',
    })
  } finally {
    themeSaving.value = false
  }
}

const removePreference = (preference: Preference) => {
  $q.dialog({
    title: '删除写作偏好',
    message: '删除后，之后的新创作不再使用这条偏好。',
    cancel: true,
    persistent: true,
  }).onOk(async () => {
    await api.deletePreference(preference.id)
    await queryClient.invalidateQueries({ queryKey: ['preferences'] })
  })
}

const logout = async () => {
  try {
    await auth.logout()
  } catch {
    $q.notify({ type: 'warning', message: '本机账号数据已清除，但服务端撤销状态尚未确认。' })
  } finally {
    queryClient.clear()
    await router.replace('/login')
  }
}

const openDeletionDialog = () => {
  deletionPassword.value = ''
  deletionConfirmation.value = ''
  deletionDialog.value = true
}

const deleteAccount = async () => {
  if (!deletionPassword.value || deletionConfirmation.value !== '注销账号') return
  deletingAccount.value = true
  try {
    const receipt = await auth.deleteAccount(deletionPassword.value)
    $q.notify({
      type: 'positive',
      timeout: 7000,
      message: `账号已冻结并撤销全部会话；个人业务数据最迟于 ${new Date(receipt.purgeAfter).toLocaleDateString('zh-CN')} 完成删除或匿名化。`,
    })
    queryClient.clear()
    await router.replace('/login')
  } catch (error) {
    $q.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '账号注销请求失败，请重试。',
    })
  } finally {
    deletingAccount.value = false
  }
}
</script>

<template>
  <q-page class="app-page settings-page">
    <PageHeader
      title="个人设置"
      subtitle="管理账号外观与写作偏好。明确偏好会用于新创作，随时可以修改或删除。"
    />

    <div class="settings-grid">
      <section class="settings-section surface-card">
        <header>
          <div>
            <h2>账号信息</h2>
            <p>当前登录账号与可用积分</p>
          </div>
        </header>
        <div class="profile-card">
          <q-avatar size="64px" color="primary" text-color="white">{{
            auth.user?.name.slice(0, 1)
          }}</q-avatar>
          <div>
            <strong>{{ auth.user?.name }}</strong
            ><span>{{ auth.user?.role }}</span
            ><small>{{ auth.user?.phone }} · {{ auth.user?.email }}</small>
          </div>
          <q-chip color="positive" text-color="white">{{ auth.user?.points }} 积分</q-chip>
        </div>
        <q-separator />
        <div class="settings-section__actions">
          <AppButton variant="outline" label="退出登录" @click="logout" />
        </div>
      </section>

      <section class="settings-section settings-section--danger surface-card">
        <header>
          <div>
            <h2>账号注销</h2>
            <p>立即撤销全部设备会话与公众号凭据，随后进入不可恢复的数据清理流程。</p>
          </div>
        </header>
        <q-banner rounded class="bg-negative text-white"
          >请先导出需要保留的内容。提交后无法再次登录；除依法留存的审计和账务记录外，个人业务数据将在
          30 日内删除或匿名化。</q-banner
        >
        <div class="settings-section__actions">
          <AppButton variant="danger" label="注销账号" @click="openDeletionDialog" />
        </div>
      </section>

      <section class="settings-section surface-card">
        <header>
          <div>
            <h2>界面主题</h2>
          </div>
        </header>
        <div class="theme-options">
          <button
            v-for="item in themes"
            :key="item.value"
            :class="{ active: theme.preference === item.value }"
            :disabled="themeSaving"
            @click="setTheme(item.value)"
          >
            <q-icon :name="item.icon" size="28px" /><span
              ><strong>{{ item.label }}</strong
              ><small>{{ item.description }}</small></span
            ><q-icon v-if="theme.preference === item.value" name="check_circle" color="primary" />
          </button>
        </div>
      </section>

      <section class="settings-section settings-section--wide surface-card">
        <header>
          <div>
            <h2>我的写作风格</h2>
          </div>
          <AppButton
            variant="outline"
            icon="add"
            label="添加写作风格"
            :disabled="preferences.length >= 20"
            @click="openPreference()"
          />
        </header>
        <AsyncStatePanel
          :loading="preferencesQuery.isPending.value"
          :error="
            preferencesQuery.error.value instanceof Error
              ? preferencesQuery.error.value.message
              : null
          "
          :empty="!preferences.length"
          empty-title="还没有写作偏好"
          empty-description="你可以明确添加，也可以在确认文章后让系统总结候选。"
          @retry="preferencesQuery.refetch()"
        >
          <q-list separator class="preferences-list">
            <q-item v-for="preference in preferences" :key="preference.id">
              <q-item-section avatar
                ><q-icon
                  name="auto_awesome"
                  :color="preference.status === 'candidate' ? 'warning' : 'primary'"
              /></q-item-section>
              <q-item-section
                ><button
                  class="preference-preview"
                  type="button"
                  @click="openPreference(preference)"
                >
                  <strong class="wrap-anywhere">{{ preference.title }}</strong>
                  <span class="preference-preview__excerpt">{{ preference.text }}</span></button
                ><q-item-label caption class="wrap-anywhere"
                  ><q-badge
                    :color="preference.status === 'candidate' ? 'warning' : 'positive'"
                    :label="preference.status === 'candidate' ? '候选，未生效' : '已生效'"
                  />
                  {{ preference.source }} ·
                  {{ new Date(preference.updatedAt).toLocaleDateString('zh-CN') }}</q-item-label
                ></q-item-section
              >
              <q-item-section side
                ><div class="preferences-list__actions">
                  <q-btn
                    v-if="preference.status === 'candidate'"
                    flat
                    round
                    dense
                    icon="check_circle_outline"
                    color="positive"
                    :loading="confirmingId === preference.id"
                    aria-label="确认使用候选偏好"
                    @click="confirmPreference(preference)"
                  /><q-btn
                    flat
                    round
                    dense
                    icon="edit"
                    aria-label="编辑偏好"
                    @click="openPreference(preference)"
                  /><q-btn
                    flat
                    round
                    dense
                    icon="delete_outline"
                    color="negative"
                    aria-label="删除偏好"
                    @click="removePreference(preference)"
                  /></div
              ></q-item-section>
            </q-item>
          </q-list>
        </AsyncStatePanel>
        <div v-if="preferencesQuery.hasNextPage.value" class="preferences-load-more">
          <AppButton
            variant="outline"
            label="加载更多偏好"
            :loading="preferencesQuery.isFetchingNextPage.value"
            @click="preferencesQuery.fetchNextPage()"
          />
        </div>
      </section>
    </div>

    <AppDialog
      v-model="preferenceDialog"
      :title="
        editing?.status === 'candidate'
          ? '确认候选写作风格'
          : editing
            ? '查看 / 编辑写作风格'
            : '添加写作风格'
      "
      width="620px"
    >
      <div class="preference-form">
        <q-input
          v-model="preferenceTitle"
          outlined
          label="写作风格标题"
          placeholder="例如：专业分析型、简洁叙事型"
          maxlength="80"
          counter
          autofocus
          :disable="saving"
        />
        <q-input
          v-model="preferenceText"
          outlined
          type="textarea"
          label="具体写作风格"
          placeholder="描述语气、文章结构、开头方式、案例运用、用词习惯等具体要求。"
          rows="9"
          :disable="saving"
          :error="[...preferenceValue].length > 2000"
          error-message="标题与内容合计不能超过 2000 字符（含格式分隔符）。"
          :hint="`已使用 ${[...preferenceValue].length} / 2000 字符`"
        />
      </div>
      <template #actions
        ><AppButton variant="ghost" label="取消" @click="preferenceDialog = false" /><AppButton
          :label="editing?.status === 'candidate' ? '确认并保存' : '保存偏好'"
          :loading="saving"
          :disabled="!preferenceValid"
          @click="savePreference"
      /></template>
    </AppDialog>

    <AppDialog v-model="deletionDialog" title="确认注销账号" width="560px" persistent>
      <div class="deletion-form">
        <q-banner rounded class="bg-negative text-white"
          >此操作不可撤销。提交后将立即退出所有设备并断开公众号。</q-banner
        >
        <q-input
          v-model="deletionPassword"
          outlined
          type="password"
          label="当前密码"
          autocomplete="current-password"
          autofocus
        />
        <q-input
          v-model="deletionConfirmation"
          outlined
          label="输入“注销账号”以确认"
          autocomplete="off"
        />
        <small>系统不会记录你在此处输入的密码或确认文本。</small>
      </div>
      <template #actions
        ><AppButton
          variant="ghost"
          label="取消"
          :disabled="deletingAccount"
          @click="deletionDialog = false" /><AppButton
          variant="danger"
          label="永久注销账号"
          :loading="deletingAccount"
          :disabled="!deletionPassword || deletionConfirmation !== '注销账号'"
          @click="deleteAccount"
      /></template>
    </AppDialog>
  </q-page>
</template>

<style scoped lang="scss">
.settings-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
  min-width: 0;
}
.settings-section {
  min-width: 0;
  padding: 22px;
}
.settings-section--wide {
  grid-column: 1 / -1;
}
.settings-section--danger {
  grid-column: 1 / -1;
  border-color: color-mix(in srgb, var(--q-negative) 45%, var(--app-border-default));
}
.settings-section > header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  min-width: 0;
  margin-bottom: 20px;
}
.settings-section > header > div {
  min-width: 0;
}
.settings-section h2 {
  margin: 0;
  font-size: 20px;
  overflow-wrap: anywhere;
}
.settings-section header p {
  margin: 5px 0 0;
  color: var(--app-text-secondary);
  overflow-wrap: anywhere;
}
.settings-section__actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 18px;
}

.profile-card {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 14px;
  min-width: 0;
  padding-bottom: 20px;
}
.profile-card > div {
  display: grid;
  min-width: 0;
}
.profile-card strong {
  font-size: 18px;
}
.profile-card span,
.profile-card small {
  color: var(--app-text-secondary);
  overflow-wrap: anywhere;
}

.theme-options {
  display: grid;
  gap: 10px;
}
.theme-options button {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  min-width: 0;
  padding: 14px;
  color: var(--app-text-primary);
  text-align: left;
  background: var(--app-bg-subtle);
  border: 1px solid var(--app-border-default);
  border-radius: 10px;
  cursor: pointer;
}
.theme-options button.active {
  background: var(--app-action-soft);
  border-color: var(--app-action-primary);
}
.theme-options span {
  display: grid;
  min-width: 0;
}
.theme-options small {
  color: var(--app-text-secondary);
  overflow-wrap: anywhere;
}

.preferences-list {
  min-width: 0;
  border: 1px solid var(--app-border-default);
  border-radius: 10px;
}
.preferences-list .q-item {
  min-width: 0;
  padding-block: 14px;
}
.preferences-list__actions {
  display: flex;
}
.preference-preview {
  display: grid;
  gap: 6px;
  width: 100%;
  min-width: 0;
  padding: 0;
  color: var(--app-text-primary);
  font: inherit;
  text-align: left;
  background: none;
  border: 0;
  cursor: pointer;
}
.preference-preview:focus-visible {
  outline: 2px solid var(--app-action-primary);
  outline-offset: 3px;
}
.preference-preview__excerpt {
  display: -webkit-box;
  overflow: hidden;
  color: var(--app-text-secondary);
  white-space: pre-line;
  overflow-wrap: anywhere;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}
.preferences-load-more {
  display: flex;
  justify-content: center;
  min-width: 0;
  padding-top: 16px;
}
.preference-form {
  display: grid;
  gap: 10px;
  min-width: 0;
  padding: 22px;
}
.preference-form small {
  color: var(--app-text-secondary);
  overflow-wrap: anywhere;
}
.preference-form :deep(textarea.q-field__native) {
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
  max-width: 100%;
  max-height: 300px;
  overflow-y: auto !important;
  overflow-wrap: anywhere;
}
.deletion-form {
  display: grid;
  gap: 16px;
  min-width: 0;
  padding: 22px;
}
.deletion-form small {
  color: var(--app-text-secondary);
  overflow-wrap: anywhere;
}

@media (max-width: 767px) {
  .settings-grid {
    grid-template-columns: 1fr;
  }
  .settings-section--wide {
    grid-column: auto;
  }
  .settings-section--danger {
    grid-column: auto;
  }
  .settings-section > header {
    align-items: stretch;
    flex-direction: column;
  }
  .profile-card {
    grid-template-columns: auto minmax(0, 1fr);
  }
  .profile-card > .q-chip {
    grid-column: 1 / -1;
    justify-self: start;
  }
  .preferences-list .q-item {
    align-items: flex-start;
  }
  .preferences-list .q-item__section--avatar {
    min-width: 34px;
  }
  .preferences-list__actions {
    flex-direction: column;
  }
}
</style>
