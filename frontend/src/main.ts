import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import * as ElementPlusIconsVue from './components/icons'
import zhCn from 'element-plus/dist/locale/zh-cn.mjs'

import App from './App.vue'
import router from './router'
import { useAuthStore } from './stores/auth'
import { setUnauthorizedHandler } from './utils/request'
import './styles/index.css'

const app = createApp(App)

// 注册所有图标
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

const pinia = createPinia()
app.use(pinia)
setUnauthorizedHandler(() => {
  useAuthStore(pinia).resetSession()
  if (router.currentRoute.value.path !== '/login') {
    void router.replace('/login')
  }
})
app.use(router)
app.use(ElementPlus, {
  locale: zhCn,
})

app.mount('#app')

// 同一浏览器的多个控制台标签共用会话，切换账户后重新验证身份。
window.addEventListener('storage', (event) => {
  if (event.key === 'token' && event.oldValue !== event.newValue)
    window.location.reload()
})
