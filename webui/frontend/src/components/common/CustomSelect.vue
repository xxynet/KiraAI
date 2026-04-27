<template>
  <div class="custom-select" ref="containerRef">
    <!-- Trigger -->
    <div
      class="custom-select-trigger"
      :class="{ active: isOpen, 'has-value': !!modelValue, placeholder: !modelValue, disabled: props.disabled }"
      @click.stop="toggleDropdown"
      @keydown.enter.prevent="toggleDropdown"
      @keydown.esc="closeDropdown"
      :tabindex="props.disabled ? -1 : 0"
      role="combobox"
      :aria-expanded="isOpen"
      aria-haspopup="listbox"
    >
      <div class="custom-select-content">
        {{ selectedLabel || placeholder }}
      </div>
      <div class="custom-select-arrow" :class="{ active: isOpen }">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="6 9 12 15 18 9"></polyline>
        </svg>
      </div>
    </div>

    <!-- Options Dropdown (teleport to body to escape overflow clipping, always fixed) -->
    <Teleport to="body">
      <div
        class="custom-select-options"
        :class="{ show: isOpen }"
        ref="optionsRef"
        role="listbox"
        :style="dropdownStyle"
      >
        <div
          v-for="option in options"
          :key="option.value"
          class="custom-select-option"
          :class="{ selected: modelValue === option.value }"
          @click.stop="selectOption(option)"
          role="option"
          :aria-selected="modelValue === option.value"
        >
          {{ option.label }}
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onUnmounted } from 'vue'

interface Option {
  value: string
  label: string
}

const props = defineProps<{
  modelValue: string
  options: Option[]
  placeholder?: string
  disabled?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const isOpen = ref(false)
const containerRef = ref<HTMLElement>()
const optionsRef = ref<HTMLElement>()
const dropdownStyle = ref<Record<string, string>>({})
let openTimerId: ReturnType<typeof setTimeout> | null = null
let scrollAncestor: HTMLElement | null = null

function findScrollAncestor(el: HTMLElement | null): HTMLElement | null {
  while (el) {
    const style = window.getComputedStyle(el)
    const overflow = style.overflow + style.overflowY + style.overflowX
    if (/(auto|scroll)/.test(overflow) && el.scrollHeight > el.clientHeight) {
      return el
    }
    el = el.parentElement
  }
  return null
}

const selectedLabel = computed(() => {
  const option = props.options.find(opt => opt.value === props.modelValue)
  return option?.label || ''
})

function toggleDropdown() {
  if (props.disabled) return
  if (isOpen.value) {
    closeDropdown()
  } else {
    openDropdown()
  }
}

function adjustPosition() {
  if (!containerRef.value || !optionsRef.value) return

  const triggerRect = containerRef.value.getBoundingClientRect()
  const optionsHeight = optionsRef.value.offsetHeight
  const windowHeight = window.innerHeight
  const spaceBelow = windowHeight - triggerRect.bottom
  const spaceAbove = triggerRect.top

  let top: number

  if (spaceBelow < optionsHeight && spaceAbove > spaceBelow) {
    // Not enough space below, show above
    top = triggerRect.top - optionsHeight - 4
  } else {
    // Show below (default)
    top = triggerRect.bottom + 4
  }

  dropdownStyle.value = {
    position: 'fixed',
    left: triggerRect.left + 'px',
    top: top + 'px',
    width: triggerRect.width + 'px',
  }
}

function openDropdown() {
  if (isOpen.value) return

  isOpen.value = true

  // Cancel any previous pending timer first
  if (openTimerId !== null) {
    clearTimeout(openTimerId)
  }

  // Wait for DOM update then adjust position before showing
  openTimerId = setTimeout(() => {
    openTimerId = null
    if (!isOpen.value) return
    adjustPosition()
    // Add scroll/resize listeners — close dropdown on any scroll
    scrollAncestor = containerRef.value ? findScrollAncestor(containerRef.value) : null
    if (scrollAncestor) {
      scrollAncestor.addEventListener('scroll', closeDropdown, { passive: true })
    }
    window.addEventListener('scroll', closeDropdown, true)
    window.addEventListener('resize', adjustPosition)
    document.addEventListener('click', handleClickOutside)
  }, 0)
}

function closeDropdown() {
  if (!isOpen.value) return

  isOpen.value = false

  // Cancel pending open timer to prevent leaked listeners
  if (openTimerId !== null) {
    clearTimeout(openTimerId)
    openTimerId = null
  }

  // Remove listeners
  document.removeEventListener('click', handleClickOutside)
  if (scrollAncestor) {
    scrollAncestor.removeEventListener('scroll', closeDropdown)
    scrollAncestor = null
  }
  window.removeEventListener('scroll', closeDropdown, true)
  window.removeEventListener('resize', adjustPosition)

  // Keep position fixed at last known location so the close animation plays
  // and the element never re-enters the document flow.
}

function selectOption(option: Option) {
  emit('update:modelValue', option.value)
  closeDropdown()
}

function handleClickOutside(event: MouseEvent) {
  const target = event.target as HTMLElement
  if (!containerRef.value?.contains(target)) {
    closeDropdown()
  }
}

onUnmounted(() => {
  // Cancel any pending open timer to prevent leaked listeners after unmount
  if (openTimerId !== null) {
    clearTimeout(openTimerId)
    openTimerId = null
  }
  closeDropdown()
})
</script>

<style scoped>
/* CustomSelect-specific overrides only; shared styles are in main.css */
.custom-select-content {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
