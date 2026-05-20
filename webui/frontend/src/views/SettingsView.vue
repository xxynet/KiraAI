<template>
  <div>
    <!-- Title -->
    <div class="flex items-center mb-6">
      <h3 class="text-lg font-semibold text-gray-800 dark:text-gray-100">{{ $t('settings.title') }}</h3>
    </div>

    <!-- Tabs -->
    <div class="flex space-x-4 mb-6 border-b border-gray-200 dark:border-gray-700">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        type="button"
        class="px-3 py-2 text-sm font-medium border-b-2 focus:outline-none transition-colors duration-150"
        :class="activeTab === tab.key ? 'border-blue-600 dark:border-blue-500 text-blue-600 dark:text-blue-500' : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 hover:border-gray-300 dark:hover:border-gray-600'"
        @click="activeTab = tab.key"
      >
        {{ tab.label }}
      </button>
    </div>

    <!-- Storage Tab -->
    <div v-show="activeTab === 'storage'" class="space-y-8">
      <!-- Storage Overview -->
      <div>
        <div class="flex items-center justify-between mb-4">
          <h4 class="text-base font-semibold text-gray-800 dark:text-gray-100">{{ $t('settings.storage_title') }}</h4>
          <button
            type="button"
            class="px-3 py-1.5 text-xs font-medium text-gray-600 dark:text-gray-300 bg-gray-100 dark:bg-gray-700 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors"
            :disabled="storageLoading"
            @click="fetchStorageInfo"
          >
            {{ $t('settings.storage_refresh') }}
          </button>
        </div>

        <div v-if="storageLoading" class="flex items-center justify-center py-12">
          <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
        </div>

        <template v-else-if="storageInfo">
          <!-- Data Path -->
          <div class="bg-gray-50 dark:bg-gray-700/50 rounded-lg p-4 mb-4">
            <div class="flex justify-between items-center">
              <span class="text-sm text-gray-500 dark:text-gray-400">{{ $t('settings.storage_data_path') }}</span>
              <span class="text-sm font-mono font-medium text-gray-800 dark:text-gray-200 break-all text-right max-w-[70%]">{{ storageInfo.data_path }}</span>
            </div>
            <div class="flex justify-between items-center mt-2">
              <span class="text-sm text-gray-500 dark:text-gray-400">{{ $t('settings.storage_total_size') }}</span>
              <span class="text-sm font-medium text-gray-800 dark:text-gray-200">{{ formatBytes(storageInfo.total_size_bytes) }}</span>
            </div>
          </div>

          <!-- Disk Usage -->
          <div class="bg-gray-50 dark:bg-gray-700/50 rounded-lg p-4 mb-4">
            <h5 class="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">{{ $t('settings.storage_disk_usage') }}</h5>
            <div class="space-y-2">
              <div class="flex justify-between text-sm">
                <span class="text-gray-500 dark:text-gray-400">{{ $t('settings.storage_disk_total') }}</span>
                <span class="font-medium text-gray-800 dark:text-gray-200">{{ formatBytes(storageInfo.disk_total_bytes) }}</span>
              </div>
              <div class="flex justify-between text-sm">
                <span class="text-gray-500 dark:text-gray-400">{{ $t('settings.storage_disk_used') }}</span>
                <span class="font-medium text-gray-800 dark:text-gray-200">{{ formatBytes(storageInfo.disk_used_bytes) }}</span>
              </div>
              <div class="flex justify-between text-sm">
                <span class="text-gray-500 dark:text-gray-400">{{ $t('settings.storage_disk_free') }}</span>
                <span class="font-medium text-gray-800 dark:text-gray-200">{{ formatBytes(storageInfo.disk_free_bytes) }}</span>
              </div>
              <!-- Progress bar -->
              <div class="w-full bg-gray-200 dark:bg-gray-600 rounded-full h-3 mt-2">
                <div
                  class="h-3 rounded-full transition-all duration-500"
                  :class="diskUsagePercent > 90 ? 'bg-red-500' : diskUsagePercent > 70 ? 'bg-yellow-500' : 'bg-blue-500'"
                  :style="{ width: diskUsagePercent + '%' }"
                ></div>
              </div>
              <div class="text-right text-xs text-gray-500 dark:text-gray-400">
                {{ diskUsagePercent.toFixed(1) }}%
              </div>
            </div>
          </div>

          <!-- Directory Breakdown -->
          <div class="bg-gray-50 dark:bg-gray-700/50 rounded-lg p-4">
            <h5 class="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">{{ $t('settings.storage_directories') }}</h5>
            <div v-if="storageInfo.directories.length === 0" class="text-sm text-gray-400 dark:text-gray-500 text-center py-4">
              {{ $t('settings.storage_no_data') }}
            </div>
            <table v-else class="w-full text-sm">
              <thead>
                <tr class="border-b border-gray-200 dark:border-gray-600">
                  <th class="text-left py-2 text-gray-500 dark:text-gray-400 font-medium">{{ $t('settings.storage_dir_name') }}</th>
                  <th class="text-right py-2 text-gray-500 dark:text-gray-400 font-medium">{{ $t('settings.storage_dir_size') }}</th>
                  <th class="text-right py-2 text-gray-500 dark:text-gray-400 font-medium">{{ $t('settings.storage_dir_files') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="dir in storageInfo.directories" :key="dir.name" class="border-b border-gray-100 dark:border-gray-700 last:border-0">
                  <td class="py-2 font-mono text-gray-800 dark:text-gray-200">{{ dir.name }}</td>
                  <td class="py-2 text-right text-gray-600 dark:text-gray-300">{{ formatBytes(dir.size_bytes) }}</td>
                  <td class="py-2 text-right text-gray-600 dark:text-gray-300">{{ dir.file_count }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
      </div>

      <!-- Backup & Restore -->
      <div>
        <h4 class="text-base font-semibold text-gray-800 dark:text-gray-100 mb-4">{{ $t('settings.backup_title') }}</h4>

        <div class="flex flex-wrap gap-3 mb-4">
          <button
            type="button"
            class="px-4 py-2 text-sm font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            :disabled="backupLoading"
            @click="backupConfirmRef?.open()"
          >
            {{ backupLoading ? $t('settings.backup_creating') : $t('settings.backup_create') }}
          </button>

          <button
            type="button"
            class="px-4 py-2 text-sm font-medium bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors"
            @click="restoreModalVisible = true"
          >
            {{ $t('settings.restore_title') }}
          </button>
        </div>

        <!-- Backup List -->
        <div v-if="backupList.length > 0">
          <h5 class="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">{{ $t('settings.backup_list') }}</h5>
          <div class="bg-gray-50 dark:bg-gray-700/50 rounded-lg divide-y divide-gray-100 dark:divide-gray-700">
            <div
              v-for="backup in backupList"
              :key="backup.filename"
              class="flex items-center justify-between px-4 py-3"
            >
              <div class="flex-1 min-w-0">
                <p class="text-sm font-mono text-gray-800 dark:text-gray-200 truncate">{{ backup.filename }}</p>
                <p class="text-xs text-gray-400 dark:text-gray-500 mt-0.5">
                  {{ formatBytes(backup.size_bytes) }} &middot; {{ formatDate(backup.created_at) }}
                </p>
              </div>
              <div class="flex items-center gap-2 ml-4">
                <button
                  type="button"
                  class="px-2.5 py-1 text-xs font-medium text-green-600 dark:text-green-400 hover:bg-green-50 dark:hover:bg-green-900/20 rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  :disabled="restoreLoading"
                  @click="openListConfirm('restore', backup.filename)"
                >
                  {{ $t('settings.backup_restore') }}
                </button>
                <button
                  type="button"
                  class="px-2.5 py-1 text-xs font-medium text-blue-600 dark:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/20 rounded transition-colors"
                  @click="handleDownloadBackup(backup.filename)"
                >
                  {{ $t('settings.backup_download') }}
                </button>
                <button
                  type="button"
                  class="px-2.5 py-1 text-xs font-medium text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 rounded transition-colors"
                  @click="openListConfirm('delete', backup.filename)"
                >
                  {{ $t('settings.backup_delete') }}
                </button>
              </div>
            </div>
          </div>
        </div>
        <div v-else class="text-sm text-gray-400 dark:text-gray-500 text-center py-4 bg-gray-50 dark:bg-gray-700/50 rounded-lg">
          {{ $t('settings.backup_no_backups') }}
        </div>
      </div>
    </div>

    <!-- Custom CSS/JS Tab -->
    <div v-show="activeTab === 'custom'" class="space-y-6">
      <div>
        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
          {{ $t('settings.custom_css') }}
        </label>
        <div class="border border-gray-300 dark:border-gray-600 rounded-lg overflow-hidden" style="height: 300px;">
          <MonacoEditor
            v-model="customCSS"
            language="css"
            :height="300"
          />
        </div>
      </div>

      <div>
        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
          {{ $t('settings.custom_js') }}
        </label>
        <div class="border border-gray-300 dark:border-gray-600 rounded-lg overflow-hidden" style="height: 300px;">
          <MonacoEditor
            v-model="customJS"
            language="javascript"
            :height="300"
          />
        </div>
      </div>

      <div class="flex justify-end">
        <button
          type="button"
          class="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          :disabled="saving"
          @click="handleSave"
        >
          {{ saving ? '...' : $t('settings.save') }}
        </button>
      </div>
    </div>

    <!-- About Tab -->
    <div v-show="activeTab === 'about'" class="space-y-6">
      <div class="flex flex-col items-center py-8">
        <div class="w-20 h-20 rounded-2xl bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center mb-4 shadow-lg">
          <span class="text-3xl font-bold text-white">K</span>
        </div>
        <h2 class="text-2xl font-bold text-gray-800 dark:text-gray-100">KiraAI</h2>
        <p class="text-sm text-gray-500 dark:text-gray-400 mt-1">{{ $t('settings.about_tagline') }}</p>
      </div>

      <div class="max-w-md mx-auto space-y-4">
        <div class="bg-gray-50 dark:bg-gray-700/50 rounded-lg p-4 space-y-3">
          <div class="flex justify-between items-center">
            <span class="text-sm text-gray-500 dark:text-gray-400">{{ $t('settings.about_version') }}</span>
            <span class="text-sm font-medium text-gray-800 dark:text-gray-200">{{ projectVersion }}</span>
          </div>
          <div class="flex justify-between items-center">
            <span class="text-sm text-gray-500 dark:text-gray-400">{{ $t('settings.about_license') }}</span>
            <span class="text-sm font-medium text-gray-800 dark:text-gray-200">AGPL-3.0</span>
          </div>
          <div class="flex justify-between items-center">
            <span class="text-sm text-gray-500 dark:text-gray-400">{{ $t('settings.about_repo') }}</span>
            <a
              href="https://github.com/xxynet/KiraAI"
              target="_blank"
              class="text-sm font-medium text-blue-600 dark:text-blue-400 hover:underline"
            >
              GitHub
            </a>
          </div>
          <div class="flex justify-between items-center">
            <span class="text-sm text-gray-500 dark:text-gray-400">{{ $t('header.docs') }}</span>
            <a
              :href="$t('header.docs_url')"
              target="_blank"
              class="text-sm font-medium text-blue-600 dark:text-blue-400 hover:underline"
            >
              {{ $t('header.docs_url') }}
            </a>
          </div>
        </div>

        <div class="bg-gray-50 dark:bg-gray-700/50 rounded-lg p-4 space-y-3">
          <h4 class="text-sm font-semibold text-gray-700 dark:text-gray-300">{{ $t('settings.about_community') }}</h4>
          <div class="flex justify-between items-center">
            <span class="text-sm text-gray-500 dark:text-gray-400">QQ {{ $t('settings.about_group') }}</span>
            <span class="text-sm font-medium text-gray-800 dark:text-gray-200">874381335</span>
          </div>
          <div class="flex justify-between items-center">
            <span class="text-sm text-gray-500 dark:text-gray-400">Discord</span>
            <a
              href="https://discord.gg/mRNmVmFHn3"
              target="_blank"
              class="text-sm font-medium text-blue-600 dark:text-blue-400 hover:underline"
            >
              KiraAI
            </a>
          </div>
        </div>
      </div>
    </div>

    <!-- Backup Confirm Modal -->
    <ConfirmModal
      ref="backupConfirmRef"
      variant="info"
      :title="$t('settings.backup_create')"
      :message="$t('settings.backup_confirm')"
      :cancel-text="$t('settings.backup_confirm_cancel')"
      :confirm-text="$t('settings.backup_confirm_ok')"
      @confirm="handleCreateBackup"
    />

    <!-- List Action Confirm Modal -->
    <ConfirmModal
      ref="listConfirmRef"
      :variant="listAction.type === 'delete' ? 'danger' : 'info'"
      :title="listAction.type === 'delete' ? $t('settings.backup_delete') : $t('settings.backup_restore')"
      :message="listAction.type === 'delete' ? $t('settings.backup_confirm_delete') : $t('settings.restore_confirm')"
      :cancel-text="$t('settings.backup_confirm_cancel')"
      :confirm-text="$t('settings.backup_confirm_ok')"
      @confirm="executeListAction"
    />

    <!-- Restore Modal -->
    <Modal v-model="restoreModalVisible" content-class="max-w-lg">
      <div class="bg-white dark:bg-gray-800 rounded-lg shadow-xl">
        <div class="px-6 py-4">
          <h3 class="text-lg font-semibold text-gray-800 dark:text-gray-100 mb-2">
            {{ $t('settings.restore_title') }}
          </h3>
          <p class="text-sm text-gray-500 dark:text-gray-400 mb-4">
            {{ $t('settings.restore_upload_hint') }}
          </p>
          <FileDropzone
            ref="restoreDropzoneRef"
            v-model="restoreFile"
            accept=".zip"
            title-key="settings.restore_dropzone_title"
            title-fallback="拖拽备份文件到此处，或点击选择"
            reselect-key="settings.restore_dropzone_reselect"
            reselect-fallback="点击或拖拽可重新选择文件"
          />
        </div>
        <div class="px-6 py-4 border-t border-gray-200 dark:border-gray-700 flex justify-end space-x-3">
          <button
            class="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
            @click="restoreModalVisible = false"
          >
            {{ $t('settings.backup_confirm_cancel') }}
          </button>
          <button
            class="px-4 py-2 bg-blue-600 dark:bg-blue-700 text-white rounded-lg hover:bg-blue-700 dark:hover:bg-blue-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            :disabled="!restoreFile || restoreLoading"
            @click="handleRestore"
          >
            {{ restoreLoading ? $t('settings.restore_uploading') : $t('settings.restore_confirm_ok') }}
          </button>
        </div>
      </div>
    </Modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { notify } from '@/composables/useNotification'
import apiClient from '@/api/client'
import MonacoEditor from '@/components/common/MonacoEditor.vue'
import ConfirmModal from '@/components/common/ConfirmModal.vue'
import Modal from '@/components/common/Modal.vue'
import FileDropzone from '@/components/common/FileDropzone.vue'
import {
  getStorageInfo,
  createBackup,
  listBackups,
  downloadBackup,
  deleteBackup,
  restoreBackup,
  restoreFromBackup,
  type StorageInfoResponse,
  type BackupItem,
} from '@/api/settings'

const { t } = useI18n()
const saving = ref(false)
const activeTab = ref('storage')

const projectVersion = ref('dev')

const tabs = computed(() => [
  { key: 'storage', label: t('settings.tab_storage') },
  { key: 'custom', label: t('settings.tab_custom') },
  { key: 'about', label: t('settings.tab_about') },
])

const customCSS = ref('')
const customJS = ref('')

// ── Storage ─────────────────────────────────────────────────────────────

const storageLoading = ref(false)
const storageInfo = ref<StorageInfoResponse | null>(null)

const diskUsagePercent = computed(() => {
  if (!storageInfo.value || storageInfo.value.disk_total_bytes === 0) return 0
  return (storageInfo.value.disk_used_bytes / storageInfo.value.disk_total_bytes) * 100
})

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return (bytes / Math.pow(k, i)).toFixed(i > 0 ? 2 : 0) + ' ' + sizes[i]
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

async function fetchStorageInfo() {
  storageLoading.value = true
  try {
    const { data } = await getStorageInfo()
    storageInfo.value = data
  } catch {
    // silent
  } finally {
    storageLoading.value = false
  }
}

// ── Backup & Restore ────────────────────────────────────────────────────

const backupLoading = ref(false)
const restoreLoading = ref(false)
const backupList = ref<BackupItem[]>([])
const backupConfirmRef = ref<InstanceType<typeof ConfirmModal>>()
const listConfirmRef = ref<InstanceType<typeof ConfirmModal>>()
const restoreDropzoneRef = ref<InstanceType<typeof FileDropzone>>()
const restoreModalVisible = ref(false)
const restoreFile = ref<File | null>(null)
const listAction = ref<{ type: 'delete' | 'restore'; filename: string }>({ type: 'delete', filename: '' })

async function fetchBackupList() {
  try {
    const { data } = await listBackups()
    backupList.value = data as unknown as BackupItem[]
  } catch {
    // silent
  }
}

async function handleCreateBackup() {
  backupLoading.value = true
  try {
    await createBackup()
    notify(t('settings.backup_created'), 'success')
    await fetchBackupList()
  } catch {
    notify(t('settings.backup_create_failed'), 'error')
  } finally {
    backupLoading.value = false
  }
}

async function handleDownloadBackup(filename: string) {
  try {
    const { data } = await downloadBackup(filename)
    const url = URL.createObjectURL(data as Blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  } catch {
    // silent
  }
}

async function handleDeleteBackup(filename: string) {
  try {
    await deleteBackup(filename)
    notify(t('settings.backup_deleted'), 'success')
    await fetchBackupList()
  } catch {
    notify(t('settings.backup_delete_failed'), 'error')
  }
}

async function handleRestoreFromBackup(filename: string) {
  restoreLoading.value = true
  try {
    const { data } = await restoreFromBackup(filename)
    const result = data as unknown as { success: boolean; message: string }
    if (result.success) {
      notify(t('settings.restore_success'), 'success')
      await fetchStorageInfo()
    } else {
      notify(result.message || t('settings.restore_failed'), 'error')
    }
  } catch {
    notify(t('settings.restore_failed'), 'error')
  } finally {
    restoreLoading.value = false
  }
}

function openListConfirm(type: 'delete' | 'restore', filename: string) {
  listAction.value = { type, filename }
  listConfirmRef.value?.open()
}

async function executeListAction() {
  if (listAction.value.type === 'delete') {
    await handleDeleteBackup(listAction.value.filename)
  } else {
    await handleRestoreFromBackup(listAction.value.filename)
  }
}

async function handleRestore() {
  const file = restoreFile.value
  if (!file) return

  restoreLoading.value = true
  try {
    const { data } = await restoreBackup(file)
    const result = data as unknown as { success: boolean; message: string }
    if (result.success) {
      notify(t('settings.restore_success'), 'success')
      restoreModalVisible.value = false
      restoreFile.value = null
      restoreDropzoneRef.value?.reset()
      await fetchStorageInfo()
    } else {
      notify(result.message || t('settings.restore_failed'), 'error')
    }
  } catch {
    notify(t('settings.restore_failed'), 'error')
  } finally {
    restoreLoading.value = false
  }
}

// ── Init ────────────────────────────────────────────────────────────────

onMounted(() => {
  customCSS.value = localStorage.getItem('custom_css') || ''
  customJS.value = localStorage.getItem('custom_js') || ''

  apiClient.get('/version').then(({ data }) => {
    if (data?.version) projectVersion.value = data.version
  }).catch(() => {})

  fetchStorageInfo()
  fetchBackupList()
})

function applyCustomCSS() {
  const css = customCSS.value
  let tag = document.getElementById('custom-user-css')
  if (!tag) {
    tag = document.createElement('style')
    tag.id = 'custom-user-css'
    document.head.appendChild(tag)
  }
  tag.textContent = css
}

function applyCustomJS() {
  const js = customJS.value
  const oldTag = document.getElementById('custom-user-js')
  if (oldTag) oldTag.remove()
  if (!js) return
  const tag = document.createElement('script')
  tag.id = 'custom-user-js'
  tag.textContent = js
  document.body.appendChild(tag)
}

async function handleSave() {
  saving.value = true
  try {
    localStorage.setItem('custom_css', customCSS.value)
    localStorage.setItem('custom_js', customJS.value)
    applyCustomCSS()
    applyCustomJS()

    notify(t('settings.saved'), 'success')
  } catch {
    notify(t('settings.save_failed'), 'error')
  } finally {
    saving.value = false
  }
}
</script>
