<template>
  <aside
    class="sidebar-gradient min-h-screen flex flex-col text-theme-strong"
    :class="{ 'sidebar-open': open, 'sidebar-collapsed': !open }"
    :inert="!open"
    :aria-hidden="!open"
  >
    <!-- Logo -->
    <div class="p-6 border-b border-blue-200/30">
      <h1 class="text-2xl font-bold text-theme-strong">{{ $t('app.title') }}</h1>
      <p id="app-version" class="text-sm text-theme-supporting mt-1">{{ appVersion }}</p>
    </div>

    <!-- Navigation -->
    <nav class="flex-1 p-4 space-y-2 overflow-y-auto">
      <div v-for="group in navGroups" :key="group.id" class="space-y-2" :class="{ 'pt-4': group.label && isSectionGroupStyle }">
        <button
          v-if="group.label"
          :id="`sidebar-group-${group.id}`"
          type="button"
          class="flex items-center justify-between gap-2 w-full px-4 rounded-lg text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500"
          :class="{
            'sidebar-group-toggle--section py-2 text-xs font-semibold text-theme-subtle text-theme-subtle-hover': isSectionGroupStyle,
            'nav-item py-3': !isSectionGroupStyle,
            active: !isSectionGroupStyle && group.items.some(item => isActive(item.route)),
          }"
          :aria-expanded="expandedGroups.has(group.id)"
          :aria-controls="`sidebar-group-items-${group.id}`"
          @click="toggleGroup(group.id)"
        >
          <span class="flex items-center gap-3 min-w-0">
            <component v-if="!isSectionGroupStyle" :is="group.icon" class="w-5 h-5 shrink-0" aria-hidden="true" />
            <span class="break-words min-w-0">{{ group.label }}</span>
          </span>
          <ArrowDown
            class="shrink-0 transition-transform"
            :class="[
              isSectionGroupStyle ? 'w-3.5 h-3.5' : 'w-4 h-4',
              { '-rotate-90': !expandedGroups.has(group.id) },
            ]"
            aria-hidden="true"
          />
        </button>
        <div
          v-show="!group.label || expandedGroups.has(group.id)"
          :id="`sidebar-group-items-${group.id}`"
          class="space-y-2"
          :class="{ 'ml-4 pl-4 border-l border-blue-200/30': group.label && !isSectionGroupStyle }"
          :role="group.label ? 'group' : undefined"
          :aria-labelledby="group.label ? `sidebar-group-${group.id}` : undefined"
        >
          <router-link
            v-for="item in group.items"
            :key="item.route"
            :to="item.route"
            class="nav-item flex items-center justify-between gap-2 px-4 py-3 rounded-lg transition-colors"
            :class="{ active: isActive(item.route) }"
          >
            <div class="flex items-center gap-3 min-w-0">
              <!--
                Plugin icons referenced by URL are rendered inline (sanitized) so
                stroke="currentColor" follows the nav text color across themes.
              -->
              <InlineSvgIcon v-if="item.iconUrl" :src="item.iconUrl" class="w-5 h-5 shrink-0">
                <template #fallback>
                  <component :is="item.icon" class="w-5 h-5" />
                </template>
              </InlineSvgIcon>
              <component :is="item.icon" v-else class="w-5 h-5 shrink-0" />
              <span class="break-words min-w-0">{{ item.isPlugin ? item.label : $t(item.label) }}</span>
            </div>
            <span class="nav-dot shrink-0"></span>
          </router-link>
        </div>
      </div>
    </nav>

    <!-- Language Selector -->
    <div class="p-4 border-t border-blue-200/30">
      <CustomSelect
        v-model="currentLanguage"
        :options="languageOptions"
        :placeholder="$t('app.select_language')"
        class="w-full"
      />
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed, ref, watch, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAppStore } from '@/stores/app'
import { useSidebarStore } from '@/stores/sidebar'
import { usePluginMenuStore } from '@/stores/pluginMenu'
import { getVersion } from '@/api/overview'
import CustomSelect from '@/components/common/CustomSelect.vue'
import InlineSvgIcon from '@/components/common/InlineSvgIcon.vue'
import { ArrowDown } from '@element-plus/icons-vue'
import { useSidebarNavigation } from '@/composables/useSidebarNavigation'

defineProps<{ open: boolean }>()

const appVersion = ref('-')
const route = useRoute()
const appStore = useAppStore()
const sidebarStore = useSidebarStore()
const isSectionGroupStyle = computed(() => appStore.sidebarGroupStyle === 'section')
const pluginMenuStore = usePluginMenuStore()
const { navGroups } = useSidebarNavigation()
const { locale } = useI18n()

// Re-resolve plugin page labels when UI language changes
watch(locale, (newLocale) => {
  pluginMenuStore.reResolveLabels(newLocale)
})

onMounted(async () => {
  try {
    const response = await getVersion()
    appVersion.value = response.data.version
  } catch (error) {
    console.error('Error loading version:', error)
  }
  pluginMenuStore.fetchAndRegisterMenus()
})

const currentLanguage = computed({
  get: () => appStore.language,
  set: (val: string) => appStore.setLanguage(val),
})

const languageOptions = [
  { value: 'en', label: 'English' },
  { value: 'zh', label: '中文' },
]

const expandedGroups = computed(() => sidebarStore.expandedGroups)
let revealCurrentPage = !sidebarStore.hasSavedOpenedItems

function toggleGroup(id: string) {
  sidebarStore.setGroupExpanded(id, !expandedGroups.value.has(id))
}

// Restore saved state on refresh, including when plugin menus arrive later.
// After navigation, reveal the active page as before.
watch(
  [
    () => route.path,
    () => navGroups.value.find(group => group.label && group.items.some(item => isActive(item.route)))?.id,
  ],
  ([path, activeGroupId], [previousPath]) => {
    if (previousPath !== undefined && path !== previousPath) revealCurrentPage = true
    if (activeGroupId && revealCurrentPage) {
      sidebarStore.setGroupExpanded(activeGroupId, true)
      revealCurrentPage = false
    }
  },
  { immediate: true },
)

function isActive(path: string): boolean {
  // Normalize trailing slashes so refresh (which Vue Router may canonicalise
  // with a trailing slash) matches the nav item path written without one.
  const norm = (p: string) => (p.length > 1 && p.endsWith('/') ? p.slice(0, -1) : p)
  return norm(route.path) === norm(path)
}
</script>

<style scoped>
.sidebar-gradient {
  width: 16rem;
  overflow: hidden;
  transition: width 0.25s ease;
}

.dark .sidebar-group-toggle--section {
  color: var(--color-text-subtle-hover);
}

.dark .sidebar-group-toggle--section:hover {
  color: var(--color-text-subtle);
}

@media (min-width: 1025px) {
  .sidebar-gradient.sidebar-collapsed {
    width: 0;
    border-right-width: 0;
  }
}

@media (max-width: 1024px) {
  .sidebar-gradient {
    position: fixed;
    top: 0;
    left: 0;
    height: 100%;
    z-index: 50;
    transform: translateX(-100%);
    transition: transform 0.25s ease;
  }

  .sidebar-gradient.sidebar-open {
    transform: translateX(0);
  }
}
</style>
