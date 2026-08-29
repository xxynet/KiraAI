<template>
  <div class="bg-white rounded-lg shadow p-6 dark:bg-gray-800 dark:shadow-gray-900/50">
    <!-- Header -->
    <div class="flex justify-between items-center mb-6">
      <h3 class="text-lg font-semibold text-theme-strong">{{ $t('logs.title') }}</h3>
      <div class="flex flex-wrap gap-2 justify-end">
        <!-- Freeze the stream so the list stops moving while reading -->
        <button
          class="px-4 py-2 rounded-lg transition-colors flex items-center whitespace-nowrap text-white"
          :class="isPaused ? 'bg-amber-600 hover:bg-amber-700' : 'bg-gray-600 hover:bg-gray-700'"
          :title="isPaused ? $t('logs.resume_hint') : $t('logs.pause_hint')"
          :aria-pressed="isPaused"
          @click="togglePause"
        >
          <svg v-if="isPaused" class="w-5 h-5 mr-2" fill="currentColor" viewBox="0 0 20 20" aria-hidden="true">
            <path d="M6.3 3.8a1 1 0 0 1 1.02.05l8 5a1 1 0 0 1 0 1.7l-8 5A1 1 0 0 1 5.8 14.7V5.3a1 1 0 0 1 .5-.87Z" />
          </svg>
          <svg v-else class="w-5 h-5 mr-2" fill="currentColor" viewBox="0 0 20 20" aria-hidden="true">
            <path d="M6 4a1 1 0 0 1 1 1v10a1 1 0 1 1-2 0V5a1 1 0 0 1 1-1Zm8 0a1 1 0 0 1 1 1v10a1 1 0 1 1-2 0V5a1 1 0 0 1 1-1Z" />
          </svg>
          <span>{{ isPaused ? $t('logs.resume') : $t('logs.pause') }}</span>
        </button>

        <!-- Auto-scroll opt-out: keeps the viewport still even while pinned to the bottom -->
        <button
          class="px-4 py-2 rounded-lg border transition-colors flex items-center whitespace-nowrap"
          :class="autoScroll
            ? 'border-blue-500 text-blue-600 bg-blue-50 dark:bg-blue-900/30 dark:text-blue-300 dark:border-blue-500'
            : 'border-gray-300 text-theme-supporting dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700'"
          :aria-pressed="autoScroll"
          @click="toggleAutoScroll"
        >
          <svg class="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 14l-7 7m0 0l-7-7m7 7V3" />
          </svg>
          <span>{{ $t('logs.auto_scroll') }}</span>
        </button>

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
    <div class="mb-4 flex flex-wrap gap-3 items-center">
      <!-- Grow-to-fill wrapper: .custom-select is width:100%, which as a flex item
           resolves to a full-width basis and forces the buttons to wrap. flex-1
           (basis 0 + grow) instead lets it fill only the space left after the
           buttons, so it spans the row without pushing them onto a new line;
           min-w gives it a floor so it wraps gracefully on a narrow screen. -->
      <div class="flex-1 min-w-[12rem]">
        <CustomMultiSelect
          v-model="filterLevels"
          :options="levelOptions"
          :placeholder="$t('logs.filter_level')"
          @update:modelValue="applyFilter"
        />
      </div>

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
          <h3 class="text-lg font-semibold text-theme-strong">{{ $t('logs.install_deps') }}</h3>
          <button type="button" class="text-theme-faint text-theme-faint-hover" @click="showInstallPanel = false">
            <IconClose class="w-6 h-6" />
          </button>
        </div>
        <div class="px-6 py-5 flex-1 overflow-y-auto">
          <div class="mb-4">
            <label class="block text-sm font-medium text-theme-body mb-2">{{ $t('logs.install_packages_label') }}</label>
            <UiTextarea
              v-model="installPackagesInput"
              :placeholder="$t('logs.install_packages_placeholder')"
              class="w-full rounded-lg px-3 py-2 font-mono text-sm resize-none transition-colors"
              rows="3"
              @keydown.ctrl.enter="handleInstall"
            />
          </div>
        </div>
        <div class="px-6 py-4 border-t border-gray-200 dark:border-gray-700 flex justify-end space-x-3">
          <button type="button" class="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-theme-body hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors" @click="showInstallPanel = false">{{ $t('logs.install_close') }}</button>
          <button type="button" class="px-4 py-2 bg-blue-600 dark:bg-blue-700 text-white rounded-lg hover:bg-blue-700 dark:hover:bg-blue-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center" :disabled="isInstalling" @click="handleInstall">
            <IconSpinner v-if="isInstalling" class="w-5 h-5 mr-2 animate-spin" />
            <IconPackage v-else class="w-5 h-5 mr-2" />
            <span>{{ isInstalling ? $t('logs.install_installing') : $t('logs.install_btn') }}</span>
          </button>
        </div>
      </div>
    </Modal>

    <!-- Log container -->
    <div class="relative">
      <div
        ref="logContainerRef"
        id="log-container"
        class="rounded-lg p-4 overflow-y-auto min-h-64"
        style="height: calc(100vh - 18rem);"
        @scroll.passive="onScroll"
      >
        <div v-if="visibleLogs.length === 0 && pendingCount === 0" class="flex justify-center items-center h-full">
          <p class="text-theme-subtle">{{ $t('logs.no_logs') }}</p>
        </div>
        <div
          v-for="log in visibleLogs"
          :key="log.id"
          data-log-entry
          class="font-mono text-base whitespace-normal break-words"
        >
          <span class="text-theme-subtle">[{{ log.timestamp }}]</span> <span :class="logLevelColor(log.level)" class="font-semibold whitespace-pre-wrap">{{ padLevel(log.level) }}</span> <span v-if="log.logger" :style="{ color: log.color || '#3b82f6' }" class="font-semibold">[{{ log.logger }}]</span> <span class="text-theme-body whitespace-pre-wrap">{{ log.message }}</span>
        </div>
      </div>

      <!-- Held-stream pill: new lines are buffered, not injected, so the view never jumps -->
      <transition
        enter-active-class="transition duration-150 ease-out"
        enter-from-class="opacity-0 translate-y-2"
        leave-active-class="transition duration-100 ease-in"
        leave-to-class="opacity-0 translate-y-2"
      >
        <button
          v-if="isHeld"
          class="absolute bottom-4 left-1/2 -translate-x-1/2 px-4 py-2 rounded-full shadow-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 transition-colors flex items-center"
          @click="jumpToLatest"
        >
          <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 14l-7 7m0 0l-7-7m7 7V3" />
          </svg>
          <span v-if="pendingCount > 0">{{ $t('logs.new_logs', { count: pendingCount }) }}</span>
          <span v-else>{{ $t('logs.jump_to_latest') }}</span>
        </button>
      </transition>
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
import UiTextarea from '@/components/ui/UiTextarea.vue'
import type { LogEntry } from '@/types'

// A stable, monotonically increasing id per row. Using the array index as the
// v-for key made Vue patch every existing row whenever the queue was trimmed
// from the front, which caused visible flicker and lost text selection.
type LogRow = LogEntry & { id: number }

// How close to the bottom (in px) still counts as "following the stream".
// A pixel threshold behaves consistently at any content height, unlike the
// previous scrollHeight ratio which flipped behaviour as the buffer grew.
const STICK_THRESHOLD_PX = 48

const { t } = useI18n()
const logContainerRef = ref<HTMLElement | null>(null)
const filterLevels = ref<string[]>(['info', 'warning', 'error'])
const allLogs = ref<LogRow[]>([])
// Lines that arrived while the view was held. They are kept out of `allLogs`
// so the rendered list is completely static while the user is reading.
const pendingLogs = ref<LogRow[]>([])
const droppedWhileHeld = ref(0)
const maxQueueSize = ref(100)

const isPaused = ref(false)
const autoScroll = ref(true)
const atBottom = ref(true)

const { messages, connect, disconnect, clear: clearSSE } = useSSE()

const showInstallPanel = ref(false)
const installPackagesInput = ref('')
const isInstalling = ref(false)

let rowId = 0
let scrollRaf = 0

const levelOptions = [
  { label: 'DEBUG', value: 'debug' },
  { label: 'INFO', value: 'info' },
  { label: 'WARNING', value: 'warning' },
  { label: 'ERROR', value: 'error' },
]

// The stream is "held" whenever appending would move content under the user's
// eyes: either they explicitly paused, or they scrolled away from the bottom.
const isHeld = computed(() => isPaused.value || !atBottom.value)
const pendingCount = computed(() => pendingLogs.value.length)

// The view can also stop being held without going through pause/jump-to-latest,
// e.g. the user drags the scrollbar back to the bottom or a resize recomputes
// `atBottom` as true. Flush on every release so buffered lines are never left
// orphaned (lost from the view, and appended out of order on the next hold).
watch(isHeld, (held) => {
  if (!held) flushPending()
})

function matchesFilters(log: LogRow): boolean {
  const level = log.level?.toLowerCase()
  // CRITICAL is treated the same as ERROR
  const normalized = level === 'critical' ? 'error' : level
  return filterLevels.value.includes(normalized)
}

const visibleLogs = computed(() => allLogs.value.filter(matchesFilters))

function applyFilter() {
  localStorage.setItem('log_filter_levels', JSON.stringify(filterLevels.value))
  // Don't yank a held view (paused or scrolled up) to the bottom on a filter
  // change — scrollToBottom sets atBottom=true, which would also flush the hold.
  if (!isHeld.value) scrollToBottom()
}

function toggleAutoScroll() {
  autoScroll.value = !autoScroll.value
  localStorage.setItem('log_auto_scroll', JSON.stringify(autoScroll.value))
  if (autoScroll.value) jumpToLatest()
}

function togglePause() {
  if (isPaused.value) {
    isPaused.value = false
    flushPending()
  } else {
    isPaused.value = true
  }
}

function jumpToLatest() {
  isPaused.value = false
  flushPending()
}

function flushPending() {
  if (pendingLogs.value.length > 0) {
    allLogs.value.push(...pendingLogs.value)
    pendingLogs.value = []
    trimVisible()
  }
  // Surface dropped lines as a one-shot notice; a banner gated on `isHeld` would
  // vanish at the exact moment the user releases the hold, so they'd never see it.
  if (droppedWhileHeld.value > 0) {
    notify(t('logs.buffer_overflow', { count: droppedWhileHeld.value }), 'warning')
    droppedWhileHeld.value = 0
  }
  scrollToBottom()
}

function trimVisible() {
  // Cap at maxQueueSize to prevent memory issues
  const overflow = allLogs.value.length - maxQueueSize.value
  if (overflow > 0) allLogs.value = allLogs.value.slice(overflow)
}

function ingest(rows: LogRow[]) {
  if (rows.length === 0) return

  if (isHeld.value) {
    pendingLogs.value.push(...rows)
    const overflow = pendingLogs.value.length - maxQueueSize.value
    if (overflow > 0) {
      pendingLogs.value = pendingLogs.value.slice(overflow)
      droppedWhileHeld.value += overflow
    }
    return
  }

  allLogs.value.push(...rows)
  trimVisible()
  // With auto-scroll off we deliberately leave `atBottom` untouched: a plain
  // append must not unpin the view (that would make "auto-scroll off" silently
  // degenerate into "paused" once a couple of rows pile up below the fold).
  // Only a user-initiated scroll or resize recomputes it.
  if (autoScroll.value) scrollToBottom()
}

function parseLogMessage(raw: unknown): LogRow {
  try {
    const logData = typeof raw === 'string' ? JSON.parse(raw) : raw
    return {
      id: rowId++,
      timestamp: logData.time || logData.timestamp || new Date().toLocaleString(),
      level: logData.level || 'info',
      message: logData.message || logData.msg || '',
      logger: logData.logger || logData.name || '',
      color: logData.color || '',
    }
  } catch {
    // Preserve raw text messages when JSON parse fails
    return {
      id: rowId++,
      timestamp: new Date().toLocaleString(),
      level: 'info',
      message: String(raw),
      logger: '',
      color: '',
    }
  }
}

function toRows(entries: LogEntry[]): LogRow[] {
  return entries.map(entry => ({ ...entry, id: rowId++ }))
}

function clearLogs() {
  if (!confirm(t('logs.clear_confirm'))) return
  allLogs.value = []
  pendingLogs.value = []
  droppedWhileHeld.value = 0
  clearSSE()
  // The now-empty list is trivially "at the bottom"; recompute rather than
  // relying on the incidental scroll event that emptying happens to fire.
  nextTick(updateAtBottom)
  notify(t('logs.cleared'), 'success')
}

async function refreshLogs() {
  disconnect()
  clearSSE()
  pendingLogs.value = []
  droppedWhileHeld.value = 0
  isPaused.value = false
  try {
    const res = await getLogHistory(maxQueueSize.value)
    allLogs.value = toRows(res.data.logs || [])
    // Defensive cap in case the backend returns more than requested.
    trimVisible()
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
  return 'text-theme-subtle'
}

function padLevel(level: string): string {
  // Pad to 7 characters for alignment (WARNING is 7 chars)
  return (level || 'INFO').toUpperCase().padEnd(7, ' ')
}

function updateAtBottom() {
  const el = logContainerRef.value
  if (!el) return
  atBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight <= STICK_THRESHOLD_PX
}

function onScroll() {
  // Coalesce the burst of scroll events a single gesture produces.
  if (scrollRaf) return
  scrollRaf = requestAnimationFrame(() => {
    scrollRaf = 0
    updateAtBottom()
  })
}

function scrollToBottom() {
  nextTick(() => {
    const el = logContainerRef.value
    if (!el) return
    // Instant (not smooth) so the scroll handler sees a single settled
    // position instead of intermediate ones that would unpin the view.
    el.scrollTop = el.scrollHeight
    atBottom.value = true
  })
}

function formatLogLine(log: LogRow): string {
  const logger = log.logger ? ` [${log.logger}]` : ''
  return `[${log.timestamp}] ${padLevel(log.level)}${logger} ${log.message}`
}

function downloadLogs() {
  // Built from the data model rather than the DOM: the previous version
  // exported only what happened to be rendered, and would now also miss
  // anything buffered while the stream was held.
  const rows = [...visibleLogs.value, ...pendingLogs.value.filter(matchesFilters)]
  if (rows.length === 0) {
    notify(t('logs.no_logs'), 'warning')
    return
  }

  const blob = new Blob([rows.map(formatLogLine).join('\n')], { type: 'text/plain;charset=utf-8' })
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
  } catch (e: any) {
    console.error('Failed to start package installation:', e)
    if (e?.response?.status === 409) {
      notify(t('logs.install_already_running'), 'warning')
    } else {
      notify(t('logs.install_failed'), 'error')
    }
  } finally {
    isInstalling.value = false
  }
}

// Watch for new SSE messages
watch(messages, (msgs) => {
  if (msgs.length === 0) return
  const rows = msgs.map(parseLogMessage)
  // Clear SSE buffer to prevent memory leak. This re-triggers the watcher with
  // an empty array, which the guard above short-circuits.
  clearSSE()
  ingest(rows)
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

  // Load saved auto-scroll preference
  try {
    const raw = localStorage.getItem('log_auto_scroll')
    if (raw !== null) autoScroll.value = JSON.parse(raw) !== false
  } catch { /* ignore */ }

  // Fetch log config (maxQueueSize)
  try {
    const configRes = await getLogConfig()
    maxQueueSize.value = configRes.data.maxQueueSize || 100
  } catch { /* ignore */ }

  // Load history
  try {
    const res = await getLogHistory(maxQueueSize.value)
    allLogs.value = toRows(res.data.logs || [])
    // Defensive cap in case the backend returns more than requested.
    trimVisible()
    scrollToBottom()
  } catch (e) {
    console.error('Failed to load log history:', e)
  }

  // Resizing changes clientHeight, which changes what counts as "at bottom"
  window.addEventListener('resize', updateAtBottom)

  // Connect SSE
  loadLogs()
})

onUnmounted(() => {
  window.removeEventListener('resize', updateAtBottom)
  if (scrollRaf) cancelAnimationFrame(scrollRaf)
  disconnect()
})
</script>
