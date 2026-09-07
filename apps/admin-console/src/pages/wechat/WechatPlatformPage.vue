<script setup lang="ts">
import { useAdminNotifier } from '@/composables/useAdminNotifier'
import { computed, onMounted, reactive, ref } from 'vue'
import type { WechatPlatformConfig } from '@/api/contracts'
import { adminRepository } from '@/api/repository'
import StatusBadge from '@/components/base/StatusBadge.vue'
import ConfirmActionDialog from '@/components/composite/ConfirmActionDialog.vue'
import PageHeader from '@/components/composite/PageHeader.vue'

const notifier = useAdminNotifier()
const defaultCallback = (path: string) => new URL(path, window.location.origin).toString()
const config = reactive<WechatPlatformConfig>({
  component_appid: '',
  app_secret_configured: false,
  message_token_configured: false,
  encoding_aes_key_configured: false,
  ticket_callback_url: defaultCallback('/callbacks/v1/wechat/tickets'),
  authorization_callback_url: defaultCallback('/callbacks/v1/wechat/authorize'),
  status: 'draft',
  ticket_health: 'down',
  token_health: 'down',
  last_ticket_at: null,
  last_token_refresh_at: null,
  affected_capabilities: ['微信平台配置尚未加载'],
})
const testing = ref(false)
const publishConfirm = ref(false)
const secretsOpen = ref(false)
const secretForm = reactive({ appSecret: '', messageToken: '', encodingAesKey: '' })

const overallHealth = computed(() =>
  config.ticket_health === 'healthy' && config.token_health === 'healthy'
    ? 'healthy'
    : config.ticket_health === 'down' || config.token_health === 'down'
      ? 'down'
      : 'degraded',
)

onMounted(async () => {
  try {
    const [loaded] = await adminRepository.wechatConfigs()
    if (loaded) Object.assign(config, loaded)
  } catch (error) {
    notifier.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '微信平台配置加载失败。',
    })
  }
})

function markDraft(): void {
  if (config.status !== 'draft') config.status = 'draft'
}

async function saveDraft(): Promise<void> {
  try {
    await adminRepository.saveWechatConfig(config, {})
    config.status = 'draft'
    notifier.notify({
      type: 'positive',
      message: '微信平台配置草稿已保存，线上继续使用当前发布版本。',
    })
  } catch (error) {
    notifier.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '微信平台配置保存失败。',
    })
  }
}

async function saveSecrets(): Promise<void> {
  try {
    await adminRepository.saveWechatConfig(config, secretForm)
    if (secretForm.appSecret) config.app_secret_configured = true
    if (secretForm.messageToken) config.message_token_configured = true
    if (secretForm.encodingAesKey) config.encoding_aes_key_configured = true
    secretForm.appSecret = ''
    secretForm.messageToken = ''
    secretForm.encodingAesKey = ''
    config.status = 'draft'
    secretsOpen.value = false
    notifier.notify({ type: 'positive', message: '密钥已加密保存且不会回显，请重新测试。' })
  } catch (error) {
    notifier.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '密钥引用保存失败。',
    })
  }
}

async function runTest(): Promise<void> {
  testing.value = true
  try {
    const result = await adminRepository.testWechatConfig()
    const [loaded] = await adminRepository.wechatConfigs()
    if (loaded) Object.assign(config, loaded)
    notifier.notify({ type: result.passed ? 'positive' : 'warning', message: result.message })
  } catch (error) {
    notifier.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '微信平台测试失败。',
    })
  } finally {
    testing.value = false
  }
}

async function publish(): Promise<void> {
  if (config.status !== 'testing') return
  try {
    await adminRepository.publishWechatConfig()
    const [loaded] = await adminRepository.wechatConfigs()
    if (loaded) Object.assign(config, loaded)
    notifier.notify({
      type: 'positive',
      message: '微信平台配置已发布，用户的新授权和微信操作将使用该版本。',
    })
  } catch (error) {
    notifier.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '微信平台配置发布失败。',
    })
  }
}

function copyText(value: string): Promise<void> {
  return window.navigator.clipboard.writeText(value)
}
</script>

<template>
  <section class="admin-page">
    <PageHeader
      title="微信平台配置"
      description="配置微信公众号第三方平台，而非企业微信开放平台。密钥保存后不回显，发布前必须验证票据、Token、加解密和授权回跳。"
      eyebrow="公众号管理"
    >
      <template #actions
        ><admin-button
          outline
          color="primary"
          icon="key"
          label="替换密钥"
          @click="secretsOpen = true"
      /></template>
    </PageHeader>

    <section class="health-grid">
      <el-card flat bordered class="surface-card health-summary"
        ><admin-card-section
          ><div><span>平台整体状态</span><StatusBadge :status="overallHealth" /></div>
          <strong>{{
            overallHealth === 'healthy'
              ? '授权链路正常'
              : overallHealth === 'degraded'
                ? '部分能力需关注'
                : '平台能力异常'
          }}</strong>
          <p>配置版本状态：<StatusBadge :status="config.status" /></p></admin-card-section
      ></el-card>
      <el-card flat bordered class="surface-card health-item"
        ><admin-card-section
          ><admin-avatar color="green-1" text-color="positive" icon="mark_email_read" />
          <div>
            <span>票据推送</span><strong>{{ config.last_ticket_at ?? '尚未收到' }}</strong>
          </div>
          <StatusBadge :status="config.ticket_health" /></admin-card-section
      ></el-card>
      <el-card flat bordered class="surface-card health-item"
        ><admin-card-section
          ><admin-avatar color="blue-1" text-color="primary" icon="vpn_key" />
          <div>
            <span>平台 Token</span><strong>{{ config.last_token_refresh_at ?? '尚未刷新' }}</strong>
          </div>
          <StatusBadge :status="config.token_health" /></admin-card-section
      ></el-card>
    </section>

    <admin-banner v-if="config.affected_capabilities.length" rounded class="impact-banner"
      ><template #avatar><app-icon name="warning" color="negative" /></template
      ><strong>当前异常会影响：</strong>
      {{
        config.affected_capabilities.join('、')
      }}。已经保存的文章和模板不受影响；请修复后重新测试并发布。<template #action
        ><admin-button flat color="negative" label="查看失败任务" to="/tasks" /></template
    ></admin-banner>

    <div class="settings-grid">
      <el-card flat bordered class="surface-card settings-card">
        <admin-card-section
          ><h2>第三方平台身份</h2>
          <p>AppID 可识别显示，Secret 加密保存且不会回显。</p></admin-card-section
        ><el-divider />
        <admin-card-section class="form-grid">
          <admin-input
            v-model.trim="config.component_appid"
            outlined
            label="Component AppID"
            @update:model-value="markDraft"
          />
          <div class="secret-row">
            <div>
              <app-icon
                :name="config.app_secret_configured ? 'check_circle' : 'error'"
                :color="config.app_secret_configured ? 'positive' : 'negative'"
              /><span>AppSecret</span>
            </div>
            <strong>{{ config.app_secret_configured ? '已配置' : '未配置' }}</strong
            ><admin-button flat color="primary" label="替换" @click="secretsOpen = true" />
          </div>
          <div class="secret-row">
            <div>
              <app-icon
                :name="config.message_token_configured ? 'check_circle' : 'error'"
                :color="config.message_token_configured ? 'positive' : 'negative'"
              /><span>消息 Token</span>
            </div>
            <strong>{{ config.message_token_configured ? '已配置' : '未配置' }}</strong
            ><admin-button flat color="primary" label="替换" @click="secretsOpen = true" />
          </div>
          <div class="secret-row">
            <div>
              <app-icon
                :name="config.encoding_aes_key_configured ? 'check_circle' : 'error'"
                :color="config.encoding_aes_key_configured ? 'positive' : 'negative'"
              /><span>EncodingAESKey</span>
            </div>
            <strong>{{ config.encoding_aes_key_configured ? '已配置' : '未配置' }}</strong
            ><admin-button flat color="primary" label="替换" @click="secretsOpen = true" />
          </div>
        </admin-card-section>
      </el-card>

      <el-card flat bordered class="surface-card settings-card">
        <admin-card-section
          ><h2>回调地址</h2>
          <p>生产环境必须使用 HTTPS，并保持对微信平台公网可达。</p></admin-card-section
        ><el-divider />
        <admin-card-section class="form-grid">
          <admin-input
            v-model.trim="config.ticket_callback_url"
            outlined
            type="url"
            label="票据回调地址"
            @update:model-value="markDraft"
            ><template #append
              ><admin-button
                flat
                round
                dense
                icon="content_copy"
                aria-label="复制票据回调地址"
                @click="copyText(config.ticket_callback_url)" /></template
          ></admin-input>
          <admin-input
            v-model.trim="config.authorization_callback_url"
            outlined
            type="url"
            label="授权回调地址"
            @update:model-value="markDraft"
            ><template #append
              ><admin-button
                flat
                round
                dense
                icon="content_copy"
                aria-label="复制授权回调地址"
                @click="copyText(config.authorization_callback_url)" /></template
          ></admin-input>
          <admin-banner rounded class="callback-note"
            ><template #avatar><app-icon name="security" /></template
            >回调验签、解密、事件去重和迟到回调状态防倒退由后端执行；前端不接触 AES
            密钥。</admin-banner
          >
        </admin-card-section>
      </el-card>

      <el-card flat bordered class="surface-card test-card">
        <admin-card-section
          ><h2>发布检查</h2>
          <p>测试不会影响用户；发布值会作用于用户下一次授权或微信操作。</p></admin-card-section
        ><el-divider />
        <admin-card-section class="check-list">
          <div>
            <app-icon
              :name="config.component_appid ? 'check_circle' : 'radio_button_unchecked'"
              :color="config.component_appid ? 'positive' : 'grey-6'"
            />
            Component AppID 已填写
          </div>
          <div>
            <app-icon
              :name="config.app_secret_configured ? 'check_circle' : 'radio_button_unchecked'"
              :color="config.app_secret_configured ? 'positive' : 'grey-6'"
            />
            AppSecret 密钥引用可用
          </div>
          <div>
            <app-icon
              :name="
                config.message_token_configured && config.encoding_aes_key_configured
                  ? 'check_circle'
                  : 'radio_button_unchecked'
              "
              :color="
                config.message_token_configured && config.encoding_aes_key_configured
                  ? 'positive'
                  : 'grey-6'
              "
            />
            消息 Token 与 AES Key 已配置
          </div>
          <div>
            <app-icon
              :name="
                config.ticket_health === 'healthy' && config.token_health === 'healthy'
                  ? 'check_circle'
                  : 'radio_button_unchecked'
              "
              :color="
                config.ticket_health === 'healthy' && config.token_health === 'healthy'
                  ? 'positive'
                  : 'grey-6'
              "
            />
            票据和 Token 测试通过
          </div>
        </admin-card-section>
      </el-card>
    </div>

    <el-card flat bordered class="surface-card action-footer"
      ><div>
        <strong>当前配置：<StatusBadge :status="config.status" /></strong
        ><span>发布新配置前，线上继续使用上一发布版本。</span>
      </div>
      <div>
        <admin-button flat icon="save" label="保存草稿" @click="saveDraft" /><admin-button
          outline
          color="primary"
          icon="science"
          label="运行全链路测试"
          :loading="testing"
          @click="runTest"
        /><admin-button
          unelevated
          color="positive"
          icon="publish"
          label="发布配置"
          :disable="config.status !== 'testing'"
          @click="publishConfirm = true"
        /></div
    ></el-card>

    <admin-dialog v-model="secretsOpen" width="min(660px, calc(100vw - 48px))"
      ><el-card class="secret-dialog"
        ><admin-toolbar
          ><admin-toolbar-title>填写平台密钥</admin-toolbar-title
          ><admin-button
            flat
            round
            dense
            icon="close"
            aria-label="关闭"
            @click="secretsOpen = false" /></admin-toolbar
        ><el-divider /><admin-card-section class="secret-form"
          ><admin-banner rounded class="callback-note"
            >请填写微信开放平台中的真实值；留空表示保持当前值。提交后立即加密，页面和接口均不回显密钥。</admin-banner
          ><admin-input
            v-model="secretForm.appSecret"
            outlined
            type="password"
            autocomplete="new-password"
            label="Component AppSecret" /><admin-input
            v-model="secretForm.messageToken"
            outlined
            type="password"
            autocomplete="new-password"
            label="消息校验 Token" /><admin-input
            v-model="secretForm.encodingAesKey"
            outlined
            type="password"
            autocomplete="new-password"
            label="EncodingAESKey" /></admin-card-section
        ><admin-card-actions align="right"
          ><admin-button flat label="取消" @click="secretsOpen = false" /><admin-button
            unelevated
            color="primary"
            icon="save"
            label="加密保存密钥"
            :disable="
              !secretForm.appSecret && !secretForm.messageToken && !secretForm.encodingAesKey
            "
            @click="saveSecrets" /></admin-card-actions></el-card
    ></admin-dialog>

    <ConfirmActionDialog
      v-model="publishConfirm"
      title="发布微信平台配置"
      description="发布后，用户的新授权、Token 刷新、草稿同步和正式发布将使用该配置。运行中的任务继续使用开始时的配置快照。"
      confirm-label="确认发布"
      require-reason
      @confirm="publish"
    />
  </section>
</template>

<style scoped lang="scss">
.health-grid {
  display: grid;
  grid-template-columns: 1.3fr repeat(2, minmax(0, 1fr));
  gap: 14px;
  min-width: 0;
  margin-bottom: 18px;
}
.health-grid > * {
  min-width: 0;
}
.health-summary .admin-card-section {
  display: grid;
  gap: 7px;
}
.health-summary .admin-card-section > div {
  display: flex;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  min-width: 0;
}
.health-summary span,
.health-item span {
  color: var(--app-text-secondary);
}
.health-summary strong {
  font-size: 20px;
  overflow-wrap: anywhere;
}
.health-summary p {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 7px;
  margin: 0;
  color: var(--app-text-secondary);
}
.health-item .admin-card-section {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  min-width: 0;
}
.health-item div {
  min-width: 0;
}
.health-item strong {
  display: block;
  margin-top: 4px;
  font-size: 12px;
  overflow-wrap: anywhere;
}
.impact-banner {
  margin-bottom: 18px;
  border: 1px solid color-mix(in srgb, var(--app-action-danger) 30%, var(--app-border-default));
  background: color-mix(in srgb, var(--app-action-danger) 8%, var(--app-bg-surface));
  overflow-wrap: anywhere;
}
.settings-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
  min-width: 0;
}
.settings-grid > * {
  min-width: 0;
}
.settings-card h2,
.test-card h2 {
  margin: 0;
  font-size: 18px;
}
.settings-card p,
.test-card p {
  margin: 4px 0 0;
  color: var(--app-text-secondary);
  overflow-wrap: anywhere;
}
.form-grid,
.secret-form {
  display: grid;
  gap: 14px;
  min-width: 0;
}
.secret-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  gap: 10px;
  align-items: center;
  min-width: 0;
  min-height: 50px;
  padding: 7px 8px 7px 13px;
  border: 1px solid var(--app-border-default);
  border-radius: 8px;
}
.secret-row > div {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.secret-row span,
.secret-row strong {
  min-width: 0;
  overflow-wrap: anywhere;
}
.callback-note {
  border: 1px solid var(--app-border-default);
  background: var(--app-bg-subtle);
  overflow-wrap: anywhere;
}
.test-card {
  grid-column: 1 / -1;
}
.check-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  min-width: 0;
}
.check-list > div {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  min-width: 0;
  overflow-wrap: anywhere;
}
.action-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  min-width: 0;
  margin-top: 18px;
  padding: 14px 16px;
  position: sticky;
  bottom: 12px;
  z-index: 10;
}
.action-footer > div {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.action-footer span {
  color: var(--app-text-secondary);
  overflow-wrap: anywhere;
}
.secret-dialog {
  width: min(620px, calc(100vw - 32px));
  max-width: 100%;
}

@media (max-width: 1023px) {
  .health-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
@media (max-width: 899px) {
  .settings-grid {
    grid-template-columns: minmax(0, 1fr);
  }
  .test-card {
    grid-column: auto;
  }
  .action-footer {
    align-items: stretch;
    flex-direction: column;
    position: static;
  }
}
@media (max-width: 599px) {
  .check-list {
    grid-template-columns: minmax(0, 1fr);
  }
  .secret-row {
    grid-template-columns: minmax(0, 1fr) auto;
  }
  .secret-row .el-button {
    grid-column: 1 / -1;
    justify-self: stretch;
  }
  .action-footer > div:last-child {
    align-items: stretch;
    flex-direction: column;
  }
  .secret-dialog {
    width: 100%;
  }
}
</style>
