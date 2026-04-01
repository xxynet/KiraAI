<template>
  <div>
    <div class="flex items-center justify-between mb-6">
      <div></div>
      <el-button type="primary" size="small" @click="openCreateDialog">
        + {{ $t('adapter.add') }}
      </el-button>
    </div>

    <!-- Adapter Cards -->
    <div v-if="adapters.length === 0" class="text-center py-12 text-gray-400">
      <el-icon :size="48"><Link /></el-icon>
      <p class="mt-2 text-sm">{{ $t('adapter.no_adapters') }}</p>
    </div>

    <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
      <div
        v-for="adapter in adapters"
        :key="adapter.id"
        class="glass-card rounded-lg p-5 flex flex-col justify-between"
      >
        <div class="flex items-start justify-between mb-4">
          <div>
            <div class="flex items-center gap-2">
              <h4 class="text-base font-semibold text-gray-900 dark:text-gray-100">{{ adapter.name }}</h4>
              <el-tag :type="adapter.status === 'active' ? 'success' : 'info'" size="small">
                {{ $t('adapter.' + adapter.status, $t('adapter.unknown')) }}
              </el-tag>
            </div>
            <p class="mt-1 text-sm text-gray-500">{{ adapter.platform }}</p>
          </div>
          <el-switch
            :model-value="adapter.status === 'active'"
            :aria-label="$t('adapter.toggle_status', { name: adapter.name })"
            @change="toggleStatus(adapter)"
          />
        </div>
        <p v-if="adapter.description" class="text-sm text-gray-600 dark:text-gray-300 mb-4">
          {{ adapter.description }}
        </p>
        <div class="flex justify-end gap-3 mt-auto">
          <el-button size="small" @click="openEditDialog(adapter)">{{ $t('adapter.edit') }}</el-button>
          <el-button size="small" type="danger" @click="handleDelete(adapter.id)">{{ $t('adapter.delete') }}</el-button>
        </div>
      </div>
    </div>

    <!-- Create/Edit Dialog -->
    <el-dialog v-model="dialogVisible" :title="editMode ? $t('adapter.edit') : $t('adapter.add')" width="600">
      <el-form label-position="top">
        <el-form-item :label="$t('adapter.name')">
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item :label="$t('adapter.platform')">
          <el-select v-model="form.platform" class="w-full" :disabled="editMode" @change="onPlatformChange">
            <el-option v-for="p in platforms" :key="p" :label="p" :value="p" />
          </el-select>
        </el-form-item>
        <el-form-item :label="$t('adapter.description')">
          <el-input v-model="form.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item :label="$t('adapter.status')">
          <el-switch v-model="formActive" :active-text="$t('adapter.active')" :inactive-text="$t('adapter.inactive')" />
        </el-form-item>
        <div v-if="adapterSchema">
          <h4 class="text-sm font-semibold mb-2">{{ $t('adapter.config') }}</h4>
          <ConfigForm v-model="form.config" :schema="adapterSchema" />
        </div>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">{{ $t('adapter.cancel') }}</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">{{ $t('adapter.save') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { Link } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getAdapters, getAdapterPlatforms, getAdapterSchema,
  createAdapter, updateAdapter, deleteAdapter,
} from '@/api/adapter'
import ConfigForm from '@/components/common/ConfigForm.vue'
import type { AdapterResponse } from '@/types'

const { t } = useI18n()
const adapters = ref<AdapterResponse[]>([])
const platforms = ref<string[]>([])
const dialogVisible = ref(false)
const editMode = ref(false)
const editId = ref<string | null>(null)
const adapterSchema = ref<any>(null)
const saving = ref(false)
const formActive = ref(false)
let platformChangeId = 0

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
    ElMessage.error(t('adapter.load_failed'))
    console.error('Failed to load adapters:', e)
  }
}

async function loadPlatforms() {
  try {
    const res = await getAdapterPlatforms()
    platforms.value = Array.isArray(res.data) ? res.data : []
  } catch (e) {
    ElMessage.error(t('adapter.platform_load_failed'))
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

function openEditDialog(adapter: AdapterResponse) {
  editMode.value = true
  editId.value = adapter.id
  form.value = {
    name: adapter.name,
    platform: adapter.platform,
    description: adapter.description || '',
    config: structuredClone(adapter.config || {}),
  }
  formActive.value = adapter.status === 'active'
  adapterSchema.value = null
  ++platformChangeId
  dialogVisible.value = true
  onPlatformChange(adapter.platform, true)
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
    ElMessage.warning(t('adapter.form_incomplete'))
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
    ElMessage.success(t('adapter.save_success'))
    await loadAdapters()
  } catch (error: any) {
    ElMessage.error(t('adapter.save_failed') + (error?.message ? ': ' + error.message : ''))
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
    ElMessage.success(t('adapter.status_updated'))
    await loadAdapters()
  } catch (error: any) {
    ElMessage.error(t('adapter.status_update_failed') + (error?.message ? ': ' + error.message : ''))
  }
}

async function handleDelete(id: string) {
  try {
    await ElMessageBox.confirm(t('adapter.delete_confirm'), t('adapter.delete'), { type: 'warning' })
  } catch {
    return // User cancelled
  }
  try {
    await deleteAdapter(id)
    ElMessage.success(t('adapter.delete_success'))
    await loadAdapters()
  } catch (error: any) {
    ElMessage.error(t('adapter.delete_failed') + (error?.message ? ': ' + error.message : ''))
  }
}

onMounted(() => {
  loadAdapters()
})
</script>
