<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AuthShell from '@/components/composite/AuthShell.vue'
import AppButton from '@/components/base/AppButton.vue'
import AppInput from '@/components/base/AppInput.vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()
const identifier = ref('')
const password = ref('')
const code = ref('')
const challengeId = ref('')
const loginMode = ref<'password' | 'code'>('password')
const sendingCode = ref(false)
const showPassword = ref(false)
const error = ref('')

const sendCode = async () => {
  error.value = ''
  if (identifier.value.trim().length < 5) return void (error.value = '请先输入正确的手机号或邮箱。')
  sendingCode.value = true
  try {
    const challenge = await auth.requestVerificationCode(identifier.value.trim(), 'login')
    challengeId.value = challenge.challengeId
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '验证码发送失败，请稍后重试。'
  } finally {
    sendingCode.value = false
  }
}

const submit = async () => {
  error.value = ''
  try {
    if (loginMode.value === 'code') {
      if (!challengeId.value) return void (error.value = '请先获取验证码。')
      await auth.loginWithCode(identifier.value.trim(), challengeId.value, code.value)
    } else await auth.login(identifier.value.trim(), password.value)
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/create'
    await router.replace(redirect)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '登录没有完成，请稍后重试。'
  }
}
</script>

<template>
  <AuthShell title="欢迎回来" subtitle="登录后继续创作与管理公众号内容">
    <q-form class="auth-form" @submit.prevent="submit">
      <AppInput
        v-model="identifier"
        label="账号"
        placeholder="请输入手机号或邮箱"
        icon="person_outline"
        autocomplete="username"
      />
      <AppInput
        v-if="loginMode === 'password'"
        v-model="password"
        label="密码"
        :type="showPassword ? 'text' : 'password'"
        placeholder="请输入密码"
        icon="lock_outline"
        autocomplete="current-password"
      >
        <template #append
          ><q-btn
            flat
            round
            dense
            :icon="showPassword ? 'visibility_off' : 'visibility'"
            aria-label="显示或隐藏密码"
            @click="showPassword = !showPassword"
        /></template>
      </AppInput>
      <div v-else class="auth-form__code">
        <AppInput
          v-model="code"
          label="验证码"
          placeholder="请输入 6 位验证码"
          icon="verified_user"
          autocomplete="one-time-code"
        /><AppButton
          type="button"
          variant="outline"
          label="获取验证码"
          :loading="sendingCode"
          @click="sendCode"
        />
      </div>
      <div class="auth-form__options">
        <span>{{ loginMode === 'password' ? '密码登录' : '验证码登录' }}</span>
        <button
          type="button"
          class="auth-form__switch"
          @click="loginMode = loginMode === 'password' ? 'code' : 'password'"
        >
          {{ loginMode === 'password' ? '忘记密码？' : '返回密码登录' }}
        </button>
      </div>
      <q-banner v-if="error" rounded class="auth-form__error"
        ><span class="wrap-anywhere">{{ error }}</span></q-banner
      >
      <AppButton type="submit" label="登录" full-width :loading="auth.loading" />
      <p>还没有账号？<router-link to="/register">立即注册</router-link></p>
      <small
        >登录即表示你已阅读并同意<router-link to="/legal/terms">《用户协议》</router-link
        >和<router-link to="/legal/privacy">《隐私政策》</router-link>，并知悉<router-link
          to="/legal/ai"
          >《AI 内容生成说明》</router-link
        >。</small
      >
    </q-form>
  </AuthShell>
</template>

<style scoped lang="scss">
.auth-form {
  display: grid;
  gap: 22px;
  min-width: 0;

  &__code {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 10px;
    min-width: 0;
  }
  &__options {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    min-width: 0;
    margin-top: -4px;
  }
  &__options > span {
    color: var(--app-text-secondary);
    font-size: 14px;
  }
  &__switch {
    justify-self: end;
    padding: 0;
    color: var(--app-action-primary);
    background: none;
    border: 0;
    cursor: pointer;
  }
  &__error {
    color: var(--app-danger);
    background: color-mix(in srgb, var(--app-danger) 9%, var(--app-bg-surface));
  }
  p {
    margin: 2px 0 0;
    text-align: center;
  }
  small {
    margin-top: 4px;
    color: var(--app-text-secondary);
    line-height: 1.7;
    text-align: center;
    overflow-wrap: anywhere;
  }
}

@media (max-width: 420px) {
  .auth-form__code {
    grid-template-columns: 1fr;
  }
}
</style>
