<template>
  <section ref="editorRef" class="space-y-3" aria-labelledby="sidebar-layout-title" @dragstart.prevent>
    <div class="flex flex-wrap items-center justify-between gap-2">
      <h4 id="sidebar-layout-title" class="text-sm font-medium text-theme-body">{{ $t('settings.sidebar_layout_title') }}</h4>
      <button type="button" class="text-sm text-blue-600 dark:text-blue-400 hover:underline" @click="resetLayout">
        {{ $t('settings.sidebar_layout_reset') }}
      </button>
    </div>
    <p class="text-xs text-theme-subtle">{{ $t('settings.sidebar_layout_hint') }}</p>
    <div class="flex gap-2">
      <UiInput
        v-model="newGroupName" class="flex-1 min-w-0 text-sm px-3 py-2 rounded-lg"
        :aria-label="$t('settings.sidebar_layout_group_name')" :placeholder="$t('settings.sidebar_layout_group_name')"
        @keydown="handleNewGroupKeydown"
      />
      <button type="button" class="px-3 py-2 text-sm rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed" :disabled="!newGroupName.trim()" @click="addGroup">
        {{ $t('settings.sidebar_layout_add_group') }}
      </button>
    </div>
    <div class="space-y-2" data-sidebar-entries>
      <template v-for="(entry, index) in visibleEntries" :key="entry.id">
        <div
          v-if="entry.type === 'group' && (index === 0 || visibleEntries[index - 1]?.type === 'item')"
          data-sidebar-ungrouped-drop
          class="p-3 border border-dashed border-gray-300 dark:border-gray-600 rounded-lg text-xs text-center text-theme-subtle"
          :class="{ 'bg-blue-50 dark:bg-blue-900/20': dragged?.type === 'item' }"
        >{{ $t('settings.sidebar_layout_drop_top_level') }}</div>
        <SidebarLayoutItem
          v-if="entry.type === 'item' && itemMap.has(entry.id)"
          :item="itemMap.get(entry.id)!"
          :hidden="hiddenItems.includes(entry.id)"
          :can-move-up="canMoveRoot(entry, -1)" :can-move-down="canMoveRoot(entry, 1)"
          @move="moveRoot(entry.id, $event)"
          @drag="startDrag($event, { type: 'item', id: entry.id })"
          @visibility="toggleHidden(entry.id)"
        />
        <div v-else-if="entry.type === 'group'" :data-sidebar-group="entry.id" class="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden bg-white dark:bg-gray-900" :class="{ 'opacity-60': hiddenItems.includes(entry.id) }">
          <div
            class="flex items-center gap-2 p-2 bg-gray-50 dark:bg-gray-800 cursor-grab active:cursor-grabbing touch-none select-none"
            @pointerdown="startDrag($event, { type: 'group', id: entry.id })"
          >
            <button
              type="button" data-sidebar-drag-handle class="layout-action cursor-grab active:cursor-grabbing"
              :aria-label="$t('settings.sidebar_layout_drag', { name: groupLabel(entry) })"
            ><Rank class="w-4 h-4" /></button>
            <Folder class="w-5 h-5 shrink-0 text-theme-subtle" />
            <input
              class="ui-input flex-1 min-w-0 text-sm px-2 py-1"
              :value="groupLabel(entry)" :aria-label="$t('settings.sidebar_layout_group_name')"
              @change="renameGroup(entry, $event)"
            />
            <span v-if="hiddenItems.includes(entry.id)" class="text-xs text-theme-subtle">{{ $t('settings.sidebar_layout_hidden') }}</span>
            <button
              type="button" class="layout-action" :aria-pressed="hiddenItems.includes(entry.id)"
              :aria-label="$t(hiddenItems.includes(entry.id) ? 'settings.sidebar_layout_show' : 'settings.sidebar_layout_hide', { name: groupLabel(entry) })"
              :title="$t(hiddenItems.includes(entry.id) ? 'settings.sidebar_layout_show' : 'settings.sidebar_layout_hide', { name: groupLabel(entry) })"
              @click="toggleHidden(entry.id)"
            ><component :is="hiddenItems.includes(entry.id) ? Hide : View" class="w-4 h-4" /></button>
            <button type="button" class="layout-action" :disabled="!canMoveRoot(entry, -1)" :aria-label="$t('settings.sidebar_layout_move_up', { name: groupLabel(entry) })" @click="moveRoot(entry.id, -1)">
              <ArrowUp class="w-4 h-4" />
            </button>
            <button type="button" class="layout-action" :disabled="!canMoveRoot(entry, 1)" :aria-label="$t('settings.sidebar_layout_move_down', { name: groupLabel(entry) })" @click="moveRoot(entry.id, 1)">
              <ArrowDown class="w-4 h-4" />
            </button>
            <button type="button" class="layout-action" :aria-label="$t('settings.sidebar_layout_remove_group', { name: groupLabel(entry) })" @click="removeGroup(entry.id)">
              <Delete class="w-4 h-4" />
            </button>
          </div>
          <div data-sidebar-group-body class="p-2 pl-6 space-y-2 min-h-12">
            <SidebarLayoutItem
              v-for="(item, itemIndex) in groupItems(entry)" :key="item.id"
              :item="item"
              :hidden="hiddenItems.includes(item.id)"
              :data-sidebar-group-id="entry.id"
              :can-move-up="itemIndex > 0" :can-move-down="itemIndex < groupItems(entry).length - 1"
              @move="moveInGroup(entry, item.id, $event)"
              @drag="startDrag($event, { type: 'item', id: item.id })"
              @visibility="toggleHidden(item.id)"
            />
            <p v-if="!groupItems(entry).length" class="p-2 text-xs text-theme-faint">{{ $t('settings.sidebar_layout_empty_group') }}</p>
          </div>
        </div>
      </template>
      <div
        v-if="!hasGroups"
        data-sidebar-ungrouped-drop
        class="p-3 border border-dashed border-gray-300 dark:border-gray-600 rounded-lg text-xs text-center text-theme-subtle"
        :class="{ 'bg-blue-50 dark:bg-blue-900/20': dragged?.type === 'item' }"
      >{{ $t('settings.sidebar_layout_drop_top_level') }}</div>
      <div
        v-else
        data-sidebar-group-end
        class="p-3 border border-dashed border-gray-300 dark:border-gray-600 rounded-lg text-xs text-center text-theme-subtle"
        :class="{ 'bg-blue-50 dark:bg-blue-900/20': dragged?.type === 'group' }"
      >{{ $t('settings.sidebar_layout_drop_group_end') }}</div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { Rank, Folder, ArrowUp, ArrowDown, Delete, View, Hide } from '@element-plus/icons-vue'
import UiInput from '@/components/ui/UiInput.vue'
import SidebarLayoutItem from './SidebarLayoutItem.vue'
import { useSidebarNavigation, type SidebarNavItem } from '@/composables/useSidebarNavigation'
import { useSidebarDrag, type SidebarDragSource, type SidebarDropTarget } from '@/composables/useSidebarDrag'
import {
  reconcileSidebarLayout, moveSidebarItem, moveSidebarGroup, removeSidebarGroup,
  type SidebarLayoutEntry, type SidebarGroupEntry,
} from '@/navigation/sidebarLayout'

const props = defineProps<{ modelValue: SidebarLayoutEntry[] | null; hiddenItems: string[] }>()
const emit = defineEmits<{
  'update:modelValue': [value: SidebarLayoutEntry[] | null]
  'update:hiddenItems': [value: string[]]
}>()
const { items, itemMap, groupLabel } = useSidebarNavigation()
const layout = computed(() => reconcileSidebarLayout(props.modelValue, items.value))
const visibleEntries = computed(() => layout.value.filter(entry => entry.type === 'group' || itemMap.value.has(entry.id)))
const hasGroups = computed(() => layout.value.some(entry => entry.type === 'group'))
const newGroupName = ref('')
const editorRef = ref<HTMLElement>()
const { dragged, startDrag } = useSidebarDrag(editorRef, applyDrop)

function groupItems(group: SidebarGroupEntry): SidebarNavItem[] {
  return group.items.map(id => itemMap.value.get(id)).filter((item): item is SidebarNavItem => !!item)
}

function addGroup() {
  const name = newGroupName.value.trim()
  if (!name) return
  const id = `group-${Array.from(crypto.getRandomValues(new Uint32Array(4)), value => value.toString(16)).join('-')}`
  emit('update:modelValue', [...layout.value, { type: 'group', id, name, items: [] }])
  newGroupName.value = ''
}

function handleNewGroupKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.isComposing) {
    event.preventDefault()
    addGroup()
  }
}

function renameGroup(group: SidebarGroupEntry, event: Event) {
  const input = event.target as HTMLInputElement
  const name = input.value.trim()
  input.value = name || groupLabel(group)
  if (!name) return
  emit('update:modelValue', layout.value.map(entry => entry.id === group.id ? { ...entry, name } : entry))
}

function removeGroup(id: string) {
  emit('update:modelValue', removeSidebarGroup(layout.value, id))
  emit('update:hiddenItems', props.hiddenItems.filter(hiddenId => hiddenId !== id))
}

function toggleHidden(id: string) {
  const hidden = new Set(props.hiddenItems)
  if (hidden.has(id)) hidden.delete(id)
  else hidden.add(id)
  emit('update:hiddenItems', [...hidden])
}

function resetLayout() {
  emit('update:modelValue', null)
  emit('update:hiddenItems', [])
}

function moveItem(id: string, groupId: string | null, beforeId?: string) {
  emit('update:modelValue', moveSidebarItem(layout.value, id, groupId, beforeId))
}

function moveRoot(id: string, direction: -1 | 1) {
  const entry = visibleEntries.value.find(entry => entry.id === id)
  if (!entry || !canMoveRoot(entry, direction)) return
  const peers = visibleEntries.value.filter(peer => peer.type === entry.type)
  const index = peers.findIndex(peer => peer.id === id)
  const beforeId = peers[direction === -1 ? index - 1 : index + 2]?.id
  emit('update:modelValue', entry.type === 'group'
    ? moveSidebarGroup(layout.value, id, beforeId)
    : moveSidebarItem(layout.value, id, null, beforeId))
}

function canMoveRoot(entry: SidebarLayoutEntry, direction: -1 | 1): boolean {
  const peers = visibleEntries.value.filter(peer => peer.type === entry.type)
  const index = peers.findIndex(peer => peer.id === entry.id)
  return index >= 0 && index + direction >= 0 && index + direction < peers.length
}

function moveInGroup(group: SidebarGroupEntry, id: string, direction: -1 | 1) {
  const children = groupItems(group)
  const index = children.findIndex(item => item.id === id)
  if (index < 0 || index + direction < 0 || index + direction >= children.length) return
  moveItem(id, group.id, children[direction === -1 ? index - 1 : index + 2]?.id)
}

function applyDrop(source: SidebarDragSource, target: SidebarDropTarget) {
  if (source.type === 'item' && target.type === 'item') moveItem(source.id, target.groupId, target.beforeId)
  else if (source.type === 'group' && target.type === 'group') {
    emit('update:modelValue', moveSidebarGroup(layout.value, source.id, target.beforeId))
  }
}
</script>

<style scoped>
.layout-action {
  color: var(--color-text-subtle);
  @apply p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-30 disabled:cursor-not-allowed;
}
</style>
