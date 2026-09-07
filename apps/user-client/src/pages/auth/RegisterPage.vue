<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useQuasar } from 'quasar'
import AuthShell from '@/components/composite/AuthShell.vue'
import AppButton from '@/components/base/AppButton.vue'
import AppInput from '@/components/base/AppInput.vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const $q = useQuasar()
const phone = ref('')
const code = ref('')
const password = ref('')
const confirmPassword = ref('')
const accepted = ref(false)
const showPassword = ref(false)
const error = ref('')
const codeSent = ref(false)
const challengeId = ref('')
const sendingCode = ref(false)

const sendCode = async () => {
  if (!/^1\d{10}$/.test(phone.value))
    return $q.notify({ type: 'warning', message: '请先输入正确的手机号。' })
  sendingCode.value = true
  try {
    const challenge = await auth.requestVerificationCode(phone.value, 'register')
    challengeId.value = challenge.challengeId
    codeSent.value = true
    $q.notify({
      type: 'positive',
      message: '验证码已发送，请查看手机短信。',
    })
  } catch (reason) {
    $q.notify({
      type: 'negative',
      message: reason instanceof Error ? reason.message : '验证码发送失败，请稍后重试。',
    })
  } finally {
    sendingCode.value = false
  }
}

const submit = async () => {
  error.value = ''
  if (password.value !== confirmPassword.value) return void (error.value = '两次输入的密码不一致。')
  if (!accepted.value) return void (error.value = '请先阅读并同意用户协议和隐私政策。')
  if (!challengeId.value) return void (error.value = '请先获取短信验证码。')
  try {
    await auth.register(phone.value, challengeId.value, code.value, password.value)
    await router.replace('/create')
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '注册没有完成，请稍后重试。'
  }
}
</script>

<template>
  <AuthShell title="创建账号" subtitle="注册后开始创作与管理公众号内容">
    <q-form class="auth-form" @submit.prevent="submit">
      <AppInput
        v-model="phone"
        label="手机号"
        placeholder="请输入手机号"
        icon="phone_iphone"
        type="tel"
        autocomplete="tel"
      />
      <div class="auth-form__code">
        <AppInput
          v-model="code"
          label="验证码"
          placeholder="请输入验证码"
          icon="verified_user"
        /><AppButton
          type="button"
          variant="outline"
          :label="codeSent ? '重新获取' : '获取验证码'"
          :loading="sendingCode"
          @click="sendCode"
        />
      </div>
      <AppInput
        v-model="password"
        label="设置密码"
        :type="showPassword ? 'text' : 'password'"
        placeholder="请输入 8—20 位密码"
        icon="lock_outline"
        autocomplete="new-password"
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
      <AppInput
        v-model="confirmPassword"
        label="确认密码"
        :type="showPassword ? 'text' : 'password'"
        placeholder="请再次输入密码"
        icon="lock_outline"
        autocomplete="new-password"
      />
      <q-checkbox v-model="accepted" class="auth-form__terms" dense
        ><span
          >我已阅读并同意<router-link to="/legal/terms">《用户协议与版权承诺》</router-link
          >、<router-link to="/legal/privacy">《隐私政策》</router-link>，并知悉<router-link
            to="/legal/ai"
            >《AI 内容生成说明》</router-link
          ></span
        ></q-checkbox
      >
      <q-banner v-if="error" rounded class="auth-form__error"
        ><span class="wrap-anywhere">{{ error }}</span></q-banner
      >
      <AppButton type="submit" label="注册" full-width :loading="auth.loading" />
      <p>已有账号？<router-link to="/login">返回登录</router-link></p>
    </q-form>
  </AuthShell>
</template>

<style scoped lang="scss">
.auth-form {
  display: grid;
  container-type: inline-size;
  gap: 20px;
  min-width: 0;

  &__code {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    align-items: end;
    gap: 10px;
    min-width: 0;

    :deep(.app-button) {
      align-self: end;
      height: 56px;
    }
  }

  &__terms {
    width: 100%;
    min-width: 0;
    align-items: flex-start;
    font-size: 13px;

    :deep(.q-checkbox__label) {
      flex: 1 1 auto;
      min-width: 0;
      line-height: 1.5;
      white-space: nowrap;
    }
  }
  &__error {
    color: var(--app-danger);
    background: color-mix(in srgb, var(--app-danger) 9%, var(--app-bg-surface));
  }
  p {
    margin: 2px 0 0;
    text-align: center;
  }
}

@media (max-width: 420px) {
  .auth-form__code {
    grid-template-columns: 1fr;
  }
}

@container (max-width: 520px) {
  .auth-form__terms {
    :deep(.q-checkbox__label) {
      white-space: normal;
    }
  }
}
</style>
