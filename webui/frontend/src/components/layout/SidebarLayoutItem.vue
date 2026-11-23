<template>
  <div
    :data-sidebar-item-id="item.id"
    class="flex flex-wrap items-center gap-2 p-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900"
    :class="{ 'opacity-60': hidden }"
  >
    <button
      type="button" data-sidebar-drag-handle class="layout-action cursor-grab active:cursor-grabbing touch-none select-none"
      :aria-label="$t('settings.sidebar_layout_drag', { name: label })"
      @pointerdown="$emit('drag', $event)"
    ><Rank class="w-4 h-4" /></button>
    <InlineSvgIcon v-if="item.iconUrl" :src="item.iconUrl" class="w-5 h-5 shrink-0 text-theme-body">
      <template #fallback><component :is="item.icon" class="w-5 h-5" /></template>
    </InlineSvgIcon>
    <component v-else :is="item.icon" class="w-5 h-5 shrink-0 text-theme-body" />
    <span class="flex-1 min-w-20 break-words text-sm text-theme-body">{{ label }}</span>
    <span v-if="hidden" class="text-xs text-theme-subtle">{{ $t('settings.sidebar_layout_hidden') }}</span>
    <div class="flex shrink-0 gap-1">
      <button
        type="button" class="layout-action" :aria-pressed="hidden"
        :aria-label="$t(hidden ? 'settings.sidebar_layout_show' : 'settings.sidebar_layout_hide', { name: label })"
        :title="$t(hidden ? 'settings.sidebar_layout_show' : 'settings.sidebar_layout_hide', { name: label })"
        @click="$emit('visibility')"
      ><component :is="hidden ? Hide : View" class="w-4 h-4" /></button>
      <button type="button" class="layout-action" :disabled="!canMoveUp" :aria-label="$t('settings.sidebar_layout_move_up', { name: label })" @click="$emit('move', -1)">
        <ArrowUp class="w-4 h-4" />
      </button>
      <button type="button" class="layout-action" :disabled="!canMoveDown" :aria-label="$t('settings.sidebar_layout_move_down', { name: label })" @click="$emit('move', 1)">
        <ArrowDown class="w-4 h-4" />
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Rank, ArrowUp, ArrowDown, View, Hide } from '@element-plus/icons-vue'
import InlineSvgIcon from '@/components/common/InlineSvgIcon.vue'
import type { SidebarNavItem } from '@/composables/useSidebarNavigation'

const props = defineProps<{
  item: SidebarNavItem
  canMoveUp: boolean
  canMoveDown: boolean
  hidden: boolean
}>()
defineEmits<{
  move: [direction: -1 | 1]
  drag: [event: PointerEvent]
  visibility: []
}>()
const { t } = useI18n()
const label = computed(() => props.item.isPlugin ? props.item.label : t(props.item.label))
</script>

<style scoped>
.layout-action {
  color: var(--color-text-subtle);
  @apply p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-800 disabled:opacity-30 disabled:cursor-not-allowed;
}
</style>
