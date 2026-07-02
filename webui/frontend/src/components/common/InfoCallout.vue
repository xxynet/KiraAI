<template>
  <div
    class="flex items-start gap-3 rounded-lg px-4 py-3 text-sm"
    :class="level === 'warning'
      ? 'bg-amber-50 dark:bg-amber-900/20 text-amber-800 dark:text-amber-200'
      : 'bg-blue-50 dark:bg-blue-900/20 text-blue-800 dark:text-blue-200'"
  >
    <IconWarning v-if="level === 'warning'" class="w-5 h-5 mt-0.5 shrink-0" />
    <IconInfo v-else class="w-5 h-5 mt-0.5 shrink-0" />
    <div>
      <p v-if="label" class="font-medium">{{ label }}</p>
      <p v-if="hint" class="mt-1 opacity-80 whitespace-pre-line">{{ hint }}</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { IconInfo, IconWarning } from '@/components/icons'

defineProps<{
  level?: string
  label?: string
  hint?: string
}>()
</script>
