import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import '@/styles/app.scss'

import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import ElementPlus from 'element-plus'
import { createPinia } from 'pinia'
import { createApp } from 'vue'
import App from './App.vue'
import * as AdminElementAdapters from './components/base/AdminElementAdapters'
import AppIcon from './components/base/AppIcon.vue'
import { router } from './router'
import { useAuthStore } from './stores/auth'
import { usePreferencesStore } from './stores/preferences'

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)
app.use(ElementPlus)
for (const [name, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(name, component)
}
app.component('AppIcon', AppIcon)
for (const [name, component] of Object.entries(AdminElementAdapters)) {
  app.component(name, component)
}

const preferences = usePreferencesStore(pinia)
preferences.applyTheme()
await useAuthStore(pinia).hydrate()
app.use(router)
app.mount('#app')
