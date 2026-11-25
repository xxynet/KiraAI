<template>
  <Modal :model-value="open" content-class="max-w-xl self-start mt-[10vh]" @update:model-value="onVisibleChange">
    <div class="quick-nav bg-white dark:bg-[#1b1b1f] border border-gray-200 dark:border-gray-700">
      <div class="quick-nav-search border-gray-200 dark:border-gray-700">
        <IconSearch class="w-4 h-4 shrink-0 opacity-70" aria-hidden="true" />
        <input
          ref="inputRef"
          v-model="query"
          class="quick-nav-input"
          type="text"
          role="combobox"
          aria-autocomplete="list"
          aria-controls="quick-nav-results"
          :aria-expanded="results.length > 0"
          :aria-activedescendant="activeOptionId"
          :aria-label="t('quickNav.aria_label')"
          :placeholder="t('quickNav.placeholder')"
          @keydown.down.prevent="stepActive(1)"
          @keydown.up.prevent="stepActive(-1)"
          @keydown.enter.prevent="activateActive"
        />
        <kbd class="quick-nav-kbd">Esc</kbd>
      </div>

      <ul
        id="quick-nav-results"
        ref="listRef"
        class="quick-nav-results"
        role="listbox"
        :aria-label="t('quickNav.title')"
      >
        <li
          v-for="(entry, index) in results"
          :id="optionId(index)"
          :key="entry.id"
          role="option"
          class="quick-nav-item"
          :class="{ 'bg-gray-100 dark:bg-[#2b2b2e]': index === activeIndex }"
          :aria-selected="index === activeIndex"
          @mouseenter="activeIndex = index"
          @click="activate(entry)"
        >
          <InlineSvgIcon v-if="entry.iconUrl" :src="entry.iconUrl" class="w-4 h-4 shrink-0">
            <template #fallback>
              <component :is="entry.icon" class="w-4 h-4" />
            </template>
          </InlineSvgIcon>
          <component :is="entry.icon" v-else class="w-4 h-4 shrink-0 opacity-70" />
          <span class="quick-nav-label">{{ entry.label }}</span>
          <span v-if="entry.group" class="quick-nav-group">{{ entry.group }}</span>
        </li>
      </ul>

      <p v-if="results.length === 0" class="quick-nav-empty">
        {{ t('quickNav.no_results', { query: query.trim() }) }}
      </p>

      <div class="quick-nav-footer border-gray-200 dark:border-gray-700">
        <span>{{ t('quickNav.results_count', { count: results.length }) }}</span>
        <span class="quick-nav-footer-hints">
          <kbd class="quick-nav-kbd">↑</kbd>
          <kbd class="quick-nav-kbd">↓</kbd>
          <span>{{ t('quickNav.hint_navigate') }}</span>
          <kbd class="quick-nav-kbd">Enter</kbd>
          <span>{{ t('quickNav.hint_open') }}</span>
          <kbd class="quick-nav-kbd">Esc</kbd>
          <span>{{ t('quickNav.hint_close') }}</span>
        </span>
      </div>
    </div>
  </Modal>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch, type Component } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import Modal from '@/components/common/Modal.vue'
import InlineSvgIcon from '@/components/common/InlineSvgIcon.vue'
import { IconSearch } from '@/components/icons'
import { useQuickNav } from '@/composables/useQuickNav'
import { useSidebarNavigation } from '@/composables/useSidebarNavigation'
import { searchQuickNav, type QuickNavTarget } from '@/utils/quickNavSearch'

interface PaletteEntry extends QuickNavTarget {
  icon: Component
  iconUrl: string | null
}

const { t } = useI18n()
const router = useRouter()
const { quickNavOpen: open, closeQuickNav } = useQuickNav()
const { navGroups } = useSidebarNavigation()

const query = ref('')
const activeIndex = ref(0)
const inputRef = ref<HTMLInputElement | null>(null)
const listRef = ref<HTMLElement | null>(null)

/**
 * Every entry the sidebar currently shows, including entries inside collapsed
 * groups. Hidden entries stay hidden: the palette mirrors the sidebar instead of
 * becoming a second, unreachable-from-navigation source of truth.
 */
const entries = computed<PaletteEntry[]>(() => navGroups.value.flatMap(group =>
  group.items.map(item => ({
    id: item.id,
    route: item.route,
    label: item.isPlugin ? item.label : t(item.label),
    group: group.label ?? '',
    icon: item.icon,
    iconUrl: item.iconUrl,
  })),
))

const results = computed(() => searchQuickNav(entries.value, query.value))
const activeOptionId = computed(() => (
  results.value.length > 0 ? optionId(activeIndex.value) : undefined
))

function optionId(index: number): string {
  return `quick-nav-option-${index}`
}

function stepActive(delta: number) {
  const total = results.value.length
  if (total === 0) return
  activeIndex.value = (activeIndex.value + delta + total) % total
}

function activate(entry: PaletteEntry) {
  closeQuickNav()
  void router.push(entry.route)
}

function activateActive() {
  const entry = results.value[activeIndex.value]
  if (entry) activate(entry)
}

function onVisibleChange(visible: boolean) {
  if (!visible) closeQuickNav()
}

// A new query restarts the highlight at the best match.
watch(query, () => {
  activeIndex.value = 0
})

watch(open, (visible) => {
  if (!visible) return
  query.value = ''
  activeIndex.value = 0
  nextTick(() => inputRef.value?.focus())
})

// Keep the highlighted row inside the scroll view.
watch(activeIndex, () => {
  nextTick(() => {
    const id = activeOptionId.value
    if (!id) return
    listRef.value?.querySelector<HTMLElement>(`#${id}`)?.scrollIntoView({ block: 'nearest' })
  })
})
</script>

<style scoped>
.quick-nav {
  display: flex;
  flex-direction: column;
  max-height: 60vh;
  overflow: hidden;
  border-radius: 0.75rem;
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.25);
}

.quick-nav-search {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem 1rem;
  border-bottom-width: 1px;
  border-bottom-style: solid;
}

.quick-nav-input {
  flex: 1;
  min-width: 0;
  border: none;
  outline: none;
  background: transparent;
  font-size: 0.9375rem;
  color: inherit;
}

.quick-nav-input::placeholder {
  opacity: 0.55;
}

.quick-nav-results {
  flex: 1;
  min-height: 0;
  margin: 0;
  padding: 0.25rem;
  overflow-y: auto;
  list-style: none;
}

.quick-nav-item {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  padding: 0.5rem 0.75rem;
  border-radius: 0.5rem;
  color: inherit;
  cursor: pointer;
}

.quick-nav-label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.quick-nav-group {
  margin-left: auto;
  padding-left: 0.75rem;
  font-size: 0.75rem;
  white-space: nowrap;
  opacity: 0.6;
}

.quick-nav-empty {
  margin: 0;
  padding: 1.5rem 1rem;
  text-align: center;
  font-size: 0.875rem;
  opacity: 0.7;
}

.quick-nav-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.5rem 1rem;
  border-top-width: 1px;
  border-top-style: solid;
  font-size: 0.75rem;
  opacity: 0.75;
}

.quick-nav-footer-hints {
  display: flex;
  align-items: center;
  gap: 0.375rem;
}

.quick-nav-kbd {
  padding: 0 0.3rem;
  border: 1px solid rgb(209 213 219);
  border-radius: 0.375rem;
  font-family: inherit;
  font-size: 0.6875rem;
  line-height: 1.5;
}

.dark .quick-nav-kbd {
  border-color: rgb(63 63 70);
}
</style>
