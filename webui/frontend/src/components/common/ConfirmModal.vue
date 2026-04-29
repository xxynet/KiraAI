<template>
  <Modal
    v-model="visible"
    content-class="max-w-md"
    @close="onCancel"
  >
    <div class="bg-white dark:bg-gray-800 rounded-lg shadow-xl">
      <div class="px-6 py-4">
        <div class="flex items-center mb-4">
          <div class="bg-red-100 dark:bg-red-900/30 rounded-full p-3 mr-4">
            <svg class="w-6 h-6 text-red-600 dark:text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path>
            </svg>
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
      </div>
      <div class="px-6 py-4 border-t border-gray-200 dark:border-gray-700 flex justify-end space-x-3">
        <button
          class="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
          @click="onCancel"
        >
          {{ cancelText }}
        </button>
        <button
          class="px-4 py-2 bg-red-600 dark:bg-red-700 text-white rounded-lg hover:bg-red-700 dark:hover:bg-red-600 transition-colors"
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

const props = withDefaults(defineProps<{
  title?: string
  message?: string
  cancelText?: string
  confirmText?: string
}>(), {
  title: 'Confirm Delete',
  message: 'This action cannot be undone.',
  cancelText: 'Cancel',
  confirmText: 'Delete',
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
