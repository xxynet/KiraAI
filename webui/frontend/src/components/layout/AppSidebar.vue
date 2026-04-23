<template>
  <aside class="sidebar-gradient w-64 min-h-screen flex flex-col text-gray-800">
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
          <span>{{ $t(item.label) }}</span>
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
import { computed, ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useAppStore } from '@/stores/app'
import { getVersion } from '@/api/overview'
import CustomSelect from '@/components/common/CustomSelect.vue'
import {
  DataAnalysis,
  Connection,
  Link,
  User,
  SetUp,
  Picture,
  Setting,
  ChatDotRound,
  Document,
  Tools,
} from '@element-plus/icons-vue'

const appVersion = ref('-')

onMounted(async () => {
  try {
    const response = await getVersion()
    appVersion.value = response.data.version
  } catch (error) {
    console.error('Error loading version:', error)
  }
})

const route = useRoute()
const appStore = useAppStore()

const currentLanguage = computed({
  get: () => appStore.language,
  set: (val: string) => appStore.setLanguage(val),
})

const languageOptions = [
  { value: 'en', label: 'English' },
  { value: 'zh', label: '中文' },
]

const navItems = [
  { route: '/overview', label: 'nav.overview', icon: DataAnalysis },
  { route: '/provider', label: 'nav.provider', icon: Connection },
  { route: '/adapter', label: 'nav.adapter', icon: Link },
  { route: '/persona', label: 'nav.persona', icon: User },
  { route: '/sticker', label: 'nav.sticker', icon: Picture },
  { route: '/configuration', label: 'nav.configuration', icon: Tools },
  { route: '/plugin', label: 'nav.plugin', icon: SetUp },
  { route: '/sessions', label: 'nav.sessions', icon: ChatDotRound },
  { route: '/logs', label: 'nav.logs', icon: Document },
  { route: '/settings', label: 'nav.settings', icon: Setting },
]

function isActive(path: string): boolean {
  return route.path === path
}
</script>
