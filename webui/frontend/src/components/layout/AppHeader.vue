<template>
  <header class="app-header px-6 py-4 flex items-center justify-between shadow-sm">
    <div class="flex items-center">
      <button
        class="sidebar-menu-btn p-1.5 mr-3 rounded-lg bg-[#f5f5f5] hover:bg-[#e7e7e8] dark:bg-[#121215] dark:hover:bg-[#2b2b2e] text-gray-500 dark:text-gray-400 transition-colors"
        aria-label="Toggle menu"
        @click="$emit('toggle-sidebar')"
      >
        <IconHamburger class="w-6 h-6" />
      </button>
      <h2 class="text-2xl font-semibold text-gray-800 dark:text-white">
        {{ title }}
      </h2>
    </div>
    <div class="flex items-center gap-2">
      <!-- Update -->
      <button
        class="p-1.5 rounded-lg bg-[#f5f5f5] hover:bg-[#e7e7e8] dark:bg-[#121215] dark:hover:bg-[#2b2b2e] transition-colors"
        :class="hasNewVersion ? 'text-blue-500 dark:text-blue-400' : 'text-gray-500 dark:text-gray-400'"
        :aria-label="t('header.releases')"
        :title="t('header.releases')"
        @click="openReleases"
      >
        <IconDownload class="w-6 h-6" />
      </button>
      <!-- Docs -->
      <a
        :href="t('header.docs_url')"
        target="_blank"
        rel="noopener noreferrer"
        class="p-1.5 rounded-lg bg-[#f5f5f5] hover:bg-[#e7e7e8] dark:bg-[#121215] dark:hover:bg-[#2b2b2e] text-gray-500 dark:text-gray-400 transition-colors"
        :aria-label="t('header.docs')"
        :title="t('header.docs')"
      >
        <IconBook class="w-6 h-6" />
      </a>
      <!-- GitHub -->
      <a
        href="https://github.com/xxynet/KiraAI"
        target="_blank"
        rel="noopener noreferrer"
        class="p-1.5 rounded-lg bg-[#f5f5f5] hover:bg-[#e7e7e8] dark:bg-[#121215] dark:hover:bg-[#2b2b2e] text-gray-500 dark:text-gray-400 transition-colors"
        aria-label="GitHub"
      >
        <IconGithub class="w-6 h-6" />
      </a>
      <!-- Theme Toggle -->
      <button
        class="p-1.5 rounded-lg bg-[#f5f5f5] hover:bg-[#e7e7e8] dark:bg-[#121215] dark:hover:bg-[#2b2b2e] text-gray-500 dark:text-gray-400 transition-colors"
        :aria-label="appStore.isDark ? t('header.switch_to_light') : t('header.switch_to_dark')"
        :title="appStore.isDark ? t('header.switch_to_light') : t('header.switch_to_dark')"
        @click="toggleTheme"
      >
        <IconMoon v-if="!appStore.isDark" class="w-6 h-6" />
        <IconSun v-else class="w-6 h-6" />
      </button>
      <!-- Logout -->
      <button
        class="p-1.5 rounded-lg bg-[#f5f5f5] hover:bg-[#e7e7e8] dark:bg-[#121215] dark:hover:bg-[#2b2b2e] text-gray-500 dark:text-gray-400 transition-colors"
        :aria-label="t('header.logout')"
        :title="t('header.logout')"
        @click="handleLogout"
      >
        <IconLogout class="w-6 h-6" />
      </button>
    </div>

    <!-- Releases Modal -->
    <ReleasesModal
      v-model="showReleases"
      :current-version="currentVersion"
      :releases="releases"
      :loading="releasesLoading"
      :error="releasesError"
      @retry="openReleases"
    />
  </header>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { useRouter } from 'vue-router'
import { useTheme } from '@/composables/useTheme'
import { useI18n } from 'vue-i18n'
import { getReleases } from '@/api/auth'
import ReleasesModal from './ReleasesModal.vue'
import type { ReleaseItem } from '@/types'
import {
  IconHamburger, IconDownload, IconBook, IconGithub, IconMoon, IconSun, IconLogout,
} from '@/components/icons'

defineProps<{ title: string }>()
defineEmits<{ 'toggle-sidebar': [] }>()

const { t } = useI18n()
const appStore = useAppStore()
const authStore = useAuthStore()
const router = useRouter()
const { toggleTheme } = useTheme()

const showReleases = ref(false)
const releases = ref<ReleaseItem[]>([])
const currentVersion = ref('')
const releasesLoading = ref(false)
const releasesError = ref(false)

const hasNewVersion = computed(() => {
  const currentRelease = releases.value.find(r => r.tag_name === currentVersion.value)
  if (!currentRelease?.published_at) return false
  return releases.value.some(r =>
    !r.prerelease && r.published_at && new Date(r.published_at).getTime() > new Date(currentRelease.published_at!).getTime()
  )
})

onMounted(async () => {
  try {
    const { data } = await getReleases()
    currentVersion.value = data.current_version
    releases.value = data.releases
  } catch {
    // ignore - button stays gray
  }
})

async function openReleases() {
  showReleases.value = true
  releasesLoading.value = true
  releasesError.value = false
  try {
    const { data } = await getReleases()
    currentVersion.value = data.current_version
    releases.value = data.releases
  } catch {
    releasesError.value = true
  } finally {
    releasesLoading.value = false
  }
}

async function handleLogout() {
  try {
    await authStore.logout()
  } finally {
    router.push('/login')
  }
}
</script>
