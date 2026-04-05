<template>
  <header class="app-header px-6 py-4 flex items-center justify-between">
    <h2 class="text-xl font-semibold text-gray-900">
      {{ title }}
    </h2>
    <div class="flex items-center gap-3">
      <!-- Theme Toggle -->
      <el-button circle :aria-label="appStore.isDark ? t('header.switch_to_light') : t('header.switch_to_dark')" :title="appStore.isDark ? t('header.switch_to_light') : t('header.switch_to_dark')" @click="toggleTheme">
        <el-icon>
          <Moon v-if="!appStore.isDark" />
          <Sunny v-else />
        </el-icon>
      </el-button>
      <!-- Logout -->
      <el-button circle :aria-label="t('header.logout')" :title="t('header.logout')" @click="handleLogout">
        <el-icon><SwitchButton /></el-icon>
      </el-button>
    </div>
  </header>
</template>

<script setup lang="ts">
import { Moon, Sunny, SwitchButton } from '@element-plus/icons-vue'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { useRouter } from 'vue-router'
import { useTheme } from '@/composables/useTheme'
import { useI18n } from 'vue-i18n'

defineProps<{ title: string }>()

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
