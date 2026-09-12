<template>
  <div>
    <!-- Header -->
    <div class="flex justify-between items-center mb-6">
      <h3 class="text-lg font-semibold text-theme-strong">
        {{ $t('pages.adapter.title') }}
      </h3>
      <button
        class="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 transition-colors flex items-center"
        @click="openCreateDialog"
      >
        <IconPlus class="w-5 h-5 mr-2" />
        <span>{{ $t('adapter.add') }}</span>
      </button>
    </div>

    <!-- Empty State -->
    <div v-if="adapters.length === 0" class="flex justify-center items-center py-12">
      <div class="text-center">
        <IconTerminal class="w-16 h-16 text-theme-faint mx-auto mb-4" />
        <p class="text-theme-subtle">{{ $t('adapter.no_adapters') }}</p>
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
              <h4 class="text-base font-semibold text-theme-high mr-2 truncate">{{ adapter.name }}</h4>
              <span
                class="px-2 py-0.5 text-xs rounded-full flex-shrink-0"
                :class="adapter.status === 'active'
                  ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200'
                  : 'bg-gray-100 text-theme-strong dark:bg-gray-700'"
              >
                {{ adapter.status }}
              </span>
            </div>
            <div class="mt-1 flex items-center gap-2 min-w-0 text-sm text-theme-subtle">
              <img
                v-if="adapterIcon(adapter)"
                :src="adapterIcon(adapter)"
                :alt="''"
                class="w-4 h-4 flex-shrink-0 object-contain"
              />
              <span class="truncate">{{ localizePlatform(adapter.platform_display_name, adapter.platform_locales, adapter.platform) }}</span>
            </div>
          </div>
          <ToggleSwitch
            :model-value="adapter.status === 'active'"
            @update:model-value="toggleStatus(adapter)"
          />
        </div>
        <p v-if="adapter.description" class="text-sm text-theme-supporting mb-4 break-words line-clamp-3">
          {{ adapter.description }}
        </p>
        <div class="flex justify-end space-x-3 mt-4">
          <button
            class="px-3 py-1.5 text-xs font-medium rounded-md border border-gray-300 text-theme-body hover:bg-gray-50 dark:border-gray-600 dark:hover:bg-gray-800 transition-colors"
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
      <div class="bg-white dark:bg-gray-900 rounded-lg shadow-xl w-full flex flex-col modal-card" style="max-height: 90vh;">
        <div class="flex justify-between items-center px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <h3 class="text-lg font-semibold text-theme-strong">
            {{ editMode ? $t('adapter.edit_title') : $t('adapter.add') }}
          </h3>
          <button class="text-theme-faint text-theme-faint-hover" @click="dialogVisible = false">
            <IconClose class="w-6 h-6" />
          </button>
        </div>
        <div class="px-6 py-4 flex-1 overflow-y-auto">
          <div class="mb-4">
            <label class="block text-sm font-medium text-theme-body mb-2">
              {{ $t('adapter.modal_name_label') }}
            </label>
            <UiInput
              v-model="form.name"
              type="text"
              class="w-full rounded-lg px-3 py-2 transition-colors"
              :placeholder="$t('adapter.name')"
            />
          </div>
          <div class="mb-4">
            <label class="block text-sm font-medium text-theme-body mb-2">
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
            <label class="block text-sm font-medium text-theme-body mb-2">
              {{ $t('adapter.modal_desc_label') }}
            </label>
            <UiTextarea
              v-model="form.description"
              rows="2"
              class="w-full rounded-lg px-3 py-2 transition-colors resize-none"
              :placeholder="$t('adapter.modal_desc_placeholder')"
            />
          </div>
          <div class="mb-4">
            <label class="block text-sm font-medium text-theme-body mb-2">
              {{ $t('adapter.modal_status_label') }}
            </label>
            <div class="flex items-center">
              <ToggleSwitch v-model="formActive" />
            </div>
          </div>
          <div v-if="adapterSchema">
            <div
              v-if="supportsQRCodeLogin && !editMode"
              class="mb-4 rounded-lg border border-blue-200 bg-blue-50 p-4 dark:border-blue-800 dark:bg-blue-950/30"
            >
              <div class="flex items-center justify-between gap-3">
                <div>
                  <h4 class="text-sm font-semibold text-theme-strong">{{ $t('adapter.qrcode_login') }}</h4>
                  <p class="mt-1 text-xs text-theme-subtle">{{ $t('adapter.qrcode_login_hint') }}</p>
                </div>
                <button
                  v-if="['idle', 'expired', 'denied', 'error'].includes(qrLoginStatus)"
                  type="button"
                  class="shrink-0 rounded-md bg-blue-600 px-3 py-1.5 text-sm text-white transition-colors hover:bg-blue-700 disabled:opacity-50"
                  :disabled="qrLoginLoading"
                  @click="startQRCodeLogin"
                >
                  {{ qrLoginStatus === 'idle' ? $t('adapter.qrcode_start') : $t('adapter.qrcode_retry') }}
                </button>
              </div>

              <div v-if="qrLoginStatus === 'starting'" class="mt-4 flex items-center justify-center gap-2 py-6 text-sm text-theme-subtle">
                <span class="h-4 w-4 animate-spin rounded-full border-2 border-blue-500 border-t-transparent"></span>
                {{ $t('adapter.qrcode_starting') }}
              </div>

              <div v-else-if="qrLoginImage" class="mt-4 flex flex-col items-center">
                <img
                  :src="qrLoginImage"
                  :alt="$t('adapter.qrcode_login')"
                  class="h-52 w-52 rounded-lg bg-white p-2"
                />
                <p
                  class="mt-2 text-center text-sm"
                  :class="qrLoginStatus === 'confirmed' ? 'text-green-600 dark:text-green-400' : 'text-theme-subtle'"
                >
                  {{ qrLoginStatusText }}
                </p>
              </div>

              <p v-if="qrLoginMessage && qrLoginStatus !== 'confirmed'" class="mt-2 text-xs text-red-600 dark:text-red-400">
                {{ qrLoginMessage }}
              </p>
            </div>
            <h4 class="text-sm font-semibold text-theme-body mb-2">{{ $t('adapter.config') }}</h4>
            <ConfigForm ref="configFormRef" v-model="form.config" :schema="adapterSchema" />
          </div>
        </div>
        <div class="px-6 py-4 border-t border-gray-200 dark:border-gray-700 flex justify-end space-x-3">
          <button
            class="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-theme-body hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
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
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useLocalized } from '@/composables/useLocalized'
import { useTheme } from '@/composables/useTheme'
import { notify } from '@/composables/useNotification'
import {
  getAdapters, getAdapterPlatforms, getAdapterSchema,
  createAdapter, updateAdapter, deleteAdapter,
  startAdapterQRCodeLogin, pollAdapterQRCodeLogin, cancelAdapterQRCodeLogin,
} from '@/api/adapter'
import ConfigForm from '@/components/common/ConfigForm.vue'
import CustomSelect from '@/components/common/CustomSelect.vue'
import ConfirmModal from '@/components/common/ConfirmModal.vue'
import Modal from '@/components/common/Modal.vue'
import ToggleSwitch from '@/components/common/ToggleSwitch.vue'
import UiInput from '@/components/ui/UiInput.vue'
import UiTextarea from '@/components/ui/UiTextarea.vue'
import { IconPlus, IconTerminal, IconClose } from '@/components/icons'
import type { AdapterPlatform, AdapterResponse, QRCodeLoginStatus } from '@/types'

const { t } = useI18n()
const { localize } = useLocalized()
const { isDark } = useTheme()

const configFormRef = ref<InstanceType<typeof ConfigForm>>()
const confirmModalRef = ref<InstanceType<typeof ConfirmModal>>()

const adapters = ref<AdapterResponse[]>([])
const platforms = ref<string[]>([])
const platformDetails = ref<AdapterPlatform[]>([])
const dialogVisible = ref(false)
const editMode = ref(false)
const editId = ref<string | null>(null)
const adapterSchema = ref<any>(null)
const schemaLoadError = ref(false)
const saving = ref(false)
const formActive = ref(false)
type QRLoginViewStatus = 'idle' | 'starting' | QRCodeLoginStatus
const qrLoginStatus = ref<QRLoginViewStatus>('idle')
const qrLoginSessionId = ref('')
const qrLoginImage = ref('')
const qrLoginMessage = ref('')
let qrLoginPollTimer: ReturnType<typeof setTimeout> | null = null
let qrLoginRequestId = 0
let platformChangeId = 0

const confirmTitle = ref('')
const confirmMessage = ref('')
let deleteTargetId: string | null = null

const form = ref({
  name: '',
  platform: '',
  description: '',
  config: {} as Record<string, any>,
})

const selectedPlatformDetails = computed(() =>
  platformDetails.value.find(item => item.id === form.value.platform)
)
const supportsQRCodeLogin = computed(() =>
  selectedPlatformDetails.value?.login_method === 'qrcode'
)
const qrLoginLoading = computed(() => qrLoginStatus.value === 'starting')
const qrLoginStatusText = computed(() => {
  switch (qrLoginStatus.value) {
    case 'starting': return t('adapter.qrcode_starting')
    case 'pending': return t('adapter.qrcode_pending')
    case 'confirmed': return t('adapter.qrcode_confirmed')
    case 'expired': return t('adapter.qrcode_expired')
    case 'denied': return t('adapter.qrcode_denied')
    case 'error': return t('adapter.qrcode_failed')
    default: return ''
  }
})
const platformOptions = computed(() =>
  platforms.value.map(id => {
    const platform = platformDetails.value.find(item => item.id === id)
    return {
      value: id,
      label: platform
        ? localize(platform, 'display_name', id)
        : id,
      icon: platform?.icon || null,
      iconDark: platform?.icon_dark || null,
    }
  })
)

function adapterIcon(adapter: AdapterResponse): string | undefined {
  return isDark.value
    ? adapter.platform_icon_dark || adapter.platform_icon || undefined
    : adapter.platform_icon || undefined
}

function clearQRCodeLoginTimer() {
  if (qrLoginPollTimer) {
    clearTimeout(qrLoginPollTimer)
    qrLoginPollTimer = null
  }
}

function qrLoginErrorMessage(error: any): string {
  return error?.response?.data?.detail || error?.message || t('adapter.qrcode_failed')
}

async function disposeQRCodeLogin() {
  const sessionId = qrLoginSessionId.value
  ++qrLoginRequestId
  clearQRCodeLoginTimer()
  qrLoginSessionId.value = ''
  qrLoginImage.value = ''
  qrLoginMessage.value = ''
  qrLoginStatus.value = 'idle'
  if (sessionId) {
    try {
      await cancelAdapterQRCodeLogin(sessionId)
    } catch {
      // The server may already have expired the session.
    }
  }
}

function scheduleQRCodeLoginPoll(requestId: number, intervalSeconds: number) {
  clearQRCodeLoginTimer()
  qrLoginPollTimer = setTimeout(() => {
    void pollQRCodeLogin(requestId, intervalSeconds)
  }, Math.max(intervalSeconds, 1) * 1000)
}

async function pollQRCodeLogin(requestId: number, intervalSeconds: number) {
  const sessionId = qrLoginSessionId.value
  if (!sessionId || requestId !== qrLoginRequestId) return
  try {
    const res = await pollAdapterQRCodeLogin(sessionId)
    if (requestId !== qrLoginRequestId) return
    const result = res.data
    qrLoginStatus.value = result.status
    qrLoginMessage.value = result.message || ''
    if (result.status === 'confirmed') {
      form.value.config = {
        ...form.value.config,
        ...(result.config_patch || {}),
      }
      notify(t('adapter.qrcode_confirmed'), 'success')
      return
    }
    if (result.status === 'pending') {
      scheduleQRCodeLoginPoll(requestId, intervalSeconds)
    }
  } catch (error: any) {
    if (requestId !== qrLoginRequestId) return
    qrLoginStatus.value = 'error'
    qrLoginMessage.value = qrLoginErrorMessage(error)
  }
}

async function startQRCodeLogin() {
  const platform = form.value.platform
  if (!platform || !supportsQRCodeLogin.value) return
  await disposeQRCodeLogin()
  const requestId = ++qrLoginRequestId
  qrLoginStatus.value = 'starting'
  try {
    const res = await startAdapterQRCodeLogin(platform, form.value.config)
    if (requestId !== qrLoginRequestId) {
      await cancelAdapterQRCodeLogin(res.data.session_id)
      return
    }
    qrLoginSessionId.value = res.data.session_id
    qrLoginImage.value = res.data.qrcode_image
    qrLoginStatus.value = res.data.status
    scheduleQRCodeLoginPoll(requestId, res.data.poll_interval)
  } catch (error: any) {
    if (requestId !== qrLoginRequestId) return
    qrLoginStatus.value = 'error'
    qrLoginMessage.value = qrLoginErrorMessage(error)
  }
}

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
    const [idsRes, detailsRes] = await Promise.all([
      getAdapterPlatforms(),
      getAdapterPlatforms(true),
    ])
    platforms.value = Array.isArray(idsRes.data) ? idsRes.data : []
    platformDetails.value = Array.isArray(detailsRes.data) ? detailsRes.data : []
  } catch (e) {
    notify(t('adapter.platform_load_failed'), 'error')
    console.error('Failed to load platforms:', e)
  }
}

function localizePlatform(
  displayName: string,
  locales: Record<string, Record<string, string>>,
  fallback: string,
) {
  return localize({ display_name: displayName, locales }, 'display_name', fallback)
}

function openCreateDialog() {
  void disposeQRCodeLogin()
  editMode.value = false
  editId.value = null
  form.value = { name: '', platform: '', description: '', config: {} }
  formActive.value = false
  adapterSchema.value = null
  schemaLoadError.value = false
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
  schemaLoadError.value = false
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
  await disposeQRCodeLogin()
  if (!platform) { ++platformChangeId; adapterSchema.value = null; schemaLoadError.value = false; return }
  adapterSchema.value = null
  schemaLoadError.value = false
  if (!preserveConfig) {
    form.value.config = {}
  }
  const requestId = ++platformChangeId
  try {
    const res = await getAdapterSchema(platform)
    if (requestId === platformChangeId) {
      adapterSchema.value = res.data
      schemaLoadError.value = false
    }
  } catch {
    if (requestId === platformChangeId) {
      adapterSchema.value = null
      schemaLoadError.value = true
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
  if (adapterSchema.value === null || schemaLoadError.value) {
    notify(t('adapter.schema_load_failed'), 'error')
    return
  }
  if (!configFormRef.value) {
    notify(t('adapter.form_incomplete'), 'warning')
    return
  }
  const validateRes = configFormRef.value.validate()
  if (!validateRes.valid) {
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

watch(dialogVisible, (visible) => {
  if (!visible) void disposeQRCodeLogin()
})

onBeforeUnmount(() => {
  void disposeQRCodeLogin()
})
onMounted(() => {
  loadAdapters()
})
</script>
