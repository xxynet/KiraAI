<template>
  <Teleport to="body">
    <Transition name="modal">
      <div
        v-show="modelValue"
        class="fixed inset-0 z-[100] flex items-center justify-center"
        @click.self="onBackdropClick"
      >
        <div class="modal-overlay absolute inset-0 bg-black bg-opacity-50" />
        <div class="modal-panel relative w-full mx-4" :class="contentClass" :style="contentStyle">
          <slot />
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { watch } from 'vue'

/* ------------------------------------------------------------------ */
/*  Global ESC stack — only the top-most modal receives Escape          */
/* ------------------------------------------------------------------ */
const _stack: { close: () => void }[] = []

let _globalListenerAttached = false
function _ensureGlobalListener() {
  if (_globalListenerAttached) return
  _globalListenerAttached = true
  document.addEventListener('keydown', (e: KeyboardEvent) => {
    if (e.key !== 'Escape' || _stack.length === 0) return
    const top = _stack[_stack.length - 1]
    if (top) top.close()
  })
}

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

function onBackdropClick() {
  if (!props.persistent) close()
}

const stackEntry = { close }

watch(() => props.modelValue, (open) => {
  if (open) {
    _stack.push(stackEntry)
    _ensureGlobalListener()
  } else {
    const idx = _stack.indexOf(stackEntry)
    if (idx !== -1) _stack.splice(idx, 1)
  }
})
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
