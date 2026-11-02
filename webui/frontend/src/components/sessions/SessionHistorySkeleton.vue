<template>
  <div role="status" :aria-label="$t('sessions.history.loading_messages')" class="space-y-4">
    <div v-for="index in count" :key="index" aria-hidden="true" class="flex motion-safe:animate-pulse" :class="index % 2 === 0 ? 'justify-end' : 'justify-start'">
      <div class="flex max-w-[85%] flex-col gap-2" :class="index % 2 === 0 ? 'w-64 items-end' : 'w-80 items-start'">
        <div class="h-3 w-20 rounded bg-gray-200 dark:bg-gray-700" />
        <div class="w-full space-y-2 rounded-lg bg-gray-100 p-4 dark:bg-gray-800">
          <div class="h-3 w-full rounded bg-gray-200 dark:bg-gray-700" />
          <div class="h-3 w-2/3 rounded bg-gray-200 dark:bg-gray-700" />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
withDefaults(defineProps<{ count?: number }>(), { count: 4 })
</script>
