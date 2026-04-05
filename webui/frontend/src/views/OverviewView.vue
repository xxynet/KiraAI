<template>
  <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
    <!-- Uptime -->
    <div class="glass-card rounded-lg p-6">
      <div class="flex items-center gap-4">
        <div class="bg-blue-100 p-3 rounded-lg">
          <el-icon :size="24" class="text-blue-600"><Timer /></el-icon>
        </div>
        <div>
          <p class="text-sm text-gray-500">{{ $t('overview.runtime_duration') }}</p>
          <p class="text-2xl font-bold text-gray-900 dark:text-white">{{ formattedUptime }}</p>
        </div>
      </div>
    </div>

    <!-- Total Messages -->
    <div class="glass-card rounded-lg p-6">
      <div class="flex items-center gap-4">
        <div class="bg-green-100 p-3 rounded-lg">
          <el-icon :size="24" class="text-green-600"><ChatDotRound /></el-icon>
        </div>
        <div>
          <p class="text-sm text-gray-500">{{ $t('overview.total_messages') }}</p>
          <p class="text-2xl font-bold text-gray-900 dark:text-white">{{ overview?.total_messages ?? 0 }}</p>
        </div>
      </div>
    </div>

    <!-- Adapter Count -->
    <div class="glass-card rounded-lg p-6">
      <div class="flex items-center gap-4">
        <div class="bg-purple-100 p-3 rounded-lg">
          <el-icon :size="24" class="text-purple-600"><Link /></el-icon>
        </div>
        <div>
          <p class="text-sm text-gray-500">{{ $t('overview.adapter_count') }}</p>
          <p class="text-2xl font-bold text-gray-900 dark:text-white">
            {{ overview?.active_adapters ?? 0 }} / {{ overview?.total_adapters ?? 0 }}
          </p>
        </div>
      </div>
    </div>

    <!-- Memory Usage -->
    <div class="glass-card rounded-lg p-6">
      <div class="flex items-center gap-4">
        <div class="bg-yellow-100 p-3 rounded-lg">
          <el-icon :size="24" class="text-yellow-600"><Cpu /></el-icon>
        </div>
        <div>
          <p class="text-sm text-gray-500">{{ $t('overview.memory_usage') }}</p>
          <p class="text-2xl font-bold text-gray-900 dark:text-white">
            {{ overview?.memory_usage ?? 0 }} MB
          </p>
        </div>
      </div>
    </div>
  </div>

  <!-- System Status -->
  <div class="glass-card rounded-lg p-6">
    <h3 class="text-lg font-semibold text-gray-900 dark:text-white mb-2">{{ $t('overview.system_status') }}</h3>
    <el-tag :type="statusType" size="large">
      {{ statusText }}
    </el-tag>
    <p class="text-sm text-gray-500 mt-2">
      {{ $t('overview.adapter_count') }}: {{ overview?.active_adapters ?? 0 }} / {{ overview?.total_adapters ?? 0 }}
      &nbsp;|&nbsp;
      {{ $t('overview.provider_stats') }} {{ overview?.active_providers ?? 0 }} / {{ overview?.total_providers ?? 0 }}
    </p>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { Timer, ChatDotRound, Link, Cpu } from '@element-plus/icons-vue'
import { getOverview } from '@/api/overview'
import type { OverviewResponse } from '@/types'

const { t } = useI18n()
const overview = ref<OverviewResponse | null>(null)
const runtimeSeconds = ref(0)
let refreshTimer: ReturnType<typeof setInterval> | null = null
let runtimeTimer: ReturnType<typeof setInterval> | null = null
let inFlight = false

const formattedUptime = computed(() => {
  const s = runtimeSeconds.value
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
})

const statusType = computed(() => {
  if (!overview.value) return 'info'
  const s = overview.value.system_status
  if (s === 'running') return 'success'
  if (s === 'starting' || s === 'degraded') return 'warning'
  if (s === 'error' || s === 'failed') return 'danger'
  return 'info'
})

const statusText = computed(() => {
  if (!overview.value) return t('overview.status_unknown')
  const validStatuses = ['running', 'stopped', 'degraded', 'starting', 'error', 'failed']
  const status = overview.value.system_status
  if (!status || !validStatuses.includes(status)) return t('overview.status_unknown')
  return t(`overview.status_${status}`)
})

async function fetchOverview() {
  if (inFlight) return
  inFlight = true
  try {
    const res = await getOverview()
    overview.value = res.data
    runtimeSeconds.value = res.data.runtime_duration
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
  if (refreshTimer) clearInterval(refreshTimer)
  if (runtimeTimer) clearInterval(runtimeTimer)
})
</script>
