<template>
  <div class="custom-select" ref="containerRef">
    <!-- Trigger -->
    <div
      class="custom-select-trigger"
      :class="{ active: isOpen, 'has-value': !!modelValue, placeholder: !modelValue }"
      @click.stop="toggleDropdown"
      @keydown.enter.prevent="toggleDropdown"
      @keydown.esc="closeDropdown"
      tabindex="0"
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

    <!-- Options Dropdown (teleport to body to avoid clipping) -->
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
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const isOpen = ref(false)
const containerRef = ref<HTMLElement>()
const optionsRef = ref<HTMLElement>()
const dropdownStyle = ref<Record<string, string>>({})

const selectedLabel = computed(() => {
  const option = props.options.find(opt => opt.value === props.modelValue)
  return option?.label || ''
})

function toggleDropdown() {
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
  
  // Position fixed relative to viewport, matching trigger width
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
  
  // Wait for DOM update then adjust position before showing
  setTimeout(() => {
    adjustPosition()
    // Add scroll/resize listeners
    window.addEventListener('scroll', adjustPosition, true)
    window.addEventListener('resize', adjustPosition)
    document.addEventListener('click', handleClickOutside)
  }, 0)
}

function closeDropdown() {
  if (!isOpen.value) return
  
  isOpen.value = false
  
  // Remove listeners - but don't clear position yet to avoid visual jump
  document.removeEventListener('click', handleClickOutside)
  window.removeEventListener('scroll', adjustPosition, true)
  window.removeEventListener('resize', adjustPosition)
  
  // Clear position after animation completes (to avoid next open flash)
  setTimeout(() => {
    if (!isOpen.value) {
      dropdownStyle.value = {}
    }
  }, 200)
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
  closeDropdown()
})
</script>

<style>
/* Base styles (non-scoped to work with dark mode class on html) */
.custom-select {
  position: relative;
  display: inline-block;
  width: 100%;
  user-select: none;
}

.custom-select-trigger {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background-color: rgba(255, 255, 255, 0.7);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border: 1px solid rgba(255, 255, 255, 0.3);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease-in-out;
  font-size: 14px;
  color: #374151;
}

.custom-select-trigger:hover {
  background-color: rgba(255, 255, 255, 0.85);
  border-color: #3b82f6;
}

.custom-select-trigger.active {
  border-color: #3b82f6;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.5);
}

.custom-select-trigger.has-value {
  color: #111827;
}

.custom-select-trigger.placeholder {
  color: #9ca3af;
}

.custom-select-content {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.custom-select-arrow {
  width: 20px;
  height: 20px;
  transition: transform 0.2s ease-in-out;
  flex-shrink: 0;
}

.custom-select-arrow.active svg {
  transform: rotate(180deg);
}

.custom-select-options {
  background-color: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border: 1px solid rgba(255, 255, 255, 0.3);
  border-radius: 12px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.1);
  max-height: 300px;
  overflow-y: auto;
  z-index: 1000;
  opacity: 0;
  visibility: hidden;
  transform: translateY(-8px);
  transition: opacity 0.2s ease-in-out, visibility 0.2s ease-in-out, transform 0.2s ease-in-out;
}

.custom-select-options.show {
  opacity: 1;
  visibility: visible;
  transform: translateY(0);
}

.custom-select-option {
  padding: 10px 12px;
  cursor: pointer;
  transition: all 0.15s ease-in-out;
  font-size: 14px;
  color: #374151;
  border-radius: 12px;
  margin: 6px 8px;
}

.custom-select-option:hover {
  background-color: rgba(59, 130, 246, 0.1);
  color: #1d4ed8;
}

.custom-select-option.selected {
  background-color: rgba(59, 130, 246, 0.15);
  color: #1d4ed8;
  font-weight: 500;
}

/* Scrollbar */
.custom-select-options::-webkit-scrollbar {
  width: 6px;
}

.custom-select-options::-webkit-scrollbar-track {
  background: rgba(229, 231, 235, 0.3);
  border-radius: 3px;
}

.custom-select-options::-webkit-scrollbar-thumb {
  background: rgba(156, 163, 175, 0.5);
  border-radius: 3px;
}

.custom-select-options::-webkit-scrollbar-thumb:hover {
  background: rgba(107, 114, 128, 0.7);
}

/* Focus styles */
.custom-select-trigger:focus {
  outline: none;
  border-color: #3b82f6;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.5);
}

/* Dark mode styles - using global .dark class on html */
.dark .custom-select-trigger {
  background-color: rgba(31, 41, 55, 0.7);
  border-color: rgba(75, 85, 99, 0.3);
  color: #e5e7eb;
}

.dark .custom-select-trigger:hover {
  background-color: rgba(31, 41, 55, 0.85);
  border-color: #3b82f6;
}

.dark .custom-select-trigger.active {
  border-color: #3b82f6;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.5);
}

.dark .custom-select-trigger.has-value {
  color: #f9fafb;
}

.dark .custom-select-trigger.placeholder {
  color: #9ca3af;
}

.dark .custom-select-options {
  background-color: rgba(31, 41, 55, 0.95);
  border-color: rgba(75, 85, 99, 0.3);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
}

.dark .custom-select-option {
  color: #e5e7eb;
}

.dark .custom-select-option:hover {
  background-color: rgba(59, 130, 246, 0.2);
  color: #93c5fd;
}

.dark .custom-select-option.selected {
  background-color: rgba(59, 130, 246, 0.25);
  color: #93c5fd;
}

.dark .custom-select-options::-webkit-scrollbar-track {
  background: rgba(75, 85, 99, 0.3);
}

.dark .custom-select-options::-webkit-scrollbar-thumb {
  background: rgba(107, 114, 128, 0.5);
}

.dark .custom-select-options::-webkit-scrollbar-thumb:hover {
  background: rgba(156, 163, 175, 0.7);
}

:global(.dark) .custom-select-trigger:hover {
  background-color: rgba(31, 41, 55, 0.85);
  border-color: #3b82f6;
}

:global(.dark) .custom-select-trigger.has-value {
  color: #f9fafb;
}

:global(.dark) .custom-select-trigger.placeholder {
  color: #9ca3af;
}

:global(.dark) .custom-select-options {
  background-color: rgba(31, 41, 55, 0.95);
  border: 1px solid rgba(75, 85, 99, 0.3);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
}

:global(.dark) .custom-select-option {
  color: #e5e7eb;
}

:global(.dark) .custom-select-option:hover {
  background-color: rgba(59, 130, 246, 0.2);
  color: #93c5fd;
}

:global(.dark) .custom-select-option.selected {
  background-color: rgba(59, 130, 246, 0.25);
  color: #93c5fd;
}

:global(.dark) .custom-select-options::-webkit-scrollbar-track {
  background: rgba(75, 85, 99, 0.3);
}

:global(.dark) .custom-select-options::-webkit-scrollbar-thumb {
  background: rgba(107, 114, 128, 0.5);
}

:global(.dark) .custom-select-options::-webkit-scrollbar-thumb:hover {
  background: rgba(156, 163, 175, 0.7);
}

/* Focus styles */
.custom-select-trigger:focus {
  outline: none;
  border-color: #3b82f6;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.5) !important;
}
</style>
