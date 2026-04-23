<template>
  <div class="flex h-screen">
    <div class="page-background"></div>
    <AppSidebar />
    <div class="flex-1 flex flex-col overflow-hidden">
      <AppHeader :title="pageTitle" />
      <main class="flex-1 overflow-auto">
        <PageContainer>
          <router-view v-slot="{ Component, route: r }">
            <transition name="page-fade" mode="out-in">
              <component :is="Component" :key="r.fullPath" />
            </transition>
          </router-view>
        </PageContainer>
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AppSidebar from '@/components/layout/AppSidebar.vue'
import AppHeader from '@/components/layout/AppHeader.vue'
import PageContainer from '@/components/layout/PageContainer.vue'

const route = useRoute()
const { t } = useI18n()

const pageTitle = computed(() => {
  const name = route.name as string | undefined
  if (!name) return ''
  const key = `pages.${name.toLowerCase()}.title`
  return t(key)
})
</script>
