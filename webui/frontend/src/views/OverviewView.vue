<template>
  <div>
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-6">
      <!-- Uptime -->
      <div class="glass-card rounded-lg p-6">
        <div class="flex items-center justify-between">
          <div>
            <p class="text-sm text-theme-supporting">{{ $t('overview.runtime_duration') }}</p>
            <p class="text-2xl font-bold text-theme-high mt-2">{{ formattedUptime }}</p>
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
            <p class="text-sm text-theme-supporting">{{ $t('overview.total_messages') }}</p>
            <p class="text-2xl font-bold text-theme-high mt-2">{{ overview?.total_messages ?? 0 }}</p>
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
            <p class="text-sm text-theme-supporting">{{ $t('overview.adapter_count') }}</p>
            <p class="text-2xl font-bold text-theme-high mt-2">
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
            <p class="text-sm text-theme-supporting">{{ $t('overview.memory_usage') }}</p>
            <p class="text-2xl font-bold text-theme-high mt-2">
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
        <h3 class="text-lg font-semibold text-theme-strong mb-4">{{ $t('overview.hourly_messages') }}</h3>
        <div ref="lineChartRef" class="w-full" style="height: 300px"></div>
      </div>
      <!-- Pie chart: platform distribution -->
      <div class="glass-card rounded-lg p-6 lg:col-span-2">
        <h3 class="text-lg font-semibold text-theme-strong mb-4">{{ $t('overview.platform_distribution') }}</h3>
        <div ref="pieChartRef" class="w-full" style="height: 300px"></div>
      </div>
    </div>

    <!-- Cache Hit Rate Chart -->
    <div class="glass-card rounded-lg p-6 mb-6">
      <div class="flex items-center justify-between mb-4">
        <h3 class="text-lg font-semibold text-theme-strong">{{ $t('overview.cache_hit_title') }}</h3>
        <div class="text-sm text-theme-supporting">
          {{ $t('overview.cache_hit_avg') }}:
          <span class="text-theme-high font-semibold">{{ cacheHitAvgLabel }}</span>
        </div>
      </div>
      <div v-if="hasCacheHitData" ref="cacheChartRef" class="w-full" style="height: 300px"></div>
      <div v-else class="flex items-center justify-center text-theme-supporting text-sm" style="height: 300px">
        {{ $t('overview.cache_hit_empty') }}
      </div>
    </div>

    <!-- LLM Stats -->
    <div class="glass-card rounded-lg p-6 mb-6">
      <h3 class="text-lg font-semibold text-theme-strong mb-4">{{ $t('overview.llm_title') }}</h3>
      <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div>
          <p class="text-xs text-theme-subtle">{{ $t('overview.llm_calls') }}</p>
          <p class="text-xl font-bold text-theme-high">{{ llmCalls }}</p>
        </div>
        <div>
          <p class="text-xs text-theme-subtle">{{ $t('overview.llm_tokens') }}</p>
          <p class="text-xl font-bold text-theme-high">{{ llmTokens }}</p>
        </div>
        <div>
          <p class="text-xs text-theme-subtle">{{ $t('overview.llm_success_rate') }}</p>
          <p class="text-xl font-bold text-theme-high">{{ llmSuccessRate }}</p>
        </div>
        <div>
          <p class="text-xs text-theme-subtle">{{ $t('overview.llm_avg_response') }}</p>
          <p class="text-xl font-bold text-theme-high">{{ llmAvgResponse }}</p>
        </div>
      </div>
      <!-- Model Usage Charts -->
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 mt-4" v-if="llmShowModelChart">
        <div>
          <p class="text-xs text-theme-subtle mb-1">{{ $t('overview.pie_tooltip_model_usage') }}</p>
          <div ref="modelChartRef" class="w-full" style="height: 200px"></div>
        </div>
        <div>
          <p class="text-xs text-theme-subtle mb-1">{{ $t('overview.llm_tokens') }}</p>
          <div ref="tokenChartRef" class="w-full" style="height: 200px"></div>
        </div>
      </div>
    </div>

    <!-- Plugin Widgets: Small Cards -->
    <div v-if="smallWidgets.length"
         class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-6">
      <div v-for="w in smallWidgets" :key="w.widget_id" class="glass-card rounded-lg p-6">
        <div class="flex items-center justify-between">
          <div>
            <p class="text-sm text-theme-supporting">{{ resolveWidgetLabel(w.label) }}</p>
            <p class="text-2xl font-bold text-theme-high mt-2">{{ w.content }}</p>
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
        <h3 class="text-lg font-semibold text-theme-strong mb-4">
          {{ resolveWidgetLabel(w.label) }}
        </h3>
        <div class="widget-html-content" v-html="DOMPurify.sanitize(w.content)"></div>
      </div>
    </template>

  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import DOMPurify from 'dompurify'
import * as echarts from 'echarts'
import { IconClock, IconChat, IconTerminal, IconCpu } from '@/components/icons'
import { getOverview } from '@/api/overview'
import type { OverviewResponse, OverviewWidget, LLMModelStat, CacheHitHourlyPoint } from '@/types'
import { Box } from '@element-plus/icons-vue'
import { iconMap } from '@/utils/iconMap'
import { useTheme } from '@/composables/useTheme'

const { t, locale } = useI18n()
const { isDark } = useTheme()
const overview = ref<OverviewResponse | null>(null)
const runtimeSeconds = ref(0)
const lineChartRef = ref<HTMLElement | null>(null)
const pieChartRef = ref<HTMLElement | null>(null)
const modelChartRef = ref<HTMLElement | null>(null)
const tokenChartRef = ref<HTMLElement | null>(null)
const cacheChartRef = ref<HTMLElement | null>(null)
let lineChart: echarts.ECharts | null = null
let pieChart: echarts.ECharts | null = null
let modelChart: echarts.ECharts | null = null
let tokenChart: echarts.ECharts | null = null
let cacheChart: echarts.ECharts | null = null
let refreshTimer: ReturnType<typeof setInterval> | null = null
let runtimeTimer: ReturnType<typeof setInterval> | null = null
let resizeObserver: ResizeObserver | null = null
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

/* ---- LLM computed properties ---- */

function formatNumber(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K'
  return String(n)
}

const llmSummary = computed(() => overview.value?.llm_summary)
const llmCalls = computed(() => formatNumber(llmSummary.value?.total_calls ?? 0))

const llmTokens = computed(() => {
  const s = llmSummary.value
  if (!s) return '0'
  return formatNumber(s.total_input_tokens + s.total_output_tokens)
})

const llmSuccessRate = computed(() => {
  const s = llmSummary.value
  if (!s || s.total_calls === 0) return '-'
  return (s.success_count / s.total_calls * 100).toFixed(1) + '%'
})

const llmAvgResponse = computed(() => {
  const s = llmSummary.value
  if (!s || s.total_calls === 0) return '-'
  const avg = s.total_response_ms / s.total_calls
  return avg < 1000 ? Math.round(avg) + ' ms' : (avg / 1000).toFixed(1) + ' s'
})

const llmShowModelChart = computed(() =>
  (llmSummary.value?.by_model?.length ?? 0) > 0,
)

/* ---- Cache hit rate ---- */

const cacheHitAvgLabel = computed(() => {
  const avg = overview.value?.cache_hit_avg
  if (avg === null || avg === undefined) return '-'
  return avg.toFixed(1) + '%'
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
  gray:   'text-theme-supporting',
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

interface CacheHitBucket {
  hour_ts: number
  hit_rate: number | null
  cached_tokens: number
  input_tokens: number
  calls: number
}

interface CacheHitSeries {
  model: string
  label: string
  points: CacheHitBucket[]
  avg: number | null
  calls: number
}

/** Like fillMissingHours, but keeps hours without cache data as null so they
 *  are not plotted as a misleading 0% hit rate (the line connects across them). */
function fillCacheHitHours(hourly: CacheHitHourlyPoint[], windowStartTs: number): CacheHitBucket[] {
  // The server window is authoritative; the client clock is only a fallback
  // for older responses so the grid cannot drift from cache_hit_avg.
  const startTs = windowStartTs > 0
    ? windowStartTs
    : Math.floor(Date.now() / 3600000) * 3600 - 23 * 3600

  const buckets: CacheHitBucket[] = []
  for (let i = 0; i < 24; i++) {
    buckets.push({ hour_ts: startTs + i * 3600, hit_rate: null, cached_tokens: 0, input_tokens: 0, calls: 0 })
  }

  const lookup = new Map<number, CacheHitHourlyPoint>()
  for (const d of hourly) {
    lookup.set(d.hour_ts, d)
  }
  for (const b of buckets) {
    const d = lookup.get(b.hour_ts)
    if (d) {
      b.hit_rate = d.hit_rate
      b.cached_tokens = d.cached_tokens
      b.input_tokens = d.input_tokens
      b.calls = d.calls
    }
  }
  return buckets
}

/** One series per model so a session model override or a failover model does
 *  not blend its cache rate with the default model's. */
const cacheHitSeries = computed<CacheHitSeries[]>(() => {
  const raw = overview.value?.cache_hit_hourly ?? []
  const windowStartTs = overview.value?.cache_hit_since_ts ?? 0
  const byModel = new Map<string, CacheHitHourlyPoint[]>()
  for (const point of raw) {
    const model = point.model || ''
    const list = byModel.get(model)
    if (list) list.push(point)
    else byModel.set(model, [point])
  }

  const series: CacheHitSeries[] = []
  for (const [model, points] of byModel) {
    let cachedTokens = 0
    let inputTokens = 0
    let calls = 0
    for (const point of points) {
      cachedTokens += point.cached_tokens
      inputTokens += point.input_tokens
      calls += point.calls
    }
    series.push({
      model,
      label: model.trim() ? model : '—',
      points: fillCacheHitHours(points, windowStartTs),
      avg: inputTokens > 0 ? Math.round(cachedTokens / inputTokens * 1000) / 10 : null,
      calls,
    })
  }
  // Most active model first; legend colors stay stable while call counts change.
  return series.sort((a, b) => b.calls - a.calls || a.model.localeCompare(b.model))
})

/** Render the chart only when at least one model has a visible bucket;
 *  a sparse payload whose rows fall outside the 24h window must not yield a
 *  blank plot. */
const hasCacheHitData = computed(() =>
  cacheHitSeries.value.some(series => series.points.some(point => point.hit_rate !== null)),
)

function formatHourLabel(hourTs: number): string {
  const d = new Date(hourTs * 1000)
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  return `${hh}:${mm}`
}

const platformColorMap: Record<string, string> = {
  qq: '#e74c3c',
  'qq official': '#1ebafc',
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

/** Generate a distinct colour per model so the bar chart looks organised. */
const modelColors = ['#3b82f6', '#8b5cf6', '#f59e0b', '#10b981', '#ef4444', '#ec4899', '#14b8a6', '#f97316']

function buildModelOption(models: LLMModelStat[], dark: boolean) {
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
        const m = models[p.dataIndex]
        const rate = m.calls > 0 ? (m.success / m.calls * 100).toFixed(1) : '-'
        return `<strong>${m.model}</strong><br/>${t('overview.pie_tooltip_count')}: ${m.calls}<br/>${t('overview.llm_success_rate')}: ${rate}%<br/>${t('overview.llm_avg_response')}: ${m.avg_response_ms}${t('overview.llm_ms')}`
      },
    },
    grid: { left: 30, right: 30, top: 10, bottom: 20 },
    xAxis: {
      type: 'category',
      data: models.map(m => {
        const parts = m.model.split('/')
        return parts[parts.length - 1]  // short name after the last /
      }),
      axisLabel: { color: tok.axisLabel, fontSize: 10, rotate: models.length > 4 ? 25 : 0 },
      axisLine: { lineStyle: { color: tok.axisLine } },
      axisTick: { alignWithLabel: true },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      axisLabel: { color: tok.axisLabel, fontSize: 10 },
      splitLine: { lineStyle: { color: tok.splitLine } },
    },
    series: [
      {
        type: 'bar',
        data: models.map((m, i) => ({
          value: m.calls,
          itemStyle: { color: modelColors[i % modelColors.length] },
        })),
        barMaxWidth: 48,
      },
    ],
  }
}

function buildTokenOption(models: LLMModelStat[], dark: boolean) {
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
        const m = models[p.dataIndex]
        return `<strong>${m.model}</strong><br/>${t('overview.llm_tokens')}: ${(m.input_tokens + m.output_tokens).toLocaleString()}<br/>${t('overview.llm_tooltip_input')}: ${m.input_tokens.toLocaleString()}<br/>${t('overview.llm_tooltip_output')}: ${m.output_tokens.toLocaleString()}<br/>${t('overview.llm_tooltip_cached')}: ${m.cached_tokens.toLocaleString()}`
      },
    },
    grid: { left: 30, right: 30, top: 10, bottom: 20 },
    xAxis: {
      type: 'category',
      data: models.map(m => {
        const parts = m.model.split('/')
        return parts[parts.length - 1]
      }),
      axisLabel: { color: tok.axisLabel, fontSize: 10, rotate: models.length > 4 ? 25 : 0 },
      axisLine: { lineStyle: { color: tok.axisLine } },
      axisTick: { alignWithLabel: true },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      axisLabel: { color: tok.axisLabel, fontSize: 10, formatter: (v: number) => v >= 1000 ? (v / 1000).toFixed(0) + 'K' : String(v) },
      splitLine: { lineStyle: { color: tok.splitLine } },
    },
    series: [
      {
        type: 'bar',
        data: models.map((m) => ({
          value: m.input_tokens + m.output_tokens,
          itemStyle: { color: '#10b981' },
        })),
        barMaxWidth: 48,
      },
    ],
  }
}

const cacheSeriesColors = [
  '#10b981', '#3b82f6', '#f59e0b', '#ef4444', '#8b5cf6',
  '#06b6d4', '#ec4899', '#84cc16', '#f97316', '#14b8a6',
]

// Keep a model's color for the lifetime of the page: a model entering or
// leaving the 24-hour window must not repaint the remaining series.
const cacheSeriesColorByModel = new Map<string, string>()

function assignCacheSeriesColors(series: CacheHitSeries[]): Map<string, string> {
  const used = new Set(cacheSeriesColorByModel.values())
  for (const model of [...series].map(s => s.model).sort()) {
    if (cacheSeriesColorByModel.has(model)) continue
    const color = cacheSeriesColors.find(c => !used.has(c))
      ?? cacheSeriesColors[cacheSeriesColorByModel.size % cacheSeriesColors.length]
    cacheSeriesColorByModel.set(model, color)
    used.add(color)
  }
  const colors = new Map<string, string>()
  for (const s of series) {
    colors.set(s.model, cacheSeriesColorByModel.get(s.model) ?? cacheSeriesColors[0])
  }
  return colors
}

function buildCacheHitOption(series: CacheHitSeries[], dark: boolean) {
  const tok = themeTokens(dark)
  const points = series[0]?.points ?? []
  const multi = series.length > 1

  const colorByModel = assignCacheSeriesColors(series)
  const byLabel = new Map(series.map(s => [s.label, s]))

  const legend = multi
    ? {
        type: 'scroll',
        top: 0,
        left: 'center',
        textStyle: { color: tok.legendText, fontSize: 11 },
        formatter: (name: string) => {
          const s = byLabel.get(name)
          return s?.avg !== null && s?.avg !== undefined ? `${name} ${s.avg.toFixed(1)}%` : name
        },
      }
    : undefined

  const tooltipFormatter = (params: any) => {
    const list = Array.isArray(params) ? params : [params]
    const first = list[0]
    if (!first) return ''
    const point = points[first.dataIndex]
    const raw = new Date((point?.hour_ts || 0) * 1000)
    const dateStr = `${raw.getMonth() + 1}/${raw.getDate()} ${formatHourLabel(point?.hour_ts || 0)}`
    const rows = list
      .map((p: any) => {
        const s = byLabel.get(p.seriesName)
        const bucket = s?.points[p.dataIndex]
        if (!bucket || bucket.hit_rate === null) return ''
        return `${p.marker}${p.seriesName}: ${bucket.hit_rate.toFixed(1)}%<br/>`
          + `&nbsp;&nbsp;${t('overview.cache_hit_tooltip_cached')}: ${bucket.cached_tokens.toLocaleString()}`
          + ` · ${t('overview.cache_hit_tooltip_input')}: ${bucket.input_tokens.toLocaleString()}`
          + ` · ${t('overview.cache_hit_tooltip_calls')}: ${bucket.calls}`
      })
      .filter(Boolean)
    if (!rows.length) {
      return `<strong>${dateStr}</strong><br/>${t('overview.cache_hit_no_data')}`
    }
    return `<strong>${dateStr}</strong><br/>${rows.join('<br/>')}`
  }

  const chartSeries = series.map((s) => {
    const color = colorByModel.get(s.model) || cacheSeriesColors[0]
    const single = series.length === 1
    const markLine = single && s.avg !== null
      ? {
          silent: true,
          symbol: 'none',
          label: {
            formatter: `${t('overview.cache_hit_avg')} ${s.avg.toFixed(1)}%`,
            color: tok.legendText,
            fontSize: 11,
            position: 'insideEndTop',
          },
          lineStyle: { color, type: 'dashed', width: 1, opacity: 0.8 },
          data: [{ yAxis: s.avg }],
        }
      : undefined
    return {
      name: s.label,
      type: 'line',
      data: s.points.map(p => p.hit_rate),
      smooth: true,
      connectNulls: true,
      lineStyle: { color, width: 2 },
      itemStyle: { color },
      symbol: 'circle',
      symbolSize: 5,
      emphasis: { focus: 'series' },
      ...(single
        ? {
            areaStyle: {
              color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: dark ? 'rgba(16,185,129,0.25)' : 'rgba(16,185,129,0.3)' },
                { offset: 1, color: 'rgba(16,185,129,0.02)' },
              ]),
            },
          }
        : {}),
      markLine,
    }
  })

  return {
    backgroundColor: 'transparent',
    legend,
    tooltip: {
      trigger: 'axis',
      backgroundColor: tok.tooltipBg,
      borderColor: tok.tooltipBorder,
      borderWidth: 1,
      textStyle: { color: tok.tooltipText, fontSize: 13 },
      formatter: tooltipFormatter,
    },
    grid: { left: 55, right: 30, top: multi ? 40 : 20, bottom: 30 },
    xAxis: {
      type: 'category',
      data: points.map(d => formatHourLabel(d.hour_ts)),
      axisLabel: { color: tok.axisLabel, fontSize: 11 },
      axisLine: { lineStyle: { color: tok.axisLine } },
      axisTick: { alignWithLabel: true },
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 100,
      axisLabel: { color: tok.axisLabel, fontSize: 11, formatter: '{value}%' },
      splitLine: { lineStyle: { color: tok.splitLine } },
    },
    series: chartSeries,
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

  const models = llmSummary.value?.by_model
  if (models && models.length > 0 && modelChartRef.value) {
    if (!modelChart) {
      modelChart = echarts.init(modelChartRef.value)
    }
    modelChart.setOption(buildModelOption(models, isDark.value), true)
  }

  if (models && models.length > 0 && tokenChartRef.value) {
    if (!tokenChart) {
      tokenChart = echarts.init(tokenChartRef.value)
    }
    tokenChart.setOption(buildTokenOption(models, isDark.value), true)
  }

  if (hasCacheHitData.value && cacheChartRef.value) {
    if (!cacheChart) {
      cacheChart = echarts.init(cacheChartRef.value)
    }
    cacheChart.setOption(
      buildCacheHitOption(cacheHitSeries.value, isDark.value),
      true,
    )
  }

  // Start observing after charts are initialised so resize() fires
  // on a live instance.
  nextTick(observeResize)
}

// Re-render charts when dark mode or locale changes
watch([isDark, locale], () => { nextTick(renderCharts) })

/* ---- Chart resize handling ---- */

function observeResize() {
  if (resizeObserver) resizeObserver.disconnect()
  resizeObserver = new ResizeObserver(() => {
    if (lineChart) lineChart.resize()
    if (pieChart) pieChart.resize()
    if (modelChart) modelChart.resize()
    if (tokenChart) tokenChart.resize()
    if (cacheChart) cacheChart.resize()
  })
  if (lineChartRef.value) resizeObserver.observe(lineChartRef.value)
  if (pieChartRef.value) resizeObserver.observe(pieChartRef.value)
  if (modelChartRef.value) resizeObserver.observe(modelChartRef.value)
  if (tokenChartRef.value) resizeObserver.observe(tokenChartRef.value)
  if (cacheChartRef.value) resizeObserver.observe(cacheChartRef.value)
}

watch(
  [lineChartRef, pieChartRef, modelChartRef, tokenChartRef, cacheChartRef],
  () => {
    if (!modelChartRef.value && modelChart) { modelChart.dispose(); modelChart = null }
    if (!tokenChartRef.value && tokenChart) { tokenChart.dispose(); tokenChart = null }
    if (!cacheChartRef.value && cacheChart) { cacheChart.dispose(); cacheChart = null }
    if (lineChartRef.value || pieChartRef.value || modelChartRef.value || tokenChartRef.value || cacheChartRef.value) {
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
  if (resizeObserver) { resizeObserver.disconnect(); resizeObserver = null }
  if (lineChart) { lineChart.dispose(); lineChart = null }
  if (pieChart) { pieChart.dispose(); pieChart = null }
  if (modelChart) { modelChart.dispose(); modelChart = null }
  if (tokenChart) { tokenChart.dispose(); tokenChart = null }
  if (cacheChart) { cacheChart.dispose(); cacheChart = null }
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
