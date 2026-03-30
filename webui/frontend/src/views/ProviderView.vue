<template>
  <div class="flex gap-6 h-full">
    <!-- Left: Provider List -->
    <div class="w-80 flex-shrink-0">
      <div class="glass-card rounded-lg p-4">
        <div class="flex items-center justify-between mb-4">
          <h3 class="text-sm font-semibold text-gray-700 dark:text-gray-300">
            {{ $t('pages.provider.title') }}
          </h3>
          <el-button size="small" type="primary" @click="openCreateDialog">
            + {{ $t('provider.add') }}
          </el-button>
        </div>

        <div v-if="providers.length === 0" class="text-center py-12 text-gray-400">
          <el-icon :size="48"><Connection /></el-icon>
          <p class="mt-2 text-sm">{{ $t('provider.no_providers') }}</p>
        </div>

        <div v-else class="space-y-2">
          <div
            v-for="provider in providers"
            :key="provider.id"
            class="provider-item flex items-center p-3 rounded-lg cursor-pointer transition-colors hover:bg-gray-100 dark:hover:bg-gray-800"
            :class="{ 'bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-700': selectedId === provider.id, 'border border-transparent': selectedId !== provider.id }"
            @click="selectProvider(provider.id)"
          >
            <div class="flex-1 min-w-0">
              <div class="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">{{ provider.name }}</div>
              <div class="text-xs text-gray-500">{{ provider.type }}</div>
            </div>
            <el-tag :type="provider.status === 'active' ? 'success' : 'info'" size="small">
              {{ provider.status }}
            </el-tag>
          </div>
        </div>
      </div>
    </div>

    <!-- Right: Provider Config Panel -->
    <div class="flex-1 min-w-0">
      <div v-if="!selectedId" class="glass-card rounded-lg p-6 flex items-center justify-center h-full">
        <div class="text-center text-gray-400">
          <el-icon :size="64"><Connection /></el-icon>
          <p class="mt-4">{{ $t('provider.select_provider') }}</p>
        </div>
      </div>

      <div v-else class="glass-card rounded-lg p-6">
        <div class="flex items-center justify-between mb-6">
          <div>
            <h3 class="text-lg font-semibold text-gray-900 dark:text-white">{{ selectedProvider?.name }}</h3>
            <p class="text-sm text-gray-500">{{ selectedProvider?.type }}</p>
          </div>
          <el-button type="danger" size="small" @click="handleDelete">
            {{ $t('provider.delete') }}
          </el-button>
        </div>

        <!-- Provider Config Fields -->
        <div v-if="providerSchema?.provider_config" class="mb-6">
          <h4 class="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">{{ $t('provider.config') }}</h4>
          <ConfigForm
            v-model="providerConfigValues"
            :schema="providerSchema.provider_config"
          />
          <el-button type="primary" size="small" class="mt-3" :loading="saving" @click="saveProviderConfig">
            {{ $t('provider.save') }}
          </el-button>
        </div>

        <!-- Model Groups -->
        <div v-if="selectedProvider?.supported_model_types?.length">
          <h4 class="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">{{ $t('provider.models') }}</h4>
          <el-collapse v-model="activeModelGroups">
            <el-collapse-item
              v-for="modelType in selectedProvider.supported_model_types"
              :key="modelType"
              :title="modelType.toUpperCase()"
              :name="modelType"
            >
              <div v-if="providerModels[modelType]" class="space-y-2">
                <div
                  v-for="(modelConfig, modelId) in providerModels[modelType]"
                  :key="modelId"
                  class="flex items-center justify-between p-3 bg-gray-50 dark:bg-gray-800 rounded-lg"
                >
                  <span class="text-sm font-mono text-gray-700 dark:text-gray-300">{{ modelId }}</span>
                  <div class="flex gap-2">
                    <el-button size="small" @click="editModel(modelType, String(modelId), modelConfig)">
                      {{ $t('provider.edit') }}
                    </el-button>
                    <el-button size="small" type="danger" @click="removeModel(modelType, String(modelId))">
                      {{ $t('provider.delete') }}
                    </el-button>
                  </div>
                </div>
              </div>
              <el-button size="small" class="mt-2" @click="openAddModelDialog(modelType)">
                + {{ $t('provider.add_model') }}
              </el-button>
            </el-collapse-item>
          </el-collapse>
        </div>
      </div>
    </div>

    <!-- Create Provider Dialog -->
    <el-dialog v-model="createDialogVisible" :title="$t('provider.add')" width="500">
      <el-form label-position="top">
        <el-form-item :label="$t('provider.name')">
          <el-input v-model="createForm.name" />
        </el-form-item>
        <el-form-item :label="$t('provider.type')">
          <el-select v-model="createForm.type" class="w-full" @change="onCreateTypeChange">
            <el-option v-for="t in providerTypes" :key="t" :label="t" :value="t" />
          </el-select>
        </el-form-item>
        <div v-if="createSchema?.provider_config">
          <ConfigForm v-model="createForm.config" :schema="createSchema.provider_config" />
        </div>
      </el-form>
      <template #footer>
        <el-button @click="createDialogVisible = false">{{ $t('provider.cancel') }}</el-button>
        <el-button type="primary" :loading="creating" @click="handleCreate">{{ $t('provider.save') }}</el-button>
      </template>
    </el-dialog>

    <!-- Add/Edit Model Dialog -->
    <el-dialog v-model="modelDialogVisible" :title="modelEditMode ? $t('provider.edit_model') : $t('provider.add_model')" width="500">
      <el-form label-position="top">
        <el-form-item :label="$t('provider.model_id')">
          <el-input v-model="modelForm.model_id" />
        </el-form-item>
        <div v-if="modelSchema">
          <ConfigForm v-model="modelForm.config" :schema="modelSchema" />
        </div>
      </el-form>
      <template #footer>
        <el-button @click="modelDialogVisible = false">{{ $t('provider.cancel') }}</el-button>
        <el-button type="primary" :loading="addingModel" @click="handleAddModel">{{ $t('provider.save') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { Connection } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getProviders, getProviderTypes, getProviderSchema,
  createProvider, updateProvider, deleteProvider,
  addModel, updateModel, getModels, deleteModel,
} from '@/api/provider'
import ConfigForm from '@/components/common/ConfigForm.vue'
import type { ProviderResponse } from '@/types'

const { t } = useI18n()

const providers = ref<ProviderResponse[]>([])
const selectedId = ref<string | null>(null)
const providerTypes = ref<string[]>([])
const providerSchema = ref<any>(null)
const providerConfigValues = ref<Record<string, any>>({})
const providerModels = ref<Record<string, any>>({})
const activeModelGroups = ref<string[]>([])
const saving = ref(false)

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

async function loadProviders() {
  try {
    const res = await getProviders()
    providers.value = Array.isArray(res.data) ? res.data : []
  } catch { /* silent */ }
}

async function selectProvider(id: string) {
  selectedId.value = id
  const provider = providers.value.find(p => p.id === id)
  if (!provider) return

  try {
    const schemaRes = await getProviderSchema(provider.type)
    providerSchema.value = schemaRes.data
    providerConfigValues.value = { ...(provider.config || {}) }
  } catch {
    providerSchema.value = null
  }

  try {
    const modelsRes = await getModels(id)
    providerModels.value = modelsRes.data || {}
  } catch {
    providerModels.value = {}
  }
}

function openCreateDialog() {
  createForm.value = { name: '', type: '', config: {} }
  createSchema.value = null
  createDialogVisible.value = true
  if (providerTypes.value.length === 0) {
    getProviderTypes().then(res => { providerTypes.value = res.data })
  }
}

async function onCreateTypeChange(type: string) {
  if (!type) { createSchema.value = null; return }
  try {
    const res = await getProviderSchema(type)
    createSchema.value = res.data
    createForm.value.config = {}
  } catch {
    createSchema.value = null
  }
}

async function handleCreate() {
  if (!createForm.value.name || !createForm.value.type) return
  creating.value = true
  try {
    await createProvider({
      name: createForm.value.name,
      type: createForm.value.type,
      status: 'active',
      config: createForm.value.config,
    })
    createDialogVisible.value = false
    ElMessage.success(t('provider.create_success'))
    await loadProviders()
  } catch {
    ElMessage.error(t('provider.create_failed'))
  } finally {
    creating.value = false
  }
}

async function saveProviderConfig() {
  if (!selectedId.value) return
  saving.value = true
  try {
    await updateProvider(selectedId.value, {
      name: selectedProvider.value!.name,
      type: selectedProvider.value!.type,
      status: selectedProvider.value!.status,
      config: providerConfigValues.value,
    })
    ElMessage.success(t('provider.save_success'))
    await loadProviders()
  } catch {
    ElMessage.error(t('provider.save_failed'))
  } finally {
    saving.value = false
  }
}

async function handleDelete() {
  if (!selectedId.value) return
  try {
    await ElMessageBox.confirm(t('provider.delete_confirm_message'), t('provider.delete_confirm_title'), { type: 'warning' })
    await deleteProvider(selectedId.value)
    selectedId.value = null
    providerSchema.value = null
    ElMessage.success(t('provider.delete_success'))
    await loadProviders()
  } catch { /* cancelled */ }
}

function openAddModelDialog(modelType: string) {
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
  addingModel.value = true
  try {
    if (modelEditMode.value) {
      await updateModel(selectedId.value, modelForm.value.model_type, originalModelId.value, {
        config: modelForm.value.config,
      })
    } else {
      await addModel(selectedId.value, {
        model_type: modelForm.value.model_type,
        model_id: modelForm.value.model_id,
        config: modelForm.value.config,
      })
    }
    modelDialogVisible.value = false
    ElMessage.success(modelEditMode.value ? t('provider.model_update_success') : t('provider.model_add_success'))
    modelEditMode.value = false
    originalModelId.value = ''
    const modelsRes = await getModels(selectedId.value)
    providerModels.value = modelsRes.data || {}
  } catch {
    ElMessage.error(modelEditMode.value ? t('provider.model_update_failed') : t('provider.model_add_failed'))
  } finally {
    addingModel.value = false
  }
}

function editModel(modelType: string, modelId: string, config: any) {
  modelEditMode.value = true
  originalModelId.value = modelId
  modelForm.value = { model_id: modelId, model_type: modelType, config: { ...config } }
  const modelConfigs = providerSchema.value?.model_config || {}
  modelSchema.value = modelConfigs[modelType] || null
  modelDialogVisible.value = true
}

async function removeModel(modelType: string, modelId: string) {
  if (!selectedId.value) return
  try {
    await ElMessageBox.confirm(t('provider.model_delete_confirm'), t('provider.delete_confirm_title'), { type: 'warning' })
    await deleteModel(selectedId.value, modelType, modelId)
    ElMessage.success(t('provider.model_delete_success'))
    const modelsRes = await getModels(selectedId.value)
    providerModels.value = modelsRes.data || {}
  } catch { /* cancelled */ }
}

onMounted(() => {
  loadProviders()
})
</script>
