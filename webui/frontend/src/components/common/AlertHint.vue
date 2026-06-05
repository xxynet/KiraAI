<template>
  <div
    class="mb-4 p-3 rounded-lg border flex items-start"
    :class="typeClasses[type]"
  >
    <slot name="icon">
      <Warning class="w-5 h-5 mr-2 flex-shrink-0 mt-0.5" :class="iconClasses[type]" />
    </slot>
    <p class="text-sm" :class="textClasses[type]">
      <slot />
    </p>
  </div>
</template>

<script setup lang="ts">
import { Warning } from '@element-plus/icons-vue'

withDefaults(defineProps<{
  type?: 'info' | 'warning' | 'error'
}>(), {
  type: 'info',
})

const typeClasses: Record<string, string> = {
  info: 'bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-800',
  warning: 'bg-yellow-50 dark:bg-yellow-900/20 border-yellow-200 dark:border-yellow-800',
  error: 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800',
}

const textClasses: Record<string, string> = {
  info: 'text-blue-700 dark:text-blue-300',
  warning: 'text-yellow-700 dark:text-yellow-300',
  error: 'text-red-700 dark:text-red-300',
}

const iconClasses: Record<string, string> = {
  info: 'text-blue-500 dark:text-blue-400',
  warning: 'text-yellow-500 dark:text-yellow-400',
  error: 'text-red-500 dark:text-red-400',
}
</script>
