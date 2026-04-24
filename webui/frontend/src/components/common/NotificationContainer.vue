<template>
  <div class="fixed top-4 right-4 z-[100] space-y-2 pointer-events-none">
    <TransitionGroup name="notify">
      <div
        v-for="n in notifications"
        :key="n.id"
        class="px-6 py-4 rounded-lg shadow-lg text-white pointer-events-auto"
        :class="typeClass(n.type)"
      >
        {{ n.message }}
      </div>
    </TransitionGroup>
  </div>
</template>

<script setup lang="ts">
import { useNotification } from '@/composables/useNotification'

const { notifications } = useNotification()

function typeClass(type: string): string {
  switch (type) {
    case 'success': return 'bg-green-500'
    case 'error': return 'bg-red-500'
    case 'warning': return 'bg-yellow-500'
    default: return 'bg-blue-500'
  }
}
</script>

<style scoped>
.notify-enter-active,
.notify-leave-active {
  transition: all 0.3s ease;
}
.notify-enter-from {
  opacity: 0;
  transform: translateX(100%);
}
.notify-leave-to {
  opacity: 0;
  transform: translateX(100%);
}
</style>
