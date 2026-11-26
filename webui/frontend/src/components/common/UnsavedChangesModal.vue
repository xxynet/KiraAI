<template>
  <Modal
    :model-value="modelValue"
    content-class="max-w-md"
    @update:model-value="onVisibleChange"
    @close="onStay"
  >
    <div class="bg-white dark:bg-gray-800 rounded-lg shadow-xl">
      <div class="px-6 pt-6 pb-4">
        <div class="flex items-start">
          <div class="rounded-full p-3 mr-4 bg-amber-100 dark:bg-amber-900/30">
            <IconWarning class="w-6 h-6 text-amber-600 dark:text-amber-400" />
          </div>
          <div>
            <h3 class="text-lg font-semibold text-theme-strong">{{ title }}</h3>
            <p class="text-sm text-theme-subtle mt-1">{{ message }}</p>
          </div>
        </div>
        <slot></slot>
      </div>
      <div class="px-6 pb-6 flex flex-wrap justify-end gap-3">
        <button
          type="button"
          class="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-theme-body hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
          @click="onStay"
        >
          {{ stayText }}
        </button>
        <button
          type="button"
          class="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-theme-body hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          :disabled="busy"
          @click="onDiscard"
        >
          {{ discardText }}
        </button>
        <button
          type="button"
          class="px-4 py-2 bg-blue-600 dark:bg-blue-700 text-white rounded-lg hover:bg-blue-700 dark:hover:bg-blue-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          :disabled="busy"
          @click="onSave"
        >
          {{ saveText }}
        </button>
      </div>
    </div>
  </Modal>
</template>

<script setup lang="ts">
import Modal from './Modal.vue'
import { IconWarning } from '@/components/icons'

defineProps<{
  modelValue: boolean
  title: string
  message: string
  saveText: string
  discardText: string
  stayText: string
  /** Disables the save button while a save request is in flight. */
  busy?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  save: []
  discard: []
  stay: []
}>()

function onVisibleChange(value: boolean) {
  emit('update:modelValue', value)
}

function onSave() {
  emit('save')
}

function onDiscard() {
  emit('discard')
}

/** Escape and backdrop clicks dismiss the dialog, which counts as staying. */
function onStay() {
  emit('stay')
}
</script>

<style scoped>
</style>
