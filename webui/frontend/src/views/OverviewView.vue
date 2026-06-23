<template>
  <div>
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-6">
      <!-- Uptime -->
      <div class="glass-card rounded-lg p-6">
        <div class="flex items-center justify-between">
          <div>
            <p class="text-sm text-gray-600">{{ $t('overview.runtime_duration') }}</p>
            <p class="text-2xl font-bold text-gray-900 mt-2">{{ formattedUptime }}</p>
          </div>
          <div class="bg-blue-100 rounded-full p-3">
            <IconClock class="w-6 h-6 text-blue-600" />
          </div>
        </div>
      </div>

      <!-- Total Messages -->
      <div class="glass-card rounded-lg p-6">
        <div class="flex items-center justify-between">
          <div>
            <p class="text-sm text-gray-600">{{ $t('overview.total_messages') }}</p>
            <p class="text-2xl font-bold text-gray-900 mt-2">{{ overview?.total_messages ?? 0 }}</p>
          </div>
          <div class="bg-green-100 rounded-full p-3">
            <IconChat class="w-6 h-6 text-green-600" />
          </div>
        </div>
      </div>

      <!-- Adapter Count -->
      <div class="glass-card rounded-lg p-6">
        <div class="flex items-center justify-between">
          <div>
            <p class="text-sm text-gray-600">{{ $t('overview.adapter_count') }}</p>
            <p class="text-2xl font-bold text-gray-900 mt-2">
              {{ overview?.active_adapters ?? 0 }} / {{ overview?.total_adapters ?? 0 }}
            </p>
          </div>
          <div class="bg-purple-100 rounded-full p-3">
            <IconTerminal class="w-6 h-6 text-purple-600" />
          </div>
        </div>
      </div>

      <!-- Memory Usage -->
      <div class="glass-card rounded-lg p-6">
        <div class="flex items-center justify-between">
          <div>
            <p class="text-sm text-gray-600">{{ $t('overview.memory_usage') }}</p>
            <p class="text-2xl font-bold text-gray-900 mt-2">
              {{ overview?.memory_usage ?? 0 }} MB
            </p>
          </div>
          <div class="bg-yellow-100 rounded-full p-3">
            <IconCpu class="w-6 h-6 text-yellow-600" />
          </div>
        </div>
      </div>
    </div>

    <!-- Plugin Widgets: Small Cards -->
    <div v-if="smallWidgets.length"
         class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-6">
      <div v-for="w in smallWidgets" :key="w.widget_id" class="glass-card rounded-lg p-6">
        <div class="flex items-center justify-between">
          <div>
            <p class="text-sm text-gray-600">{{ resolveWidgetLabel(w.label) }}</p>
            <p class="text-2xl font-bold text-gray-900 mt-2">{{ w.value }}</p>
          </div>
          <div class="rounded-full p-3" :class="widgetBgClass(w.color)">
            <component :is="resolveWidgetIcon(w.icon)"
                       class="w-6 h-6" :class="widgetFgClass(w.color)" />
          </div>
        </div>
      </div>
    </div>

    <!-- Plugin Widgets: Wide Cards -->
    <template v-for="w in wideWidgets" :key="w.widget_id">
      <div class="glass-card rounded-lg p-6 mb-6">
        <h3 class="text-lg font-semibold text-gray-800 mb-4">
          {{ resolveWidgetLabel(w.label) }}
        </h3>
        <div class="widget-html-content" v-html="w.html"></div>
      </div>
    </template>

    <!-- System Status -->
    <div class="glass-card rounded-lg p-6">
      <h3 class="text-lg font-semibold text-gray-800 mb-4">{{ $t('overview.system_status') }}</h3>
      <div class="flex items-center">
        <span class="w-3 h-3 rounded-full mr-2" :class="statusDotClass"></span>
        <span class="text-gray-700">{{ statusText }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { IconClock, IconChat, IconTerminal, IconCpu } from '@/components/icons'
import { getOverview } from '@/api/overview'
import type { OverviewResponse, OverviewWidget } from '@/types'
import { Box } from '@element-plus/icons-vue'
import { iconMap } from '@/utils/iconMap'

const { t, locale } = useI18n()
const overview = ref<OverviewResponse | null>(null)
const runtimeSeconds = ref(0)
let refreshTimer: ReturnType<typeof setInterval> | null = null
let runtimeTimer: ReturnType<typeof setInterval> | null = null
let inFlight = false
let disposed = false

const formattedUptime = computed(() => {
  // Normalize against malformed / non-integer API values so the formatter
  // can never produce `NaN:NaN:NaN` or fractional seconds.
  const raw = Number(runtimeSeconds.value)
  const s = Number.isFinite(raw) ? Math.max(0, Math.floor(raw)) : 0
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
})

const statusDotClass = computed(() => {
  if (!overview.value) return 'bg-gray-400'
  const s = overview.value.system_status
  if (s === 'running') return 'bg-green-500'
  if (s === 'starting' || s === 'degraded') return 'bg-yellow-500'
  if (s === 'error' || s === 'failed') return 'bg-red-500'
  return 'bg-gray-400'
})

const statusText = computed(() => {
  if (!overview.value) return t('overview.status_unknown')
  const validStatuses = ['running', 'stopped', 'degraded', 'starting', 'error', 'failed']
  const status = overview.value.system_status
  if (!status || !validStatuses.includes(status)) return t('overview.status_unknown')
  return t(`overview.status_${status}`)
})

/* ---- Plugin widget helpers ---- */

function resolveWidgetLabel(label: string | Record<string, string>): string {
  if (typeof label === 'string') return label
  const loc = locale.value
  return label[loc] || label['en'] || Object.values(label)[0] || ''
}

function resolveWidgetIcon(iconName: string) {
  return iconMap[iconName] || Box
}

/** Map widget color names to Tailwind classes.
 *  Using Tailwind class names (not inline styles) so the global dark-mode
 *  overrides in main.css (.dark .text-blue-600, etc.) take effect. */
const widgetBgClasses: Record<string, string> = {
  blue:   'bg-blue-100',
  green:  'bg-green-100',
  purple: 'bg-purple-100',
  yellow: 'bg-yellow-100',
  red:    'bg-red-100',
  gray:   'bg-gray-100',
}
const widgetFgClasses: Record<string, string> = {
  blue:   'text-blue-600',
  green:  'text-green-600',
  purple: 'text-purple-600',
  yellow: 'text-yellow-600',
  red:    'text-red-600',
  gray:   'text-gray-600',
}

function widgetBgClass(color: string) {
  return widgetBgClasses[color] || widgetBgClasses.blue
}
function widgetFgClass(color: string) {
  return widgetFgClasses[color] || widgetFgClasses.blue
}

const smallWidgets = computed(() =>
  (overview.value?.widgets || [])
    .filter(w => w.size === 'small')
    .sort((a, b) => a.order - b.order),
)

const wideWidgets = computed(() =>
  (overview.value?.widgets || [])
    .filter(w => w.size === 'wide')
    .sort((a, b) => a.order - b.order),
)

async function fetchOverview() {
  if (inFlight || disposed) return
  inFlight = true
  try {
    const res = await getOverview()
    // If the component unmounted while awaiting, bail without touching state
    // or resurrecting the runtime timer.
    if (disposed) return
    overview.value = res.data
    const rawRuntime = Number(res.data.runtime_duration)
    runtimeSeconds.value = Number.isFinite(rawRuntime) ? Math.max(0, Math.floor(rawRuntime)) : 0
    // Start or restart the 1s runtime tick after a successful fetch
    if (runtimeTimer) clearInterval(runtimeTimer)
    runtimeTimer = setInterval(() => {
      runtimeSeconds.value++
    }, 1000)
  } catch {
    // silent
  } finally {
    inFlight = false
  }
}

onMounted(() => {
  fetchOverview()
  refreshTimer = setInterval(fetchOverview, 30000)
})

onUnmounted(() => {
  disposed = true
  if (refreshTimer) clearInterval(refreshTimer)
  if (runtimeTimer) clearInterval(runtimeTimer)
  refreshTimer = null
  runtimeTimer = null
})
</script>

<style scoped>
/* Dark-mode defaults for unstyled elements inside v-html widget content.
   Gives bare <td>, <p>, etc. a readable light text colour.
   Elements with explicit Tailwind classes (e.g. dark:text-gray-100)
   will override this via the global dark-mode rules in main.css. */
.dark .widget-html-content :deep(td),
.dark .widget-html-content :deep(th),
.dark .widget-html-content :deep(p),
.dark .widget-html-content :deep(span),
.dark .widget-html-content :deep(li),
.dark .widget-html-content :deep(label) {
  color: #e5e7eb;
}
.dark .widget-html-content :deep(a:not([class])) {
  color: #60a5fa;
}
</style>
