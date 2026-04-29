<template>
  <div class="custom-select" ref="containerRef">
    <!-- Trigger -->
    <div
      class="custom-select-trigger"
      :class="{ active: isOpen, 'has-value': hasValue, placeholder: !hasValue }"
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
        <template v-if="selectedOptions.length > 0">
          <span
            v-for="opt in selectedOptions"
            :key="opt.value"
            class="custom-select-tag"
          >
            {{ opt.label }}
            <span class="custom-select-tag-remove" @click.stop="removeOption(opt.value)">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
                <path d="M18 6L6 18M6 6l12 12" />
              </svg>
            </span>
          </span>
        </template>
        <template v-else>
          {{ props.placeholder || '' }}
        </template>
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
        @keydown.down.prevent="handleArrowDown"
        @keydown.up.prevent="handleArrowUp"
        @keydown.enter.prevent="handleEnterKey"
        @keydown.space.prevent="handleSpaceKey"
        @keydown.esc="closeDropdown"
      >
        <div
          v-for="(option, idx) in options"
          :key="option.value"
          :id="`${selectId}-opt-${idx}`"
          class="custom-select-option"
          :class="{ selected: isSelected(option.value), active: activeIndex === idx }"
          @click.stop="toggleOption(option.value)"
          @mouseenter="activeIndex = idx"
          role="option"
          :aria-selected="isSelected(option.value)"
        >
          <span class="select-check mr-2">{{ isSelected(option.value) ? '✓' : '' }}</span>
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
  modelValue: string[]
  options: Option[]
  placeholder?: string
  disabled?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string[]]
}>()

const isOpen = ref(false)
const containerRef = ref<HTMLElement>()
const optionsRef = ref<HTMLElement>()
const dropdownStyle = ref<Record<string, string>>({})
const activeIndex = ref(-1)
const selectId = `cms-${Math.random().toString(36).slice(2, 9)}`
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

const hasValue = computed(() => props.modelValue.length > 0)

const selectedOptions = computed(() => {
  return props.options.filter(opt => props.modelValue.includes(opt.value))
})

function isSelected(value: string): boolean {
  return props.modelValue.includes(value)
}

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
    top = triggerRect.top - optionsHeight - 4
  } else {
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
  activeIndex.value = -1

  if (openTimerId !== null) {
    clearTimeout(openTimerId)
  }

  openTimerId = setTimeout(() => {
    openTimerId = null
    if (!isOpen.value) return
    adjustPosition()
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

  if (openTimerId !== null) {
    clearTimeout(openTimerId)
    openTimerId = null
  }

  document.removeEventListener('click', handleClickOutside)
  if (scrollAncestor) {
    scrollAncestor.removeEventListener('scroll', closeDropdown)
    scrollAncestor = null
  }
  window.removeEventListener('scroll', closeDropdown, true)
  window.removeEventListener('resize', adjustPosition)
}

function toggleOption(value: string) {
  const current = [...props.modelValue]
  const index = current.indexOf(value)
  if (index > -1) {
    current.splice(index, 1)
  } else {
    current.push(value)
  }
  emit('update:modelValue', current)
}

function onEnter() {
  if (props.disabled) return
  if (!isOpen.value) {
    openDropdown()
    return
  }
  const option = props.options[activeIndex.value]
  if (option) toggleOption(option.value)
}

function onArrowDown() {
  if (props.disabled) return
  if (!isOpen.value) {
    openDropdown()
    activeIndex.value = 0
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
    activeIndex.value = props.options.length - 1
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

function removeOption(value: string) {
  const current = [...props.modelValue]
  const index = current.indexOf(value)
  if (index > -1) {
    current.splice(index, 1)
    emit('update:modelValue', current)
  }
}

function handleClickOutside(event: MouseEvent) {
  const target = event.target as HTMLElement
  if (!containerRef.value?.contains(target)) {
    closeDropdown()
  }
}

function handleArrowDown() {
  if (props.options.length === 0) return
  activeIndex.value = (activeIndex.value + 1) % props.options.length
  scrollActiveIntoView()
}

function handleArrowUp() {
  if (props.options.length === 0) return
  activeIndex.value = activeIndex.value <= 0
    ? props.options.length - 1
    : activeIndex.value - 1
  scrollActiveIntoView()
}

function handleEnterKey() {
  if (activeIndex.value >= 0 && activeIndex.value < props.options.length) {
    toggleOption(props.options[activeIndex.value].value)
  }
}

function handleSpaceKey() {
  if (activeIndex.value >= 0 && activeIndex.value < props.options.length) {
    toggleOption(props.options[activeIndex.value].value)
  }
}

onUnmounted(() => {
  if (openTimerId !== null) {
    clearTimeout(openTimerId)
    openTimerId = null
  }
  closeDropdown()
})
</script>

<style scoped>
/* CustomMultiSelect-specific overrides only; shared styles are in main.css */
.custom-select-content {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-right: 8px;
  overflow: hidden;
}

.custom-select-tag {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  background-color: rgba(59, 130, 246, 0.15);
  color: #1d4ed8;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
}

.custom-select-tag-remove {
  margin-left: 4px;
  cursor: pointer;
  opacity: 0.6;
  transition: opacity 0.15s ease-in-out;
  display: inline-flex;
  align-items: center;
}

.custom-select-tag-remove:hover {
  opacity: 1;
}

.select-check {
  display: inline-block;
  width: 16px;
  text-align: center;
}

.custom-select-option.highlighted {
  background-color: rgba(59, 130, 246, 0.1);
}
</style>

<style>
.dark .custom-select-tag {
  background-color: rgba(30, 58, 138, 0.3);
  color: #93c5fd;
}

.dark .custom-select-option.highlighted {
  background-color: rgba(59, 130, 246, 0.2);
}
</style>
