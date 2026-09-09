<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import type { WechatArticleApi } from '@/api/contracts'
import { adminRepository } from '@/api/repository'
import { useAdminNotifier } from '@/composables/useAdminNotifier'
import StatusBadge from '@/components/base/StatusBadge.vue'
import PageHeader from '@/components/composite/PageHeader.vue'

const notifier = useAdminNotifier()
const items = ref<WechatArticleApi[]>([])
const loading = ref(false)
const saving = ref(false)
const testingId = ref<string | null>(null)
const editorOpen = ref(false)
const selected = ref<WechatArticleApi | null>(null)
const testUrl = ref('')
const form = reactive({
  name: '',
  baseUrl: '',
  priority: 100,
  apiKey: '',
  authHeader: 'X-Auth-Key',
  authPrefix: '',
  clearApiKey: false,
})

const canSave = computed(
  () =>
    Boolean(
      form.name.trim() && /^https:\/\//i.test(form.baseUrl.trim()) && form.authHeader.trim(),
    ) &&
    Number.isInteger(form.priority) &&
    form.priority >= 1 &&
    form.priority <= 999,
)

onMounted(load)

async function load(): Promise<void> {
  loading.value = true
  try {
    items.value = await adminRepository.wechatArticleApis()
  } catch (error) {
    notifyError(error, '正文 API 配置加载失败。')
  } finally {
    loading.value = false
  }
}

function openCreate(): void {
  selected.value = null
  Object.assign(form, {
    name: '',
    baseUrl: '',
    priority: Math.min(999, Math.max(100, ...items.value.map((item) => item.priority + 10))),
    apiKey: '',
    authHeader: 'X-Auth-Key',
    authPrefix: '',
    clearApiKey: false,
  })
  editorOpen.value = true
}

function openEdit(item: WechatArticleApi): void {
  selected.value = item
  Object.assign(form, {
    name: item.name,
    baseUrl: item.base_url,
    priority: item.priority,
    apiKey: '',
    authHeader: item.auth_header,
    authPrefix: item.auth_prefix,
    clearApiKey: false,
  })
  editorOpen.value = true
}

async function save(): Promise<void> {
  if (!canSave.value) return
  saving.value = true
  try {
    const input = {
      name: form.name.trim(),
      baseUrl: form.baseUrl.trim(),
      priority: form.priority,
      apiKey: form.apiKey || undefined,
      authHeader: form.authHeader.trim(),
      authPrefix: form.authPrefix,
    }
    if (selected.value) {
      await adminRepository.updateWechatArticleApi(selected.value.id, {
        ...input,
        clearApiKey: form.clearApiKey,
        reason: '管理员更新微信公众号正文 API 配置',
      })
    } else {
      await adminRepository.createWechatArticleApi(input)
    }
    editorOpen.value = false
    await load()
    notifier.notify({ type: 'positive', message: '正文 API 配置已保存，密钥不会回显。' })
  } catch (error) {
    notifyError(error, '正文 API 配置保存失败。')
  } finally {
    saving.value = false
  }
}

async function toggle(item: WechatArticleApi): Promise<void> {
  try {
    await adminRepository.updateWechatArticleApi(item.id, {
      status: item.status === 'active' ? 'disabled' : 'active',
      reason: `管理员${item.status === 'active' ? '停用' : '启用'}正文 API`,
    })
    await load()
    notifier.notify({
      type: 'positive',
      message: `已${item.status === 'active' ? '停用' : '启用'}。`,
    })
  } catch (error) {
    notifyError(error, '状态更新失败。')
  }
}

async function test(item: WechatArticleApi): Promise<void> {
  if (!/^https:\/\/mp\.weixin\.qq\.com\//i.test(testUrl.value.trim())) {
    notifier.notify({ type: 'warning', message: '请先填写一条有效的微信公众号文章链接。' })
    return
  }
  testingId.value = item.id
  try {
    const result = await adminRepository.testWechatArticleApi(item.id, testUrl.value.trim())
    await load()
    notifier.notify({ type: result.passed ? 'positive' : 'warning', message: result.message })
  } catch (error) {
    notifyError(error, '连接测试失败。')
  } finally {
    testingId.value = null
  }
}

function notifyError(error: unknown, fallback: string): void {
  notifier.notify({ type: 'negative', message: error instanceof Error ? error.message : fallback })
}

function formatTime(value: string | null): string {
  return value
    ? new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(
        new Date(value),
      )
    : '尚未测试'
}
</script>

<template>
  <section class="admin-page article-api-page">
    <PageHeader
      title="公众号正文解析 API"
      description="用户只需粘贴微信文章链接。系统按优先级调用已启用的第三方 API，失败后自动切换下一个，最后再尝试服务器直连。"
      eyebrow="系统治理"
    >
      <template #actions>
        <admin-button
          unelevated
          color="primary"
          icon="add"
          label="添加兜底 API"
          @click="openCreate"
        />
      </template>
    </PageHeader>

    <admin-banner rounded class="info-banner">
      <template #avatar><app-icon name="verified_user" color="primary" /></template>
      mptext 免费 API
      已作为默认第一顺位。公共免费接口可能限流，生产环境建议继续添加一个带密钥的备用服务；密钥加密保存且不会回显。
    </admin-banner>

    <el-card flat bordered class="surface-card test-card">
      <admin-card-section>
        <div class="test-copy">
          <strong>用真实文章验证配置</strong>
          <span>测试只调用你选择的 API，不会用服务器直连结果代替。</span>
        </div>
        <admin-input
          v-model.trim="testUrl"
          outlined
          label="微信公众号文章链接"
          placeholder="https://mp.weixin.qq.com/s/..."
        />
      </admin-card-section>
    </el-card>

    <admin-inner-loading :showing="loading" label="正在加载正文 API…" />
    <div v-if="items.length" class="api-grid">
      <el-card v-for="item in items" :key="item.id" flat bordered class="surface-card api-card">
        <admin-card-section class="api-head">
          <div class="api-title">
            <h2>{{ item.name }}</h2>
            <admin-badge v-if="item.is_default" color="primary" outline label="默认" />
          </div>
          <StatusBadge :status="item.status" />
        </admin-card-section>
        <admin-card-section class="api-details">
          <div>
            <span>优先级</span><strong>{{ item.priority }}</strong>
          </div>
          <div>
            <span>接口地址</span><code>{{ item.base_url }}</code>
          </div>
          <div>
            <span>认证 Header</span><strong>{{ item.auth_header }}</strong>
          </div>
          <div>
            <span>API 密钥</span
            ><strong>{{ item.secret_configured ? '已配置' : '未配置（匿名调用）' }}</strong>
          </div>
          <div>
            <span>最近测试</span>
            <strong :class="item.last_test_passed ? 'tone-success' : 'tone-warning'">
              {{ item.last_test_passed ? '通过' : '未通过或未测试' }}
            </strong>
            <small>{{ formatTime(item.last_tested_at) }}</small>
          </div>
        </admin-card-section>
        <el-divider />
        <admin-card-actions class="api-actions">
          <admin-button flat color="primary" icon="edit" label="编辑" @click="openEdit(item)" />
          <admin-button
            outline
            color="primary"
            icon="science"
            label="测试"
            :loading="testingId === item.id"
            @click="test(item)"
          />
          <admin-space />
          <admin-button
            outline
            :color="item.status === 'active' ? 'warning' : 'positive'"
            :icon="item.status === 'active' ? 'pause_circle' : 'play_circle'"
            :label="item.status === 'active' ? '停用' : '启用'"
            @click="toggle(item)"
          />
        </admin-card-actions>
      </el-card>
    </div>

    <admin-dialog v-model="editorOpen" width="min(720px, calc(100vw - 32px))" persistent>
      <el-card class="editor-dialog">
        <admin-toolbar>
          <admin-toolbar-title>{{
            selected ? '编辑正文 API' : '添加兜底 API'
          }}</admin-toolbar-title>
          <admin-button
            flat
            round
            dense
            icon="close"
            aria-label="关闭"
            @click="editorOpen = false"
          />
        </admin-toolbar>
        <el-divider />
        <admin-card-section class="editor-form">
          <div class="two-column">
            <admin-input v-model.trim="form.name" outlined label="配置名称" maxlength="120" />
            <admin-input
              v-model.number="form.priority"
              outlined
              type="number"
              label="优先级（数字越小越先调用）"
              min="1"
              max="999"
            />
          </div>
          <admin-input
            v-model.trim="form.baseUrl"
            outlined
            label="下载接口 URL"
            hint="必须是 HTTPS；系统会附加 url 和 format=html 查询参数"
          />
          <div class="two-column">
            <admin-input v-model.trim="form.authHeader" outlined label="密钥 Header" />
            <admin-input
              v-model="form.authPrefix"
              outlined
              label="密钥前缀（可留空）"
              placeholder="例如 Bearer "
            />
          </div>
          <admin-input
            v-model="form.apiKey"
            outlined
            type="password"
            autocomplete="new-password"
            :label="selected?.secret_configured ? '替换 API 密钥（留空保持）' : 'API 密钥（可选）'"
          />
          <admin-checkbox
            v-if="selected?.secret_configured"
            v-model="form.clearApiKey"
            label="清除现有 API 密钥，改为匿名调用"
          />
        </admin-card-section>
        <el-divider />
        <admin-card-actions align="right" class="editor-actions">
          <admin-button flat label="取消" @click="editorOpen = false" />
          <admin-button
            unelevated
            color="primary"
            label="保存"
            :disable="!canSave"
            :loading="saving"
            @click="save"
          />
        </admin-card-actions>
      </el-card>
    </admin-dialog>
  </section>
</template>

<style scoped lang="scss">
@use 'sass:map';
@use '@/styles/tokens/generated' as tokens;

.article-api-page,
.api-grid,
.api-card,
.api-details,
.editor-dialog,
.editor-form {
  min-width: 0;
}
.info-banner,
.test-card {
  margin-bottom: map.get(tokens.$app-space, '4');
}
.test-card :deep(.admin-card-section) {
  display: grid;
  grid-template-columns: minmax(180px, 0.7fr) minmax(280px, 1.3fr);
  gap: map.get(tokens.$app-space, '4');
  align-items: center;
}
.test-copy {
  display: grid;
  gap: map.get(tokens.$app-space, '1');
  min-width: 0;
}
.test-copy span {
  color: var(--app-text-secondary);
  overflow-wrap: anywhere;
}
.api-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: map.get(tokens.$app-space, '4');
}
.api-card {
  display: flex;
  flex-direction: column;
}
.api-head,
.api-title,
.api-actions {
  display: flex;
  align-items: center;
  gap: map.get(tokens.$app-space, '2');
  min-width: 0;
}
.api-head {
  justify-content: space-between;
}
.api-title {
  overflow: hidden;
}
.api-title h2 {
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 18px;
}
.api-details {
  display: grid;
  gap: map.get(tokens.$app-space, '3');
}
.api-details > div {
  display: grid;
  grid-template-columns: 108px minmax(0, 1fr);
  gap: map.get(tokens.$app-space, '2');
  min-width: 0;
}
.api-details span,
.api-details small {
  color: var(--app-text-secondary);
}
.api-details strong,
.api-details code {
  min-width: 0;
  overflow-wrap: anywhere;
}
.api-details small {
  grid-column: 2;
}
.api-actions {
  flex-wrap: wrap;
}
.editor-form {
  display: grid;
  gap: map.get(tokens.$app-space, '4');
  max-height: min(68vh, 620px);
  overflow-y: auto;
}
.two-column {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: map.get(tokens.$app-space, '3');
  min-width: 0;
}
.tone-success {
  color: var(--app-action-success);
}
.tone-warning {
  color: var(--app-action-warning);
}
@media (max-width: 900px) {
  .api-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
@media (max-width: 640px) {
  .test-card :deep(.admin-card-section),
  .two-column {
    grid-template-columns: minmax(0, 1fr);
  }
  .api-details > div {
    grid-template-columns: minmax(0, 1fr);
  }
  .api-details small {
    grid-column: 1;
  }
}
</style>
