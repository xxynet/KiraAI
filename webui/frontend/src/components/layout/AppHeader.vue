<template>
  <header class="app-header px-6 py-4 flex items-center justify-between shadow-sm">
    <div class="flex items-center">
      <button
        class="sidebar-menu-btn p-1.5 mr-3 rounded-lg bg-[#f5f5f5] hover:bg-[#e7e7e8] dark:bg-[#121215] dark:hover:bg-[#2b2b2e] text-gray-500 dark:text-gray-400 transition-colors"
        aria-label="Toggle menu"
        @click="$emit('toggle-sidebar')"
      >
        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16" />
        </svg>
      </button>
      <h2 class="text-2xl font-semibold text-gray-800 dark:text-white">
        {{ title }}
      </h2>
    </div>
    <div class="flex items-center gap-2">
      <!-- GitHub -->
      <a
        href="https://github.com/xxynet/KiraAI"
        target="_blank"
        rel="noopener noreferrer"
        class="p-1.5 rounded-lg bg-[#f5f5f5] hover:bg-[#e7e7e8] dark:bg-[#121215] dark:hover:bg-[#2b2b2e] text-gray-500 dark:text-gray-400 transition-colors"
        aria-label="GitHub"
      >
        <svg class="w-6 h-6" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <path fill-rule="evenodd" d="M12 2C6.477 2 2 6.486 2 12.021c0 4.424 2.865 8.18 6.839 9.504.5.092.683-.217.683-.483 0-.237-.009-.866-.014-1.699-2.782.605-3.369-1.342-3.369-1.342-.455-1.158-1.11-1.467-1.11-1.467-.908-.62.069-.608.069-.608 1.004.071 1.532 1.035 1.532 1.035.892 1.534 2.341 1.091 2.91.834.091-.647.35-1.09.636-1.341-2.221-.253-4.555-1.115-4.555-4.961 0-1.095.39-1.99 1.029-2.691-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.027A9.564 9.564 0 0 1 12 6.844c.85.004 1.705.115 2.504.337 1.909-1.297 2.748-1.027 2.748-1.027.546 1.378.202 2.397.1 2.65.64.701 1.027 1.596 1.027 2.691 0 3.857-2.337 4.705-4.566 4.953.359.31.678.921.678 1.856 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.481A10.025 10.025 0 0 0 22 12.021C22 6.486 17.523 2 12 2Z" clip-rule="evenodd" />
        </svg>
      </a>
      <!-- Theme Toggle -->
      <button
        class="p-1.5 rounded-lg bg-[#f5f5f5] hover:bg-[#e7e7e8] dark:bg-[#121215] dark:hover:bg-[#2b2b2e] text-gray-500 dark:text-gray-400 transition-colors"
        :aria-label="appStore.isDark ? t('header.switch_to_light') : t('header.switch_to_dark')"
        :title="appStore.isDark ? t('header.switch_to_light') : t('header.switch_to_dark')"
        @click="toggleTheme"
      >
        <svg v-if="!appStore.isDark" class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z"></path>
        </svg>
        <svg v-else class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z"></path>
        </svg>
      </button>
      <!-- Logout -->
      <button
        class="p-1.5 rounded-lg bg-[#f5f5f5] hover:bg-[#e7e7e8] dark:bg-[#121215] dark:hover:bg-[#2b2b2e] text-gray-500 dark:text-gray-400 transition-colors"
        :aria-label="t('header.logout')"
        :title="t('header.logout')"
        @click="handleLogout"
      >
        <svg class="w-6 h-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6A2.25 2.25 0 005.25 5.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15M18 12H9m9 0l-3-3m3 3l-3 3" />
        </svg>
      </button>
    </div>
  </header>
</template>

<script setup lang="ts">
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { useRouter } from 'vue-router'
import { useTheme } from '@/composables/useTheme'
import { useI18n } from 'vue-i18n'

defineProps<{ title: string }>()
defineEmits<{ 'toggle-sidebar': [] }>()

const { t } = useI18n()
const appStore = useAppStore()
const authStore = useAuthStore()
const router = useRouter()
const { toggleTheme } = useTheme()

async function handleLogout() {
  try {
    await authStore.logout()
  } finally {
    router.push('/login')
  }
}
</script>
