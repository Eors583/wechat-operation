<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useInfiniteQuery } from '@tanstack/vue-query'
import type { QTableColumn } from 'quasar'
import { useQuasar } from 'quasar'
import { toDataURL } from 'qrcode'
import { api } from '@/api/client'
import type { OfficialAccount, OfficialAccountAuthorization } from '@/api/types'
import { queryClient } from '@/boot/query'
import { platform } from '@/platform'
import AppButton from '@/components/base/AppButton.vue'
import AppDialog from '@/components/base/AppDialog.vue'
import AsyncStatePanel from '@/components/composite/AsyncStatePanel.vue'
import PageHeader from '@/components/composite/PageHeader.vue'
import ResponsiveTable from '@/components/composite/ResponsiveTable.vue'
import OfficialAccountCard from '@/components/business/OfficialAccountCard.vue'
import LayoutTemplateEditor from '@/components/business/LayoutTemplateEditor.vue'
import { usePublicSettings } from '@/composables/usePublicSettings'

const $q = useQuasar()
const { settings: publicSettings } = usePublicSettings()
const accountsQuery = useInfiniteQuery({
  queryKey: ['accounts'],
  queryFn: ({ pageParam }) => api.listOfficialAccountsPage(pageParam),
  initialPageParam: undefined as string | undefined,
  getNextPageParam: (lastPage) => lastPage.nextCursor,
})
const accounts = computed(() => [
  ...new Map(
    (accountsQuery.data.value?.pages.flatMap((page) => page.items) ?? []).map((account) => [
      account.id,
      account,
    ]),
  ).values(),
])
const selected = ref<OfficialAccount | null>(null)
const detailDialog = ref(false)
const authDialog = ref(false)
const templateDialog = ref(false)
const authorizing = ref(false)
const authorization = ref<OfficialAccountAuthorization | null>(null)
const authorizationQr = ref('')
const authorizationError = ref('')
const previousAccountIds = ref<string[]>([])
let authorizationPoll: ReturnType<typeof setInterval> | null = null
let authorizationDeadline = 0

const stopAuthorizationPolling = () => {
  if (authorizationPoll) clearInterval(authorizationPoll)
  authorizationPoll = null
}
const templatesQuery = useInfiniteQuery({
  queryKey: computed(() => ['templates', selected.value?.id ?? 'global']),
  queryFn: ({ pageParam }) => api.listTemplatesPage(selected.value?.id ?? null, pageParam),
  initialPageParam: undefined as string | undefined,
  getNextPageParam: (lastPage) => lastPage.nextCursor,
  enabled: computed(() => templateDialog.value),
  refetchInterval: (query) =>
    templateDialog.value &&
    query.state.data?.pages.some((page) =>
      page.items.some((template) => template.status === 'extracting'),
    )
      ? 5000
      : false,
})
const templates = computed(() => [
  ...new Map(
    (templatesQuery.data.value?.pages.flatMap((page) => page.items) ?? []).map((template) => [
      template.id,
      template,
    ]),
  ).values(),
])

const columns: QTableColumn<OfficialAccount>[] = [
  { name: 'account', label: '公众号', field: 'name', align: 'left', style: 'width: 27%' },
  { name: 'status', label: '授权状态', field: 'status', align: 'left', style: 'width: 16%' },
  {
    name: 'capabilities',
    label: '已授权能力',
    field: 'capabilities',
    align: 'left',
    style: 'width: 25%',
  },
  {
    name: 'lastSync',
    label: '最近同步',
    field: 'lastSyncedAt',
    align: 'left',
    style: 'width: 14%',
  },
  { name: 'actions', label: '操作', field: 'id', align: 'right', style: 'width: 18%' },
]

const statusInfo = (status: OfficialAccount['status']) =>
  ({
    connected: { label: '已绑定 · 长期有效', color: 'positive' },
    reconnect: { label: '授权已解除', color: 'warning' },
    unsupported: { label: '当前公众号不支持该功能', color: 'negative' },
  })[status]
const capabilityLabel = (capability: string) =>
  ({ draft: '写入草稿箱', publish: '发布文章', assets: '管理素材' })[capability] ?? capability
const capabilityDetail = (capability: string) =>
  ({
    draft: { label: '草稿箱', description: '可将文章写入公众号草稿箱' },
    publish: { label: '文章发布', description: '可发布已确认的公众号文章' },
    assets: { label: '素材管理', description: '可读取并管理公众号素材' },
  })[capability] ?? { label: capability, description: '已获得公众号授权' }
const detailStatusLabel = (status: OfficialAccount['status']) =>
  ({ connected: '授权正常', reconnect: '需要重新授权', unsupported: '能力受限' })[status]
const formatDetailTime = (value: string) =>
  new Date(value).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })

const showDetail = (account: OfficialAccount) => {
  selected.value = account
  detailDialog.value = true
}
const showTemplates = (account: OfficialAccount) => {
  selected.value = account
  templateDialog.value = true
}
const showTemplatesFromHeader = () => {
  selected.value = null
  templateDialog.value = true
}
const showSelectedTemplates = () => {
  if (!selected.value) return
  detailDialog.value = false
  showTemplates(selected.value)
}
const requestAuthorization = async () => {
  authorizing.value = true
  authorization.value = null
  authorizationQr.value = ''
  authorizationError.value = ''
  try {
    const result = await api.createOfficialAccountAuthorization(
      platform.oauthRedirectUri('/official-accounts'),
    )
    authorization.value = result
    authorizationDeadline = Date.now() + result.expiresIn * 1000
    authorizationQr.value = await toDataURL(result.authorizationUrl, {
      width: 220,
      margin: 1,
      errorCorrectionLevel: 'M',
    })
    stopAuthorizationPolling()
    authorizationPoll = setInterval(() => {
      if (Date.now() >= authorizationDeadline) {
        stopAuthorizationPolling()
        authorizationError.value = '本次授权二维码已过期，请重新生成。'
        return
      }
      void finishAuthorize(true)
    }, 2000)
  } catch (error) {
    authorizationError.value =
      error instanceof Error ? error.message : '暂时无法生成公众号授权入口。'
  } finally {
    authorizing.value = false
  }
}
const openAuthorize = async (account?: OfficialAccount) => {
  selected.value = account ?? null
  authDialog.value = true
  authorizing.value = true
  if (!account && !accountsQuery.data.value) await accountsQuery.refetch()
  previousAccountIds.value = accounts.value.map((item) => item.id)
  await requestAuthorization()
}
const reconnectSelected = () => {
  if (!selected.value) return
  const account = selected.value
  detailDialog.value = false
  void openAuthorize(account)
}

const finishAuthorize = async (silent = false) => {
  if (authorizing.value) return
  authorizing.value = true
  try {
    const account = await api.completeOfficialAccountAuthorization(
      selected.value?.id,
      previousAccountIds.value,
    )
    await queryClient.invalidateQueries({ queryKey: ['accounts'] })
    if (!account) {
      if (!silent)
        $q.notify({
          type: 'warning',
          message: '尚未检测到授权结果。请在微信公众平台完成确认后再刷新。',
        })
      return
    }
    stopAuthorizationPolling()
    authDialog.value = false
    $q.notify({ type: 'positive', message: `${account.name}已完成授权。` })
  } catch (reason) {
    if (!silent)
      $q.notify({
        type: 'negative',
        message: reason instanceof Error ? reason.message : '授权状态查询失败，请稍后重试。',
      })
  } finally {
    authorizing.value = false
  }
}

let removeOAuthListener: (() => void) | null = null
onMounted(async () => {
  removeOAuthListener = await platform.onOAuthCallback((url) => {
    try {
      const callback = new URL(url)
      if (!callback.pathname.includes('official-accounts')) return
      authDialog.value = true
      void finishAuthorize()
    } catch {
      // Ignore unrelated or malformed app links.
    }
  })
})
watch(authDialog, (open) => {
  if (!open) stopAuthorizationPolling()
})
onBeforeUnmount(() => {
  stopAuthorizationPolling()
  removeOAuthListener?.()
})

const disconnect = () => {
  if (!selected.value) return
  $q.dialog({
    title: '解除公众号连接',
    message: `解除“${selected.value.name}”后不能再写入草稿或发布，已有文章和模板仍保留。`,
    cancel: true,
    persistent: true,
  }).onOk(async () => {
    await api.disconnectOfficialAccount(selected.value!.id)
    detailDialog.value = false
    await queryClient.invalidateQueries({ queryKey: ['accounts'] })
  })
}
</script>

<template>
  <q-page class="app-page accounts-page">
    <PageHeader title="公众号管理">
      <template #actions>
        <AppButton
          variant="outline"
          icon="auto_fix_high"
          label="排版模板"
          @click="showTemplatesFromHeader"
        />
        <AppButton icon="add" label="授权新公众号" @click="openAuthorize()" />
      </template>
    </PageHeader>

    <section class="accounts-table surface-card">
      <AsyncStatePanel
        :loading="accountsQuery.isPending.value"
        :error="
          accountsQuery.error.value instanceof Error ? accountsQuery.error.value.message : null
        "
        :empty="!accounts.length"
        empty-title="还没有连接公众号"
        empty-description="连接后可将已确认排版的文章写入草稿箱或发布。"
        @retry="accountsQuery.refetch()"
      >
        <ResponsiveTable :rows="accounts" :columns="columns">
          <template #row="{ row, props }">
            <q-tr :props="props">
              <q-td key="account" :props="props"
                ><div class="account-identity">
                  <q-avatar :style="{ background: row.avatarColor, color: '#fff' }">{{
                    row.avatarText
                  }}</q-avatar
                  ><span
                    ><strong>{{ row.name }}</strong
                    ><small>ID · {{ row.id.slice(0, 12) }}</small></span
                  >
                </div></q-td
              >
              <q-td key="status" :props="props"
                ><q-badge :color="statusInfo(row.status).color" outline>{{
                  statusInfo(row.status).label
                }}</q-badge></q-td
              >
              <q-td key="capabilities" :props="props"
                ><div class="account-capabilities">
                  <q-chip v-for="capability in row.capabilities" :key="capability" dense>{{
                    capabilityLabel(capability)
                  }}</q-chip
                  ><span v-if="!row.capabilities.length" class="text-muted">暂不可用</span>
                </div></q-td
              >
              <q-td key="lastSync" :props="props">{{
                new Date(row.lastSyncedAt).toLocaleString('zh-CN', {
                  month: '2-digit',
                  day: '2-digit',
                  hour: '2-digit',
                  minute: '2-digit',
                })
              }}</q-td>
              <q-td key="actions" :props="props" class="text-right"
                ><q-btn
                  v-if="row.status === 'reconnect'"
                  outline
                  dense
                  no-caps
                  color="warning"
                  label="重新扫码绑定"
                  @click="openAuthorize(row)" /><q-btn
                  flat
                  dense
                  no-caps
                  color="primary"
                  label="查看详情"
                  @click="showDetail(row)" /><q-btn
                  flat
                  dense
                  no-caps
                  color="primary"
                  label="排版管理"
                  @click="showTemplates(row)"
              /></q-td>
            </q-tr>
          </template>
          <template #card="{ row }"
            ><OfficialAccountCard
              :account="row"
              role="listitem"
              @detail="showDetail(row)"
              @templates="showTemplates(row)"
              @reconnect="openAuthorize(row)"
          /></template>
        </ResponsiveTable>
      </AsyncStatePanel>
      <div v-if="accountsQuery.hasNextPage.value" class="accounts-load-more">
        <AppButton
          variant="outline"
          label="加载更多公众号"
          :loading="accountsQuery.isFetchingNextPage.value"
          @click="accountsQuery.fetchNextPage()"
        />
      </div>
    </section>

    <AppDialog
      v-if="selected"
      v-model="detailDialog"
      title="公众号详情"
      width="600px"
      compact
    >
      <div class="account-detail">
        <div class="account-detail__hero">
          <q-avatar size="46px" :style="{ background: selected.avatarColor, color: '#fff' }">{{
            selected.avatarText
          }}</q-avatar>
          <div class="account-detail__identity">
            <div class="account-detail__name">
              <h2>{{ selected.name }}</h2>
              <q-badge :color="statusInfo(selected.status).color">{{
                detailStatusLabel(selected.status)
              }}</q-badge>
            </div>
            <small>ID：{{ selected.id }}</small>
          </div>
        </div>
        <q-separator />
        <section class="account-detail__section">
          <h3>基本信息</h3>
          <dl class="account-detail__facts">
            <div><dt>公众号名称</dt><dd>{{ selected.name }}</dd></div>
            <div>
              <dt>授权状态</dt>
              <dd :class="`text-${statusInfo(selected.status).color}`">
                {{ detailStatusLabel(selected.status) }}
              </dd>
            </div>
            <div><dt>账号 ID</dt><dd>{{ selected.id }}</dd></div>
            <div><dt>授权时间</dt><dd>{{ formatDetailTime(selected.authorizedAt) }}</dd></div>
            <div><dt>最近同步</dt><dd>{{ formatDetailTime(selected.lastSyncedAt) }}</dd></div>
          </dl>
        </section>
        <section class="account-detail__section">
          <h3>已授权能力</h3>
          <div class="account-detail__capabilities">
            <div
              v-for="capability in selected.capabilities"
              :key="capability"
              class="account-detail__capability"
            >
              <q-icon name="check_circle" color="positive" size="17px" />
              <div>
                <strong>{{ capabilityDetail(capability).label }}</strong>
                <small>{{ capabilityDetail(capability).description }}</small>
              </div>
              <q-badge color="positive">已授权</q-badge>
            </div>
          </div>
        </section>
        <p class="account-detail__note">授权状态由微信公众平台同步更新。</p>
      </div>
      <template #actions
        ><AppButton variant="danger" label="解除连接" @click="disconnect" /><AppButton
          variant="outline"
          label="排版管理"
          @click="showSelectedTemplates" /><AppButton
          v-if="selected.status === 'reconnect'"
          label="重新扫码绑定"
          @click="reconnectSelected"
      /></template>
    </AppDialog>

    <AppDialog
      v-model="authDialog"
      :title="selected ? '重新扫码绑定公众号' : '授权新公众号'"
      width="650px"
      persistent
    >
      <div class="authorize-dialog">
        <div class="authorize-dialog__steps">
          <span class="active">1</span>扫码授权<i /><span>2</span>授权完成
        </div>
        <q-spinner v-if="authorizing && !authorization" color="primary" size="58px" />
        <q-banner v-else-if="authorizationError" rounded class="authorize-dialog__error"
          ><span class="wrap-anywhere">{{ authorizationError }}</span
          ><template #action
            ><AppButton variant="outline" label="重试" @click="requestAuthorization" /></template
        ></q-banner>
        <img
          v-else-if="authorizationQr"
          :src="authorizationQr"
          class="authorize-dialog__qr"
          alt="微信公众号授权二维码"
        />
        <h2>{{ authorizationError ? '授权入口暂不可用' : '请使用公众号管理员微信扫码' }}</h2>
        <p v-if="authorization">
          本次扫码仅用于绑定公众号，请选择需要接入的公众号。二维码约在
          <strong>{{ Math.ceil(authorization.expiresIn / 60) }} 分钟</strong>
          后失效；绑定后授权长期有效，接口令牌由系统自动续期，无需重复扫码。如需解除，请在公众号后台“授权管理”操作。
        </p>
        <p v-else-if="!authorizationError">正在向微信公众平台申请一次性授权入口…</p>
        <q-banner rounded
          ><q-icon
            name="shield"
            color="positive"
          />仅公众号管理员可以完成授权，系统不会获取管理员的个人聊天信息。</q-banner
        >
      </div>
      <template #actions
        ><AppButton variant="ghost" label="取消" @click="authDialog = false" /><AppButton
          label="已完成授权，刷新状态"
          :loading="authorizing"
          :disabled="!authorization"
          @click="finishAuthorize()"
      /></template>
    </AppDialog>

    <LayoutTemplateEditor
      v-model="templateDialog"
      :account="selected"
      :templates="templates"
      :has-more="templatesQuery.hasNextPage.value"
      :loading-more="templatesQuery.isFetchingNextPage.value"
      :extraction-enabled="publicSettings.features.featureFlags.template_extraction !== false"
      @changed="templatesQuery.refetch()"
      @load-more="templatesQuery.fetchNextPage()"
    />
  </q-page>
</template>

<style scoped lang="scss">
.accounts-table {
  min-width: 0;
  overflow: clip;
  box-shadow: none;
}
.accounts-load-more {
  display: flex;
  justify-content: center;
  min-width: 0;
  padding: 14px;
  border-top: 1px solid var(--app-border-default);
}
.account-identity {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}
.account-identity > span {
  display: grid;
  min-width: 0;
}
.account-identity strong {
  min-width: 0;
  overflow-wrap: anywhere;
}
.account-identity small {
  margin-top: 3px;
  color: var(--app-text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.account-capabilities {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  min-width: 0;
}
.account-capabilities .q-chip {
  margin: 0;
  color: var(--app-text-primary);
  background: var(--app-bg-subtle);
}

.account-detail {
  display: grid;
  gap: 18px;
  min-width: 0;
  padding: 20px;
  font-size: 12px;
}
.account-detail__hero {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}
.account-detail__identity {
  display: grid;
  gap: 4px;
  min-width: 0;
}
.account-detail__name {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  min-width: 0;
}
.account-detail h2 {
  margin: 0;
  overflow-wrap: anywhere;
  font-size: 15px;
  line-height: 1.4;
}
.account-detail h3 {
  margin: 0 0 9px;
  font-size: 12px;
  line-height: 1.5;
}
.account-detail__identity small,
.account-detail__capability small,
.account-detail__note {
  color: var(--app-text-secondary);
}
.account-detail__identity small {
  overflow-wrap: anywhere;
  font-size: 11px;
}
.account-detail :deep(.q-badge) {
  padding: 3px 7px;
  font-size: 10px;
  line-height: 1.2;
  border-radius: 4px;
}
.account-detail__section {
  min-width: 0;
}
.account-detail__facts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  min-width: 0;
  margin: 0;
  padding: 4px 14px;
  border: 1px solid var(--app-border-default);
  border-radius: 6px;
}
.account-detail__facts > div {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr);
  gap: 6px;
  align-items: center;
  min-width: 0;
  min-height: 42px;
}
.account-detail__facts > div:nth-child(n + 3) {
  border-top: 1px solid var(--app-border-default);
}
.account-detail__facts dt {
  color: var(--app-text-secondary);
}
.account-detail__facts dd {
  min-width: 0;
  margin: 0;
  overflow-wrap: anywhere;
  font-weight: 600;
}
.account-detail__capabilities {
  display: grid;
  min-width: 0;
  border: 1px solid var(--app-border-default);
  border-radius: 6px;
  overflow: clip;
}
.account-detail__capability {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  min-width: 0;
  min-height: 42px;
  padding: 7px 14px;
  border-bottom: 1px solid var(--app-border-default);
}
.account-detail__capability:last-child {
  border-bottom: 0;
}
.account-detail__capability > div {
  display: flex;
  align-items: baseline;
  gap: 16px;
  min-width: 0;
}
.account-detail__capability strong {
  flex: 0 0 68px;
  font-size: 12px;
}
.account-detail__capability small {
  min-width: 0;
  overflow-wrap: anywhere;
  font-size: 10px;
}
.account-detail__note {
  margin: -2px 0 0;
  font-size: 10px;
}

.authorize-dialog {
  display: grid;
  place-items: center;
  gap: 14px;
  min-width: 0;
  padding: 28px;
  text-align: center;
}
.authorize-dialog__steps {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  width: 100%;
  color: var(--app-text-muted);
}
.authorize-dialog__steps span {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  background: var(--app-bg-subtle);
  border-radius: 50%;
}
.authorize-dialog__steps span.active {
  color: #fff;
  background: var(--app-action-primary);
}
.authorize-dialog__steps i {
  width: min(160px, 30vw);
  height: 1px;
  background: var(--app-border-strong);
}
.authorize-dialog__qr {
  display: block;
  width: 220px;
  max-width: 100%;
  height: auto;
  padding: 8px;
  background: #fff;
  border: 1px solid var(--app-border-default);
  border-radius: 12px;
}
.authorize-dialog__error {
  width: 100%;
  color: var(--app-danger);
  background: color-mix(in srgb, var(--app-danger) 9%, var(--app-bg-surface));
}
.authorize-dialog h2 {
  margin: 0;
  font-size: 22px;
}
.authorize-dialog p {
  max-width: 520px;
  margin: 0;
  color: var(--app-text-secondary);
  overflow-wrap: anywhere;
}
.authorize-dialog p strong {
  color: var(--app-warning);
}
.authorize-dialog .q-banner {
  width: 100%;
  color: var(--app-action-primary);
  background: var(--app-action-soft);
  overflow-wrap: anywhere;
}

@media (max-width: 767px) {
  .accounts-table {
    overflow: visible;
    background: transparent;
    border: 0;
    box-shadow: none;
  }
  .account-detail__facts {
    grid-template-columns: 1fr;
  }
  .account-detail__facts > div:nth-child(n + 2) {
    border-top: 1px solid var(--app-border-default);
  }
  .account-detail__capability > div {
    display: grid;
    gap: 2px;
  }
}
</style>
