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
              <IconX width="12" height="12" />
            </span>
          </span>
        </template>
        <template v-else>
          {{ props.placeholder || '' }}
        </template>
      </div>
      <div class="custom-select-arrow" :class="{ active: isOpen }">
        <IconChevronDown width="20" height="20" />
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
        <!-- Free-form entry: lets the user add a value that is not listed below.
             click.stop keeps the teleported dropdown from being treated as an
             outside click by the document listener. -->
        <div v-if="allowCustom" class="custom-select-custom" @click.stop>
          <input
            ref="customInputRef"
            v-model="customDraft"
            type="text"
            class="custom-select-custom-input"
            :placeholder="customPlaceholder || ''"
            @click.stop
            @keydown.enter.prevent.stop="commitCustomValue"
            @keydown.space.stop
          >
          <button
            type="button"
            class="custom-select-custom-add"
            :disabled="!customDraft.trim()"
            :title="customPlaceholder || ''"
            @click.stop="commitCustomValue"
          >
            <IconPlus width="16" height="16" />
          </button>
        </div>
        <div v-if="allowCustom && options.length > 0" class="custom-select-divider" />
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
          <span class="custom-select-option-label">{{ option.label }}</span>
          <IconCheck v-if="isSelected(option.value)" class="select-check" width="16" height="16" />
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onUnmounted } from 'vue'
import { IconCheck, IconPlus, IconX, IconChevronDown } from '@/components/icons'

interface Option {
  value: string
  label: string
}

const props = defineProps<{
  modelValue: string[]
  options: Option[]
  placeholder?: string
  disabled?: boolean
  /** Allow values typed by the user that are not part of `options` */
  allowCustom?: boolean
  /** Placeholder for the free-form entry input (only used with allowCustom) */
  customPlaceholder?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string[]]
}>()

const isOpen = ref(false)
const containerRef = ref<HTMLElement>()
const optionsRef = ref<HTMLElement>()
const customInputRef = ref<HTMLInputElement>()
const customDraft = ref('')
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

/**
 * Selected entries as {value, label} pairs: known options keep their label and
 * the option-list order, while values absent from `options` (typed by the user
 * when allowCustom is set) are appended and labelled by their raw value.
 */
const selectedOptions = computed(() => {
  const knownOptions = props.options.filter(opt => props.modelValue.includes(opt.value))
  const knownValues = new Set(props.options.map(opt => opt.value))
  const customOptions = props.modelValue
    .filter(value => !knownValues.has(value))
    .map(value => ({ value, label: value }))
  return [...knownOptions, ...customOptions]
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
    minWidth: triggerRect.width + 'px',
    width: 'max-content',
    maxWidth: `calc(100vw - ${triggerRect.left + 8}px)`,
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
    // Free-form entry is the primary action for custom values, so focus it on open.
    if (props.allowCustom) {
      customInputRef.value?.focus({ preventScroll: true })
    }
    scrollAncestor = containerRef.value ? findScrollAncestor(containerRef.value) : null
    if (scrollAncestor) {
      scrollAncestor.addEventListener('scroll', closeDropdown, { passive: true })
    }
    window.addEventListener('scroll', handleWindowScroll, true)
    window.addEventListener('resize', adjustPosition)
    document.addEventListener('click', handleClickOutside)
  }, 0)
}

function closeDropdown() {
  if (!isOpen.value) return

  isOpen.value = false
  activeIndex.value = -1
  customDraft.value = ''

  if (openTimerId !== null) {
    clearTimeout(openTimerId)
    openTimerId = null
  }

  document.removeEventListener('click', handleClickOutside)
  if (scrollAncestor) {
    scrollAncestor.removeEventListener('scroll', closeDropdown)
    scrollAncestor = null
  }
  window.removeEventListener('scroll', handleWindowScroll, true)
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

/** Add the free-form entry as a new value (no-op when empty or already selected). */
function commitCustomValue() {
  const value = customDraft.value.trim()
  if (!value) return
  customDraft.value = ''
  if (props.modelValue.includes(value)) return
  emit('update:modelValue', [...props.modelValue, value])
}

function handleClickOutside(event: MouseEvent) {
  const target = event.target as HTMLElement
  if (!containerRef.value?.contains(target)) {
    closeDropdown()
  }
}

function handleWindowScroll(event: Event) {
  // Ignore scrolls originating from inside the dropdown itself
  if (optionsRef.value?.contains(event.target as Node)) return
  closeDropdown()
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
  background-color: var(--color-accent-tag);
  color: var(--color-text-accent);
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
  flex-shrink: 0;
  margin-left: auto;
}

.select-check.mr-2 {
  display: none;
}

.custom-select-option-label {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.custom-select-option.highlighted {
  background-color: var(--color-accent-subtle);
}

/* Free-form entry row (allowCustom) */
.custom-select-custom {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px;
  /* Keep the entry visible while the option list scrolls underneath it */
  position: sticky;
  top: 0;
  z-index: 1;
  background-color: var(--color-surface-overlay);
}

.custom-select-custom-input {
  flex: 1 1 auto;
  min-width: 0;
  padding: 6px 8px;
  font-size: 13px;
  color: var(--color-text-primary);
  background-color: var(--color-surface-raised);
  border: 1px solid var(--color-border-strong);
  border-radius: 6px;
  outline: none;
  transition: border-color 0.15s ease-in-out, box-shadow 0.15s ease-in-out;
}

.custom-select-custom-input:focus {
  border-color: var(--color-accent);
  box-shadow: 0 0 0 2px var(--color-focus-ring);
}

.custom-select-custom-input::placeholder {
  color: var(--color-text-muted);
}

.custom-select-custom-add {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  color: var(--color-text-accent);
  background-color: var(--color-accent-subtle);
  cursor: pointer;
  transition: opacity 0.15s ease-in-out;
}

.custom-select-custom-add:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.custom-select-divider {
  height: 1px;
  margin: 2px 6px 6px;
  background-color: var(--color-border-strong);
}
</style>
