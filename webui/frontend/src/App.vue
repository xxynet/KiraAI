<template>
  <div class="page-background"></div>
  <router-view />
  <NotificationContainer />
</template>

<script setup lang="ts">
import { useAppStore } from '@/stores/app'
import NotificationContainer from '@/components/common/NotificationContainer.vue'

// Initialize theme on app load
const appStore = useAppStore()
appStore.setTheme(appStore.theme)
</script>
