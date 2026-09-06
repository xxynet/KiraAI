<template>
  <div class="min-h-screen flex items-center justify-center relative p-4">
    <div class="token-setup-light-spot token-setup-light-spot-1"></div>
    <div class="token-setup-light-spot token-setup-light-spot-2"></div>
    <div class="token-setup-light-spot token-setup-light-spot-3"></div>

    <button type="button" class="fixed top-4 right-4 z-50 p-2 rounded-lg bg-white/70 backdrop-blur-md border border-white/30 shadow-lg hover:bg-white/90 transition-all duration-200 dark:bg-gray-800/70 dark:border-gray-700/30 dark:hover:bg-gray-800/90" :aria-label="appStore.isDark ? t('header.switch_to_light') : t('header.switch_to_dark')" @click="appStore.toggleTheme">
      <IconSun v-if="appStore.isDark" class="w-6 h-6 text-yellow-500" />
      <IconMoon v-else class="w-6 h-6 text-theme-body" />
    </button>

    <div class="relative z-10 w-full max-w-md">
      <div class="bg-white/70 backdrop-blur-xl rounded-2xl shadow-xl border border-white/30 p-8 dark:bg-gray-800/70 dark:border-gray-700/30">
        <div class="text-center mb-8">
          <div class="inline-flex items-center justify-center w-16 h-16 bg-gradient-to-br from-blue-500 to-purple-600 rounded-2xl mb-4 shadow-lg">
            <IconKey class="w-8 h-8 text-white" />
          </div>
          <h1 class="text-3xl font-bold text-theme-high mb-2">{{ t('tokenSetup.title') }}</h1>
          <p class="text-theme-supporting">{{ t('tokenSetup.description') }}</p>
        </div>

        <form class="space-y-6" @submit.prevent="handleSave">
          <div>
            <label class="block text-sm font-medium text-theme-body mb-2" for="new-token">{{ t('tokenSetup.new_token') }}</label>
            <div class="relative">
              <div class="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                <IconKey class="h-5 w-5 text-theme-faint" />
              </div>
              <UiInput
                id="new-token"
                v-model="newToken"
                :type="showNewToken ? 'text' : 'password'"
                autocomplete="off"
                class="block w-full pl-10 pr-10 py-3 rounded-xl transition-all duration-200"
                :placeholder="t('tokenSetup.new_token_placeholder')"
              />
              <button type="button" class="absolute inset-y-0 right-0 pr-3 flex items-center text-theme-faint hover:text-theme-body transition-colors" :aria-label="showNewToken ? t('tokenSetup.hide_token') : t('tokenSetup.show_token')" @click="showNewToken = !showNewToken">
                <IconEyeOff v-if="showNewToken" class="h-5 w-5" />
                <IconEye v-else class="h-5 w-5" />
              </button>
            </div>
          </div>
          <div>
            <label class="block text-sm font-medium text-theme-body mb-2" for="confirm-token">{{ t('tokenSetup.confirm_token') }}</label>
            <div class="relative">
              <div class="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                <IconKey class="h-5 w-5 text-theme-faint" />
              </div>
              <UiInput
                id="confirm-token"
                v-model="confirmToken"
                :type="showConfirmToken ? 'text' : 'password'"
                autocomplete="off"
                class="block w-full pl-10 pr-10 py-3 rounded-xl transition-all duration-200"
                :placeholder="t('tokenSetup.confirm_token_placeholder')"
              />
              <button type="button" class="absolute inset-y-0 right-0 pr-3 flex items-center text-theme-faint hover:text-theme-body transition-colors" :aria-label="showConfirmToken ? t('tokenSetup.hide_token') : t('tokenSetup.show_token')" @click="showConfirmToken = !showConfirmToken">
                <IconEyeOff v-if="showConfirmToken" class="h-5 w-5" />
                <IconEye v-else class="h-5 w-5" />
              </button>
            </div>
            <p class="mt-2 text-xs text-theme-subtle">{{ t('tokenSetup.hint') }}</p>
          </div>

          <button type="submit" class="w-full flex justify-center items-center py-3 px-4 border border-transparent rounded-xl shadow-sm text-sm font-medium text-white bg-[#2563eb] hover:bg-[#1d4ed8] focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-[#2563eb] transition-all duration-200 active:scale-[0.98] disabled:opacity-50 dark:bg-blue-600 dark:hover:bg-blue-700 dark:focus:ring-blue-500" :disabled="loading">
            <span>{{ loading ? t('tokenSetup.saving') : t('tokenSetup.save') }}</span>
            <IconSpinner v-if="loading" class="animate-spin ml-2 h-5 w-5 text-white" />
          </button>
          <button type="button" class="w-full flex justify-center py-3 px-4 border border-gray-300 rounded-xl text-sm font-medium text-theme-body hover:bg-gray-50 transition-colors disabled:opacity-50 dark:border-gray-600 dark:hover:bg-gray-700" :disabled="loading" @click="handleSkip">
            {{ t('tokenSetup.skip') }}
          </button>
        </form>

        <div v-if="errorMessage" class="mt-4 p-4 bg-red-50 border border-red-200 rounded-xl dark:bg-red-900/20 dark:border-red-800/30">
          <div class="flex items-center"><IconInfo class="w-5 h-5 text-red-600 mr-2 dark:text-red-400" /><span class="text-sm text-red-700 dark:text-red-300">{{ errorMessage }}</span></div>
        </div>
        <div class="mt-8 text-center"><p class="text-xs text-theme-subtle">KiraAI WebUI</p></div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import axios from 'axios'
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { markTokenSetupDone } from '@/router'
import { useI18n } from 'vue-i18n'
import { setupOnboardingToken } from '@/api/onboarding'
import UiInput from '@/components/ui/UiInput.vue'
import { IconEye, IconEyeOff, IconInfo, IconKey, IconMoon, IconSpinner, IconSun } from '@/components/icons'
import { useAppStore } from '@/stores/app'

const { t } = useI18n()
const router = useRouter()
const appStore = useAppStore()

const newToken = ref('')
const confirmToken = ref('')
const showNewToken = ref(false)
const showConfirmToken = ref(false)
const loading = ref(false)
const errorMessage = ref('')

function finishSetup() {
  markTokenSetupDone()
  router.push('/onboarding')
}

async function handleSave() {
  if (loading.value) return
  const token = newToken.value.trim()
  if (!token) {
    errorMessage.value = t('tokenSetup.token_required')
    return
  }
  if (token.length < 6) {
    errorMessage.value = t('tokenSetup.token_too_short')
    return
  }
  if (token !== confirmToken.value.trim()) {
    errorMessage.value = t('tokenSetup.token_mismatch')
    return
  }
  loading.value = true
  errorMessage.value = ''
  try {
    const { data } = await setupOnboardingToken({ token })
    // Rotating the access token invalidates the current session JWT (tv
    // fingerprint); the backend re-mints one against the new token.
    if (data.access_token) {
      localStorage.setItem('jwt_token', data.access_token)
    }
    finishSetup()
  } catch (error: unknown) {
    handleSetupError(error)
  } finally {
    loading.value = false
  }
}

async function handleSkip() {
  if (loading.value) return
  loading.value = true
  errorMessage.value = ''
  try {
    await setupOnboardingToken({ token: null })
    finishSetup()
  } catch (error: unknown) {
    handleSetupError(error)
  } finally {
    loading.value = false
  }
}

function handleSetupError(error: unknown) {
  const detail = axios.isAxiosError(error) ? error.response?.data?.detail : null
  if (typeof detail === 'string' && detail.includes('already completed')) {
    // Setup or onboarding finished elsewhere (e.g. another tab) while this
    // page's guard cache was stale — sync the cache and let the router
    // resolve onward instead of stranding the user on an error.
    markTokenSetupDone()
    router.push('/onboarding')
    return
  }
  errorMessage.value = typeof detail === 'string' && detail.includes('reserved')
    ? t('tokenSetup.token_reserved')
    : t('tokenSetup.save_error')
}
</script>

<style>
.token-setup-light-spot { position: fixed; border-radius: 50%; filter: blur(80px); opacity: 0.6; animation: token-setup-float 8s ease-in-out infinite; pointer-events: none; }
.token-setup-light-spot-1 { width: 300px; height: 300px; background: radial-gradient(circle, rgb(59 130 246 / .4) 0%, transparent 70%); top: 10%; left: 10%; }
.token-setup-light-spot-2 { width: 250px; height: 250px; background: radial-gradient(circle, rgb(147 197 253 / .4) 0%, transparent 70%); top: 60%; right: 15%; animation-delay: 2s; }
.token-setup-light-spot-3 { width: 200px; height: 200px; background: radial-gradient(circle, rgb(167 139 250 / .4) 0%, transparent 70%); bottom: 15%; left: 25%; animation-delay: 4s; }
@keyframes token-setup-float { 0%, 100% { transform: translateY(0) scale(1); } 50% { transform: translateY(-20px) scale(1.05); } }
.dark .token-setup-light-spot { opacity: 0.3; }
.dark .token-setup-light-spot-1 { background: radial-gradient(circle, rgb(59 130 246 / .3) 0%, transparent 70%); }
.dark .token-setup-light-spot-2 { background: radial-gradient(circle, rgb(99 102 241 / .3) 0%, transparent 70%); }
.dark .token-setup-light-spot-3 { background: radial-gradient(circle, rgb(139 92 246 / .3) 0%, transparent 70%); }
</style>
