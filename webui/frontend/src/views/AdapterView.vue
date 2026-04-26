<template>
  <div>
    <!-- Header -->
    <div class="flex justify-between items-center mb-6">
      <h3 class="text-lg font-semibold text-gray-800 dark:text-gray-100">
        {{ $t('pages.adapter.title') }}
      </h3>
      <button
        class="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 transition-colors flex items-center"
        @click="openCreateDialog"
      >
        <svg class="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"></path>
        </svg>
        <span>{{ $t('adapter.add') }}</span>
      </button>
    </div>

    <!-- Empty State -->
    <div v-if="adapters.length === 0" class="flex justify-center items-center py-12">
      <div class="text-center">
        <svg class="w-16 h-16 text-gray-400 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"></path>
        </svg>
        <p class="text-gray-500">{{ $t('adapter.no_adapters') }}</p>
      </div>
    </div>

    <!-- Adapter Cards -->
    <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
      <div
        v-for="adapter in adapters"
        :key="adapter.id"
        class="bg-white dark:bg-gray-900 rounded-lg shadow p-5 flex flex-col justify-between"
      >
        <div class="flex items-start justify-between mb-4">
          <div class="min-w-0 flex-1">
            <div class="flex items-center min-w-0">
              <h4 class="text-base font-semibold text-gray-900 dark:text-gray-100 mr-2 truncate">{{ adapter.name }}</h4>
              <span
                class="px-2 py-0.5 text-xs rounded-full flex-shrink-0"
                :class="adapter.status === 'active'
                  ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200'
                  : 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300'"
              >
                {{ adapter.status }}
              </span>
            </div>
            <p class="mt-1 text-sm text-gray-500 dark:text-gray-400 truncate">{{ adapter.platform }}</p>
          </div>
          <ToggleSwitch
            :model-value="adapter.status === 'active'"
            @update:model-value="toggleStatus(adapter)"
          />
        </div>
        <p v-if="adapter.description" class="text-sm text-gray-600 dark:text-gray-300 mb-4 break-words line-clamp-3">
          {{ adapter.description }}
        </p>
        <div class="flex justify-end space-x-3 mt-4">
          <button
            class="px-3 py-1.5 text-xs font-medium rounded-md border border-gray-300 text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-800 transition-colors"
            @click="openEditDialog(adapter)"
          >
            {{ $t('adapter.edit') }}
          </button>
          <button
            class="px-3 py-1.5 text-xs font-medium rounded-md border border-red-300 text-red-600 hover:bg-red-50 dark:border-red-600 dark:text-red-400 dark:hover:bg-red-900/30 transition-colors"
            @click="handleDelete(adapter.id)"
          >
            {{ $t('adapter.delete') }}
          </button>
        </div>
      </div>
    </div>

    <!-- Create/Edit Modal -->
    <Modal v-model="dialogVisible" content-class="max-w-md">
      <div class="bg-white dark:bg-gray-900 rounded-lg shadow-xl w-full mx-4 flex flex-col modal-card" style="max-height: 90vh;">
        <div class="flex justify-between items-center px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <h3 class="text-lg font-semibold text-gray-800 dark:text-gray-100">
            {{ editMode ? $t('adapter.edit_title') : $t('adapter.add') }}
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
              {{ $t('adapter.modal_name_label') }}
            </label>
            <input
              v-model="form.name"
              type="text"
              class="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
              :placeholder="$t('adapter.name')"
            />
          </div>
          <div class="mb-4">
            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
              {{ $t('adapter.modal_platform_label') }}
            </label>
            <CustomSelect
              v-model="form.platform"
              :options="platformOptions"
              :placeholder="$t('adapter.platform_placeholder') || 'Select adapter platform...'"
              :disabled="editMode"
              @update:model-value="onPlatformChange"
            />
          </div>
          <div class="mb-4">
            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
              {{ $t('adapter.modal_desc_label') }}
            </label>
            <textarea
              v-model="form.description"
              rows="2"
              class="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors resize-none"
              :placeholder="$t('adapter.modal_desc_placeholder')"
            />
          </div>
          <div class="mb-4">
            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
              {{ $t('adapter.modal_status_label') }}
            </label>
            <div class="flex items-center">
              <ToggleSwitch v-model="formActive" />
            </div>
          </div>
          <div v-if="adapterSchema">
            <h4 class="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">{{ $t('adapter.config') }}</h4>
            <ConfigForm ref="configFormRef" v-model="form.config" :schema="adapterSchema" />
          </div>
        </div>
        <div class="px-6 py-4 border-t border-gray-200 dark:border-gray-700 flex justify-end space-x-3">
          <button
            class="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
            @click="dialogVisible = false"
          >
            {{ $t('adapter.modal_cancel') }}
          </button>
          <button
            class="px-4 py-2 bg-blue-600 dark:bg-blue-700 text-white rounded-lg hover:bg-blue-700 dark:hover:bg-blue-600 transition-colors disabled:opacity-50"
            :disabled="saving"
            @click="handleSave"
          >
            {{ $t('adapter.modal_save') }}
          </button>
        </div>
      </div>
    </Modal>

    <ConfirmModal
      ref="confirmModalRef"
      :title="confirmTitle"
      :message="confirmMessage"
      :cancel-text="t('adapter.modal_cancel')"
      :confirm-text="t('adapter.delete')"
      @confirm="onConfirmDelete"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { notify } from '@/composables/useNotification'
import {
  getAdapters, getAdapterPlatforms, getAdapterSchema,
  createAdapter, updateAdapter, deleteAdapter,
} from '@/api/adapter'
import ConfigForm from '@/components/common/ConfigForm.vue'
import CustomSelect from '@/components/common/CustomSelect.vue'
import ConfirmModal from '@/components/common/ConfirmModal.vue'
import Modal from '@/components/common/Modal.vue'
import ToggleSwitch from '@/components/common/ToggleSwitch.vue'
import type { AdapterResponse } from '@/types'

const { t } = useI18n()

const configFormRef = ref<InstanceType<typeof ConfigForm>>()
const confirmModalRef = ref<InstanceType<typeof ConfirmModal>>()

const adapters = ref<AdapterResponse[]>([])
const platforms = ref<string[]>([])
const dialogVisible = ref(false)
const editMode = ref(false)
const editId = ref<string | null>(null)
const adapterSchema = ref<any>(null)
const saving = ref(false)
const formActive = ref(false)
let platformChangeId = 0

const confirmTitle = ref('')
const confirmMessage = ref('')
let deleteTargetId: string | null = null

const platformOptions = computed(() =>
  platforms.value.map(p => ({ value: p, label: p }))
)

const form = ref({
  name: '',
  platform: '',
  description: '',
  config: {} as Record<string, any>,
})

async function loadAdapters() {
  try {
    const res = await getAdapters()
    adapters.value = Array.isArray(res.data) ? res.data : []
  } catch (e) {
    notify(t('adapter.load_failed'), 'error')
    console.error('Failed to load adapters:', e)
  }
}

async function loadPlatforms() {
  try {
    const res = await getAdapterPlatforms()
    platforms.value = Array.isArray(res.data) ? res.data : []
  } catch (e) {
    notify(t('adapter.platform_load_failed'), 'error')
    console.error('Failed to load platforms:', e)
  }
}

function openCreateDialog() {
  editMode.value = false
  editId.value = null
  form.value = { name: '', platform: '', description: '', config: {} }
  formActive.value = false
  adapterSchema.value = null
  ++platformChangeId
  dialogVisible.value = true
  if (platforms.value.length === 0) loadPlatforms()
}

async function openEditDialog(adapter: AdapterResponse) {
  editMode.value = true
  editId.value = adapter.id
  form.value = {
    name: adapter.name,
    platform: adapter.platform,
    description: adapter.description || '',
    config: deepClone(adapter.config || {}),
  }
  formActive.value = adapter.status === 'active'
  adapterSchema.value = null
  ++platformChangeId
  if (platforms.value.length === 0) {
    await loadPlatforms()
  }
  dialogVisible.value = true
  onPlatformChange(adapter.platform, true)
}

function deepClone<T>(obj: T): T {
  try {
    return structuredClone(obj)
  } catch {
    return JSON.parse(JSON.stringify(obj))
  }
}

async function onPlatformChange(platform: string, preserveConfig = false) {
  if (!platform) { ++platformChangeId; adapterSchema.value = null; return }
  adapterSchema.value = null
  if (!preserveConfig) {
    form.value.config = {}
  }
  const requestId = ++platformChangeId
  try {
    const res = await getAdapterSchema(platform)
    if (requestId === platformChangeId) {
      adapterSchema.value = res.data
    }
  } catch {
    if (requestId === platformChangeId) {
      adapterSchema.value = null
    }
  }
}

async function handleSave() {
  const trimmedName = form.value.name?.trim()
  const trimmedPlatform = form.value.platform?.trim()
  if (!trimmedName || !trimmedPlatform) {
    notify(t('adapter.form_incomplete'), 'warning')
    return
  }
  const validateRes = configFormRef.value?.validate()
  if (validateRes && !validateRes.valid) {
    notify(validateRes.message || t('configform.invalid_json'), 'error')
    return
  }
  saving.value = true
  const payload = {
    name: trimmedName,
    platform: trimmedPlatform,
    status: formActive.value ? 'active' : 'inactive',
    description: form.value.description?.trim() || '',
    config: form.value.config,
  }
  try {
    if (editMode.value && editId.value) {
      await updateAdapter(editId.value, payload)
    } else {
      await createAdapter(payload)
    }
    dialogVisible.value = false
    notify(t('adapter.save_success'), 'success')
    await loadAdapters()
  } catch (error: any) {
    notify(t('adapter.save_failed') + (error?.message ? ': ' + error.message : ''), 'error')
  } finally {
    saving.value = false
  }
}

async function toggleStatus(adapter: AdapterResponse) {
  const newStatus = adapter.status === 'active' ? 'inactive' : 'active'
  try {
    await updateAdapter(adapter.id, {
      name: adapter.name,
      platform: adapter.platform,
      status: newStatus,
      description: adapter.description || '',
      config: adapter.config || {},
    })
    notify(t('adapter.status_updated'), 'success')
    await loadAdapters()
  } catch (error: any) {
    notify(t('adapter.status_update_failed') + (error?.message ? ': ' + error.message : ''), 'error')
  }
}

function handleDelete(id: string) {
  deleteTargetId = id
  confirmTitle.value = t('adapter.delete_confirm_title')
  confirmMessage.value = t('adapter.delete_confirm_message')
  confirmModalRef.value?.open()
}

async function onConfirmDelete() {
  if (!deleteTargetId) return
  const id = deleteTargetId
  deleteTargetId = null
  try {
    await deleteAdapter(id)
    notify(t('adapter.delete_success'), 'success')
    await loadAdapters()
  } catch (error: any) {
    notify(t('adapter.delete_failed') + (error?.message ? ': ' + error.message : ''), 'error')
  }
}

onMounted(() => {
  loadAdapters()
})
</script>


