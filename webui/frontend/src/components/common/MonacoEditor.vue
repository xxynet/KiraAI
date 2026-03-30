<template>
  <div ref="containerRef" class="monaco-container" :style="{ height: computedHeight }"></div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import * as monaco from 'monaco-editor'
import { useAppStore } from '@/stores/app'

const props = withDefaults(
  defineProps<{
    modelValue: string
    language?: string
    height?: number | string
    readOnly?: boolean
  }>(),
  {
    language: 'json',
    height: 500,
    readOnly: false,
  },
)

const computedHeight = computed(() => {
  if (typeof props.height === 'string') return props.height
  return props.height + 'px'
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const containerRef = ref<HTMLDivElement>()
const appStore = useAppStore()
let editor: monaco.editor.IStandaloneCodeEditor | null = null

onMounted(() => {
  if (!containerRef.value) return

  editor = monaco.editor.create(containerRef.value, {
    value: props.modelValue,
    language: props.language,
    theme: appStore.isDark ? 'vs-dark' : 'vs',
    automaticLayout: true,
    readOnly: props.readOnly,
    minimap: { enabled: false },
    scrollBeyondLastLine: false,
    wordWrap: 'on',
    fontSize: 14,
  })

  editor.onDidChangeModelContent(() => {
    if (editor) {
      emit('update:modelValue', editor.getValue())
    }
  })
})

watch(
  () => props.modelValue,
  (newVal) => {
    if (editor && editor.getValue() !== newVal) {
      editor.setValue(newVal)
    }
  },
)

watch(
  () => props.language,
  (newLang) => {
    if (editor) {
      const model = editor.getModel()
      if (model) {
        monaco.editor.setModelLanguage(model, newLang)
      }
    }
  },
)

watch(
  () => appStore.isDark,
  (isDark) => {
    monaco.editor.setTheme(isDark ? 'vs-dark' : 'vs')
  },
)

watch(
  () => props.readOnly,
  (newVal) => {
    if (editor) {
      editor.updateOptions({ readOnly: newVal })
    }
  },
)

onUnmounted(() => {
  const model = editor?.getModel()
  editor?.dispose()
  model?.dispose()
  editor = null
})
</script>
