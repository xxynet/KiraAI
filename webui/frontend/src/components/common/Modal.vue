<template>
  <Teleport to="body">
    <Transition name="modal">
      <div
        ref="rootRef"
        v-show="modelValue"
        class="fixed inset-0 z-[100] flex items-center justify-center"
        @mousedown="onMouseDown"
        @mouseup="onMouseUp"
      >
        <div class="modal-overlay absolute inset-0 bg-black bg-opacity-50" />
        <div ref="panelRef" tabindex="-1" class="modal-panel relative w-full mx-4" :class="contentClass" :style="contentStyle">
          <slot />
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { provide, ref, watch, onUnmounted } from 'vue'
import { modalPanelKey, registerModal } from './modalFocus'

const props = withDefaults(defineProps<{
  modelValue: boolean
  contentClass?: string
  contentStyle?: string
  persistent?: boolean
}>(), {
  contentClass: '',
  contentStyle: '',
  persistent: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  close: []
}>()

function close() {
  emit('update:modelValue', false)
  emit('close')
}

const mouseDownTarget = ref<EventTarget | null>(null)
const panelRef = ref<HTMLElement | null>(null)
const rootRef = ref<HTMLElement | null>(null)
provide(modalPanelKey, panelRef)

function isOutsidePanel(target: EventTarget | null): boolean {
  const panel = panelRef.value
  if (!panel || !(target instanceof Node)) return false
  return !panel.contains(target)
}

function onMouseDown(e: MouseEvent) {
  mouseDownTarget.value = isOutsidePanel(e.target) ? e.target : null
}

function onMouseUp(e: MouseEvent) {
  if (
    !props.persistent &&
    mouseDownTarget.value !== null &&
    isOutsidePanel(e.target)
  ) {
    close()
  }
  mouseDownTarget.value = null
}

let unregister: (() => void) | undefined

watch(() => props.modelValue, (open) => {
  unregister?.()
  unregister = undefined
  if (open && rootRef.value && panelRef.value) {
    unregister = registerModal(rootRef.value, panelRef.value, close)
  }
}, { immediate: true, flush: 'post' })

watch(rootRef, root => {
  if (root && props.modelValue && panelRef.value && !unregister) {
    unregister = registerModal(root, panelRef.value, close)
  }
}, { flush: 'post' })

onUnmounted(() => unregister?.())
</script>

<style scoped>
/* --- enter / leave transitions (Vue <Transition name="modal">) --- */
.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.2s ease;
}
.modal-enter-active .modal-panel,
.modal-leave-active .modal-panel {
  transition: all 0.2s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}
.modal-enter-from .modal-panel,
.modal-leave-to .modal-panel {
  opacity: 0;
  transform: scale(0.95) translateY(-10px);
}
</style>
