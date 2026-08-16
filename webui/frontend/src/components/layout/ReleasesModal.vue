<template>
  <Modal v-model="show" content-class="max-w-2xl" :persistent="isUpdating">
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
          <IconClose class="w-5 h-5" />
        </button>
      </div>

      <!-- Content -->
      <div class="max-h-[70vh] overflow-y-auto">
        <!-- In-place update progress -->
        <div v-if="updateProgress" class="mx-6 mt-5 rounded-xl border border-blue-200 bg-blue-50/60 p-4 dark:border-blue-900/60 dark:bg-blue-950/20">
          <div class="flex items-start justify-between gap-4">
            <div>
              <p class="font-medium text-gray-800 dark:text-gray-100">{{ t('header.update_progress_title') }}</p>
              <p class="mt-1 text-sm text-gray-600 dark:text-gray-300">{{ updateProgress.message }}</p>
            </div>
            <span class="shrink-0 text-sm font-semibold text-blue-600 dark:text-blue-300">{{ updateProgress.overall_percent }}%</span>
          </div>
          <div class="mt-3 h-2 overflow-hidden rounded-full bg-blue-100 dark:bg-blue-950">
            <div class="h-full rounded-full bg-blue-500 transition-all duration-300" :style="{ width: `${updateProgress.overall_percent}%` }" />
          </div>
          <div class="mt-4 space-y-2">
            <div v-for="stage in updateStages" :key="stage.name" class="flex items-center justify-between text-sm">
              <span :class="stageClass(stage.status)">{{ stageLabel(stage.name) }}</span>
              <span :class="stageClass(stage.status)">{{ stageText(stage.status) }}</span>
            </div>
          </div>
          <p v-if="updateProgress.status === 'failed'" class="mt-4 text-sm text-red-600 dark:text-red-400">
            {{ t('header.update_rollback_notice') }}
          </p>
        </div>

        <!-- Loading -->
        <div v-if="loading" class="p-6 space-y-4">
          <div v-for="i in 3" :key="i" class="animate-pulse">
            <div class="h-5 bg-gray-200 dark:bg-gray-700 rounded w-1/3 mb-2" />
            <div class="h-4 bg-gray-200 dark:bg-gray-700 rounded w-full mb-1" />
            <div class="h-4 bg-gray-200 dark:bg-gray-700 rounded w-2/3" />
          </div>
        </div>

        <!-- Error -->
        <div v-else-if="error" class="p-6 text-center">
          <p class="text-gray-500 dark:text-gray-400 mb-3">{{ t('header.fetch_error') }}</p>
          <button
            class="px-4 py-1.5 text-sm rounded-lg bg-blue-500 hover:bg-blue-600 text-white transition-colors"
            @click="emit('retry')"
          >
            {{ t('header.retry') }}
          </button>
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
            <div class="flex items-start justify-between mb-2">
              <div>
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
                <span class="text-xs text-gray-400 dark:text-gray-500 mt-0.5 block">
                  {{ formatDate(release.published_at) }}
                </span>
              </div>
              <button
                v-if="release.tag_name !== currentVersion"
                :class="actionButtonClass(release)"
                :disabled="isUpdating"
                class="shrink-0 ml-3 px-3 py-1 text-xs font-medium rounded-lg transition-colors"
                @click="onActionClick(release)"
              >
                {{ actionButtonText(release) }}
              </button>
            </div>

            <!-- Release body -->
            <div
              v-if="release.body"
              class="release-body text-sm text-gray-600 dark:text-gray-400 line-clamp-4 mb-2"
              v-html="renderMarkdown(release.body)"
            />

            <!-- Link -->
            <a
              v-if="release.html_url"
              :href="release.html_url"
              target="_blank"
              rel="noopener noreferrer"
              class="inline-flex items-center gap-1 text-xs text-blue-500 hover:text-blue-600 dark:text-blue-400 dark:hover:text-blue-300"
            >
              {{ t('header.view_on_github') }}
              <IconExternalLink class="w-3 h-3" />
            </a>
          </div>
        </div>
      </div>
    </div>

    <!-- Confirm Modal -->
    <ConfirmModal
      ref="confirmRef"
      :title="confirmTitle"
      :message="confirmMessage"
      :cancel-text="t('provider.modal_cancel')"
      :confirm-text="confirmButton"
      variant="info"
      @confirm="handleConfirm"
    />
  </Modal>
</template>

<script setup lang="ts">
import { ref, computed, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import Modal from '@/components/common/Modal.vue'
import ConfirmModal from '@/components/common/ConfirmModal.vue'
import { notify } from '@/composables/useNotification'
import { IconClose, IconExternalLink } from '@/components/icons'
import { downloadRelease, getReleaseUpdateProgress } from '@/api/auth'
import { waitUntilReady } from '@/composables/useRestart'
import type { ReleaseItem, ReleaseUpdateProgress } from '@/types'

const props = defineProps<{
  modelValue: boolean
  currentVersion: string
  releases: ReleaseItem[]
  loading: boolean
  error: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  retry: []
}>()

const { t } = useI18n()

const show = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val),
})

const downloadingTag = ref<string | null>(null)
const updateProgress = ref<ReleaseUpdateProgress | null>(null)
const confirmRef = ref<InstanceType<typeof ConfirmModal>>()
const pendingRelease = ref<ReleaseItem | null>(null)

const confirmTitle = ref('')
const confirmMessage = ref('')
const confirmButton = ref('')
let progressTimer: ReturnType<typeof setTimeout> | null = null

const isUpdating = computed(() => updateProgress.value?.status === 'running' || updateProgress.value?.status === 'restarting')
const updateStages = computed(() => {
  const stages = updateProgress.value?.stages || {}
  return ['download', 'verify', 'apply', 'dependencies', 'restart']
    .map(name => ({ name, status: stages[name]?.status ?? 'pending', percent: stages[name]?.percent ?? 0 }))
})

function isNewer(tag: string): boolean {
  const currentRelease = props.releases.find(r => r.tag_name === props.currentVersion)
  if (!currentRelease?.published_at) return false
  const targetRelease = props.releases.find(r => r.tag_name === tag)
  if (!targetRelease?.published_at) return false
  return new Date(targetRelease.published_at).getTime() > new Date(currentRelease.published_at).getTime()
}

function isCurrentVersion(tag: string): boolean {
  return tag === props.currentVersion
}

function actionButtonClass(release: ReleaseItem): string {
  const isDownloading = downloadingTag.value !== null
  if (isNewer(release.tag_name)) {
    return isDownloading
      ? 'bg-blue-300 dark:bg-blue-800 text-white/70 cursor-not-allowed'
      : 'bg-blue-500 hover:bg-blue-600 text-white'
  }
  return isDownloading
    ? 'bg-gray-200 dark:bg-gray-700 text-gray-400 dark:text-gray-500 cursor-not-allowed'
    : 'bg-gray-200 dark:bg-gray-700 hover:bg-gray-300 dark:hover:bg-gray-600 text-gray-700 dark:text-gray-300'
}

function actionButtonText(release: ReleaseItem): string {
  const isNew = isNewer(release.tag_name)
  if (downloadingTag.value === release.tag_name) {
    return isNew ? t('header.updating') : t('header.switching')
  }
  return isNew ? t('header.update') : t('header.switch')
}

function onActionClick(release: ReleaseItem) {
  if (downloadingTag.value) return
  pendingRelease.value = release
  const isNew = isNewer(release.tag_name)
  const version = release.name || release.tag_name

  if (release.prerelease) {
    confirmTitle.value = isNew ? t('header.prerelease_update_title') : t('header.prerelease_switch_title')
    confirmMessage.value = isNew
      ? t('header.prerelease_update_message', { version })
      : t('header.prerelease_switch_message', { version })
  } else {
    confirmTitle.value = isNew ? t('header.confirm_update_title') : t('header.confirm_switch_title')
    confirmMessage.value = isNew
      ? t('header.confirm_update_message', { version })
      : t('header.confirm_switch_message', { version })
  }
  confirmButton.value = isNew ? t('header.update') : t('header.switch')
  confirmRef.value?.open()
}

async function handleConfirm() {
  const release = pendingRelease.value
  if (!release) return
  downloadingTag.value = release.tag_name
  const isNew = isNewer(release.tag_name)
  try {
    const { data } = await downloadRelease(release.tag_name)
    updateProgress.value = data
    await pollUpdateProgress(data.id, isNew)
  } catch {
    notify(t('header.download_failed'), 'error')
  } finally {
    downloadingTag.value = null
    pendingRelease.value = null
  }
}

async function pollUpdateProgress(taskId: string, isNew: boolean) {
  while (true) {
    const { data } = await getReleaseUpdateProgress(taskId)
    updateProgress.value = data
    if (data.status === 'failed') {
      notify(t('header.update_failed'), 'error', 10000)
      return
    }
    if (data.status === 'restarting') {
      notify(isNew ? t('header.update_success') : t('header.switch_success'), 'success')
      try {
        await waitUntilReady({ requireRestart: true })
      } catch {
        notify(t('header.restart_timeout'), 'warning', 600000)
      }
      return
    }
    await new Promise<void>(resolve => {
      progressTimer = setTimeout(resolve, 500)
    })
    progressTimer = null
  }
}

function stageLabel(stage: string): string {
  return t(`header.update_stage_${stage}`)
}

function stageText(status: string): string {
  return status === 'done' ? t('header.update_stage_done') : status === 'running' ? t('header.update_stage_running') : t('header.update_stage_pending')
}

function stageClass(status: string): string {
  if (status === 'done') return 'text-green-600 dark:text-green-400'
  if (status === 'running') return 'text-blue-600 dark:text-blue-300'
  return 'text-gray-500 dark:text-gray-400'
}

onBeforeUnmount(() => {
  if (progressTimer) clearTimeout(progressTimer)
})

function renderMarkdown(text: string): string {
  return DOMPurify.sanitize(marked.parse(text, { async: false }) as string)
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

<style scoped>
.release-body :deep(h1),
.release-body :deep(h2),
.release-body :deep(h3) {
  font-weight: 600;
  margin-top: 0.5em;
  margin-bottom: 0.25em;
}

.release-body :deep(h1) { font-size: 1.1em; }
.release-body :deep(h2) { font-size: 1em; }
.release-body :deep(h3) { font-size: 0.95em; }

.release-body :deep(ul) {
  list-style-type: disc;
  padding-left: 1.25em;
  margin: 0.25em 0;
}

.release-body :deep(ol) {
  list-style-type: decimal;
  padding-left: 1.25em;
  margin: 0.25em 0;
}

.release-body :deep(li) {
  margin: 0.15em 0;
}

.release-body :deep(a) {
  color: #3b82f6;
  text-decoration: underline;
}

.release-body :deep(code) {
  background: rgba(0, 0, 0, 0.06);
  padding: 0.1em 0.3em;
  border-radius: 3px;
  font-size: 0.9em;
}

.release-body :deep(pre) {
  background: rgba(0, 0, 0, 0.06);
  padding: 0.5em;
  border-radius: 4px;
  overflow-x: auto;
  margin: 0.5em 0;
}

.release-body :deep(pre code) {
  background: none;
  padding: 0;
}

.release-body :deep(p) {
  margin: 0.25em 0;
}

:deep(.dark) .release-body :deep(code) {
  background: rgba(255, 255, 255, 0.1);
}

:deep(.dark) .release-body :deep(pre) {
  background: rgba(255, 255, 255, 0.1);
}

:deep(.dark) .release-body :deep(a) {
  color: #60a5fa;
}
</style>
