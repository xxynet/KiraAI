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

    <!-- Message Distribution Charts -->
    <div class="grid grid-cols-1 lg:grid-cols-5 gap-6 mb-6">
      <!-- Line chart: hourly messages (wider) -->
      <div class="glass-card rounded-lg p-6 lg:col-span-3">
        <h3 class="text-lg font-semibold text-gray-800 mb-4">{{ $t('overview.hourly_messages') }}</h3>
        <div ref="lineChartRef" class="w-full" style="height: 300px"></div>
      </div>
      <!-- Pie chart: platform distribution -->
      <div class="glass-card rounded-lg p-6 lg:col-span-2">
        <h3 class="text-lg font-semibold text-gray-800 mb-4">{{ $t('overview.platform_distribution') }}</h3>
        <div ref="pieChartRef" class="w-full" style="height: 300px"></div>
      </div>
    </div>

    <!-- Plugin Widgets: Small Cards -->
    <div v-if="smallWidgets.length"
         class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-6">
      <div v-for="w in smallWidgets" :key="w.widget_id" class="glass-card rounded-lg p-6">
        <div class="flex items-center justify-between">
          <div>
            <p class="text-sm text-gray-600">{{ resolveWidgetLabel(w.label) }}</p>
            <p class="text-2xl font-bold text-gray-900 mt-2">{{ w.content }}</p>
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
        <div class="widget-html-content" v-html="w.content"></div>
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
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import * as echarts from 'echarts'
import { IconClock, IconChat, IconTerminal, IconCpu } from '@/components/icons'
import { getOverview } from '@/api/overview'
import type { OverviewResponse, OverviewWidget } from '@/types'
import { Box } from '@element-plus/icons-vue'
import { iconMap } from '@/utils/iconMap'
import { useTheme } from '@/composables/useTheme'

const { t, locale } = useI18n()
const { isDark } = useTheme()
const overview = ref<OverviewResponse | null>(null)
const runtimeSeconds = ref(0)
const lineChartRef = ref<HTMLElement | null>(null)
const pieChartRef = ref<HTMLElement | null>(null)
let lineChart: echarts.ECharts | null = null
let pieChart: echarts.ECharts | null = null
let refreshTimer: ReturnType<typeof setInterval> | null = null
let runtimeTimer: ReturnType<typeof setInterval> | null = null
let inFlight = false
let disposed = false

const formattedUptime = computed(() => {
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

/* ---- Charts ---- */

/** Return color tokens for the current theme. */
function themeTokens(dark: boolean) {
  return {
    tooltipBg: dark ? 'rgba(30,41,59,0.94)' : 'rgba(255,255,255,0.9)',
    tooltipBorder: dark ? '#4b5563' : '#e5e7eb',
    tooltipText: dark ? '#e5e7eb' : '#1f2937',
    axisLabel: dark ? '#9ca3af' : '#6b7280',
    axisLine: dark ? '#374151' : '#e5e7eb',
    splitLine: dark ? '#1f2937' : '#f3f4f6',
    legendText: dark ? '#9ca3af' : '#6b7280',
    seriesBlue: '#3b82f6',
    areaGradientTop: dark ? 'rgba(59,130,246,0.25)' : 'rgba(59,130,246,0.3)',
    areaGradientBottom: dark ? 'rgba(59,130,246,0.01)' : 'rgba(59,130,246,0.02)',
  }
}

/** Generate a complete 24-hour series filled with zeros, then merge
 *  API data into it so empty hours still appear on the x-axis. */
function fillMissingHours(hourly: OverviewResponse['message_hourly']): OverviewResponse['message_hourly'] {
  const now = Date.now()
  const currentHour = Math.floor(now / 3600000) * 3600
  const startTs = currentHour - 23 * 3600

  const buckets: OverviewResponse['message_hourly'] = []
  for (let i = 0; i < 24; i++) {
    const hourTs = startTs + i * 3600
    buckets.push({ hour_ts: hourTs, count: 0 })
  }

  const lookup = new Map<number, number>()
  for (const d of hourly) {
    lookup.set(d.hour_ts, d.count)
  }
  for (const b of buckets) {
    b.count = lookup.get(b.hour_ts) ?? 0
  }
  return buckets
}

const filledHourly = computed(() =>
  overview.value ? fillMissingHours(overview.value.message_hourly) : [],
)

function formatHourLabel(hourTs: number): string {
  const d = new Date(hourTs * 1000)
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  return `${hh}:${mm}`
}

const platformColorMap: Record<string, string> = {
  qq: '#e74c3c',
  telegram: '#3498db',
  discord: '#5865f2',
  wechat: '#27ae60',
  bilibili: '#fb7299',
  slack: '#4a154b',
  whatsapp: '#25d366',
}

function getPlatformColor(platform: string): string {
  return platformColorMap[platform.toLowerCase()] || '#7f8c8d'
}

function buildLineOption(data: OverviewResponse['message_hourly'], dark: boolean) {
  const tok = themeTokens(dark)
  return {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      backgroundColor: tok.tooltipBg,
      borderColor: tok.tooltipBorder,
      borderWidth: 1,
      textStyle: { color: tok.tooltipText, fontSize: 13 },
      formatter: (params: any) => {
        const p = params[0]
        if (!p) return ''
        const raw = new Date(data[p.dataIndex]?.hour_ts * 1000 || 0)
        const dateStr = `${raw.getMonth() + 1}/${raw.getDate()} ${String(raw.getHours()).padStart(2, '0')}:00`
        return `<strong>${dateStr}</strong><br/>${t('overview.hourly_tooltip')}: ${p.value}`
      },
    },
    grid: { left: 50, right: 20, top: 20, bottom: 30 },
    xAxis: {
      type: 'category',
      data: data.map(d => formatHourLabel(d.hour_ts)),
      axisLabel: { color: tok.axisLabel, fontSize: 11 },
      axisLine: { lineStyle: { color: tok.axisLine } },
      axisTick: { alignWithLabel: true },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      axisLabel: { color: tok.axisLabel, fontSize: 11 },
      splitLine: { lineStyle: { color: tok.splitLine } },
    },
    series: [
      {
        type: 'line',
        data: data.map(d => d.count),
        smooth: true,
        lineStyle: { color: tok.seriesBlue, width: 2 },
        itemStyle: { color: tok.seriesBlue },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: tok.areaGradientTop },
            { offset: 1, color: tok.areaGradientBottom },
          ]),
        },
        symbol: 'circle',
        symbolSize: 6,
      },
    ],
  }
}

function buildPieOption(data: OverviewResponse['message_by_platform'], dark: boolean) {
  const tok = themeTokens(dark)
  return {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'item',
      backgroundColor: tok.tooltipBg,
      borderColor: tok.tooltipBorder,
      borderWidth: 1,
      textStyle: { color: tok.tooltipText, fontSize: 13 },
      formatter: (params: any) => {
        return `<strong>${params.name}</strong><br/>${t('overview.pie_tooltip_count')}: ${params.value}<br/>${t('overview.pie_tooltip_pct')}: ${params.percent}%`
      },
    },
    legend: {
      orient: 'horizontal',
      bottom: 0,
      left: 'center',
      textStyle: { color: tok.legendText, fontSize: 12 },
    },
    grid: { left: 0, right: 0, top: 0, bottom: 40 },
    series: [
      {
        type: 'pie',
        radius: ['40%', '65%'],
        center: ['50%', '45%'],
        avoidLabelOverlap: true,
        label: { show: false },
        emphasis: {
          label: { show: true, fontSize: 14, fontWeight: 'bold' },
          itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(0,0,0,0.15)' },
        },
        data: data.map(d => ({
          value: d.count,
          name: d.platform,
          itemStyle: { color: getPlatformColor(d.platform) },
        })),
      },
    ],
  }
}

function renderCharts() {
  if (!overview.value || disposed) return

  if (lineChartRef.value) {
    if (!lineChart) {
      lineChart = echarts.init(lineChartRef.value)
    }
    lineChart.setOption(buildLineOption(filledHourly.value, isDark.value), true)
  }

  if (pieChartRef.value) {
    if (!pieChart) {
      pieChart = echarts.init(pieChartRef.value)
    }
    pieChart.setOption(buildPieOption(overview.value.message_by_platform, isDark.value), true)
  }
}

// Re-render charts when dark mode toggles
watch(isDark, () => { nextTick(renderCharts) })

watch(
  [lineChartRef, pieChartRef],
  () => {
    if (lineChartRef.value || pieChartRef.value) {
      nextTick(renderCharts)
    }
  },
)

async function fetchOverview() {
  if (inFlight || disposed) return
  inFlight = true
  try {
    const res = await getOverview()
    if (disposed) return
    overview.value = res.data
    const rawRuntime = Number(res.data.runtime_duration)
    runtimeSeconds.value = Number.isFinite(rawRuntime) ? Math.max(0, Math.floor(rawRuntime)) : 0
    if (runtimeTimer) clearInterval(runtimeTimer)
    runtimeTimer = setInterval(() => {
      runtimeSeconds.value++
    }, 1000)
    await nextTick()
    renderCharts()
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
  if (lineChart) { lineChart.dispose(); lineChart = null }
  if (pieChart) { pieChart.dispose(); pieChart = null }
  if (refreshTimer) clearInterval(refreshTimer)
  if (runtimeTimer) clearInterval(runtimeTimer)
  refreshTimer = null
  runtimeTimer = null
})
</script>

<style scoped>
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
