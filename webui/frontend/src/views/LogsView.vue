<template>
  <div class="flex flex-col h-full">
    <!-- Toolbar -->
    <div class="flex items-center justify-between mb-4">
      <div class="flex items-center gap-3">
        <el-select
          v-model="filterLevels"
          multiple
          collapse-tags
          size="small"
          :placeholder="$t('logs.filter_level')"
          style="width: 280px;"
          @change="applyFilter"
        >
          <el-option label="DEBUG" value="debug" />
          <el-option label="INFO" value="info" />
          <el-option label="WARNING" value="warning" />
          <el-option label="ERROR" value="error" />
        </el-select>
        <el-switch v-model="autoScroll" :active-text="$t('logs.auto_scroll')" size="small" />
      </div>
      <div class="flex gap-2">
        <el-button size="small" @click="clearLogs">{{ $t('logs.clear') }}</el-button>
        <el-tag :type="connected ? 'success' : 'danger'" size="small">
          {{ connected ? $t('logs.connected') : $t('logs.disconnected') }}
        </el-tag>
      </div>
    </div>

    <!-- Log Container -->
    <div
      ref="logContainerRef"
      class="log-container flex-1 glass-card rounded-lg p-4 overflow-auto font-mono text-sm"
      style="min-height: 400px;"
    >
      <div v-if="filteredLogs.length === 0" class="flex items-center justify-center h-full text-gray-400">
        {{ $t('logs.no_logs') }}
      </div>
      <div
        v-for="(log, idx) in filteredLogs"
        :key="idx"
        class="log-entry py-0.5 border-b border-gray-100 dark:border-gray-800"
        :class="logLevelClass(log.level)"
      >
        <span class="text-gray-400 mr-2">{{ log.timestamp }}</span>
        <span class="font-semibold mr-2 uppercase" :class="logLevelColor(log.level)">[{{ log.level }}]</span>
        <span v-if="log.logger" class="text-gray-500 mr-2">[{{ log.logger }}]</span>
        <span class="text-gray-800 dark:text-gray-200 whitespace-pre-wrap break-words">{{ log.message }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useSSE } from '@/composables/useSSE'
import { getLogHistory } from '@/api/logs'
import type { LogEntry } from '@/types'

const { t } = useI18n()
const logContainerRef = ref<HTMLElement | null>(null)
const filterLevels = ref<string[]>(['debug', 'info', 'warning', 'error'])
const autoScroll = ref(true)
const allLogs = ref<LogEntry[]>([])

const { messages, connected, connect, disconnect, clear: clearSSE } = useSSE()
let lastProcessedIndex = 0

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

function logLevelClass(level: string) {
  const l = level?.toLowerCase()
  if (l === 'error') return 'bg-red-50/50 dark:bg-red-900/10'
  if (l === 'warning') return 'bg-yellow-50/50 dark:bg-yellow-900/10'
  return ''
}

function logLevelColor(level: string) {
  const l = level?.toLowerCase()
  if (l === 'error') return 'text-red-600'
  if (l === 'warning') return 'text-yellow-600'
  if (l === 'info') return 'text-blue-600'
  return 'text-gray-500'
}

function scrollToBottom() {
  if (!autoScroll.value || !logContainerRef.value) return
  nextTick(() => {
    logContainerRef.value!.scrollTop = logContainerRef.value!.scrollHeight
  })
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
      })
      added = true
    } catch {
      // Preserve raw text messages when JSON parse fails
      allLogs.value.push({
        timestamp: new Date().toLocaleString(),
        level: 'info',
        message: String(msgs[i]),
        logger: '',
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
  const token = localStorage.getItem('jwt_token')
  if (token) {
    connect(`/api/live-log`, token)
  }
})

onUnmounted(() => {
  disconnect()
})
</script>
