<template>
  <div class="collapsible-section">
    <div
      class="collapsible-section-header flex items-center justify-between px-4 py-3 cursor-pointer rounded-t-lg select-none transition-colors duration-150 bg-gray-50 dark:bg-gray-800 hover:bg-gray-100 dark:hover:bg-gray-700 active:bg-gray-200 dark:active:bg-gray-600 border border-gray-200 dark:border-gray-700"
      :class="{ 'rounded-b-lg': isCollapsed }"
      role="button"
      tabindex="0"
      :aria-expanded="!isCollapsed"
      @click="toggle"
      @keydown.enter.prevent="toggle"
      @keydown.space.prevent="toggle"
    >
      <div class="flex items-center space-x-3 min-w-0">
        <slot name="icon" />
        <div class="min-w-0">
          <h4 class="text-sm font-semibold text-gray-800 dark:text-gray-100">
            {{ title }}
          </h4>
          <p v-if="description" class="text-xs text-gray-500 dark:text-gray-400 truncate">
            {{ description }}
          </p>
        </div>
      </div>
      <IconChevronDown
        class="w-5 h-5 text-gray-400 dark:text-gray-500 transform transition-transform duration-200 shrink-0 ml-2"
        :class="{ 'rotate-180': !isCollapsed }"
      />
    </div>
    <div
      class="collapsible-section-body border border-t-0 border-gray-200 dark:border-gray-700 rounded-b-lg bg-white dark:bg-gray-900 overflow-hidden transition-all duration-200"
      :class="{ 'max-h-0 opacity-0 py-0 border-0': isCollapsed, 'max-h-[2000px] opacity-100': !isCollapsed }"
    >
      <div class="p-4">
        <slot />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { IconChevronDown } from '@/components/icons'

const props = withDefaults(defineProps<{
  title: string
  description?: string
  collapsed?: boolean
}>(), {
  collapsed: false,
})

const emit = defineEmits<{
  'update:collapsed': [value: boolean]
}>()

const isCollapsed = computed({
  get: () => props.collapsed,
  set: (v) => emit('update:collapsed', v),
})

function toggle() {
  isCollapsed.value = !isCollapsed.value
}
</script>
