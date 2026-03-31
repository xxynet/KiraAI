<template>
  <header class="app-header px-6 py-4 flex items-center justify-between">
    <h2 class="text-xl font-semibold text-gray-900">
      {{ title }}
    </h2>
    <div class="flex items-center gap-3">
      <!-- Theme Toggle -->
      <el-button circle :aria-label="appStore.isDark ? 'Switch to light theme' : 'Switch to dark theme'" :title="appStore.isDark ? 'Switch to light theme' : 'Switch to dark theme'" @click="toggleTheme">
        <el-icon>
          <Moon v-if="!appStore.isDark" />
          <Sunny v-else />
        </el-icon>
      </el-button>
      <!-- Logout -->
      <el-button circle aria-label="Logout" title="Logout" @click="handleLogout">
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

defineProps<{ title: string }>()

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
