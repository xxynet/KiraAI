<template>
  <div
    class="border border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors"
    :class="dropzoneClasses"
    @click="fileInputRef?.click()"
    @dragover.prevent="dragOver = true"
    @dragleave.prevent="dragOver = false"
    @drop.prevent="onFileDrop"
  >
    <input
      ref="fileInputRef"
      type="file"
      :accept="accept"
      class="hidden"
      @change="onFileInputChange"
    />
    <template v-if="!modelValue">
      <svg class="w-8 h-8 text-gray-400 mx-auto mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"></path>
      </svg>
      <p class="text-sm font-medium text-gray-700 dark:text-gray-300">
        {{ titleText }}
      </p>
      <p class="text-xs text-gray-500 dark:text-gray-400 mt-1">
        {{ subtitleText }}
      </p>
    </template>
    <template v-else>
      <svg class="w-8 h-8 text-emerald-500 mx-auto mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>
      </svg>
      <p class="text-sm font-medium text-emerald-600 dark:text-emerald-400">
        {{ selectedPrefix }}{{ modelValue.name }}
      </p>
      <p class="text-xs text-gray-500 dark:text-gray-400 mt-1">
        {{ selectedHint }}
      </p>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'

const props = withDefaults(defineProps<{
  modelValue: File | null
  accept?: string
  titleText?: string
  subtitleText?: string
  selectedPrefix?: string
  selectedHint?: string
}>(), {
  accept: 'image/*',
  titleText: 'Drop image here or click to select file',
  subtitleText: 'Common image formats such as JPG and PNG are supported',
  selectedPrefix: 'Selected file: ',
  selectedHint: 'Click or drag to select another image',
})

const emit = defineEmits<{
  'update:modelValue': [value: File | null]
}>()

const dragOver = ref(false)
const fileInputRef = ref<HTMLInputElement | null>(null)

const dropzoneClasses = computed(() => {
  // Selected state: green border & dark green bg
  if (props.modelValue) {
    return 'border-emerald-500 bg-emerald-50 dark:bg-emerald-900/20'
  }
  // Drag over state: green border & bg
  if (dragOver.value) {
    return 'border-emerald-500 bg-emerald-50 dark:bg-emerald-900/20'
  }
  // Default: gray dashed border, hover bg more obvious, border stays gray
  return 'border-gray-300 dark:border-gray-600 hover:border-gray-400 dark:hover:border-gray-500 hover:bg-gray-100 dark:hover:bg-gray-700'
})

function onFileInputChange(e: Event) {
  const target = e.target as HTMLInputElement
  const file = target.files?.[0] || null
  if (file) {
    emit('update:modelValue', file)
  }
}

function onFileDrop(e: DragEvent) {
  dragOver.value = false
  const file = e.dataTransfer?.files?.[0] || null
  if (file && file.type.startsWith('image/')) {
    emit('update:modelValue', file)
  } else if (file) {
    emit('update:modelValue', null)
  }
}
</script>
