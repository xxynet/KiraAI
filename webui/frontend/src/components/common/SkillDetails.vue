<template>
  <Modal :model-value="modelValue" content-class="max-w-4xl" @update:model-value="close">
    <div role="dialog" aria-modal="true" aria-labelledby="skill-details-title" class="bg-white dark:bg-gray-900 rounded-lg shadow-xl w-full min-w-0 overflow-hidden flex flex-col max-h-[90vh]">
      <div class="flex items-start justify-between gap-4 px-6 py-4 border-b border-gray-200 dark:border-gray-700">
        <div class="min-w-0">
          <h3 id="skill-details-title" class="text-lg font-semibold text-theme-strong break-words">{{ skill?.name }}</h3>
        </div>
        <button type="button" class="shrink-0 p-1 rounded-md text-theme-faint text-theme-faint-hover enabled:hover:bg-gray-100 dark:enabled:hover:bg-gray-800 transition-colors disabled:opacity-50 disabled:cursor-not-allowed" :aria-label="$t('plugin.close')" :disabled="saving" @click="close">
          <IconClose class="w-6 h-6" />
        </button>
      </div>
      <div class="skill-details-content px-6 py-4 overflow-y-auto overflow-x-hidden min-h-0 min-w-0 max-w-full">
        <section v-if="description" aria-labelledby="skill-description-title" class="mb-5 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 p-4">
          <h4 id="skill-description-title" class="text-sm font-medium text-theme-high">{{ $t('plugin.skills_description') }}</h4>
          <p class="mt-2 text-sm text-theme-supporting whitespace-pre-wrap break-words">{{ description }}</p>
        </section>
        <p v-if="error" role="alert" class="mb-4 text-sm text-red-600 dark:text-red-400 whitespace-pre-wrap">{{ error }}</p>
        <div v-if="loading" role="status" class="flex items-center gap-2 text-theme-subtle">
          <IconSpinner class="w-5 h-5 animate-spin" />{{ $t('plugin.status_loading') }}
        </div>
        <template v-else-if="loaded">
          <div class="flex items-center justify-between gap-3 mb-3">
            <h4 class="font-medium text-theme-high">SKILL.md</h4>
            <button v-if="!editing" type="button" class="text-sm text-blue-600 dark:text-blue-400 hover:underline" @click="editing = true">{{ $t('plugin.skills_edit') }}</button>
          </div>
          <template v-if="editing">
            <p class="mb-3 text-sm text-theme-subtle">{{ $t('plugin.skills_edit_hint') }}</p>
            <MonacoEditor v-model="content" language="markdown" height="50vh" horizontal-scrollbar="hidden" :read-only="saving" />
          </template>
          <PluginReadme v-else :readme="previewContent" :loading="false" :repo-url="null" repo-ref="HEAD" />
        </template>
        <button v-else-if="!loading" type="button" class="text-sm text-blue-600 dark:text-blue-400 hover:underline" @click="loadContent">{{ $t('plugin.skills_retry') }}</button>
      </div>
      <div class="px-6 py-4 flex justify-end gap-3 border-t border-gray-200 dark:border-gray-700">
        <template v-if="editing">
          <button type="button" class="px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-theme-body enabled:hover:bg-gray-50 dark:enabled:hover:bg-gray-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed" :disabled="saving" @click="cancelEdit">{{ $t('plugin.cancel') }}</button>
          <button type="button" class="px-4 py-2 rounded-lg bg-blue-600 dark:bg-blue-700 text-white enabled:hover:bg-blue-700 dark:enabled:hover:bg-blue-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed" :disabled="saving || !dirty" @click="saveContent">
            <IconSpinner v-if="saving" class="inline-block w-4 h-4 mr-1 animate-spin" />{{ $t('plugin.save') }}
          </button>
        </template>
        <button v-else type="button" class="px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-theme-body hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors" @click="close">{{ $t('plugin.close') }}</button>
      </div>
    </div>
  </Modal>
  <ConfirmModal
    ref="discardModal"
    :title="$t('plugin.skills_discard_title')"
    :message="$t('plugin.skills_discard_message')"
    :cancel-text="$t('plugin.cancel')"
    :confirm-text="$t('plugin.skills_discard')"
    @confirm="discardChanges"
  />
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { getSkillContent, updateSkillContent, type SkillItem } from '@/api/skills'
import { notify } from '@/composables/useNotification'
import { IconClose, IconSpinner } from '@/components/icons'
import Modal from './Modal.vue'
import ConfirmModal from './ConfirmModal.vue'
import MonacoEditor from './MonacoEditor.vue'
import PluginReadme from './PluginReadme.vue'

const props = defineProps<{ modelValue: boolean; skill: SkillItem | null }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; saved: [] }>()
const { t } = useI18n()
const content = ref('')
const originalContent = ref('')
const description = ref('')
const loading = ref(false)
const loaded = ref(false)
const editing = ref(false)
const saving = ref(false)
const error = ref<string | null>(null)
const discardModal = ref<InstanceType<typeof ConfirmModal> | null>(null)
const dirty = computed(() => content.value !== originalContent.value)
const previewContent = computed(() => content.value.replace(/^---\r?\n[\s\S]*?\r?\n---(?:\r?\n|$)/, ''))
let request = 0
let closeAfterDiscard = false

watch(() => props.modelValue, visible => {
  if (visible) {
    description.value = props.skill?.description || ''
    void loadContent()
  } else {
    request++
  }
})

async function loadContent() {
  if (!props.skill) return
  const current = ++request
  loading.value = true
  loaded.value = false
  editing.value = false
  error.value = null
  content.value = originalContent.value = ''
  try {
    const response = await getSkillContent(props.skill.id)
    if (current !== request) return
    content.value = originalContent.value = response.data.content
    loaded.value = true
  } catch (e: any) {
    if (current === request) error.value = errorMessage('plugin.skills_content_load_failed', e)
  } finally {
    if (current === request) loading.value = false
  }
}

function errorMessage(key: string, e: any): string {
  const detail = e?.response?.data?.detail || e?.message
  return detail ? `${t(key)}: ${typeof detail === 'string' ? detail : JSON.stringify(detail)}` : t(key)
}

function close() {
  if (saving.value) return
  if (dirty.value) {
    closeAfterDiscard = true
    discardModal.value?.open()
  } else {
    emit('update:modelValue', false)
  }
}

function cancelEdit() {
  if (dirty.value) {
    closeAfterDiscard = false
    discardModal.value?.open()
  } else {
    editing.value = false
  }
}

function discardChanges() {
  content.value = originalContent.value
  editing.value = false
  error.value = null
  if (closeAfterDiscard) emit('update:modelValue', false)
}

async function saveContent() {
  if (!props.skill || saving.value || !dirty.value) return
  saving.value = true
  error.value = null
  try {
    const response = await updateSkillContent(props.skill.id, content.value, originalContent.value)
    originalContent.value = content.value
    description.value = response.data.description
    editing.value = false
    notify(t('plugin.skills_save_success'), 'success')
    emit('saved')
  } catch (e: any) {
    error.value = errorMessage(e?.response?.status === 409 ? 'plugin.skills_save_conflict' : 'plugin.skills_save_failed', e)
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.skill-details-content {
  overflow-wrap: anywhere;
}

.skill-details-content :deep(.plugin-readme pre) {
  white-space: pre-wrap;
  overflow-x: hidden;
}

.skill-details-content :deep(.plugin-readme pre code) {
  white-space: inherit;
}

.skill-details-content :deep(.plugin-readme table) {
  display: table;
  width: 100%;
  table-layout: fixed;
}
</style>
