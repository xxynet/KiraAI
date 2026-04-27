<template>
  <div class="bg-white rounded-lg shadow p-6 h-full flex flex-col dark:bg-gray-800 dark:shadow-gray-900/50">
    <!-- Header -->
    <div class="flex justify-between items-center mb-6">
      <h3 class="text-lg font-semibold text-gray-800 dark:text-gray-100">{{ $t('logs.title') }}</h3>
      <div class="flex space-x-2">
        <button
          class="bg-gray-600 text-white px-4 py-2 rounded-lg hover:bg-gray-700 transition-colors flex items-center"
          @click="clearLogs"
        >
          <svg class="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path>
          </svg>
          <span>{{ $t('logs.clear') }}</span>
        </button>
        <button
          class="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 transition-colors flex items-center"
          @click="refreshLogs"
        >
          <svg class="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path>
          </svg>
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
        <svg class="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"></path>
        </svg>
        <span>{{ $t('logs.download') }}</span>
      </button>
    </div>

    <!-- Log container -->
    <div
      ref="logContainerRef"
      id="log-container"
      class="rounded-lg p-4 overflow-y-auto flex-1"
    >
      <div v-if="filteredLogs.length === 0" class="flex justify-center items-center h-full">
        <p class="text-gray-500 dark:text-gray-400">{{ $t('logs.no_logs') }}</p>
      </div>
      <div
        v-for="(log, idx) in filteredLogs"
        :key="idx"
        class="log-entry font-mono break-words"
      >
        <span class="text-gray-500 dark:text-gray-400">[{{ log.timestamp }}]</span>&nbsp;<span :class="logLevelColor(log.level)" class="font-semibold whitespace-pre-wrap">{{ padLevel(log.level) }}</span>&nbsp;<span v-if="log.logger" :style="{ color: log.color || '#3b82f6' }" class="font-semibold">[{{ log.logger }}]</span>&nbsp;<span class="text-gray-700 dark:text-gray-300 whitespace-pre-wrap">{{ log.message }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useSSE } from '@/composables/useSSE'
import { getLogHistory } from '@/api/logs'
import CustomMultiSelect from '@/components/common/CustomMultiSelect.vue'
import type { LogEntry } from '@/types'

const { t } = useI18n()
const logContainerRef = ref<HTMLElement | null>(null)
const filterLevels = ref<string[]>(['info', 'warning', 'error'])
const allLogs = ref<LogEntry[]>([])

const { messages, connected, connect, disconnect, clear: clearSSE } = useSSE()
let lastProcessedIndex = 0

const levelOptions = [
  { label: 'DEBUG', value: 'debug' },
  { label: 'INFO', value: 'info' },
  { label: 'WARNING', value: 'warning' },
  { label: 'ERROR', value: 'error' },
]

const filteredLogs = computed(() => {
  return allLogs.value.filter(log =>
    filterLevels.value.includes(log.level?.toLowerCase())
  )
})

function applyFilter() {
  localStorage.setItem('log_filter_levels', JSON.stringify(filterLevels.value))
}

function clearLogs() {
  allLogs.value = []
  clearSSE()
  lastProcessedIndex = 0
}

function refreshLogs() {
  disconnect()
  clearSSE()
  lastProcessedIndex = 0
  allLogs.value = []
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
    // Smart auto-scroll: only scroll if user is already near the bottom (ratio > 0.95)
    const scrollRatio = (el.scrollTop + el.clientHeight) / el.scrollHeight
    if (scrollRatio > 0.95) {
      el.scrollTop = el.scrollHeight
    }
  })
}

function downloadLogs() {
  const container = logContainerRef.value
  if (!container) return

  const lines = Array.from(container.querySelectorAll('.log-entry'))
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
  // Cap at 1000 entries
  if (allLogs.value.length > 1000) {
    allLogs.value = allLogs.value.slice(-1000)
  }
  if (added) scrollToBottom()
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
