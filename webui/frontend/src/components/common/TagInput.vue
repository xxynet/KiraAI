<template>
  <div class="tag-input" ref="containerRef">
    <div class="tag-input-wrapper" @click="focusInput">
      <template v-for="(item, idx) in modelValue" :key="idx">
        <span
          v-if="editingIndex !== idx"
          class="tag-input-tag"
          @click.stop="startEdit(idx)"
        >
          {{ item }}
          <span class="tag-input-tag-remove" @click.stop="removeItem(idx)">
            <IconX width="12" height="12" />
          </span>
        </span>
        <input
          v-else
          ref="editInputRef"
          :value="editDraft"
          class="tag-input-edit"
          @input="editDraft = ($event.target as HTMLInputElement).value"
          @keydown.enter.prevent="commitEdit"
          @keydown.escape.prevent="cancelEdit"
          @blur="commitEdit"
        />
      </template>
      <input
        ref="inputRef"
        v-model="draft"
        type="text"
        class="tag-input-field"
        :placeholder="modelValue.length === 0 ? (placeholder || '') : ''"
        @keydown.enter.prevent="addItem"
        @keydown.backspace="onBackspace"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick } from 'vue'
import { IconX } from '@/components/icons'

const props = defineProps<{
  modelValue: string[]
  placeholder?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string[]]
}>()

const draft = ref('')
const inputRef = ref<HTMLInputElement>()
const editInputRef = ref<HTMLInputElement[]>()
const containerRef = ref<HTMLElement>()
const editingIndex = ref<number>(-1)
const editDraft = ref('')

function focusInput() {
  if (editingIndex.value >= 0) return
  inputRef.value?.focus()
}

function addItem() {
  const val = draft.value.trim()
  if (!val) return
  emit('update:modelValue', [...props.modelValue, val])
  draft.value = ''
}

function removeItem(idx: number) {
  const copy = [...props.modelValue]
  copy.splice(idx, 1)
  emit('update:modelValue', copy)
  if (editingIndex.value === idx) editingIndex.value = -1
}

function onBackspace() {
  if (draft.value === '' && props.modelValue.length > 0) {
    removeItem(props.modelValue.length - 1)
  }
}

function startEdit(idx: number) {
  editingIndex.value = idx
  editDraft.value = props.modelValue[idx]
  nextTick(() => {
    const el = editInputRef.value?.[0]
    el?.focus()
    el?.select()
  })
}

function commitEdit() {
  if (editingIndex.value < 0) return
  const idx = editingIndex.value
  const val = editDraft.value.trim()
  editingIndex.value = -1
  if (!val) { removeItem(idx); return }
  if (val !== props.modelValue[idx]) {
    const copy = [...props.modelValue]
    copy[idx] = val
    emit('update:modelValue', copy)
  }
}

function cancelEdit() {
  editingIndex.value = -1
}
</script>

<style scoped>
.tag-input-wrapper {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  padding: 6px 10px;
  min-height: 38px;
  border: 1px solid rgba(209, 213, 219, 0.8);
  border-radius: 0.5rem;
  background-color: rgba(255, 255, 255, 0.7);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  cursor: text;
  transition: border-color 0.15s, box-shadow 0.15s;
  width: 100%;
}

.tag-input-wrapper:focus-within {
  border-color: #3b82f6;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.5);
}

.tag-input-tag {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  background-color: rgba(59, 130, 246, 0.15);
  color: #1d4ed8;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
  line-height: 1.4;
  cursor: pointer;
}

.tag-input-tag:hover {
  background-color: rgba(59, 130, 246, 0.25);
}

.tag-input-tag-remove {
  margin-left: 4px;
  cursor: pointer;
  opacity: 0.6;
  transition: opacity 0.15s;
  display: inline-flex;
  align-items: center;
}

.tag-input-tag-remove:hover {
  opacity: 1;
}

.tag-input-edit {
  display: inline-flex;
  padding: 2px 6px;
  font-size: 12px;
  border-radius: 4px;
  outline: none;
  min-width: 40px;
}

.tag-input-field {
  flex: 1 1 80px;
  min-width: 80px;
  border: none !important;
  outline: none !important;
  background: transparent !important;
  backdrop-filter: none !important;
  box-shadow: none !important;
  font-size: 14px;
  line-height: 1.4;
  padding: 0;
}
</style>

<style>
.dark .tag-input-wrapper {
  background-color: rgba(31, 41, 55, 0.7) !important;
  border-color: rgba(75, 85, 99, 0.3);
  color: #f9fafb;
}

.dark .tag-input-wrapper:focus-within {
  border-color: #3b82f6;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.5);
}

.dark .tag-input-tag {
  background-color: rgba(30, 58, 138, 0.3);
  color: #93c5fd;
}

.dark .tag-input-tag:hover {
  background-color: rgba(30, 58, 138, 0.45);
}
</style>
