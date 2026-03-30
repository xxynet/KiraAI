<template>
  <aside class="sidebar-gradient w-64 min-h-screen flex flex-col py-6 px-4">
    <!-- Logo -->
    <div class="mb-8 px-2">
      <h1 class="text-2xl font-bold text-gray-900">{{ $t('app.title') }}</h1>
      <p class="text-sm text-gray-500 mt-1">{{ $t('app.subtitle') }}</p>
    </div>

    <!-- Navigation -->
    <nav class="flex-1 space-y-1">
      <router-link
        v-for="item in navItems"
        :key="item.route"
        :to="item.route"
        class="nav-item flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm"
        :class="{ active: isActive(item.route) }"
      >
        <component :is="item.icon" class="w-5 h-5" />
        <span>{{ $t(item.label) }}</span>
        <span class="nav-dot ml-auto"></span>
      </router-link>
    </nav>

    <!-- Language Selector -->
    <div class="mt-4 px-2">
      <el-select
        v-model="currentLanguage"
        size="small"
        class="w-full"
        @change="onLanguageChange"
      >
        <el-option label="English" value="en" />
        <el-option label="中文" value="zh" />
      </el-select>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAppStore } from '@/stores/app'
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

const route = useRoute()
const { locale } = useI18n()
const appStore = useAppStore()

const currentLanguage = computed({
  get: () => appStore.language,
  set: (val: string) => val,
})

const navItems = [
  { route: '/overview', label: 'nav.overview', icon: DataAnalysis },
  { route: '/provider', label: 'nav.provider', icon: Connection },
  { route: '/adapter', label: 'nav.adapter', icon: Link },
  { route: '/persona', label: 'nav.persona', icon: User },
  { route: '/plugin', label: 'nav.plugin', icon: SetUp },
  { route: '/sticker', label: 'nav.sticker', icon: Picture },
  { route: '/configuration', label: 'nav.configuration', icon: Tools },
  { route: '/sessions', label: 'nav.sessions', icon: ChatDotRound },
  { route: '/logs', label: 'nav.logs', icon: Document },
  { route: '/settings', label: 'nav.settings', icon: Setting },
]

function isActive(path: string): boolean {
  return route.path === path
}

function onLanguageChange(lang: string) {
  appStore.setLanguage(lang)
  locale.value = lang
}
</script>
