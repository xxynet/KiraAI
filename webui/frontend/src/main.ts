import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
// Dark theme CSS variables — activated when <html> has class="dark"
import 'element-plus/theme-chalk/dark/css-vars.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'

import App from './App.vue'
import router from './router'
import i18n from './i18n'
import './assets/main.css'

// Apply custom CSS / JS from localStorage on app startup
const customCSS = localStorage.getItem('custom_css') || ''
if (customCSS) {
  const tag = document.createElement('style')
  tag.id = 'custom-user-css'
  tag.textContent = customCSS
  document.head.appendChild(tag)
}

const customJS = localStorage.getItem('custom_js') || ''
if (customJS) {
  const tag = document.createElement('script')
  tag.id = 'custom-user-js'
  tag.textContent = customJS
  document.body.appendChild(tag)
}

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(i18n)
app.use(ElementPlus)

// Register all Element Plus icons globally
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.mount('#app')
