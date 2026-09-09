<script setup lang="ts">
import AppIcon from '@/components/base/AppIcon.vue'

defineProps<{ activePath: string }>()

const navGroups = [
  { label: '运行总览', items: [{ label: '管理首页', icon: 'home', to: '/' }] },
  {
    label: 'AI 能力',
    items: [
      { label: '模型与积分', icon: 'hub', to: '/ai/config' },
      { label: '提示词版本', icon: 'data_object', to: '/ai/prompts' },
      { label: '官方技能', icon: 'auto_awesome', to: '/skills' },
    ],
  },
  {
    label: '平台运营',
    items: [
      { label: '用户与额度', icon: 'person', to: '/users' },
      { label: '微信平台配置', icon: 'settings_input_antenna', to: '/wechat/platform' },
      { label: '公众号连接', icon: 'forum', to: '/wechat/accounts' },
      { label: '任务与对账', icon: 'fact_check', to: '/tasks' },
    ],
  },
  {
    label: '系统治理',
    items: [
      { label: '系统设置', icon: 'tune', to: '/settings' },
      { label: '外部知识库', icon: 'link', to: '/settings/external-knowledge' },
      { label: '正文解析 API', icon: 'language', to: '/settings/wechat-article-apis' },
      { label: '管理员账号', icon: 'admin_panel_settings', to: '/settings/admins' },
      { label: '审计日志', icon: 'verified_user', to: '/settings/audit' },
    ],
  },
]
</script>

<template>
  <aside class="admin-sidebar">
    <div class="drawer-brand">
      <admin-avatar :size="42" class="brand-avatar"
        ><AppIcon name="smart_toy" :size="22"
      /></admin-avatar>
      <div><strong>微信公众号</strong><span>AI 运营助手</span></div>
    </div>

    <el-scrollbar class="drawer-scroll">
      <el-menu router :default-active="activePath" class="nav-menu">
        <el-menu-item-group v-for="group in navGroups" :key="group.label" :title="group.label">
          <el-menu-item v-for="item in group.items" :key="item.to" :index="item.to">
            <AppIcon :name="item.icon" />
            <span>{{ item.label }}</span>
          </el-menu-item>
        </el-menu-item-group>
      </el-menu>
    </el-scrollbar>

    <div class="drawer-note">
      <AppIcon name="visibility_off" /><span>默认不展示用户文章正文、对话全文和原始资料。</span>
    </div>
  </aside>
</template>

<style scoped lang="scss">
.admin-sidebar {
  display: grid;
  grid-template-rows: 78px minmax(0, 1fr) 80px;
  width: 252px;
  height: 100%;
  min-width: 0;
  min-height: 0;
  background: var(--app-bg-sidebar);
  color: var(--app-text-on-dark);
}
.drawer-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  padding: 16px 18px;
}
.brand-avatar {
  flex: 0 0 auto;
  background: var(--app-action-primary);
  color: #fff;
}
.drawer-brand > div {
  display: flex;
  min-width: 0;
  flex-direction: column;
}
.drawer-brand strong,
.drawer-brand span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.drawer-brand span {
  opacity: 0.7;
  font-size: 12px;
}
.drawer-scroll {
  min-height: 0;
}
.nav-menu {
  border: 0;
  background: transparent;
}
.nav-menu :deep(.el-menu-item-group__title) {
  padding: 14px 16px 5px !important;
  color: rgb(245 247 255 / 52%);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
}
.nav-menu :deep(.el-menu-item) {
  min-width: 0;
  height: 42px;
  margin: 3px 10px;
  padding-inline: 14px !important;
  border-radius: 9px;
  color: rgb(245 247 255 / 78%);
  gap: 12px;
}
.nav-menu :deep(.el-menu-item:hover) {
  background: rgb(125 157 255 / 12%);
  color: #fff;
}
.nav-menu :deep(.el-menu-item.is-active) {
  background: rgb(125 157 255 / 20%);
  color: #fff;
}
.nav-menu :deep(.el-menu-item span) {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}
.drawer-note {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  min-width: 0;
  padding: 14px 16px;
  border-top: 1px solid rgb(255 255 255 / 10%);
  color: rgb(245 247 255 / 64%);
  font-size: 12px;
}
.drawer-note span {
  min-width: 0;
  overflow-wrap: anywhere;
}
</style>
