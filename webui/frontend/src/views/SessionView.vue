<template>
  <div class="glass-card rounded-lg shadow p-6">
    <div class="flex justify-between items-center mb-6">
      <h3 class="text-lg font-semibold text-theme-strong">{{ $t('sessions.title') }}</h3>
      <button class="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 transition-colors flex items-center" @click="handleNewSession">
        <IconPlus class="w-5 h-5 mr-2" />
        <span>{{ $t('sessions.new') }}</span>
      </button>
    </div>

    <div v-if="sessions.length === 0" class="flex justify-center items-center py-12">
      <div class="text-center">
        <ChatDotRound class="w-16 h-16 text-theme-faint mx-auto mb-4" />
        <p class="text-theme-subtle">{{ $t('sessions.no_sessions') }}</p>
      </div>
    </div>

    <div v-else class="overflow-x-auto">
      <table class="min-w-full divide-y divide-gray-200 dark:divide-gray-800">
        <thead class="bg-gray-50 dark:bg-gray-800">
          <tr>
            <th class="px-6 py-3 text-left text-xs font-medium text-theme-subtle uppercase tracking-wider">{{ $t('sessions.name') }}</th>
            <th class="px-6 py-3 text-left text-xs font-medium text-theme-subtle uppercase tracking-wider">{{ $t('sessions.adapter_name') }}</th>
            <th class="px-6 py-3 text-left text-xs font-medium text-theme-subtle uppercase tracking-wider">{{ $t('sessions.session_type') }}</th>
            <th class="px-6 py-3 text-left text-xs font-medium text-theme-subtle uppercase tracking-wider">{{ $t('sessions.session_id') }}</th>
            <th class="px-6 py-3 text-left text-xs font-medium text-theme-subtle uppercase tracking-wider">{{ $t('sessions.message_count') }}</th>
            <th class="px-6 py-3 text-left text-xs font-medium text-theme-subtle uppercase tracking-wider">{{ $t('sessions.actions') }}</th>
          </tr>
        </thead>
        <tbody class="bg-white dark:bg-gray-900 divide-y divide-gray-200 dark:divide-gray-800">
          <tr v-for="session in sessions" :key="resolveSessionId(session)" class="hover:bg-gray-50 dark:hover:bg-gray-700/50">
            <td class="px-6 py-4 whitespace-nowrap">
              <div class="text-sm font-medium text-theme-high" :title="getDisplayTitleSource(session)">{{ getDisplayTitle(session) }}</div>
            </td>
            <td class="px-6 py-4 whitespace-nowrap">
              <div class="text-sm text-theme-subtle">{{ session.adapter_name }}</div>
            </td>
            <td class="px-6 py-4 whitespace-nowrap">
              <span class="px-2 py-1 text-xs rounded-full" :class="getSessionTypeColor(session.session_type)">
                {{ getSessionTypeLabel(session.session_type) }}
              </span>
            </td>
            <td class="px-6 py-4">
              <div class="flex items-center gap-2 max-w-xs">
                <div class="text-sm text-theme-subtle font-mono break-all">{{ session.session_id || session.id }}</div>
                <button
                  type="button"
                  class="session-copy-button shrink-0 text-theme-faint hover:text-blue-600 dark:hover:text-blue-300 transition-colors"
                  :title="$t('sessions.copy_session_id')"
                  :aria-label="$t('sessions.copy_session_id')"
                  @click="copySessionId(session)"
                >
                  <IconCopy class="w-4 h-4" />
                </button>
              </div>
            </td>
            <td class="px-6 py-4 whitespace-nowrap">
              <div class="text-sm text-theme-subtle">{{ session.message_count }}</div>
            </td>
            <td class="px-6 py-4 whitespace-nowrap text-sm font-medium">
              <button class="text-blue-600 hover:text-blue-900 dark:hover:text-blue-300 mr-3" @click="editSession(session)">{{ $t('sessions.edit') }}</button>
              <button class="text-amber-600 hover:text-amber-900 dark:hover:text-amber-600 mr-3" @click="handleClear(session)">{{ $t('sessions.clear') }}</button>
              <button class="text-red-600 hover:text-red-900 dark:hover:text-red-300" @click="handleDelete(session)">{{ $t('sessions.delete') }}</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

  <!-- Session Editor Modal -->
  <Modal
    v-model="editorVisible"
    content-class="max-w-4xl"
    content-style="max-height: 95vh;"
  >
    <div class="bg-white dark:bg-gray-900 rounded-lg shadow-xl flex flex-col max-h-[95vh] modal-card">
      <div class="flex justify-between items-center px-6 py-4 border-b border-gray-200 dark:border-gray-700">
        <div class="flex-1 min-w-0">
          <h3 class="text-lg font-semibold text-theme-strong">{{ $t('sessions.modal_title') }}</h3>
          <p class="text-sm text-theme-subtle truncate mt-1">{{ currentSessionId }}</p>
        </div>
        <button class="text-theme-faint text-theme-faint-hover ml-4" @click="editorVisible = false">
          <IconClose class="w-6 h-6" />
        </button>
      </div>
      <div class="px-6 py-4 flex-1 overflow-y-auto">
        <div class="mb-4">
          <label class="block text-sm font-medium text-theme-body mb-2">{{ $t('sessions.name') }}</label>
          <UiInput v-model="sessionTitle" class="w-full rounded-lg px-3 py-2" />
        </div>
        <div class="mb-4">
          <label class="block text-sm font-medium text-theme-body mb-2">{{ $t('sessions.description') }}</label>
          <UiTextarea
            v-model="sessionDescription"
            :placeholder="$t('sessions.description_placeholder')"
            rows="2"
            class="w-full rounded-lg px-3 py-2 resize-none"
          />
        </div>
        <div class="mb-4">
          <label class="block text-sm font-medium text-theme-body mb-2">{{ $t('sessions.session_data') }}</label>
          <MonacoEditor
            v-model="editorContent"
            language="json"
            :height="350"
            :folding="false"
            :sticky-scroll="false"
            class="border border-gray-300 dark:border-gray-600 rounded-lg overflow-hidden"
          />
        </div>
      </div>
      <div class="px-6 py-4 border-t border-gray-200 dark:border-gray-700 flex justify-between items-center">
        <div class="flex items-center space-x-2 text-sm text-theme-subtle">
          <span>{{ $t('sessions.message_count') }}: {{ messageCount }}</span>
        </div>
        <div class="flex space-x-3">
          <button class="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-theme-body hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors" @click="editorVisible = false">{{ $t('sessions.modal_cancel') }}</button>
          <button class="px-4 py-2 bg-blue-600 dark:bg-blue-700 text-white rounded-lg hover:bg-blue-700 dark:hover:bg-blue-600 transition-colors" :disabled="saving" @click="handleSave">
            <span v-if="saving">{{ $t('sessions.save') }}...</span>
            <span v-else>{{ $t('sessions.modal_save') }}</span>
          </button>
        </div>
      </div>
    </div>
  </Modal>
  <ConfirmModal
    ref="clearConfirmModalRef"
    :title="$t('sessions.clear_confirm_title')"
    :message="$t('sessions.clear_confirm_message')"
    :cancel-text="$t('sessions.modal_cancel')"
    :confirm-text="$t('sessions.clear')"
    @confirm="onClearConfirmed"
  />

  <ConfirmModal
    ref="confirmModalRef"
    :title="$t('sessions.delete_confirm_title')"
    :message="$t('sessions.delete_confirm_message')"
    :cancel-text="$t('sessions.modal_cancel')"
    :confirm-text="$t('sessions.delete')"
    @confirm="onDeleteConfirmed"
  />
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ChatDotRound } from '@element-plus/icons-vue'
import { notify } from '@/composables/useNotification'
import { getSessions, getSession, updateSession, deleteSession } from '@/api/session'
import MonacoEditor from '@/components/common/MonacoEditor.vue'
import Modal from '@/components/common/Modal.vue'
import ConfirmModal from '@/components/common/ConfirmModal.vue'
import UiInput from '@/components/ui/UiInput.vue'
import UiTextarea from '@/components/ui/UiTextarea.vue'
import { IconPlus, IconClose, IconCopy } from '@/components/icons'
import type { SessionItem } from '@/types'

const { t } = useI18n()
const sessions = ref<SessionItem[]>([])
const editorVisible = ref(false)
const editorContent = ref('')
const currentSessionId = ref('')
const sessionTitle = ref('')
const sessionDescription = ref('')
const messageCount = ref(0)
const saving = ref(false)
const clearConfirmModalRef = ref<InstanceType<typeof ConfirmModal>>()
const confirmModalRef = ref<InstanceType<typeof ConfirmModal>>()
const sessionToClear = ref<SessionItem | null>(null)
const sessionToDelete = ref<SessionItem | null>(null)

async function loadSessions() {
  try {
    const res = await getSessions()
    const data = res.data
    sessions.value = Array.isArray(data.sessions) ? data.sessions : Array.isArray(data) ? data : []
  } catch (e) {
    sessions.value = []
    console.error('Failed to load sessions:', e)
    notify(t('sessions.load_failed'), 'error')
  }
}

function resolveSessionId(session: SessionItem): string {
  return session.id || session.session_id || ''
}

function getSessionIdentifier(session: SessionItem): string {
  return session.id || [session.adapter_name, session.session_type, session.session_id].filter(Boolean).join(':')
}

async function copyTextToClipboard(text: string): Promise<boolean> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // Fall back for browsers or embedded contexts that deny Clipboard API access.
    }
  }

  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', '')
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.select()

  try {
    return document.execCommand('copy')
  } finally {
    textarea.remove()
  }
}

async function copySessionId(session: SessionItem) {
  const sessionIdentifier = getSessionIdentifier(session)
  if (!sessionIdentifier) {
    notify(t('sessions.copy_failed'), 'error')
    return
  }

  if (await copyTextToClipboard(sessionIdentifier)) {
    notify(t('sessions.copy_success'), 'success')
  } else {
    notify(t('sessions.copy_failed'), 'error')
  }
}

function getDisplayTitleSource(session: SessionItem): string {
  return session.title || session.session_id || session.adapter_name || ''
}

function getDisplayTitle(session: SessionItem): string {
  const source = getDisplayTitleSource(session)
  const maxLength = 20
  if (source.length > maxLength) {
    return source.slice(0, maxLength) + '...'
  }
  return source
}

function getSessionTypeLabel(type: string): string {
  if (type === 'dm') return t('sessions.type_dm')
  if (type === 'gm') return t('sessions.type_gm')
  return type
}

function getSessionTypeColor(type: string): string {
  if (type === 'dm') return 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300'
  if (type === 'gm') return 'bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300'
  return 'bg-gray-100 text-theme-strong dark:bg-gray-700'
}

function handleNewSession() {
  notify(t('sessions.new_coming_soon'), 'info')
}

async function editSession(session: SessionItem) {
  const id = resolveSessionId(session)
  if (!id) {
    notify(t('sessions.load_failed'), 'error')
    return
  }
  currentSessionId.value = id
  try {
    const res = await getSession(id)
    const data = res.data
    sessionTitle.value = data.title || ''
    sessionDescription.value = data.description || ''
    messageCount.value = data.messages?.length || 0
    editorContent.value = JSON.stringify(data.messages || [], null, 2)
    editorVisible.value = true
  } catch {
    notify(t('sessions.load_failed'), 'error')
  }
}

async function handleSave() {
  saving.value = true
  try {
    let messages: any[]
    try {
      messages = JSON.parse(editorContent.value)
    } catch {
      notify(t('sessions.invalid_json'), 'error')
      saving.value = false
      return
    }
    if (!Array.isArray(messages)) {
      notify(t('sessions.invalid_json'), 'error')
      saving.value = false
      return
    }
    await updateSession(currentSessionId.value, {
      title: sessionTitle.value,
      description: sessionDescription.value,
      messages,
    })
    notify(t('sessions.save_success'), 'success')
    editorVisible.value = false
    await loadSessions()
  } catch {
    notify(t('sessions.save_failed'), 'error')
  } finally {
    saving.value = false
  }
}

function handleDelete(session: SessionItem) {
  sessionToDelete.value = session
  confirmModalRef.value?.open()
}

function handleClear(session: SessionItem) {
  sessionToClear.value = session
  clearConfirmModalRef.value?.open()
}

async function onClearConfirmed() {
  if (!sessionToClear.value) return
  const id = resolveSessionId(sessionToClear.value)
  if (!id) {
    notify(t('sessions.clear_failed'), 'error')
    sessionToClear.value = null
    return
  }
  try {
    await updateSession(id, { messages: [] })
    notify(t('sessions.clear_success'), 'success')
    await loadSessions()
  } catch {
    notify(t('sessions.clear_failed'), 'error')
  } finally {
    sessionToClear.value = null
  }
}

async function onDeleteConfirmed() {
  if (!sessionToDelete.value) return
  const id = resolveSessionId(sessionToDelete.value)
  if (!id) {
    notify(t('sessions.delete_failed'), 'error')
    sessionToDelete.value = null
    return
  }
  try {
    await deleteSession(id)
    notify(t('sessions.delete_success'), 'success')
    await loadSessions()
  } catch {
    notify(t('sessions.delete_failed'), 'error')
  } finally {
    sessionToDelete.value = null
  }
}

onMounted(() => {
  loadSessions()
})
</script>
