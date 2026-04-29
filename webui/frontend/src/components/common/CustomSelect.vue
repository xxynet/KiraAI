<template>
  <div class="custom-select" ref="containerRef">
    <!-- Trigger -->
    <div
      class="custom-select-trigger"
      :class="{ active: isOpen, 'has-value': !!modelValue, placeholder: !modelValue, disabled: props.disabled }"
      @click.stop="toggleDropdown"
      @keydown.enter.prevent="onEnter"
      @keydown.space.prevent="onEnter"
      @keydown.esc="closeDropdown"
      @keydown.down.prevent="onArrowDown"
      @keydown.up.prevent="onArrowUp"
      :tabindex="props.disabled ? -1 : 0"
      role="combobox"
      :aria-expanded="isOpen"
      aria-haspopup="listbox"
      :aria-activedescendant="isOpen && activeIndex >= 0 ? `${selectId}-opt-${activeIndex}` : undefined"
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
          v-for="(option, idx) in options"
          :key="option.value"
          :id="`${selectId}-opt-${idx}`"
          class="custom-select-option"
          :class="{ selected: modelValue === option.value, active: activeIndex === idx }"
          @click.stop="selectOption(option)"
          @mouseenter="activeIndex = idx"
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
const activeIndex = ref(-1)
const selectId = `cs-${Math.random().toString(36).slice(2, 9)}`
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
  const matched = props.options.findIndex(o => o.value === props.modelValue)
  activeIndex.value = matched >= 0 ? matched : -1

  // Cancel any previous pending timer first
  if (openTimerId !== null) {
    clearTimeout(openTimerId)
  }

  // Wait for DOM update then adjust position before showing
  openTimerId = setTimeout(() => {
    openTimerId = null
    if (!isOpen.value) return
    adjustPosition()
    scrollToActive()
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
  activeIndex.value = -1

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

function onEnter() {
  if (props.disabled) return
  if (!isOpen.value) {
    openDropdown()
    return
  }
  const option = props.options[activeIndex.value]
  if (option) selectOption(option)
}

function onArrowDown() {
  if (props.disabled) return
  if (!isOpen.value) {
    openDropdown()
    activeIndex.value = props.options.findIndex(o => o.value === props.modelValue)
    if (activeIndex.value < 0) activeIndex.value = 0
    return
  }
  if (props.options.length === 0) return
  activeIndex.value = (activeIndex.value + 1) % props.options.length
  scrollActiveIntoView()
}

function onArrowUp() {
  if (props.disabled) return
  if (!isOpen.value) {
    openDropdown()
    activeIndex.value = props.options.findIndex(o => o.value === props.modelValue)
    if (activeIndex.value < 0) activeIndex.value = props.options.length - 1
    return
  }
  if (props.options.length === 0) return
  activeIndex.value = (activeIndex.value - 1 + props.options.length) % props.options.length
  scrollActiveIntoView()
}

function scrollActiveIntoView() {
  if (!optionsRef.value) return
  const el = optionsRef.value.querySelector<HTMLElement>(`#${selectId}-opt-${activeIndex.value}`)
  el?.scrollIntoView({ block: 'nearest' })
}

function handleClickOutside(event: MouseEvent) {
  const target = event.target as HTMLElement
  if (!containerRef.value?.contains(target)) {
    closeDropdown()
  }
}

function handleEnterKey() {
  if (!isOpen.value) {
    toggleDropdown()
  } else if (activeIndex.value >= 0 && activeIndex.value < props.options.length) {
    selectOption(props.options[activeIndex.value])
  }
}

function handleArrowDown() {
  if (!isOpen.value) {
    openDropdown()
  } else if (props.options.length > 0) {
    activeIndex.value = (activeIndex.value + 1) % props.options.length
    scrollToActive()
  }
}

function handleArrowUp() {
  if (!isOpen.value) {
    openDropdown()
  } else if (props.options.length > 0) {
    activeIndex.value = activeIndex.value <= 0
      ? props.options.length - 1
      : activeIndex.value - 1
    scrollToActive()
  }
}

function scrollToActive() {
  if (!optionsRef.value || activeIndex.value < 0) return
  const activeElement = optionsRef.value.querySelector(`#option-${activeIndex.value}`)
  if (activeElement) {
    activeElement.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
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

.custom-select-option.highlighted {
  background-color: rgba(59, 130, 246, 0.1);
}
</style>

<style>
.dark .custom-select-option.highlighted {
  background-color: rgba(59, 130, 246, 0.2);
}
</style>
