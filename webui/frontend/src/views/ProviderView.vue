<template>
  <div class="flex gap-6 h-[calc(100vh-8rem)]">
    <!-- Left: Provider List -->
    <div class="w-1/3 bg-white rounded-lg shadow p-6 flex flex-col overflow-hidden">
      <div class="flex justify-between items-center mb-6 flex-shrink-0">
        <h3 class="text-lg font-semibold text-gray-800">
          {{ $t('pages.provider.title') }}
        </h3>
        <button class="bg-blue-600 text-white px-3 py-2 rounded-lg hover:bg-blue-700 transition-colors flex items-center" @click="openCreateDialog">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"></path>
          </svg>
          <span class="ml-1">{{ $t('provider.add_short') }}</span>
        </button>
      </div>

      <div v-if="providers.length === 0" class="flex justify-center items-center py-12 flex-1">
        <div class="text-center">
          <svg class="w-16 h-16 text-gray-400 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z"></path>
          </svg>
          <p class="text-gray-500 text-sm">{{ $t('provider.no_providers') }}</p>
        </div>
      </div>

      <div v-else class="space-y-2 overflow-y-auto flex-1">
          <div
            v-for="provider in providers"
            :key="provider.id"
            class="provider-item flex items-center p-3 rounded-lg cursor-pointer transition-colors hover:bg-gray-100"
            :class="{ 'bg-blue-50 border border-blue-200': selectedId === provider.id, 'border border-transparent': selectedId !== provider.id }"
            @click="selectProvider(provider.id)"
          >
            <div class="mr-3">
              <svg class="w-5 h-5 text-gray-500 dark:text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z"></path>
              </svg>
            </div>
            <div class="flex-1 min-w-0">
              <div class="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">{{ provider.name }}</div>
              <div class="text-xs text-gray-500">{{ provider.type }}</div>
            </div>
            <span class="px-2 py-1 text-xs rounded-full" :class="provider.status === 'active' ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200' : 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300'">
              {{ provider.status }}
            </span>
          </div>
        </div>
    </div>

    <!-- Right: Provider Config Panel -->
    <div class="w-2/3 bg-white rounded-lg shadow p-6 flex flex-col">
      <div v-if="!selectedId" class="flex justify-center items-center flex-1">
        <div class="text-center">
          <svg class="w-16 h-16 text-gray-400 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z"></path>
          </svg>
          <p class="text-gray-500">{{ $t('provider.select_provider') }}</p>
        </div>
      </div>

      <div v-else class="flex flex-col flex-1 overflow-y-auto">
        <div class="border-b border-gray-200 dark:border-gray-700 pb-4 mb-6">
          <h3 class="text-xl font-semibold text-gray-800 dark:text-gray-100 truncate">{{ selectedProvider?.name }}</h3>
          <p class="text-sm text-gray-500 mt-1 truncate">{{ selectedProvider?.type }}</p>
        </div>

        <!-- Provider Config Fields -->
        <div class="space-y-4 mb-6">
          <div class="mb-4">
            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">{{ $t('provider.name') }}</label>
            <input v-model="providerName" type="text" class="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors" />
          </div>
          <div v-if="providerSchema && Object.keys(providerSchema.provider_config || providerSchema).length > 0">
            <ConfigForm
              ref="configFormRef"
              v-model="providerConfigValues"
              :schema="providerSchema"
            />
          </div>
          <div v-else-if="schemaError" class="text-red-500 dark:text-red-400 py-2">{{ $t('provider.schema_error') }}</div>
          <div v-else-if="schemaLoading" class="text-center text-gray-500 py-4">{{ $t('provider.schema_loading') }}</div>
          <div v-else class="text-gray-500 dark:text-gray-400 py-2">{{ $t('provider.schema_none') }}</div>
          <div class="flex justify-end space-x-3 pt-2">
            <button class="bg-blue-600 text-white px-3 py-2 rounded-lg hover:bg-blue-700 transition-colors flex items-center disabled:opacity-50" :disabled="saving || schemaError" @click="saveProviderConfig">
              {{ $t('provider.save') }}
            </button>
            <button class="bg-red-600 text-white px-3 py-2 rounded-lg hover:bg-red-700 transition-colors flex items-center" @click="handleDelete">
              {{ $t('provider.delete') }}
            </button>
          </div>
        </div>

        <!-- Model Groups -->
        <div v-if="selectedProvider?.supported_model_types?.length" class="space-y-3">
          <h4 class="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">{{ $t('provider.model_groups') }}</h4>
          <div
            v-for="modelType in selectedProvider.supported_model_types"
            :key="modelType"
            class="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden"
          >
            <div
              class="flex items-center justify-between px-4 py-3 bg-gray-50 dark:bg-gray-800 cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
              @click="toggleModelGroup(modelType)"
            >
              <div class="flex items-center">
                <svg
                  class="w-5 h-5 text-gray-500 dark:text-gray-400 mr-2 transition-transform duration-200"
                  :class="{ 'rotate-180': activeModelGroups.includes(modelType) }"
                  fill="none" stroke="currentColor" viewBox="0 0 24 24"
                >
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path>
                </svg>
                <span class="font-medium text-gray-700 dark:text-gray-200">{{ $t(`provider.model_group_${modelType}`) }}</span>
              </div>
              <button class="p-1 text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 transition-colors" @click.stop="openAddModelDialog(modelType)">
                <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"></path>
                </svg>
              </button>
            </div>
            <div v-show="activeModelGroups.includes(modelType)" class="px-4 py-3 bg-white dark:bg-gray-900">
              <div v-if="providerModels[modelType] && Object.keys(providerModels[modelType]).length" class="space-y-2">
                <div
                  v-for="(modelConfig, modelId) in providerModels[modelType]"
                  :key="modelId"
                  class="flex items-center justify-between py-1 border-b border-gray-100 dark:border-gray-800 last:border-b-0"
                >
                  <span class="flex-1 text-sm text-gray-800 dark:text-gray-100">{{ modelId }}</span>
                  <div class="flex items-center space-x-2">
                    <button class="p-1 text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 transition-colors disabled:opacity-50" :disabled="!providerSchema" @click="editModel(modelType, String(modelId), modelConfig)">
                      <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4"></path>
                      </svg>
                    </button>
                    <button class="p-1 text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-300 transition-colors disabled:opacity-50" :disabled="!providerSchema" @click="removeModel(modelType, String(modelId))">
                      <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                      </svg>
                    </button>
                  </div>
                </div>
              </div>
              <div v-else class="text-sm text-gray-500 dark:text-gray-400 text-center py-4">
                {{ $t('provider.no_models') }}
              </div>
              <button class="mt-2 px-3 py-1.5 text-sm border border-gray-300 dark:border-gray-600 rounded-lg text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors disabled:opacity-50" :disabled="!providerSchema" @click="openAddModelDialog(modelType)">
                + {{ $t('provider.add_model') }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Create Provider Dialog -->
    <Modal v-model="createDialogVisible" content-class="max-w-md">
      <div class="bg-white dark:bg-gray-900 rounded-lg shadow-xl w-full mx-4 flex flex-col modal-card" style="max-height: 90vh;">
        <div class="flex justify-between items-center px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <h3 class="text-lg font-semibold text-gray-800 dark:text-gray-100">{{ $t('provider.add') }}</h3>
          <button class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300" @click="createDialogVisible = false">
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
            </svg>
          </button>
        </div>
        <div class="px-6 py-4 flex-1 overflow-y-auto">
          <div class="mb-4">
            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">{{ $t('provider.name') }}</label>
            <input v-model="createForm.name" type="text" class="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 focus:outline-none bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100" :placeholder="$t('provider.name_placeholder') || 'Enter provider name...'" />
          </div>
          <div class="mb-4">
            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">{{ $t('provider.type') }}</label>
            <CustomSelect
              v-model="createForm.type"
              :options="providerTypes.map(t => ({ value: t, label: t }))"
              :placeholder="$t('provider.select_type') || 'Select provider type...'"
              @update:modelValue="onCreateTypeChange"
            />
          </div>
          <div v-if="createSchema">
            <ConfigForm ref="createConfigFormRef" v-model="createForm.config" :schema="createSchema" />
          </div>
        </div>
        <div class="px-6 py-4 border-t border-gray-200 dark:border-gray-700 flex justify-end space-x-3">
          <button class="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors" @click="createDialogVisible = false">{{ $t('provider.cancel') }}</button>
          <button class="px-4 py-2 bg-blue-600 dark:bg-blue-700 text-white rounded-lg hover:bg-blue-700 dark:hover:bg-blue-600 transition-colors" :disabled="creating" @click="handleCreate">{{ $t('provider.save') }}</button>
        </div>
      </div>
    </Modal>

    <!-- Add/Edit Model Dialog -->
    <Modal v-model="modelDialogVisible" content-class="max-w-md">
      <div class="bg-white dark:bg-gray-900 rounded-lg shadow-xl w-full mx-4 modal-card">
        <div class="flex justify-between items-center px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <h3 class="text-lg font-semibold text-gray-800 dark:text-gray-100">{{ modelEditMode ? $t('provider.edit_model') : $t('provider.add_model') }}</h3>
          <button class="text-gray-400 hover:text-gray-600 dark:text-gray-400 dark:hover:text-gray-300" @click="modelDialogVisible = false">
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
            </svg>
          </button>
        </div>
        <div class="px-6 py-4">
          <!-- Model type label -->
          <div class="mb-2">
            <p class="text-sm text-gray-500 dark:text-gray-400">{{ $t(`provider.model_group_${modelForm.model_type}`) }}</p>
          </div>
          <div class="mb-4">
            <div class="flex items-center mb-2">
              <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">{{ $t('provider.model_id') }}</label>
              <div class="relative ml-1 group">
                <button type="button" class="p-0.5" :aria-label="$t('provider.model_id_tooltip')">
                  <svg class="w-4 h-4 text-gray-400 dark:text-gray-500 cursor-help" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>
                  </svg>
                </button>
                <div role="tooltip" class="absolute left-1/2 -translate-x-1/2 bottom-full mb-2 px-3 py-2 bg-gray-800 dark:bg-gray-700 text-white text-xs rounded-lg shadow-lg opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-200 whitespace-nowrap z-50">
                  {{ $t('provider.model_id_tooltip') }}
                </div>
              </div>
            </div>
            <input v-model="modelForm.model_id" type="text" class="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors" :placeholder="$t('provider.model_id_placeholder')" :disabled="modelEditMode" />
            <p class="text-xs text-gray-500 dark:text-gray-400 mt-1">{{ $t('provider.model_id_hint') }}</p>
          </div>
          <div v-if="modelSchema">
            <ConfigForm ref="modelConfigFormRef" v-model="modelForm.config" :schema="modelSchema" />
          </div>
        </div>
        <div class="px-6 py-4 border-t border-gray-200 dark:border-gray-700 flex justify-end space-x-3">
          <button class="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors" @click="modelDialogVisible = false">{{ $t('provider.cancel') }}</button>
          <button class="px-4 py-2 bg-blue-600 dark:bg-blue-700 text-white rounded-lg hover:bg-blue-700 dark:hover:bg-blue-600 transition-colors" :disabled="addingModel" @click="handleAddModel">{{ $t('provider.save') }}</button>
        </div>
      </div>
    </Modal>

    <ConfirmModal
      ref="confirmModalRef"
      :title="confirmTitle"
      :message="confirmMessage"
      :cancel-text="t('provider.cancel')"
      :confirm-text="t('provider.delete')"
      @confirm="onConfirmAction"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { notify } from '@/composables/useNotification'
import {
  getProviders, getProviderTypes, getProviderSchema,
  createProvider, updateProvider, deleteProvider,
  addModel, updateModel, getModels, deleteModel,
} from '@/api/provider'
import ConfigForm from '@/components/common/ConfigForm.vue'
import CustomSelect from '@/components/common/CustomSelect.vue'
import ConfirmModal from '@/components/common/ConfirmModal.vue'
import Modal from '@/components/common/Modal.vue'
import type { ProviderResponse } from '@/types'

const { t } = useI18n()

const configFormRef = ref<InstanceType<typeof ConfigForm>>()
const createConfigFormRef = ref<InstanceType<typeof ConfigForm>>()
const modelConfigFormRef = ref<InstanceType<typeof ConfigForm>>()
const confirmModalRef = ref<InstanceType<typeof ConfirmModal>>()

const confirmTitle = ref('')
const confirmMessage = ref('')
let confirmCallback: (() => void) | null = null

function openConfirm(title: string, message: string, onConfirm: () => void) {
  confirmTitle.value = title
  confirmMessage.value = message
  confirmCallback = onConfirm
  confirmModalRef.value?.open()
}

function onConfirmAction() {
  if (confirmCallback) {
    confirmCallback()
    confirmCallback = null
  }
}

const providers = ref<ProviderResponse[]>([])
const selectedId = ref<string | null>(null)
const providerTypes = ref<string[]>([])
const providerSchema = ref<any>(null)
const providerConfigValues = ref<Record<string, any>>({})
const providerModels = ref<Record<string, any>>({})
const activeModelGroups = ref<string[]>([])
const providerName = ref('')
const saving = ref(false)
const schemaLoading = ref(false)
const schemaError = ref(false)
let selectProviderRequestId = 0
let createTypeChangeId = 0

// Create provider
const createDialogVisible = ref(false)
const createForm = ref({ name: '', type: '', config: {} as Record<string, any> })
const createSchema = ref<any>(null)
const creating = ref(false)

// Add model
const modelDialogVisible = ref(false)
const modelForm = ref({ model_id: '', model_type: '', config: {} as Record<string, any> })
const modelSchema = ref<any>(null)
const addingModel = ref(false)
const modelEditMode = ref(false)
const originalModelId = ref('')

const selectedProvider = computed(() => providers.value.find(p => p.id === selectedId.value))

function deepClone<T>(obj: T): T {
  try {
    return structuredClone(obj)
  } catch {
    return JSON.parse(JSON.stringify(obj))
  }
}

function toggleModelGroup(modelType: string) {
  const idx = activeModelGroups.value.indexOf(modelType)
  if (idx >= 0) {
    activeModelGroups.value.splice(idx, 1)
  } else {
    activeModelGroups.value.push(modelType)
  }
}

async function loadProviders() {
  try {
    const res = await getProviders()
    providers.value = Array.isArray(res.data) ? res.data : []
    // Validate selectedId still exists (only after successful fetch)
    if (selectedId.value && !providers.value.some(p => p.id === selectedId.value)) {
      selectedId.value = null
      providerSchema.value = null
      providerConfigValues.value = {}
      providerModels.value = {}
      activeModelGroups.value = []
    }
  } catch (e) {
    providers.value = []
    console.error('Failed to load providers:', e)
    notify(t('provider.load_failed'), 'error')
  }
}

async function selectProvider(id: string) {
  selectedId.value = id
  providerSchema.value = null
  providerConfigValues.value = {}
  providerModels.value = {}
  activeModelGroups.value = []
  providerName.value = ''
  schemaLoading.value = true
  schemaError.value = false
  const currentRequestId = ++selectProviderRequestId
  const provider = providers.value.find(p => p.id === id)
  if (!provider) {
    schemaLoading.value = false
    return
  }

  // Seed from existing provider data immediately so saveProviderConfig()
  // has valid values even if the schema request fails.
  providerConfigValues.value = deepClone(provider.config || {})
  providerName.value = provider.name || ''

  try {
    const schemaRes = await getProviderSchema(provider.type)
    if (selectProviderRequestId === currentRequestId) {
      providerSchema.value = schemaRes.data
    }
  } catch (e: any) {
    console.error('Error loading provider schema:', e)
    if (selectProviderRequestId === currentRequestId) {
      providerSchema.value = null
      schemaError.value = true
    }
  } finally {
    if (selectProviderRequestId === currentRequestId) {
      schemaLoading.value = false
    }
  }

  try {
    const modelsRes = await getModels(id)
    if (selectProviderRequestId === currentRequestId) {
      providerModels.value = deepClone(modelsRes.data || {})
    }
  } catch {
    if (selectProviderRequestId === currentRequestId) {
      providerModels.value = {}
    }
  }
}

function openCreateDialog() {
  ++createTypeChangeId
  createForm.value = { name: '', type: '', config: {} }
  createSchema.value = null
  createDialogVisible.value = true
  if (providerTypes.value.length === 0) {
    getProviderTypes().then(res => { providerTypes.value = res.data }).catch(() => {
      notify(t('provider.load_types_failed'), 'error')
    })
  }
}

async function onCreateTypeChange(type: string) {
  if (!type) { ++createTypeChangeId; createSchema.value = null; createForm.value.config = {}; return }
  createSchema.value = null
  createForm.value.config = {}
  const requestId = ++createTypeChangeId
  try {
    const res = await getProviderSchema(type)
    if (requestId === createTypeChangeId) {
      createSchema.value = res.data
    }
  } catch {
    if (requestId === createTypeChangeId) {
      createSchema.value = null
    }
  }
}

async function handleCreate() {
  const name = createForm.value.name.trim()
  const type = createForm.value.type.trim()
  if (!name || !type) {
    notify(t('provider.fill_required_fields'), 'warning')
    return
  }
  const validateRes = createConfigFormRef.value?.validate()
  if (validateRes && !validateRes.valid) {
    notify(validateRes.message || t('configform.invalid_json'), 'error')
    return
  }
  creating.value = true
  try {
    await createProvider({
      name,
      type,
      status: 'active',
      config: createForm.value.config,
    })
    createDialogVisible.value = false
    notify(t('provider.create_success'), 'success')
    await loadProviders()
  } catch (error: any) {
    notify(t('provider.create_failed') + (error?.message ? ': ' + error.message : ''), 'error')
  } finally {
    creating.value = false
  }
}

async function saveProviderConfig() {
  if (!selectedId.value) return
  const provider = selectedProvider.value
  if (!provider) return
  if (schemaError.value) {
    notify(t('provider.schema_error'), 'error')
    return
  }
  const validateRes = configFormRef.value?.validate()
  if (validateRes && !validateRes.valid) {
    notify(validateRes.message || t('configform.invalid_json'), 'error')
    return
  }
  saving.value = true
  try {
    await updateProvider(selectedId.value, {
      name: providerName.value,
      type: provider.type,
      status: provider.status,
      config: providerConfigValues.value,
    })
    notify(t('provider.save_success'), 'success')
    await loadProviders()
  } catch (error: any) {
    notify(t('provider.save_failed') + (error?.message ? ': ' + error.message : ''), 'error')
  } finally {
    saving.value = false
  }
}

async function handleDelete() {
  if (!selectedId.value) return
  const deletingId = selectedId.value
  openConfirm(t('provider.delete_confirm_title'), t('provider.delete_confirm_message'), async () => {
    try {
      await deleteProvider(deletingId)
      if (selectedId.value === deletingId) {
        selectedId.value = null
        providerSchema.value = null
        providerConfigValues.value = {}
        providerModels.value = {}
        activeModelGroups.value = []
      }
      notify(t('provider.delete_success'), 'success')
      await loadProviders()
    } catch (error: any) {
      notify(t('provider.delete_failed') + (error?.message ? ': ' + error.message : ''), 'error')
    }
  })
}

function openAddModelDialog(modelType: string) {
  if (!providerSchema.value) return
  modelEditMode.value = false
  originalModelId.value = ''
  modelForm.value = { model_id: '', model_type: modelType, config: {} }
  // Get model config schema from provider schema
  const modelConfigs = providerSchema.value?.model_config || {}
  modelSchema.value = modelConfigs[modelType] || null
  modelDialogVisible.value = true
}

async function handleAddModel() {
  if (!selectedId.value || !modelForm.value.model_id) return
  const providerId = selectedId.value
  const isEdit = modelEditMode.value
  const validateRes = modelConfigFormRef.value?.validate()
  if (validateRes && !validateRes.valid) {
    notify(validateRes.message || t('configform.invalid_json'), 'error')
    return
  }
  addingModel.value = true
  try {
    if (isEdit) {
      await updateModel(providerId, modelForm.value.model_type, originalModelId.value, {
        config: modelForm.value.config,
      })
    } else {
      await addModel(providerId, {
        model_type: modelForm.value.model_type,
        model_id: modelForm.value.model_id,
        config: modelForm.value.config,
      })
    }
    modelDialogVisible.value = false
    notify(isEdit ? t('provider.model_update_success') : t('provider.model_add_success'), 'success')
    modelEditMode.value = false
    originalModelId.value = ''
    try {
      const modelsRes = await getModels(providerId)
      if (selectedId.value === providerId) {
        providerModels.value = modelsRes.data || {}
      }
    } catch { /* refresh failure is non-critical */ }
  } catch (error: any) {
    notify((isEdit ? t('provider.model_update_failed') : t('provider.model_add_failed')) + (error?.message ? ': ' + error.message : ''), 'error')
  } finally {
    addingModel.value = false
  }
}

function editModel(modelType: string, modelId: string, config: any) {
  if (!providerSchema.value) return
  modelEditMode.value = true
  originalModelId.value = modelId
  modelForm.value = { model_id: modelId, model_type: modelType, config: deepClone(config ?? {}) }
  const modelConfigs = providerSchema.value?.model_config || {}
  modelSchema.value = modelConfigs[modelType] || null
  modelDialogVisible.value = true
}

async function removeModel(modelType: string, modelId: string) {
  if (!selectedId.value) return
  const providerId = selectedId.value
  openConfirm(t('provider.delete_confirm_title'), t('provider.model_delete_confirm'), async () => {
    try {
      await deleteModel(providerId, modelType, modelId)
      notify(t('provider.model_delete_success'), 'success')
      try {
        const modelsRes = await getModels(providerId)
        if (selectedId.value === providerId) {
          providerModels.value = modelsRes.data || {}
        }
      } catch { /* refresh failure is non-critical */ }
    } catch (error: any) {
      notify(t('provider.model_delete_failed') + (error?.message ? ': ' + error.message : ''), 'error')
    }
  })
}

onMounted(() => {
  loadProviders()
})
</script>


