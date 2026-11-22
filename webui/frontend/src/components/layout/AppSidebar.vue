<template>
  <aside
    class="sidebar-gradient h-[100dvh] shrink-0 flex flex-col text-theme-strong"
    :class="{ 'sidebar-open': open, 'sidebar-collapsed': collapsed, 'sidebar-hidden': hidden }"
    :inert="hidden"
    :aria-hidden="hidden"
  >
    <!-- Logo -->
    <div v-if="!collapsed" class="p-6 shrink-0 border-b border-blue-200/30">
      <h1 class="text-2xl font-bold text-theme-strong">{{ $t('app.title') }}</h1>
      <p id="app-version" class="text-sm text-theme-supporting mt-1">{{ appVersion }}</p>
    </div>

    <!-- Navigation -->
    <nav class="flex-1 min-h-0 space-y-2 overflow-y-auto" :class="collapsed ? 'sidebar-nav--collapsed p-2' : 'p-4'">
      <div v-for="group in navGroups" :key="group.id" class="space-y-2" :class="{ 'pt-4': !collapsed && group.label && isSectionGroupStyle, 'border-t border-blue-200/30 pt-2': collapsed && group.label }">
        <button
          v-if="group.label && !collapsed"
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
          v-show="collapsed || !group.label || expandedGroups.has(group.id)"
          :id="`sidebar-group-items-${group.id}`"
          class="space-y-2"
          :class="{ 'ml-4 pl-4 border-l border-blue-200/30': !collapsed && group.label && !isSectionGroupStyle }"
          :role="group.label ? 'group' : undefined"
          :aria-labelledby="group.label && !collapsed ? `sidebar-group-${group.id}` : undefined"
          :aria-label="collapsed ? group.label : undefined"
        >
          <router-link
            v-for="item in group.items"
            :key="item.route"
            :to="item.route"
            class="nav-item flex items-center py-3 rounded-lg transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500 focus-visible:outline-offset-2"
            :class="[collapsed ? 'justify-center px-2' : 'justify-between gap-2 px-4', { active: isActive(item.route) }]"
            :aria-label="item.isPlugin ? item.label : $t(item.label)"
            :title="collapsed ? (item.isPlugin ? item.label : $t(item.label)) : undefined"
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
              <span v-if="!collapsed" class="break-words min-w-0">{{ item.isPlugin ? item.label : $t(item.label) }}</span>
            </div>
            <span v-if="!collapsed" class="nav-dot shrink-0"></span>
          </router-link>
        </div>
      </div>
    </nav>

    <!-- Language Selector -->
    <div v-if="!collapsed" class="p-4 shrink-0 border-t border-blue-200/30">
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

const props = defineProps<{ open: boolean; mobile: boolean }>()

const appVersion = ref('-')
const route = useRoute()
const appStore = useAppStore()
const collapsed = computed(() => !props.open && !props.mobile && appStore.sidebarCollapsedIcons)
const hidden = computed(() => !props.open && !collapsed.value)
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

.sidebar-nav--collapsed {
  scrollbar-width: none;
}

.sidebar-nav--collapsed::-webkit-scrollbar {
  display: none;
}

.dark .sidebar-group-toggle--section {
  color: var(--color-text-subtle-hover);
}

.dark .sidebar-group-toggle--section:hover {
  color: var(--color-text-subtle);
}

@media (min-width: 1025px) {
  .sidebar-gradient.sidebar-collapsed {
    width: 4.5rem;
  }

  .sidebar-gradient.sidebar-hidden {
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
