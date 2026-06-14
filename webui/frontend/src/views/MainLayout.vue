<template>
  <div class="flex h-screen">
    <div class="page-background"></div>
    <div
      class="sidebar-overlay"
      :class="{ open: sidebarOpen }"
      @click="closeSidebar"
    ></div>
    <AppSidebar :open="sidebarOpen" />
    <div class="flex-1 flex flex-col overflow-hidden">
      <main class="flex-1 flex flex-col" :class="route.meta.pluginPage ? 'overflow-hidden' : 'overflow-auto'">
        <AppHeader
          :title="pageTitle"
          @toggle-sidebar="toggleSidebar"
        />
        <PageContainer :class="{ 'flex-1 min-h-0 !p-0': route.meta.pluginPage }">
          <router-view v-slot="{ Component, route: r }">
            <transition name="page-fade">
              <component :is="Component" :key="r.fullPath" />
            </transition>
          </router-view>
        </PageContainer>
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { usePluginMenuStore } from '@/stores/pluginMenu'
import AppSidebar from '@/components/layout/AppSidebar.vue'
import AppHeader from '@/components/layout/AppHeader.vue'
import PageContainer from '@/components/layout/PageContainer.vue'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const pluginMenuStore = usePluginMenuStore()

const sidebarOpen = ref(false)

function toggleSidebar() {
  sidebarOpen.value = !sidebarOpen.value
}

function closeSidebar() {
  sidebarOpen.value = false
}

// Auto-close sidebar on navigation for mobile
watch(() => route.path, () => {
  if (window.innerWidth <= 768) {
    sidebarOpen.value = false
  }
})

const pageTitle = computed(() => {
  // Plugin pages: look up label from store (reactively updates when menus load)
  if (route.meta.pluginPage) {
    const pluginId = route.params.pluginId as string
    const pageRoute = route.params.pageRoute as string
    const menu = pluginMenuStore.menus.find(m => m.pluginId === pluginId && m.pageRoute === pageRoute)
    if (menu) return menu.label
    return route.meta.title as string || 'Plugin Page'
  }
  const name = route.name as string | undefined
  if (!name) return ''
  const key = `pages.${name.toLowerCase()}.title`
  return t(key)
})
</script>
