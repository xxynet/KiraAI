<template>
  <div class="min-h-screen flex items-center justify-center relative">
    <!-- Light Spots (fixed to viewport) -->
    <div class="login-light-spot login-light-spot-1"></div>
    <div class="login-light-spot login-light-spot-2"></div>
    <div class="login-light-spot login-light-spot-3"></div>

    <!-- Theme Toggle Button -->
    <button
      type="button"
      class="fixed top-4 right-4 z-50 p-2 rounded-lg bg-white/70 backdrop-blur-md border border-white/30 shadow-lg hover:bg-white/90 transition-all duration-200 dark:bg-gray-800/70 dark:border-gray-700/30 dark:hover:bg-gray-800/90"
      :aria-label="appStore.isDark ? t('header.switch_to_light') : t('header.switch_to_dark')"
      @click="toggleTheme"
    >
      <IconSun v-if="appStore.isDark" class="w-6 h-6 text-yellow-500" />
      <IconMoon v-else class="w-6 h-6 text-gray-700" />
    </button>

    <!-- Login Container -->
    <div class="relative z-10 w-full max-w-md px-6">
      <!-- Login Card with Glassmorphism -->
      <div class="bg-white/70 backdrop-blur-xl rounded-2xl shadow-xl border border-white/30 p-8 dark:bg-gray-800/70 dark:border-gray-700/30">
        <!-- Logo and Title -->
        <div class="text-center mb-8">
          <div class="inline-flex items-center justify-center w-16 h-16 bg-gradient-to-br from-blue-500 to-purple-600 rounded-2xl mb-4 shadow-lg">
            <IconLightning class="w-8 h-8 text-white" />
          </div>
          <h1 class="text-3xl font-bold text-gray-900 mb-2 dark:text-white">{{ $t('login.title') }}</h1>
          <p class="text-gray-600 dark:text-gray-400">{{ $t('login.subtitle') }}</p>
        </div>

        <!-- Login Form -->
        <form @submit.prevent="handleLogin" class="space-y-6">
          <!-- Access Token Input -->
          <div>
            <label class="block text-sm font-medium text-gray-700 mb-2 dark:text-gray-300">
              {{ $t('login.access_token') }}
            </label>
            <div class="relative">
              <div class="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                <IconKey class="h-5 w-5 text-gray-400 dark:text-gray-500" />
              </div>
              <input
                v-model="accessToken"
                type="password"
                required
                autocomplete="off"
                class="block w-full pl-10 pr-3 py-3 border border-gray-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white/50 backdrop-blur-sm transition-all duration-200 dark:border-gray-600 dark:bg-gray-700/50 dark:text-white dark:placeholder-gray-400 dark:focus:ring-blue-400"
                :placeholder="$t('login.placeholder')"
              >
            </div>
            <p class="mt-2 text-xs text-gray-500 dark:text-gray-400">
              {{ $t('login.token_hint') }}
            </p>
          </div>

          <!-- Login Button -->
          <button
            type="submit"
            class="w-full flex justify-center items-center py-3 px-4 border border-transparent rounded-xl shadow-sm text-sm font-medium text-white bg-[#2563eb] hover:bg-[#1d4ed8] focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-[#2563eb] transition-all duration-200 transform hover:scale-[1.02] active:scale-[0.98] dark:bg-blue-600 dark:hover:bg-blue-700 dark:focus:ring-blue-500"
            :disabled="loading"
          >
            <span>{{ loading ? '...' : $t('login.submit') }}</span>
            <IconSpinner v-if="loading" class="animate-spin ml-2 h-5 w-5 text-white" />
          </button>
        </form>

        <!-- Error Message -->
        <div
          v-if="errorMsg"
          class="mt-4 p-4 bg-red-50 border border-red-200 rounded-xl dark:bg-red-900/20 dark:border-red-800/30"
        >
          <div class="flex items-center">
            <IconInfo class="w-5 h-5 text-red-600 mr-2 dark:text-red-400" />
            <span class="text-sm text-red-700 dark:text-red-300">{{ errorMsg }}</span>
          </div>
        </div>

        <!-- Footer -->
        <div class="mt-8 text-center">
          <p class="text-xs text-gray-500 dark:text-gray-400">
            KiraAI WebUI
          </p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useAppStore } from '@/stores/app'
import { useI18n } from 'vue-i18n'
import { IconSun, IconMoon, IconLightning, IconKey, IconSpinner, IconInfo } from '@/components/icons'

const { t } = useI18n()
const router = useRouter()
const authStore = useAuthStore()
const appStore = useAppStore()

const accessToken = ref('')
const loading = ref(false)
const errorMsg = ref('')

async function handleLogin() {
  if (loading.value) return
  const trimmedToken = accessToken.value.trim()
  if (!trimmedToken) {
    errorMsg.value = t('login.token_required')
    return
  }
  loading.value = true
  errorMsg.value = ''
  try {
    await authStore.login(trimmedToken)
    await router.push('/overview')
  } catch {
    errorMsg.value = t('login.error')
  } finally {
    loading.value = false
  }
}

function toggleTheme() {
  appStore.toggleTheme()
}
</script>

<style>
.login-light-spot {
  position: fixed;
  border-radius: 50%;
  filter: blur(80px);
  opacity: 0.6;
  animation: login-float 8s ease-in-out infinite;
  pointer-events: none;
}

.login-light-spot-1 {
  width: 300px;
  height: 300px;
  background: radial-gradient(circle, rgba(59, 130, 246, 0.4) 0%, transparent 70%);
  top: 10%;
  left: 10%;
  animation-delay: 0s;
}

.login-light-spot-2 {
  width: 250px;
  height: 250px;
  background: radial-gradient(circle, rgba(147, 197, 253, 0.4) 0%, transparent 70%);
  top: 60%;
  right: 15%;
  animation-delay: 2s;
}

.login-light-spot-3 {
  width: 200px;
  height: 200px;
  background: radial-gradient(circle, rgba(167, 139, 250, 0.4) 0%, transparent 70%);
  bottom: 15%;
  left: 25%;
  animation-delay: 4s;
}

@keyframes login-float {
  0%, 100% {
    transform: translateY(0) scale(1);
  }
  50% {
    transform: translateY(-20px) scale(1.05);
  }
}

.dark .login-light-spot {
  opacity: 0.3;
}

.dark .login-light-spot-1 {
  background: radial-gradient(circle, rgba(59, 130, 246, 0.3) 0%, transparent 70%);
}

.dark .login-light-spot-2 {
  background: radial-gradient(circle, rgba(99, 102, 241, 0.3) 0%, transparent 70%);
}

.dark .login-light-spot-3 {
  background: radial-gradient(circle, rgba(139, 92, 246, 0.3) 0%, transparent 70%);
}
</style>
