<template>
  <Modal
    v-model="visible"
    content-class="max-w-md"
    @close="onCancel"
  >
    <div class="bg-white dark:bg-gray-800 rounded-lg shadow-xl">
      <div class="px-6 py-4">
        <div class="flex items-center mb-4">
          <div :class="variant === 'info' ? 'bg-blue-100 dark:bg-blue-900/30' : 'bg-red-100 dark:bg-red-900/30'" class="rounded-full p-3 mr-4">
            <IconInfo v-if="variant === 'info'" class="w-6 h-6 text-blue-600 dark:text-blue-400" />
            <IconWarning v-else class="w-6 h-6 text-red-600 dark:text-red-400" />
          </div>
          <div>
            <h3 class="text-lg font-semibold text-gray-800 dark:text-gray-100">
              {{ title }}
            </h3>
            <p class="text-sm text-gray-500 dark:text-gray-400 mt-1">
              {{ message }}
            </p>
          </div>
        </div>
        <slot></slot>
      </div>
      <div class="px-6 py-4 border-t border-gray-200 dark:border-gray-700 flex justify-end space-x-3">
        <button
          class="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
          @click="onCancel"
        >
          {{ cancelText }}
        </button>
        <button
          :class="variant === 'info' ? 'bg-blue-600 dark:bg-blue-700 hover:bg-blue-700 dark:hover:bg-blue-600' : 'bg-red-600 dark:bg-red-700 hover:bg-red-700 dark:hover:bg-red-600'"
          class="px-4 py-2 text-white rounded-lg transition-colors"
          @click="onConfirm"
        >
          {{ confirmText }}
        </button>
      </div>
    </div>
  </Modal>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import Modal from './Modal.vue'
import { IconInfo, IconWarning } from '@/components/icons'

const props = withDefaults(defineProps<{
  title?: string
  message?: string
  cancelText?: string
  confirmText?: string
  variant?: 'danger' | 'info'
}>(), {
  title: 'Confirm Delete',
  message: 'This action cannot be undone.',
  cancelText: 'Cancel',
  confirmText: 'Delete',
  variant: 'danger',
})

const emit = defineEmits<{
  confirm: []
  cancel: []
}>()

const visible = ref(false)

function open() {
  visible.value = true
}

function close() {
  visible.value = false
}

function onCancel() {
  close()
  emit('cancel')
}

function onConfirm() {
  close()
  emit('confirm')
}

defineExpose({ open, close })
</script>
