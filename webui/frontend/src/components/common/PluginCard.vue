<template>
  <div
    class="bg-white dark:bg-gray-900 rounded-lg shadow p-4 flex flex-col"
    :class="error ? 'ring-1 ring-red-300 dark:ring-red-700' : ''"
  >
    <div class="flex items-start justify-between mb-3">
      <div>
        <div class="text-base font-semibold text-gray-900 dark:text-gray-100">{{ name || id }}</div>
        <div v-if="version || author" class="mt-1 text-xs text-gray-500 dark:text-gray-400">
          {{ version ? `v${version}` : '' }}{{ version && author ? ' · ' : '' }}{{ author || '' }}
          <span v-if="hasUpdate" class="ml-2 inline-flex items-center px-1.5 py-0.5 text-[10px] font-medium rounded-full bg-green-50 text-green-600 dark:bg-green-900/30 dark:text-green-400">
            {{ $t('plugin.update_available') }}
          </span>
        </div>
        <div v-if="coreVersion" class="mt-1 text-xs text-gray-400 dark:text-gray-500">
          {{ $t('plugin.core_version') }}: {{ coreVersion }}
        </div>
        <div v-if="status === 'installing'" class="mt-2 flex items-center gap-1.5 text-xs">
          <IconSpinner class="animate-spin h-3.5 w-3.5 text-yellow-500" />
          <span class="text-yellow-600 dark:text-yellow-400">{{ $t('plugin.status_installing') }}</span>
        </div>
        <div v-else-if="status === 'loading'" class="mt-2 flex items-center gap-1.5 text-xs">
          <IconSpinner class="animate-spin h-3.5 w-3.5 text-blue-500" />
          <span class="text-blue-600 dark:text-blue-400">{{ $t('plugin.status_loading') }}</span>
        </div>
        <div v-else-if="status === 'pending'" class="mt-2 flex items-center gap-1.5 text-xs">
          <span class="inline-block h-2 w-2 rounded-full bg-gray-400"></span>
          <span class="text-gray-500 dark:text-gray-400">{{ $t('plugin.status_pending') }}</span>
        </div>
        <div v-if="error" class="mt-2 min-w-0 flex items-start gap-1.5 rounded-md bg-red-50 dark:bg-red-900/20 px-2 py-1.5 text-xs text-red-600 dark:text-red-400 overflow-hidden">
          <IconInfo class="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
          <span class="min-w-0 break-all line-clamp-6">{{ error }}</span>
        </div>
      </div>
      <div class="flex items-start space-x-2">
        <!-- Repo link -->
        <a
          v-if="safeRepo"
          :href="safeRepo"
          target="_blank"
          rel="noopener noreferrer"
          class="inline-flex items-center text-gray-500 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-100 transition-colors mt-1"
          :title="$t('plugin.repo_link')"
        >
          <IconGithub class="w-4 h-4" />
        </a>
        <!-- Enable/disable toggle (installed mode) -->
        <button
          v-if="mode === 'installed' && !error"
          type="button"
          class="ml-2 relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer items-center rounded-full border transition-colors duration-200 ease-in-out focus:outline-none"
          :class="enabled ? 'bg-blue-600 border-blue-600 dark:bg-blue-500 dark:border-blue-500' : 'bg-gray-200 border-gray-300 dark:bg-gray-700 dark:border-gray-600'"
          :aria-pressed="enabled ? 'true' : 'false'"
          @click="emit('toggle')"
        >
          <span
            class="pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out"
            :class="enabled ? 'translate-x-4' : 'translate-x-0'"
          />
        </button>
      </div>
    </div>
    <p v-if="description" class="text-sm text-gray-600 dark:text-gray-300 line-clamp-3 mb-3">
      {{ description }}
    </p>
    <div v-if="tags && tags.length" class="flex flex-wrap gap-1.5 mb-3">
      <span
        v-for="tag in tags"
        :key="tag"
        class="inline-block text-[10px] font-medium px-2 py-0.5 rounded-full bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400"
      >
        {{ tag }}
      </span>
    </div>
    <div class="mt-auto">
      <div v-if="mode === 'installed'" class="text-xs font-mono text-gray-400 dark:text-gray-500 break-all mb-3">{{ id }}</div>
      <!-- Installed mode: Configure / Reload / Uninstall buttons -->
      <div v-if="mode === 'installed'" class="flex items-center justify-end space-x-3">
        <button
          v-if="hasUpdate && !builtin"
          type="button"
          class="px-3 py-1.5 text-xs font-medium rounded-md border transition-colors"
          :class="updating
            ? 'border-gray-200 text-gray-400 cursor-wait dark:border-gray-700 dark:text-gray-500'
            : 'border-green-300 text-green-600 hover:bg-green-50 dark:border-green-600 dark:text-green-400 dark:hover:bg-green-900/30'"
          :disabled="updating"
          @click="!updating && emit('update')"
        >
          <span v-if="updating" class="flex items-center">
            <IconSpinner class="animate-spin h-3 w-3 mr-1" />
            {{ $t('plugin.updating') }}
          </span>
          <span v-else>{{ $t('plugin.update') }}</span>
        </button>
        <button
          v-if="!error"
          type="button"
          class="px-3 py-1.5 text-xs font-medium rounded-md border border-gray-300 text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-800 transition-colors"
          @click="emit('configure')"
        >
          {{ $t('plugin.configure') }}
        </button>
        <button
          v-if="!builtin"
          type="button"
          class="px-3 py-1.5 text-xs font-medium rounded-md border transition-colors"
          :class="reloading
            ? 'border-gray-200 text-gray-400 cursor-wait dark:border-gray-700 dark:text-gray-500'
            : 'border-gray-300 text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-800'"
          :disabled="reloading"
          @click="!reloading && emit('reload')"
        >
          <span v-if="reloading" class="flex items-center">
            <IconSpinner class="animate-spin h-3 w-3 mr-1" />
            {{ $t('plugin.reloading') }}
          </span>
          <span v-else>{{ $t('plugin.reload') }}</span>
        </button>
        <button
          type="button"
          class="px-3 py-1.5 text-xs font-medium rounded-md border transition-colors"
          :class="uninstallable
            ? 'border-red-300 text-red-600 hover:bg-red-50 dark:border-red-600 dark:text-red-400 dark:hover:bg-red-900/30'
            : 'border-gray-200 text-gray-300 cursor-not-allowed dark:border-gray-700 dark:text-gray-600'"
          :disabled="!uninstallable"
          @click="uninstallable && emit('uninstall')"
        >
          {{ $t('plugin.uninstall') }}
        </button>
      </div>
      <!-- Store mode: Install button -->
      <div v-if="mode === 'store'" class="flex items-center justify-end">
        <button
          type="button"
          class="px-3 py-1.5 text-xs font-medium rounded-md border transition-colors"
          :class="installed
            ? 'border-gray-200 text-gray-400 cursor-default dark:border-gray-700 dark:text-gray-500'
            : 'border-blue-300 text-blue-600 hover:bg-blue-50 dark:border-blue-600 dark:text-blue-400 dark:hover:bg-blue-900/30'"
          :disabled="installed || installing"
          @click="!installed && !installing && emit('install')"
        >
          <span v-if="installing" class="flex items-center">
            <IconSpinner class="animate-spin h-3 w-3 mr-1" />
            {{ $t('pluginStore.installing') }}
          </span>
          <span v-else>{{ installed ? $t('pluginStore.installed') : $t('pluginStore.install') }}</span>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { IconInfo, IconGithub, IconSpinner } from '@/components/icons'

const props = withDefaults(defineProps<{
  id: string
  name: string
  version?: string
  author?: string
  description?: string
  repo?: string | null
  mode: 'installed' | 'store'
  // installed mode
  enabled?: boolean
  builtin?: boolean
  uninstallable?: boolean
  tags?: string[]
  coreVersion?: string | null
  error?: string | null
  status?: string
  reloading?: boolean
  // update
  hasUpdate?: boolean
  latestVersion?: string | null
  updating?: boolean
  // store mode
  installed?: boolean
  installing?: boolean
}>(), {
  version: '',
  author: '',
  description: '',
  repo: null,
  enabled: true,
  builtin: false,
  uninstallable: false,
  tags: () => [],
  coreVersion: null,
  error: null,
  status: 'ready',
  reloading: false,
  hasUpdate: false,
  latestVersion: null,
  updating: false,
  installed: false,
  installing: false,
})

const emit = defineEmits<{
  toggle: []
  configure: []
  uninstall: []
  install: []
  reload: []
  update: []
}>()

const safeRepo = computed(() => {
  if (typeof props.repo !== 'string' || !props.repo) return null
  try {
    const parsed = new URL(props.repo)
    if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
      return parsed.toString()
    }
  } catch { /* invalid URL */ }
  return null
})
</script>
