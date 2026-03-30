<template>
  <div class="page-background"></div>
  <router-view />
</template>

<script setup lang="ts">
import { useAppStore } from '@/stores/app'

// Initialize theme on app load
const appStore = useAppStore()
appStore.setTheme(appStore.theme)
</script>
