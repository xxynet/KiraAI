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
    <div class="header-actions flex items-center gap-2">
      <!-- Update -->
      <button
        type="button"
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
        type="button"
        class="p-1.5 rounded-lg bg-[#f5f5f5] hover:bg-[#e7e7e8] disabled:cursor-wait disabled:opacity-60 dark:bg-[#121215] dark:hover:bg-[#2b2b2e] text-gray-500 dark:text-gray-400 transition-colors"
        :aria-label="appStore.isDark ? t('header.switch_to_light') : t('header.switch_to_dark')"
        :title="appStore.isDark ? t('header.switch_to_light') : t('header.switch_to_dark')"
        :disabled="appStore.isThemeTransitioning"
        @click="handleThemeToggle"
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

    <div ref="mobileMenu" class="mobile-header-menu relative" @focusout="handleMobileMenuFocusOut" @keydown.esc.prevent.stop="closeMobileMenu(true)">
      <button
        ref="mobileMenuTrigger"
        type="button"
        class="p-1.5 rounded-lg bg-[#f5f5f5] hover:bg-[#e7e7e8] dark:bg-[#121215] dark:hover:bg-[#2b2b2e] text-gray-500 dark:text-gray-400 transition-colors"
        :aria-label="t('header.more_actions')"
        :title="t('header.more_actions')"
        :aria-expanded="mobileMenuOpen"
        aria-controls="mobile-header-menu-panel"
        @click="toggleMobileMenu"
      >
        <IconMoreVertical class="w-6 h-6" />
      </button>
      <Transition name="mobile-header-menu">
        <div
          v-if="mobileMenuOpen"
          id="mobile-header-menu-panel"
          class="mobile-header-menu-panel absolute right-0 top-full mt-2 min-w-48 rounded-xl border border-gray-200 bg-white/95 p-1.5 text-gray-600 shadow-lg dark:border-gray-700 dark:bg-[#1b1b1f]/95 dark:text-gray-300"
        >
          <button type="button" class="mobile-header-menu-item hover:bg-gray-100 active:bg-gray-200 focus-visible:bg-gray-100 dark:hover:bg-[#2b2b2e] dark:active:bg-[#3a3a3e] dark:focus-visible:bg-[#2b2b2e]" @click="openReleases">
            <IconDownload class="w-5 h-5" :class="hasNewVersion ? 'text-blue-500 dark:text-blue-400' : ''" />
            <span>{{ t('header.releases') }}</span>
          </button>
          <a
            :href="t('header.docs_url')"
            target="_blank"
            rel="noopener noreferrer"
            class="mobile-header-menu-item hover:bg-gray-100 active:bg-gray-200 focus-visible:bg-gray-100 dark:hover:bg-[#2b2b2e] dark:active:bg-[#3a3a3e] dark:focus-visible:bg-[#2b2b2e]"
            @click="() => closeMobileMenu()"
          >
            <IconBook class="w-5 h-5" />
            <span>{{ t('header.docs') }}</span>
          </a>
          <a
            href="https://github.com/xxynet/KiraAI"
            target="_blank"
            rel="noopener noreferrer"
            class="mobile-header-menu-item hover:bg-gray-100 active:bg-gray-200 focus-visible:bg-gray-100 dark:hover:bg-[#2b2b2e] dark:active:bg-[#3a3a3e] dark:focus-visible:bg-[#2b2b2e]"
            @click="() => closeMobileMenu()"
          >
            <IconGithub class="w-5 h-5" />
            <span>GitHub</span>
          </a>
          <button type="button" class="mobile-header-menu-item hover:bg-gray-100 active:bg-gray-200 focus-visible:bg-gray-100 disabled:cursor-wait disabled:opacity-60 dark:hover:bg-[#2b2b2e] dark:active:bg-[#3a3a3e] dark:focus-visible:bg-[#2b2b2e]" :disabled="appStore.isThemeTransitioning" @click="handleThemeToggle">
            <IconMoon v-if="!appStore.isDark" class="w-5 h-5" />
            <IconSun v-else class="w-5 h-5" />
            <span>{{ appStore.isDark ? t('header.switch_to_light') : t('header.switch_to_dark') }}</span>
          </button>
          <button type="button" class="mobile-header-menu-item hover:bg-gray-100 active:bg-gray-200 focus-visible:bg-gray-100 dark:hover:bg-[#2b2b2e] dark:active:bg-[#3a3a3e] dark:focus-visible:bg-[#2b2b2e]" @click="handleLogout">
            <IconLogout class="w-5 h-5" />
            <span>{{ t('header.logout') }}</span>
          </button>
        </div>
      </Transition>
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
import { ref, computed, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { useRouter } from 'vue-router'
import { useTheme } from '@/composables/useTheme'
import { useI18n } from 'vue-i18n'
import { getReleases } from '@/api/auth'
import ReleasesModal from './ReleasesModal.vue'
import type { ReleaseItem } from '@/types'
import {
  IconHamburger, IconMoreVertical, IconDownload, IconBook, IconGithub, IconMoon, IconSun, IconLogout,
} from '@/components/icons'

defineProps<{ title: string }>()
defineEmits<{ 'toggle-sidebar': [] }>()

const { t } = useI18n()
const appStore = useAppStore()
const authStore = useAuthStore()
const router = useRouter()
const { toggleTheme } = useTheme()

const mobileMenu = ref<HTMLElement | null>(null)
const mobileMenuTrigger = ref<HTMLButtonElement | null>(null)
const mobileMenuOpen = ref(false)
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
  document.addEventListener('pointerdown', closeMobileMenuOnOutsideClick)
  try {
    const { data } = await getReleases()
    currentVersion.value = data.current_version
    releases.value = data.releases
  } catch {
    // ignore - button stays gray
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', closeMobileMenuOnOutsideClick)
})

function closeMobileMenuOnOutsideClick(event: PointerEvent) {
  if (!mobileMenu.value?.contains(event.target as Node)) {
    closeMobileMenu()
  }
}

function toggleMobileMenu() {
  if (mobileMenuOpen.value) {
    closeMobileMenu()
  } else {
    mobileMenuOpen.value = true
  }
}

function closeMobileMenu(restoreFocus = false) {
  mobileMenuOpen.value = false
  if (restoreFocus) {
    nextTick(() => mobileMenuTrigger.value?.focus())
  }
}

function handleMobileMenuFocusOut(event: FocusEvent) {
  if (!event.relatedTarget || !mobileMenu.value?.contains(event.relatedTarget as Node)) {
    closeMobileMenu()
  }
}

async function openReleases() {
  closeMobileMenu()
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

async function handleThemeToggle() {
  closeMobileMenu()
  await toggleTheme()
}

async function handleLogout() {
  closeMobileMenu()
  try {
    await authStore.logout()
  } finally {
    router.push('/login')
  }
}
</script>

<style scoped>
.mobile-header-menu {
  display: none;
}

.mobile-header-menu-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  width: 100%;
  padding: 0.625rem 0.75rem;
  border-radius: 0.625rem;
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition: background-color 0.15s ease, transform 0.15s ease;
}

.mobile-header-menu-item:active {
  transform: scale(0.98);
}

.mobile-header-menu-enter-active,
.mobile-header-menu-leave-active {
  transform-origin: top right;
  transition: opacity 0.16s ease, transform 0.16s ease;
}

.mobile-header-menu-enter-from,
.mobile-header-menu-leave-to {
  opacity: 0;
  transform: translateY(-0.5rem) scale(0.96);
}

@media (max-width: 768px) {
  .header-actions {
    display: none;
  }

  .mobile-header-menu {
    display: block;
  }
}
</style>
