<template>
  <div class="min-h-screen flex items-center justify-center">
    <div class="glass-card rounded-2xl p-8 w-full max-w-md">
      <div class="text-center mb-8">
        <h1 class="text-3xl font-bold text-gray-900 dark:text-white">{{ $t('login.title') }}</h1>
        <p class="text-gray-500 dark:text-gray-400 mt-2">{{ $t('login.subtitle') }}</p>
      </div>

      <el-form @submit.prevent="handleLogin">
        <el-form-item :label="$t('login.access_token')">
          <el-input
            v-model="accessToken"
            type="password"
            :placeholder="$t('login.placeholder')"
            show-password
            size="large"
            @keyup.enter="handleLogin"
          />
        </el-form-item>

        <el-alert
          v-if="errorMsg"
          :title="errorMsg"
          type="error"
          show-icon
          class="mb-4"
          :closable="false"
        />

        <el-button
          type="primary"
          size="large"
          class="w-full"
          :loading="loading"
          @click="handleLogin"
        >
          {{ $t('login.submit') }}
        </el-button>
      </el-form>

      <!-- Theme toggle -->
      <div class="mt-6 text-center">
        <el-button circle :aria-label="appStore.isDark ? t('header.switch_to_light') : t('header.switch_to_dark')" @click="toggleTheme">
          <el-icon>
            <Moon v-if="!appStore.isDark" />
            <Sunny v-else />
          </el-icon>
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useAppStore } from '@/stores/app'
import { Moon, Sunny } from '@element-plus/icons-vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
const router = useRouter()
const authStore = useAuthStore()
const appStore = useAppStore()

const accessToken = ref('')
const loading = ref(false)
const errorMsg = ref('')

async function handleLogin() {
  if (loading.value) return
  if (!accessToken.value.trim()) return
  loading.value = true
  errorMsg.value = ''
  try {
    await authStore.login(accessToken.value.trim())
    router.push('/overview')
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
