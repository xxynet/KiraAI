<template>
  <aside class="sidebar-gradient min-h-screen flex flex-col text-gray-800" :class="{ 'sidebar-open': open }">
    <!-- Logo -->
    <div class="p-6 border-b border-blue-200/30">
      <h1 class="text-2xl font-bold text-gray-800">{{ $t('app.title') }}</h1>
      <p id="app-version" class="text-sm text-gray-600 mt-1">{{ appVersion }}</p>
    </div>

    <!-- Navigation -->
    <nav class="flex-1 p-4 space-y-2 overflow-y-auto">
      <router-link
        v-for="item in navItems"
        :key="item.route"
        :to="item.route"
        class="nav-item flex items-center justify-between px-4 py-3 rounded-lg transition-colors"
        :class="{ active: isActive(item.route) }"
      >
        <div class="flex items-center gap-3">
          <component :is="item.icon" class="w-5 h-5" />
          <span>{{ item.isPlugin ? item.label : $t(item.label) }}</span>
        </div>
        <span class="nav-dot"></span>
      </router-link>
    </nav>

    <!-- Language Selector -->
    <div class="p-4 border-t border-blue-200/30">
      <CustomSelect
        v-model="currentLanguage"
        :options="languageOptions"
        :placeholder="$t('app.select_language')"
        class="w-full"
      />
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed, ref, watch, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAppStore } from '@/stores/app'
import { usePluginMenuStore } from '@/stores/pluginMenu'
import { getVersion } from '@/api/overview'
import CustomSelect from '@/components/common/CustomSelect.vue'
import {
  DataAnalysis, Connection, Link, User, SetUp, Picture,
  Setting, ChatDotRound, Document, Tools, Box,
} from '@element-plus/icons-vue'
import { iconMap } from '@/utils/iconMap'

defineProps<{ open: boolean }>()

const appVersion = ref('-')
const route = useRoute()
const appStore = useAppStore()
const pluginMenuStore = usePluginMenuStore()
const { locale } = useI18n()

// Re-resolve plugin page labels when UI language changes
watch(locale, (newLocale) => {
  pluginMenuStore.reResolveLabels(newLocale)
})

onMounted(async () => {
  try {
    const response = await getVersion()
    appVersion.value = response.data.version
  } catch (error) {
    console.error('Error loading version:', error)
  }
  pluginMenuStore.fetchAndRegisterMenus()
})

const currentLanguage = computed({
  get: () => appStore.language,
  set: (val: string) => appStore.setLanguage(val),
})

const languageOptions = [
  { value: 'en', label: 'English' },
  { value: 'zh', label: '中文' },
]

const staticNavItems: { route: string; label: string; icon: any; isPlugin: boolean }[] = [
  { route: '/overview', label: 'nav.overview', icon: DataAnalysis, isPlugin: false },
  { route: '/provider', label: 'nav.provider', icon: Connection, isPlugin: false },
  { route: '/adapter', label: 'nav.adapter', icon: Link, isPlugin: false },
  { route: '/persona', label: 'nav.persona', icon: User, isPlugin: false },
  { route: '/sticker', label: 'nav.sticker', icon: Picture, isPlugin: false },
  { route: '/configuration', label: 'nav.configuration', icon: Tools, isPlugin: false },
  { route: '/plugin', label: 'nav.plugin', icon: SetUp, isPlugin: false },
  { route: '/sessions', label: 'nav.sessions', icon: ChatDotRound, isPlugin: false },
  { route: '/logs', label: 'nav.logs', icon: Document, isPlugin: false },
  { route: '/settings', label: 'nav.settings', icon: Setting, isPlugin: false },
]

const navItems = computed(() => {
  const items = [...staticNavItems]
  for (const menu of pluginMenuStore.menus) {
    items.push({
      route: menu.route,
      label: menu.label,
      icon: iconMap[menu.icon || ''] || Box,
      isPlugin: true,
    })
  }
  return items
})

function isActive(path: string): boolean {
  // Normalize trailing slashes so refresh (which Vue Router may canonicalise
  // with a trailing slash) matches the nav item path written without one.
  const norm = (p: string) => (p.length > 1 && p.endsWith('/') ? p.slice(0, -1) : p)
  return norm(route.path) === norm(path)
}
</script>

<style scoped>
.sidebar-gradient {
  width: 16rem;
}

@media (max-width: 768px) {
  .sidebar-gradient {
    position: fixed;
    top: 0;
    left: 0;
    height: 100%;
    z-index: 50;
    transform: translateX(-100%);
    transition: transform 0.25s ease;
  }
  .sidebar-gradient.sidebar-open {
    transform: translateX(0);
  }
}
</style>
