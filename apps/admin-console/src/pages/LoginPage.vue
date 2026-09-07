<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '@/components/base/AppIcon.vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const loading = ref(false)
const showPassword = ref(false)
const error = ref('')
const form = reactive({ username: '', password: '' })
const redirectTarget = computed(() =>
  typeof route.query.redirect === 'string' ? route.query.redirect : '/',
)

async function submitPassword(): Promise<void> {
  error.value = ''
  if (!form.username.trim() || form.password.length < 8) {
    error.value = '请输入管理员账号和至少 8 位密码。'
    return
  }
  loading.value = true
  const result = await auth.submitPassword(form)
  loading.value = false
  if (!result.ok) error.value = result.message
  else await router.replace(redirectTarget.value)
}
</script>

<template>
  <main class="login-layout">
    <div class="login-page">
      <section class="login-visual" aria-label="产品介绍">
        <div class="login-visual__content">
          <admin-avatar :size="54" class="login-logo"
            ><AppIcon name="smart_toy" :size="26"
          /></admin-avatar>
          <p class="login-visual__eyebrow">WECHAT AI OPERATIONS</p>
          <h1>让每一项 AI 能力<br />可配置、可追踪、可恢复</h1>
          <p>统一维护模型、提示词、技能、公众号连接和失败任务，同时尊重用户内容边界。</p>
          <div class="login-visual__points">
            <span><AppIcon name="verified_user" /> 独立管理员会话</span>
            <span><AppIcon name="history" /> 高风险操作全量审计</span>
            <span><AppIcon name="visibility_off" /> 默认不读取用户正文</span>
          </div>
        </div>
      </section>

      <section class="login-panel">
        <el-card shadow="never" class="login-card">
          <div class="login-card__head">
            <div class="login-card__mobile-brand"><AppIcon name="smart_toy" /> AI 运营助手</div>
            <h2>管理员登录</h2>
            <p class="text-secondary">使用独立管理账号登录，认证结果由管理后台实时返回。</p>
          </div>

          <el-form label-position="top" class="login-fields" @submit.prevent="submitPassword">
            <el-form-item label="管理员账号">
              <el-input v-model.trim="form.username" autocomplete="username">
                <template #prefix><AppIcon name="person" /></template>
              </el-input>
            </el-form-item>
            <el-form-item label="密码">
              <el-input
                v-model="form.password"
                :type="showPassword ? 'text' : 'password'"
                autocomplete="current-password"
              >
                <template #prefix><AppIcon name="lock" /></template>
                <template #suffix>
                  <el-button
                    text
                    circle
                    :aria-label="showPassword ? '隐藏密码' : '显示密码'"
                    @click="showPassword = !showPassword"
                  >
                    <AppIcon :name="showPassword ? 'visibility_off' : 'visibility'" />
                  </el-button>
                </template>
              </el-input>
            </el-form-item>
            <el-alert
              v-if="error"
              type="error"
              :closable="false"
              show-icon
              :title="error"
              class="long-text"
            />
            <el-button
              type="primary"
              size="large"
              native-type="submit"
              :loading="loading"
              class="login-submit"
              >登录</el-button
            >
          </el-form>
        </el-card>
      </section>
    </div>
  </main>
</template>

<style scoped lang="scss">
.login-layout,
.login-page {
  min-height: 100dvh;
}
.login-page {
  display: grid;
  grid-template-columns: minmax(0, 1.12fr) minmax(420px, 0.88fr);
  background: var(--app-bg-page);
}
.login-visual {
  display: flex;
  align-items: center;
  min-width: 0;
  padding: clamp(40px, 7vw, 100px);
  background:
    radial-gradient(circle at 20% 20%, rgb(125 157 255 / 48%), transparent 35%),
    linear-gradient(145deg, #111d39, #263c80 70%, #3b67f3);
  color: white;
}
.login-visual__content {
  max-width: 660px;
  min-width: 0;
}
.login-logo {
  background: #fff;
  color: var(--app-action-primary);
}
.login-visual__eyebrow {
  margin: 26px 0 10px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.16em;
  opacity: 0.72;
}
.login-visual h1 {
  margin: 0;
  font-size: clamp(34px, 4vw, 58px);
  line-height: 1.15;
  overflow-wrap: anywhere;
}
.login-visual p {
  max-width: 590px;
  font-size: 17px;
  opacity: 0.82;
  overflow-wrap: anywhere;
}
.login-visual__points {
  display: grid;
  gap: 12px;
  margin-top: 38px;
}
.login-visual__points span {
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 0;
  overflow-wrap: anywhere;
}
.login-panel {
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 0;
  padding: 32px;
}
.login-card {
  width: min(460px, 100%);
  min-width: 0;
  border-radius: 18px;
  box-shadow: var(--app-shadow-soft);
}
.login-card__head {
  margin-bottom: 24px;
}
.login-card h2 {
  margin: 4px 0 8px;
  font-size: 30px;
}
.login-card p {
  margin: 0;
  overflow-wrap: anywhere;
}
.login-card__mobile-brand {
  display: none;
  margin-bottom: 24px;
  align-items: center;
  gap: 8px;
  font-weight: 700;
}
.login-fields {
  display: grid;
  min-width: 0;
  gap: 2px;
}
.login-fields :deep(.el-form-item) {
  min-width: 0;
}
.login-submit {
  width: 100%;
  margin-top: 4px;
}
@media (max-width: 900px) {
  .login-page {
    grid-template-columns: minmax(0, 1fr);
  }
  .login-visual {
    display: none;
  }
  .login-card__mobile-brand {
    display: flex;
  }
}
@media (max-width: 599px) {
  .login-panel {
    align-items: stretch;
    padding: 0;
  }
  .login-card {
    width: 100%;
    min-height: 100dvh;
    border: 0;
    border-radius: 0;
    box-shadow: none;
  }
  .login-card :deep(.el-card__body) {
    padding: 32px 20px;
  }
  .captcha-row {
    grid-template-columns: minmax(0, 1fr);
  }
  .captcha-code {
    margin-top: -4px;
  }
}
</style>
