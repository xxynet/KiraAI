<template>
  <div>
    <!-- Header -->
    <div class="flex justify-between items-center mb-6">
      <h3 class="text-lg font-semibold text-gray-800 dark:text-gray-100">
        {{ $t('pages.persona.title') }}
      </h3>
      <button
        class="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 transition-colors flex items-center"
        @click="openCreateDialog"
      >
        <svg class="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"></path>
        </svg>
        <span>{{ $t('persona.add') }}</span>
      </button>
    </div>

    <!-- Empty State -->
    <div v-if="personas.length === 0" class="flex justify-center items-center py-12">
      <div class="text-center">
        <svg class="w-16 h-16 text-gray-400 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"></path>
        </svg>
        <p class="text-gray-500">{{ $t('persona.no_personas') }}</p>
      </div>
    </div>

    <!-- Persona Cards -->
    <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
      <div
        v-for="persona in personas"
        :key="persona.id"
        class="bg-white dark:bg-gray-900 rounded-lg shadow p-5 flex flex-col justify-between"
      >
        <div>
          <div class="flex items-start justify-between mb-3 min-w-0">
            <div class="flex items-center min-w-0">
              <h4 class="text-base font-semibold text-gray-900 dark:text-gray-100 mr-2 truncate">{{ persona.name }}</h4>
              <span
                class="px-2 py-0.5 text-xs rounded-full bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200 flex-shrink-0"
              >
                {{ formatLabel(persona.format) }}
              </span>
            </div>
          </div>
          <p class="text-sm text-gray-600 dark:text-gray-300 mb-4 line-clamp-3">
            {{ persona.content || $t('persona.no_content') }}
          </p>
        </div>
        <div class="flex justify-end space-x-3 mt-2">
          <button
            class="px-3 py-1.5 text-xs font-medium rounded-md border border-gray-300 text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-800 transition-colors"
            @click="openEditDialog(persona)"
          >
            {{ $t('persona.edit') }}
          </button>
          <button
            v-if="persona.id !== 'default'"
            class="px-3 py-1.5 text-xs font-medium rounded-md border border-red-300 text-red-600 hover:bg-red-50 dark:border-red-600 dark:text-red-400 dark:hover:bg-red-900/30 transition-colors"
            @click="handleDelete(persona.id)"
          >
            {{ $t('common.delete') }}
          </button>
        </div>
      </div>
    </div>

    <!-- Create/Edit Modal -->
    <Modal v-model="dialogVisible" content-class="max-w-4xl" content-style="width: 90%;">
      <div class="bg-white dark:bg-gray-900 rounded-lg shadow-xl w-full mx-4 flex flex-col modal-card" style="max-height: 90vh;">
        <div class="flex justify-between items-center px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <h3 class="text-lg font-semibold text-gray-800 dark:text-gray-100">
            {{ editMode ? $t('persona.edit_title') : $t('persona.modal_title') }}
          </h3>
          <button class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300" @click="dialogVisible = false">
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
            </svg>
          </button>
        </div>
        <div class="px-6 py-4 flex-1 overflow-y-auto">
          <div class="mb-4">
            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
              {{ $t('persona.modal_name_label') }}
            </label>
            <input
              v-model="form.name"
              type="text"
              class="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
              :placeholder="$t('persona.name')"
            />
          </div>
          <div class="mb-4">
            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
              {{ $t('persona.format') }}
            </label>
            <CustomSelect
              v-model="form.format"
              :options="formatOptions"
              :placeholder="$t('persona.format')"
            />
          </div>
          <div class="mb-4">
            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
              {{ $t('persona.modal_content_label') }}
            </label>
            <MonacoEditor
              v-model="form.content"
              :language="monacoLanguage"
              height="50vh"
            />
          </div>
        </div>
        <div class="px-6 py-4 border-t border-gray-200 dark:border-gray-700 flex justify-end space-x-3">
          <button
            class="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
            @click="dialogVisible = false"
          >
            {{ $t('persona.modal_cancel') }}
          </button>
          <button
            class="px-4 py-2 bg-blue-600 dark:bg-blue-700 text-white rounded-lg hover:bg-blue-700 dark:hover:bg-blue-600 transition-colors disabled:opacity-50"
            :disabled="saving"
            @click="handleSave"
          >
            {{ $t('persona.modal_save') }}
          </button>
        </div>
      </div>
    </Modal>

    <ConfirmModal
      ref="confirmModalRef"
      :title="confirmTitle"
      :message="confirmMessage"
      :cancel-text="t('persona.modal_cancel')"
      :confirm-text="t('common.delete')"
      @confirm="onConfirmDelete"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { notify } from '@/composables/useNotification'
import {
  getPersonas, createPersona, updatePersona, deletePersona,
} from '@/api/persona'
import MonacoEditor from '@/components/common/MonacoEditor.vue'
import CustomSelect from '@/components/common/CustomSelect.vue'
import ConfirmModal from '@/components/common/ConfirmModal.vue'
import Modal from '@/components/common/Modal.vue'
import type { PersonaResponse } from '@/types'

const { t } = useI18n()

const confirmModalRef = ref<InstanceType<typeof ConfirmModal>>()

const personas = ref<PersonaResponse[]>([])
const dialogVisible = ref(false)
const editMode = ref(false)
const editId = ref<string | null>(null)
const saving = ref(false)

const confirmTitle = ref('')
const confirmMessage = ref('')
let deleteTargetId: string | null = null

const formatOptions = computed(() => [
  { value: 'text', label: t('persona.format_text') },
  { value: 'markdown', label: t('persona.format_markdown') },
  { value: 'json', label: t('persona.format_json') },
  { value: 'yaml', label: t('persona.format_yaml') },
])

const form = ref({
  name: '',
  format: 'text',
  content: '',
})

const monacoLanguage = computed(() => {
  const map: Record<string, string> = {
    text: 'plaintext',
    markdown: 'markdown',
    json: 'json',
    yaml: 'yaml',
  }
  return map[form.value.format] || 'plaintext'
})

function formatLabel(fmt: string) {
  const map: Record<string, string> = {
    text: t('persona.format_text'),
    markdown: t('persona.format_markdown'),
    json: t('persona.format_json'),
    yaml: t('persona.format_yaml'),
  }
  return map[fmt] || fmt
}

async function loadPersonas() {
  try {
    const res = await getPersonas()
    const list = Array.isArray(res.data) ? res.data : []
    personas.value = list.sort((a, b) => (a.created_at || 0) - (b.created_at || 0))
  } catch (e) {
    notify(t('persona.load_failed'), 'error')
    console.error('Failed to load personas:', e)
  }
}

function openCreateDialog() {
  editMode.value = false
  editId.value = null
  form.value = { name: '', format: 'text', content: '' }
  dialogVisible.value = true
}

function openEditDialog(persona: PersonaResponse) {
  editMode.value = true
  editId.value = persona.id
  form.value = {
    name: persona.name,
    format: persona.format || 'text',
    content: persona.content || '',
  }
  dialogVisible.value = true
}

async function handleSave() {
  const trimmedName = form.value.name?.trim()
  if (!trimmedName) {
    notify(t('persona.form_incomplete'), 'warning')
    return
  }
  saving.value = true
  const payload = {
    name: trimmedName,
    format: form.value.format || 'text',
    content: form.value.content || '',
  }
  try {
    if (editMode.value && editId.value) {
      await updatePersona(editId.value, payload)
    } else {
      await createPersona(payload)
    }
    dialogVisible.value = false
    notify(t('persona.save_success'), 'success')
    await loadPersonas()
  } catch (error: any) {
    notify(t('persona.save_failed') + (error?.message ? ': ' + error.message : ''), 'error')
  } finally {
    saving.value = false
  }
}

function handleDelete(id: string) {
  deleteTargetId = id
  confirmTitle.value = t('persona.delete_confirm_title')
  confirmMessage.value = t('persona.delete_confirm_message')
  confirmModalRef.value?.open()
}

async function onConfirmDelete() {
  if (!deleteTargetId) return
  const id = deleteTargetId
  deleteTargetId = null
  try {
    await deletePersona(id)
    notify(t('persona.delete_success'), 'success')
    await loadPersonas()
  } catch (error: any) {
    notify(t('persona.delete_failed') + (error?.message ? ': ' + error.message : ''), 'error')
  }
}

onMounted(() => {
  loadPersonas()
})
</script>
