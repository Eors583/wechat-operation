<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { ThemePreference } from '@/api/contracts'
import AppIcon from '@/components/base/AppIcon.vue'
import AdminSidebar from '@/components/composite/AdminSidebar.vue'
import { useAuthStore } from '@/stores/auth'
import { usePreferencesStore } from '@/stores/preferences'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const preferences = usePreferencesStore()
const drawerOpen = ref(true)
const isMobile = ref(false)
let mobileMediaQuery: MediaQueryList | undefined
const themeIcon = computed(
  () =>
    ({ light: 'verified', dark: 'visibility_off', system: 'settings_suggest' })[preferences.theme],
)
const themeLabel = computed(
  () => ({ light: '浅色', dark: '深色', system: '跟随系统' })[preferences.theme],
)

function syncMobileLayout(event: MediaQueryListEvent | MediaQueryList): void {
  const wasMobile = isMobile.value
  isMobile.value = event.matches
  if (event.matches && !wasMobile) drawerOpen.value = false
  if (!event.matches && wasMobile) drawerOpen.value = true
}

onMounted(() => {
  mobileMediaQuery = window.matchMedia('(max-width: 599px)')
  isMobile.value = mobileMediaQuery.matches
  drawerOpen.value = !mobileMediaQuery.matches
  mobileMediaQuery.addEventListener('change', syncMobileLayout)
})

onBeforeUnmount(() => mobileMediaQuery?.removeEventListener('change', syncMobileLayout))
watch(
  () => route.path,
  () => {
    if (isMobile.value) drawerOpen.value = false
  },
)

function setTheme(value: ThemePreference): void {
  preferences.setTheme(value)
}

async function logout(): Promise<void> {
  await auth.logout()
  await router.replace('/login')
}
</script>

<template>
  <el-container direction="vertical" class="admin-layout">
    <el-header class="admin-header">
      <div class="admin-toolbar">
        <el-button text circle aria-label="打开或收起导航" @click="drawerOpen = !drawerOpen">
          <AppIcon name="menu" :size="20" />
        </el-button>
        <div class="admin-toolbar__title"><strong>AI 运营助手</strong><span>管理控制台</span></div>
        <div class="admin-toolbar__spacer" />

        <el-dropdown trigger="click" @command="setTheme">
          <el-button text circle :aria-label="`当前主题：${themeLabel}`">
            <AppIcon :name="themeIcon" :size="20" />
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="light"><AppIcon name="verified" />浅色</el-dropdown-item>
              <el-dropdown-item command="dark"
                ><AppIcon name="visibility_off" />深色</el-dropdown-item
              >
              <el-dropdown-item command="system"
                ><AppIcon name="settings_suggest" />跟随系统</el-dropdown-item
              >
            </el-dropdown-menu>
          </template>
        </el-dropdown>

        <el-dropdown
          trigger="click"
          @command="(command: string) => command === 'logout' && logout()"
        >
          <el-button text class="profile-button">
            <AppIcon name="account_circle" :size="20" />
            <span>{{ auth.identity?.display_name ?? '管理员' }}</span>
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item disabled>
                <div class="profile-summary">
                  <strong>{{ auth.identity?.display_name }}</strong>
                  <span>{{ auth.identity?.username }} · 独立管理会话</span>
                </div>
              </el-dropdown-item>
              <el-dropdown-item divided command="logout"
                ><AppIcon name="logout" />退出登录</el-dropdown-item
              >
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </el-header>

    <el-container class="admin-body">
      <div
        v-if="drawerOpen && isMobile"
        class="admin-aside-scrim"
        aria-hidden="true"
        @click="drawerOpen = false"
      />
      <el-aside
        v-if="drawerOpen"
        width="252px"
        class="admin-aside"
        :class="{ 'admin-aside--mobile': isMobile }"
      >
        <AdminSidebar :active-path="route.path" />
      </el-aside>
      <el-main class="admin-content"><router-view /></el-main>
    </el-container>
  </el-container>
</template>

<style scoped lang="scss">
.admin-layout {
  width: 100%;
  height: 100dvh;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}
.admin-header {
  position: relative;
  z-index: 10;
  height: 64px;
  min-width: 0;
  padding: 0;
  border-bottom: 1px solid var(--app-border-default);
  background: color-mix(in srgb, var(--app-bg-surface) 92%, transparent);
  color: var(--app-text-primary);
  backdrop-filter: blur(14px);
}
.admin-toolbar {
  display: flex;
  align-items: center;
  min-width: 0;
  height: 64px;
  padding: 0 24px 0 18px;
}
.admin-toolbar__title {
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
  margin-left: 12px;
}
.admin-toolbar__title strong,
.admin-toolbar__title span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.admin-toolbar__title span {
  color: var(--app-text-secondary);
  font-size: 13px;
}
.admin-toolbar__spacer {
  flex: 1 1 auto;
  min-width: 8px;
}
.profile-button {
  max-width: 220px;
  min-width: 0;
}
.profile-button span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.profile-summary {
  display: flex;
  min-width: 180px;
  flex-direction: column;
}
.profile-summary span {
  color: var(--app-text-secondary);
  font-size: 12px;
}
.admin-body {
  min-width: 0;
  min-height: 0;
}
.admin-aside {
  min-height: 0;
  overflow: hidden;
  background: var(--app-bg-sidebar);
}
.admin-aside-scrim {
  position: fixed;
  z-index: 8;
  inset: 64px 0 0;
  background: color-mix(in srgb, var(--app-text-primary) 32%, transparent);
}
.admin-aside--mobile {
  position: fixed;
  z-index: 9;
  top: 64px;
  bottom: 0;
  left: 0;
  width: 252px !important;
  box-shadow: var(--app-shadow-soft);
}
.admin-content {
  min-width: 0;
  min-height: 0;
  padding: 0;
  overflow: auto;
  background: var(--app-bg-page);
}
@media (max-width: 599px) {
  .admin-toolbar {
    padding-inline: 8px;
  }
  .admin-toolbar__title span,
  .profile-button span {
    display: none;
  }
  .profile-button {
    width: 40px;
    padding-inline: 8px;
  }
}
</style>
