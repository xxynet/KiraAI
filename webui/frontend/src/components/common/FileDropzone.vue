<template>
  <div
    ref="containerRef"
    class="border border-dashed rounded-lg px-4 py-6 flex flex-col items-center justify-center space-y-2 cursor-pointer transition-colors"
    :class="hasFile
      ? 'border-green-400 dark:border-green-500 bg-green-50 dark:bg-green-900/20 hover:bg-green-100 dark:hover:bg-green-900/30'
      : dragActive
        ? 'border-blue-400 dark:border-blue-500 bg-blue-50 dark:bg-blue-900/20'
        : 'border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-800 hover:bg-gray-100 dark:hover:bg-gray-700'"
    @click="onClick"
    @dragover.prevent="onDragOver"
    @dragleave.prevent="onDragLeave"
    @drop.prevent="onDrop"
  >
    <div v-if="hasFile">
      <svg class="w-10 h-10 text-green-500 dark:text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
      </svg>
    </div>
    <div v-else>
      <svg class="w-10 h-10 text-gray-400 dark:text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
      </svg>
    </div>
    <p
      class="text-sm"
      :class="hasFile ? 'text-green-700 dark:text-green-300 font-medium' : 'text-gray-600 dark:text-gray-300'"
    >
      {{ fileName || titleText }}
    </p>
    <p v-if="hasFile" class="text-xs text-gray-400 dark:text-gray-500">
      {{ reselectText }}
    </p>
  </div>
  <input
    ref="inputRef"
    type="file"
    class="hidden"
    :accept="accept"
    @change="onInputChange"
  >
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps<{
  modelValue?: File | null
  accept?: string
  titleKey?: string
  titleFallback?: string
  reselectKey?: string
  reselectFallback?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: File | null]
}>()

const { t } = useI18n()

const inputRef = ref<HTMLInputElement>()
const containerRef = ref<HTMLDivElement>()
const dragActive = ref(false)

const hasFile = computed(() => props.modelValue !== null && props.modelValue !== undefined)
const fileName = computed(() => props.modelValue?.name || '')

const titleText = computed(() => {
  const key = props.titleKey || 'dropzone.file_title'
  const val = t(key)
  return val !== key ? val : (props.titleFallback || 'Drop a file here or click to select')
})

const reselectText = computed(() => {
  const key = props.reselectKey || 'dropzone.file_reselect'
  const val = t(key)
  return val !== key ? val : (props.reselectFallback || 'Click or drag to reselect')
})

function onClick() {
  inputRef.value?.click()
}

function setFile(file: File | null) {
  emit('update:modelValue', file)
}

function onInputChange(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0] || null
  setFile(file)
}

function onDragOver() {
  dragActive.value = true
}

function onDragLeave() {
  dragActive.value = false
}

function onDrop(e: DragEvent) {
  dragActive.value = false
  const file = e.dataTransfer?.files?.[0] || null
  if (file) setFile(file)
}

function reset() {
  setFile(null)
  if (inputRef.value) inputRef.value.value = ''
}

defineExpose({ reset })
</script>
