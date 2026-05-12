<template>
  <Modal v-model="show" content-class="max-w-2xl">
    <div class="bg-white dark:bg-[#1a1a1e] rounded-xl shadow-xl overflow-hidden">
      <!-- Header -->
      <div class="px-6 py-4 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between">
        <div class="flex items-center gap-3">
          <h3 class="text-lg font-semibold text-gray-800 dark:text-white">
            {{ t('header.releases_title') }}
          </h3>
          <span class="px-2 py-0.5 text-xs font-medium rounded-full bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300">
            {{ t('header.current_version') }}: {{ currentVersion }}
          </span>
        </div>
        <button
          class="p-1 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-400 transition-colors"
          @click="show = false"
        >
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <!-- Content -->
      <div class="max-h-[70vh] overflow-y-auto">
        <!-- Loading -->
        <div v-if="loading" class="p-6 space-y-4">
          <div v-for="i in 3" :key="i" class="animate-pulse">
            <div class="h-5 bg-gray-200 dark:bg-gray-700 rounded w-1/3 mb-2" />
            <div class="h-4 bg-gray-200 dark:bg-gray-700 rounded w-full mb-1" />
            <div class="h-4 bg-gray-200 dark:bg-gray-700 rounded w-2/3" />
          </div>
        </div>

        <!-- Empty -->
        <div v-else-if="releases.length === 0" class="p-6 text-center text-gray-500 dark:text-gray-400">
          {{ t('header.no_releases') }}
        </div>

        <!-- Release list -->
        <div v-else class="divide-y divide-gray-100 dark:divide-gray-800">
          <div
            v-for="(release, index) in releases"
            :key="release.tag_name"
            class="px-6 py-4 hover:bg-gray-50 dark:hover:bg-[#202024] transition-colors"
          >
            <!-- Release header -->
            <div class="flex items-center justify-between mb-2">
              <div class="flex items-center gap-2 flex-wrap">
                <span class="font-semibold text-gray-800 dark:text-white">
                  {{ release.name || release.tag_name }}
                </span>
                <span
                  v-if="index === 0"
                  class="px-1.5 py-0.5 text-xs font-medium rounded bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300"
                >
                  {{ t('header.latest') }}
                </span>
                <span
                  v-if="isNewer(release.tag_name)"
                  class="px-1.5 py-0.5 text-xs font-medium rounded bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300"
                >
                  {{ t('header.new_version_available') }}
                </span>
                <span
                  v-if="release.prerelease"
                  class="px-1.5 py-0.5 text-xs font-medium rounded bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300"
                >
                  {{ t('header.prerelease') }}
                </span>
              </div>
              <span class="text-xs text-gray-400 dark:text-gray-500 shrink-0 ml-2">
                {{ formatDate(release.published_at) }}
              </span>
            </div>

            <!-- Release body -->
            <p
              v-if="release.body"
              class="text-sm text-gray-600 dark:text-gray-400 whitespace-pre-line line-clamp-4 mb-2"
            >
              {{ release.body }}
            </p>

            <!-- Link -->
            <a
              v-if="release.html_url"
              :href="release.html_url"
              target="_blank"
              rel="noopener noreferrer"
              class="inline-flex items-center gap-1 text-xs text-blue-500 hover:text-blue-600 dark:text-blue-400 dark:hover:text-blue-300"
            >
              {{ t('header.view_on_github') }}
              <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
              </svg>
            </a>
          </div>
        </div>
      </div>
    </div>
  </Modal>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import Modal from '@/components/common/Modal.vue'
import type { ReleaseItem } from '@/types'

const props = defineProps<{
  modelValue: boolean
  currentVersion: string
  releases: ReleaseItem[]
  loading: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const { t } = useI18n()

const show = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val),
})

function normalizeVersion(v: string): string {
  return v.replace(/^v/i, '')
}

function isNewer(tag: string): boolean {
  const current = normalizeVersion(props.currentVersion)
  const target = normalizeVersion(tag)
  return target !== current && target > current
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return ''
  try {
    return new Date(dateStr).toLocaleDateString()
  } catch {
    return dateStr
  }
}
</script>
