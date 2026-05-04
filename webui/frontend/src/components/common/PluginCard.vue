<template>
  <div
    class="bg-white dark:bg-gray-900 rounded-lg shadow p-4 flex flex-col"
  >
    <div class="flex items-start justify-between mb-3">
      <div>
        <div class="text-base font-semibold text-gray-900 dark:text-gray-100">{{ name || id }}</div>
        <div v-if="version || author" class="mt-1 text-xs text-gray-500 dark:text-gray-400">
          {{ version ? `v${version}` : '' }}{{ version && author ? ' · ' : '' }}{{ author || '' }}
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
          <svg class="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 0C5.37 0 0 5.37 0 12c0 5.3 3.438 9.8 8.205 11.387.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.726-4.042-1.61-4.042-1.61-.546-1.387-1.333-1.756-1.333-1.756-1.09-.745.083-.73.083-.73 1.205.085 1.84 1.237 1.84 1.237 1.07 1.835 2.807 1.305 3.492.998.108-.776.42-1.305.762-1.605-2.665-.305-5.467-1.334-5.467-5.93 0-1.31.468-2.382 1.235-3.22-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.3 1.23A11.51 11.51 0 0112 5.803c1.02.005 2.047.138 3.006.404 2.29-1.552 3.297-1.23 3.297-1.23.653 1.652.242 2.873.118 3.176.77.838 1.233 1.91 1.233 3.22 0 4.61-2.807 5.624-5.479 5.92.43.372.823 1.102.823 2.222 0 1.606-.014 2.898-.014 3.293 0 .322.216.694.825.576C20.565 21.795 24 17.298 24 12c0-6.63-5.37-12-12-12z" />
          </svg>
        </a>
        <!-- Enable/disable toggle (installed mode) -->
        <button
          v-if="mode === 'installed'"
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
    <div class="mt-auto">
      <div v-if="mode === 'installed'" class="text-xs font-mono text-gray-400 dark:text-gray-500 break-all mb-3">{{ id }}</div>
      <!-- Installed mode: Configure / Uninstall buttons -->
      <div v-if="mode === 'installed'" class="flex items-center justify-end space-x-3">
        <button
          type="button"
          class="px-3 py-1.5 text-xs font-medium rounded-md border border-gray-300 text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-800 transition-colors"
          @click="emit('configure')"
        >
          {{ $t('plugin.configure') }}
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
            <svg class="animate-spin h-3 w-3 mr-1" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
            </svg>
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
  uninstallable?: boolean
  // store mode
  installed?: boolean
  installing?: boolean
}>(), {
  version: '',
  author: '',
  description: '',
  repo: null,
  enabled: true,
  uninstallable: false,
  installed: false,
  installing: false,
})

const emit = defineEmits<{
  toggle: []
  configure: []
  uninstall: []
  install: []
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
