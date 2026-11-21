<template>
  <Modal :model-value="modelValue" content-class="max-w-6xl" @update:model-value="close">
    <div role="dialog" aria-modal="true" aria-labelledby="skill-details-title" class="bg-white dark:bg-gray-900 rounded-lg shadow-xl w-full min-w-0 overflow-hidden flex flex-col h-[90vh]">
      <div class="flex shrink-0 items-start justify-between gap-4 px-6 py-4 border-b border-gray-200 dark:border-gray-700">
        <div class="min-w-0">
          <h3 id="skill-details-title" class="text-lg font-semibold text-theme-strong break-words">{{ skill?.name }}</h3>
        </div>
        <button type="button" class="shrink-0 p-1 rounded-md text-theme-faint text-theme-faint-hover enabled:hover:bg-gray-100 dark:enabled:hover:bg-gray-800 transition-colors disabled:opacity-50 disabled:cursor-not-allowed" :aria-label="$t('plugin.close')" :disabled="saving" @click="close">
          <IconClose class="w-6 h-6" />
        </button>
      </div>
      <div class="skill-details-content flex-1 px-6 py-4 overflow-y-auto overflow-x-hidden min-h-0 min-w-0 max-w-full">
        <section v-if="description" aria-labelledby="skill-description-title" class="mb-5 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 p-4">
          <h4 id="skill-description-title" class="text-sm font-medium text-theme-high">{{ $t('plugin.skills_description') }}</h4>
          <p class="mt-2 text-sm text-theme-supporting whitespace-pre-wrap break-words">{{ description }}</p>
        </section>
        <div class="grid grid-cols-1 md:grid-cols-[14rem_minmax(0,1fr)] gap-5">
          <nav :aria-label="$t('plugin.skills_files')" class="min-w-0 md:sticky md:top-0 md:self-start md:flex md:max-h-[calc(90vh-11rem)] md:flex-col">
            <div class="flex shrink-0 items-center justify-between gap-3 mb-3">
              <h4 class="font-medium text-theme-high">{{ $t('plugin.skills_files') }}</h4>
              <button type="button" class="p-1 rounded-md text-theme-subtle enabled:hover:bg-gray-100 dark:enabled:hover:bg-gray-800 transition-colors disabled:opacity-50 disabled:cursor-not-allowed" :disabled="saving || filesLoading" :aria-label="$t('common.refresh')" @click="requestAction(loadFiles)">
                <IconRefresh class="w-4 h-4" />
              </button>
            </div>
            <div v-if="filesLoading" role="status">
              <span class="sr-only">{{ $t('plugin.status_loading') }}</span>
              <div aria-hidden="true" class="space-y-3 motion-safe:animate-pulse">
                <div v-for="index in 5" :key="index" class="h-8 w-full rounded bg-gray-200 dark:bg-gray-700" />
              </div>
            </div>
            <template v-else-if="filesError">
              <p role="alert" class="text-sm text-red-600 dark:text-red-400 whitespace-pre-wrap">{{ filesError }}</p>
              <button type="button" class="mt-2 text-sm text-blue-600 dark:text-blue-400 hover:underline" @click="loadFiles">{{ $t('plugin.skills_retry') }}</button>
            </template>
            <p v-else-if="!files.length" class="text-sm text-theme-subtle">{{ $t('plugin.skills_no_files') }}</p>
            <ul v-else class="max-h-48 md:min-h-0 md:max-h-[50vh] overflow-y-auto overflow-x-hidden space-y-1">
              <li v-for="item in visibleFileNodes" :key="item.path">
                <button type="button" class="flex items-start gap-2 w-full rounded-md px-3 py-2 text-left text-sm transition-colors disabled:opacity-50 disabled:cursor-not-allowed" :class="activePath === item.path ? 'bg-blue-50 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400' : 'text-theme-body enabled:hover:bg-gray-100 dark:enabled:hover:bg-gray-800'" :style="{ paddingInlineStart: `${0.75 + item.depth * 0.75}rem` }" :title="item.path" :aria-expanded="item.children ? expandedDirectories.has(item.path) : undefined" :aria-current="activePath === item.path ? 'true' : undefined" :disabled="saving" @click="item.children ? toggleDirectory(item.path) : selectFile(item.path)">
                  <IconChevronDown v-if="item.children" class="w-4 h-4 mt-0.5 shrink-0 transition-transform" :class="expandedDirectories.has(item.path) ? '' : '-rotate-90'" />
                  <IconFileText v-else class="w-4 h-4 mt-0.5 shrink-0" />
                  <span class="min-w-0 break-all">{{ item.name }}</span>
                </button>
              </li>
            </ul>
          </nav>
          <div class="min-w-0" :aria-busy="loading">
            <div v-if="activePath" class="flex min-h-8 flex-wrap items-center justify-between gap-3 mb-3">
              <h4 class="font-medium text-theme-high break-all">{{ activePath }}</h4>
              <div v-if="file && !loading" class="flex items-center gap-3">
                <button v-if="file.kind === 'text' && !editing" type="button" class="text-sm text-blue-600 dark:text-blue-400 hover:underline" @click="editing = true">{{ $t('plugin.skills_edit') }}</button>
                <button type="button" class="text-sm text-blue-600 dark:text-blue-400 enabled:hover:underline disabled:opacity-50 disabled:cursor-not-allowed" :disabled="downloading" @click="downloadFile">{{ $t('plugin.skills_download_file') }}</button>
              </div>
            </div>
            <p v-if="error" role="alert" class="mb-4 text-sm text-red-600 dark:text-red-400 whitespace-pre-wrap">{{ error }}</p>
            <div v-if="loading" class="min-h-[50vh]">
              <PluginReadme :readme="null" :loading="true" :repo-url="null" repo-ref="HEAD" />
            </div>
            <template v-else-if="file">
              <template v-if="file.kind === 'text'">
                <p v-if="editing && activePath === 'SKILL.md'" class="mb-3 text-sm text-theme-subtle">{{ $t('plugin.skills_edit_hint') }}</p>
                <PluginReadme v-if="!editing && language === 'markdown'" :readme="previewContent" :loading="false" :repo-url="null" repo-ref="HEAD" />
                <MonacoEditor v-else :key="activePath" v-model="content" :language="language" height="50vh" horizontal-scrollbar="hidden" :read-only="!editing || saving" />
              </template>
              <img v-else-if="file.kind === 'image' && imageUrl" :src="imageUrl" :alt="activePath" class="max-w-full h-auto rounded-md" />
              <p v-else class="text-sm text-theme-subtle">{{ $t(file.reason === 'too_large' ? 'plugin.skills_file_too_large' : 'plugin.skills_file_binary') }}</p>
            </template>
            <button v-else-if="activePath && !loading" type="button" class="text-sm text-blue-600 dark:text-blue-400 hover:underline" @click="loadContent(activePath)">{{ $t('plugin.skills_retry') }}</button>
          </div>
        </div>
      </div>
      <div class="px-6 py-4 flex shrink-0 justify-end gap-3 border-t border-gray-200 dark:border-gray-700">
        <template v-if="editing">
          <button type="button" class="px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-theme-body enabled:hover:bg-gray-50 dark:enabled:hover:bg-gray-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed" :disabled="saving" @click="cancelEdit">{{ $t('plugin.cancel') }}</button>
          <button type="button" class="px-4 py-2 rounded-lg bg-blue-600 dark:bg-blue-700 text-white enabled:hover:bg-blue-700 dark:enabled:hover:bg-blue-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed" :disabled="saving || !dirty" @click="saveContent">
            <IconSpinner v-if="saving" class="inline-block w-4 h-4 mr-1 animate-spin" />{{ $t('plugin.save') }}
          </button>
        </template>
        <button v-else type="button" class="px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-theme-body hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors" @click="close">{{ $t('plugin.close') }}</button>
      </div>
    </div>
  </Modal>
  <ConfirmModal
    ref="discardModal"
    :title="$t('plugin.skills_discard_title')"
    :message="$t('plugin.skills_discard_message', { path: activePath })"
    :cancel-text="$t('plugin.cancel')"
    :confirm-text="$t('plugin.skills_discard')"
    @confirm="discardChanges"
    @cancel="pendingAction = null"
  />
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { downloadSkillFile, getSkillFile, getSkillFiles, updateSkillFile, type SkillFileContent, type SkillFileItem, type SkillItem } from '@/api/skills'
import { notify } from '@/composables/useNotification'
import { IconChevronDown, IconClose, IconFileText, IconRefresh, IconSpinner } from '@/components/icons'
import Modal from './Modal.vue'
import ConfirmModal from './ConfirmModal.vue'
import MonacoEditor from './MonacoEditor.vue'
import PluginReadme from './PluginReadme.vue'

const props = defineProps<{ modelValue: boolean; skill: SkillItem | null }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; saved: [] }>()
const { t } = useI18n()
const content = ref('')
const originalContent = ref('')
const description = ref('')
const files = ref<SkillFileItem[]>([])
const expandedDirectories = ref(new Set<string>())
const filesLoading = ref(false)
const filesError = ref<string | null>(null)
const activePath = ref('')
const file = ref<SkillFileContent | null>(null)
const imageUrl = ref<string | null>(null)
const loading = ref(false)
const editing = ref(false)
const saving = ref(false)
const downloading = ref(false)
const error = ref<string | null>(null)
const discardModal = ref<InstanceType<typeof ConfirmModal> | null>(null)
const dirty = computed(() => content.value !== originalContent.value)
type SkillFileNode = { name: string; path: string; children?: SkillFileNode[] }
const fileTree = computed(() => {
  const roots: SkillFileNode[] = []
  const directories = new Map<string, SkillFileNode>()
  for (const file of files.value) {
    const parts = file.path.split('/')
    let siblings = roots
    for (let index = 0; index < parts.length; index++) {
      const name = parts[index]!
      const path = parts.slice(0, index + 1).join('/')
      if (index === parts.length - 1) {
        siblings.push({ name, path })
      } else {
        let directory = directories.get(path)
        if (!directory) {
          directory = { name, path, children: [] }
          directories.set(path, directory)
          siblings.push(directory)
        }
        siblings = directory.children!
      }
    }
  }
  return roots
})
const visibleFileNodes = computed(() => {
  const visible: (SkillFileNode & { depth: number })[] = []
  function visit(nodes: SkillFileNode[], depth: number) {
    const sorted = [...nodes].sort((a, b) =>
      Number(!!b.children) - Number(!!a.children) || a.name.localeCompare(b.name))
    for (const node of sorted) {
      visible.push({ ...node, depth })
      if (node.children && expandedDirectories.value.has(node.path)) visit(node.children, depth + 1)
    }
  }
  visit(fileTree.value, 0)
  return visible
})
const previewContent = computed(() => activePath.value === 'SKILL.md'
  ? content.value.replace(/^---\r?\n[\s\S]*?\r?\n---(?:\r?\n|$)/, '')
  : content.value)
const fileLanguages: Record<string, string> = {
  md: 'markdown', markdown: 'markdown', py: 'python', js: 'javascript', mjs: 'javascript', cjs: 'javascript',
  ts: 'typescript', tsx: 'typescript', jsx: 'javascript', json: 'json', yaml: 'yaml', yml: 'yaml',
  sh: 'shell', bash: 'shell', ps1: 'powershell', html: 'html', css: 'css', scss: 'scss',
  xml: 'xml', svg: 'xml', sql: 'sql', toml: 'ini', ini: 'ini', rb: 'ruby', rs: 'rust', go: 'go',
  java: 'java', c: 'c', h: 'c', cpp: 'cpp', cs: 'csharp', bat: 'bat', cmd: 'bat',
}
const language = computed(() => {
  const name = activePath.value.split('/').pop()?.toLowerCase() || ''
  return name === 'dockerfile' ? 'dockerfile' : fileLanguages[name.split('.').pop() || ''] || 'plaintext'
})
let request = 0
let filesRequest = 0
const pendingAction = ref<(() => void) | null>(null)

watch(() => props.modelValue, visible => {
  if (visible) {
    expandedDirectories.value = new Set()
    description.value = props.skill?.description || ''
    void loadFiles()
  } else {
    request++
    filesRequest++
    releaseImage()
  }
})

function releaseImage() {
  if (imageUrl.value) URL.revokeObjectURL(imageUrl.value)
  imageUrl.value = null
}

onBeforeUnmount(() => {
  request++
  filesRequest++
  releaseImage()
})

async function loadFiles() {
  if (!props.skill) return
  const current = ++filesRequest
  request++
  filesLoading.value = true
  loading.value = false
  filesError.value = null
  files.value = []
  file.value = null
  activePath.value = ''
  content.value = originalContent.value = ''
  editing.value = false
  error.value = null
  releaseImage()
  try {
    const response = await getSkillFiles(props.skill.id)
    if (current !== filesRequest) return
    files.value = response.data
    const initial = files.value.find(item => item.path === 'SKILL.md') || files.value[0]
    if (initial) void loadContent(initial.path)
  } catch (e: any) {
    if (current === filesRequest) filesError.value = errorMessage('plugin.skills_files_load_failed', e)
  } finally {
    if (current === filesRequest) filesLoading.value = false
  }
}

async function loadContent(path: string) {
  if (!props.skill) return
  const parts = path.split('/')
  for (let index = 1; index < parts.length; index++) {
    expandedDirectories.value.add(parts.slice(0, index).join('/'))
  }
  const current = ++request
  const skillName = props.skill.id
  activePath.value = path
  loading.value = true
  file.value = null
  editing.value = false
  error.value = null
  content.value = originalContent.value = ''
  releaseImage()
  try {
    const response = await getSkillFile(skillName, path)
    if (current !== request) return
    if (response.data.kind === 'image') {
      const image = await downloadSkillFile(skillName, path)
      if (current !== request) return
      imageUrl.value = URL.createObjectURL(image.data)
    }
    content.value = originalContent.value = response.data.content ?? ''
    file.value = response.data
  } catch (e: any) {
    if (current === request) error.value = errorMessage('plugin.skills_content_load_failed', e)
  } finally {
    if (current === request) loading.value = false
  }
}

function errorMessage(key: string, e: any): string {
  const detail = e?.response?.data?.detail || e?.message
  return detail ? `${t(key)}: ${typeof detail === 'string' ? detail : JSON.stringify(detail)}` : t(key)
}

function selectFile(path: string) {
  if (path !== activePath.value) requestAction(() => { void loadContent(path) })
}

function toggleDirectory(path: string) {
  if (expandedDirectories.value.has(path)) expandedDirectories.value.delete(path)
  else expandedDirectories.value.add(path)
}

function requestAction(action: () => void) {
  if (saving.value || pendingAction.value) return
  if (dirty.value) {
    pendingAction.value = action
    discardModal.value?.open()
  } else {
    action()
  }
}

function close() {
  requestAction(() => emit('update:modelValue', false))
}

function cancelEdit() {
  requestAction(() => { editing.value = false })
}

function discardChanges() {
  content.value = originalContent.value
  editing.value = false
  error.value = null
  const action = pendingAction.value
  pendingAction.value = null
  action?.()
}

async function saveContent() {
  if (!props.skill || file.value?.kind !== 'text' || saving.value || !dirty.value) return
  saving.value = true
  error.value = null
  try {
    const response = await updateSkillFile(props.skill.id, activePath.value, content.value, originalContent.value)
    originalContent.value = content.value
    description.value = response.data.description
    const item = files.value.find(item => item.path === activePath.value)
    if (item) item.size_bytes = response.data.size_bytes
    editing.value = false
    notify(t('plugin.skills_save_success'), 'success')
    emit('saved')
  } catch (e: any) {
    error.value = errorMessage(e?.response?.status === 409 ? 'plugin.skills_save_conflict' : 'plugin.skills_save_failed', e)
  } finally {
    saving.value = false
  }
}

async function downloadFile() {
  if (!props.skill || !activePath.value || downloading.value) return
  const path = activePath.value
  downloading.value = true
  try {
    const response = await downloadSkillFile(props.skill.id, path)
    const url = URL.createObjectURL(response.data)
    const link = document.createElement('a')
    link.href = url
    link.download = path.split('/').pop() || path
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (e: any) {
    notify(errorMessage('plugin.skills_download_failed', e), 'error')
  } finally {
    downloading.value = false
  }
}
</script>

<style scoped>
.skill-details-content {
  overflow-wrap: anywhere;
}

.skill-details-content :deep(.plugin-readme pre) {
  white-space: pre-wrap;
  overflow-x: hidden;
}

.skill-details-content :deep(.plugin-readme pre code) {
  white-space: inherit;
}

.skill-details-content :deep(.plugin-readme table) {
  display: table;
  width: 100%;
  table-layout: fixed;
}
</style>
