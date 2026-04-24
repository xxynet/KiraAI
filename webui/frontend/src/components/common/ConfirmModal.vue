<template>
  <Modal
    v-model="visible"
    content-class="max-w-md"
    @close="onCancel"
  >
    <div
      class="rounded-lg shadow-xl"
      :class="isDark ? 'bg-gray-800' : 'bg-white'"
    >
      <div class="px-6 py-4">
        <div class="flex items-center mb-4">
          <div
            class="rounded-full p-3 mr-4"
            :class="isDark ? 'bg-red-900/30' : 'bg-red-100'"
          >
            <svg
              class="w-6 h-6"
              :class="isDark ? 'text-red-400' : 'text-red-600'"
              fill="none" stroke="currentColor" viewBox="0 0 24 24"
            >
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path>
            </svg>
          </div>
          <div>
            <h3
              class="text-lg font-semibold"
              :class="isDark ? 'text-gray-100' : 'text-gray-800'"
            >
              {{ title }}
            </h3>
            <p
              class="text-sm mt-1"
              :class="isDark ? 'text-gray-400' : 'text-gray-500'"
            >
              {{ message }}
            </p>
          </div>
        </div>
      </div>
      <div
        class="px-6 py-4 flex justify-end space-x-3"
        :class="isDark ? 'border-t border-gray-700' : 'border-t border-gray-200'"
      >
        <button
          class="px-4 py-2 border rounded-lg transition-colors"
          :class="isDark
            ? 'border-gray-600 text-gray-300 hover:bg-gray-700'
            : 'border-gray-300 text-gray-700 hover:bg-gray-50'"
          @click="onCancel"
        >
          {{ cancelText }}
        </button>
        <button
          class="px-4 py-2 text-white rounded-lg transition-colors"
          :class="confirmClass"
          @click="onConfirm"
        >
          {{ confirmText }}
        </button>
      </div>
    </div>
  </Modal>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import Modal from './Modal.vue'

const props = withDefaults(defineProps<{
  title?: string
  message?: string
  cancelText?: string
  confirmText?: string
  confirmClass?: string
}>(), {
  title: 'Confirm Delete',
  message: 'This action cannot be undone.',
  cancelText: 'Cancel',
  confirmText: 'Delete',
  confirmClass: 'bg-red-600 hover:bg-red-700 dark:bg-red-700 dark:hover:bg-red-600',
})

const emit = defineEmits<{
  confirm: []
  cancel: []
}>()

const visible = ref(false)

const isDark = computed(() => document.documentElement.classList.contains('dark'))

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
