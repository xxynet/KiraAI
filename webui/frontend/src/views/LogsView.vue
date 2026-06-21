<template>
  <div class="bg-white rounded-lg shadow p-6 dark:bg-gray-800 dark:shadow-gray-900/50">
    <!-- Header -->
    <div class="flex justify-between items-center mb-6">
      <h3 class="text-lg font-semibold text-gray-800 dark:text-gray-100">{{ $t('logs.title') }}</h3>
      <div class="flex space-x-2">
        <button
          class="bg-gray-600 text-white px-4 py-2 rounded-lg hover:bg-gray-700 transition-colors flex items-center"
          @click="clearLogs"
        >
          <IconTrash class="w-5 h-5 mr-2" />
          <span>{{ $t('logs.clear') }}</span>
        </button>
        <button
          class="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 transition-colors flex items-center"
          @click="refreshLogs"
        >
          <IconRefresh class="w-5 h-5 mr-2" />
          <span>{{ $t('logs.refresh') }}</span>
        </button>
      </div>
    </div>

    <!-- Filter row -->
    <div class="mb-4 flex space-x-4 items-center">
      <CustomMultiSelect
        v-model="filterLevels"
        :options="levelOptions"
        :placeholder="$t('logs.filter_level')"
        class="w-60"
        @update:modelValue="applyFilter"
      />
      <button
        class="bg-green-600 text-white px-4 py-2 rounded-lg hover:bg-green-700 transition-colors flex items-center whitespace-nowrap"
        @click="downloadLogs"
      >
        <IconDownload class="w-5 h-5 mr-2" />
        <span>{{ $t('logs.download') }}</span>
      </button>
      <button
        class="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 transition-colors flex items-center whitespace-nowrap"
        @click="showInstallPanel = !showInstallPanel"
      >
        <IconPackage class="w-5 h-5 mr-2" />
        <span>{{ $t('logs.install_deps') }}</span>
      </button>
    </div>

    <!-- Install dependencies modal -->
    <Modal v-model="showInstallPanel" content-class="max-w-md">
      <div class="bg-white dark:bg-gray-900 rounded-lg shadow-xl w-full flex flex-col" style="max-height: 90vh;">
        <div class="flex justify-between items-center px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <h3 class="text-lg font-semibold text-gray-800 dark:text-gray-100">{{ $t('logs.install_deps') }}</h3>
          <button type="button" class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300" @click="showInstallPanel = false">
            <IconClose class="w-6 h-6" />
          </button>
        </div>
        <div class="px-6 py-5 flex-1 overflow-y-auto">
          <div class="mb-4">
            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">{{ $t('logs.install_packages_label') }}</label>
            <textarea
              v-model="installPackagesInput"
              :placeholder="$t('logs.install_packages_placeholder')"
              class="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 font-mono text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
              rows="3"
              @keydown.ctrl.enter="handleInstall"
            ></textarea>
          </div>
        </div>
        <div class="px-6 py-4 border-t border-gray-200 dark:border-gray-700 flex justify-end space-x-3">
          <button type="button" class="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors" @click="showInstallPanel = false">{{ $t('logs.install_close') }}</button>
          <button type="button" class="px-4 py-2 bg-blue-600 dark:bg-blue-700 text-white rounded-lg hover:bg-blue-700 dark:hover:bg-blue-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center" :disabled="isInstalling" @click="handleInstall">
            <IconSpinner v-if="isInstalling" class="w-5 h-5 mr-2 animate-spin" />
            <IconPackage v-else class="w-5 h-5 mr-2" />
            <span>{{ isInstalling ? $t('logs.install_installing') : $t('logs.install_btn') }}</span>
          </button>
        </div>
      </div>
    </Modal>

    <!-- Log container -->
    <div
      ref="logContainerRef"
      id="log-container"
      class="rounded-lg p-4 overflow-y-auto min-h-64"
      style="height: calc(100vh - 18rem);"
    >
      <div v-if="filteredLogs.length === 0" class="flex justify-center items-center h-full">
        <p class="text-gray-500 dark:text-gray-400">{{ $t('logs.no_logs') }}</p>
      </div>
      <div
        v-for="(log, idx) in filteredLogs"
        :key="idx"
        data-log-entry
        class="font-mono text-base whitespace-normal break-words"
      >
        <span class="text-gray-500 dark:text-gray-400">[{{ log.timestamp }}]</span> <span :class="logLevelColor(log.level)" class="font-semibold whitespace-pre-wrap">{{ padLevel(log.level) }}</span> <span v-if="log.logger" :style="{ color: log.color || '#3b82f6' }" class="font-semibold">[{{ log.logger }}]</span> <span class="text-gray-700 dark:text-gray-300 whitespace-pre-wrap">{{ log.message }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useSSE } from '@/composables/useSSE'
import { getLogHistory, getLogConfig, installPackages } from '@/api/logs'
import CustomMultiSelect from '@/components/common/CustomMultiSelect.vue'
import { notify } from '@/composables/useNotification'
import { IconTrash, IconRefresh, IconDownload, IconPackage, IconSpinner, IconClose } from '@/components/icons'
import Modal from '@/components/common/Modal.vue'
import type { LogEntry } from '@/types'

const { t } = useI18n()
const logContainerRef = ref<HTMLElement | null>(null)
const filterLevels = ref<string[]>(['info', 'warning', 'error'])
const allLogs = ref<LogEntry[]>([])
const maxQueueSize = ref(100)

const { messages, connected, connect, disconnect, clear: clearSSE } = useSSE()
let lastProcessedIndex = 0

const showInstallPanel = ref(false)
const installPackagesInput = ref('')
const isInstalling = ref(false)

const levelOptions = [
  { label: 'DEBUG', value: 'debug' },
  { label: 'INFO', value: 'info' },
  { label: 'WARNING', value: 'warning' },
  { label: 'ERROR', value: 'error' },
]

const filteredLogs = computed(() => {
  return allLogs.value.filter(log => {
    const level = log.level?.toLowerCase()
    // CRITICAL is treated the same as ERROR
    const normalized = level === 'critical' ? 'error' : level
    return filterLevels.value.includes(normalized)
  })
})

function applyFilter() {
  localStorage.setItem('log_filter_levels', JSON.stringify(filterLevels.value))
  scrollToBottom()
}

function clearLogs() {
  if (!confirm(t('logs.clear_confirm'))) return
  allLogs.value = []
  clearSSE()
  lastProcessedIndex = 0
  notify(t('logs.cleared'), 'success')
}

async function refreshLogs() {
  disconnect()
  clearSSE()
  lastProcessedIndex = 0
  try {
    const res = await getLogHistory(100)
    allLogs.value = res.data.logs || []
    scrollToBottom()
    notify(t('logs.refreshed'), 'success')
  } catch (e) {
    console.error('Failed to load log history:', e)
    notify(t('logs.refresh_failed'), 'error')
  }
  loadLogs()
}

function loadLogs() {
  const token = localStorage.getItem('jwt_token')
  if (token) {
    connect(`/api/live-log`, token)
  }
}

function logLevelColor(level: string) {
  const l = level?.toLowerCase()
  if (l === 'error' || l === 'critical') return 'text-red-600 dark:text-red-400'
  if (l === 'warning') return 'text-yellow-600 dark:text-yellow-400'
  if (l === 'info') return 'text-green-600 dark:text-green-400'
  if (l === 'debug') return 'text-cyan-600 dark:text-cyan-400'
  return 'text-gray-500 dark:text-gray-400'
}

function padLevel(level: string): string {
  const l = (level || 'INFO').toUpperCase()
  // Pad to 7 characters for alignment (WARNING is 7 chars)
  return l.padEnd(7, ' ')
}

function getScrollContainer(): HTMLElement | null {
  return logContainerRef.value
}

function scrollToBottom() {
  nextTick(() => {
    const el = getScrollContainer()
    if (!el) return
    el.scrollTop = el.scrollHeight
  })
}

function smartScrollToBottom() {
  nextTick(() => {
    const el = getScrollContainer()
    if (!el) return
    const scrollRatio = (el.scrollTop + el.clientHeight) / el.scrollHeight
    if (scrollRatio > 0.95) {
      el.scrollTop = el.scrollHeight
    }
  })
}

function downloadLogs() {
  const container = logContainerRef.value
  if (!container) return

  const lines = Array.from(container.children)
    .filter(el => el.hasAttribute('data-log-entry'))
    .map(el => el.textContent?.trim() || '')
    .join('\n')

  const blob = new Blob([lines], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `logs_${new Date().toISOString().replace(/[:.]/g, '-')}.txt`
  a.click()
  URL.revokeObjectURL(url)
}

async function handleInstall() {
  const packages = installPackagesInput.value.trim()
  if (!packages) {
    notify(t('logs.install_no_packages'), 'warning')
    return
  }
  isInstalling.value = true
  try {
    await installPackages(packages)
    notify(t('logs.install_started'), 'success')
    showInstallPanel.value = false
    installPackagesInput.value = ''
  } catch (e) {
    console.error('Failed to start package installation:', e)
    notify(t('logs.install_failed'), 'error')
  } finally {
    isInstalling.value = false
  }
}

// Watch for new SSE messages
watch(messages, (msgs) => {
  if (lastProcessedIndex > msgs.length) lastProcessedIndex = 0
  if (msgs.length <= lastProcessedIndex) return
  let added = false
  for (let i = lastProcessedIndex; i < msgs.length; i++) {
    try {
      const logData = typeof msgs[i] === 'string' ? JSON.parse(msgs[i]) : msgs[i]
      allLogs.value.push({
        timestamp: logData.time || logData.timestamp || new Date().toLocaleString(),
        level: logData.level || 'info',
        message: logData.message || logData.msg || '',
        logger: logData.logger || logData.name || '',
        color: logData.color || '',
      })
      added = true
    } catch {
      // Preserve raw text messages when JSON parse fails
      allLogs.value.push({
        timestamp: new Date().toLocaleString(),
        level: 'info',
        message: String(msgs[i]),
        logger: '',
        color: '',
      })
      added = true
    }
  }
  // Clear SSE buffer to prevent memory leak
  clearSSE()
  lastProcessedIndex = 0
  // Cap at maxQueueSize to prevent memory issues
  if (allLogs.value.length > maxQueueSize.value) {
    allLogs.value = allLogs.value.slice(-maxQueueSize.value)
  }
  if (added) smartScrollToBottom()
}, { deep: true })

onMounted(async () => {
  // Load saved filter levels
  try {
    const raw = localStorage.getItem('log_filter_levels')
    if (raw !== null) {
      const saved = JSON.parse(raw)
      if (Array.isArray(saved)) filterLevels.value = saved
    }
  } catch { /* ignore */ }

  // Fetch log config (maxQueueSize)
  try {
    const configRes = await getLogConfig()
    maxQueueSize.value = configRes.data.maxQueueSize || 100
  } catch { /* ignore */ }

  // Load history
  try {
    const res = await getLogHistory(100)
    allLogs.value = res.data.logs || []
    scrollToBottom()
  } catch (e) {
    console.error('Failed to load log history:', e)
  }

  // Connect SSE
  loadLogs()
})

onUnmounted(() => {
  disconnect()
})
</script>
