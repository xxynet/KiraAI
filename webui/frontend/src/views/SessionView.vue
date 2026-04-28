<template>
  <div class="glass-card rounded-lg shadow p-6">
    <div class="flex justify-between items-center mb-6">
      <h3 class="text-lg font-semibold text-gray-800 dark:text-gray-100">{{ $t('sessions.title') }}</h3>
      <button class="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 transition-colors flex items-center" @click="handleNewSession">
        <svg class="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"></path>
        </svg>
        <span>{{ $t('sessions.new') }}</span>
      </button>
    </div>

    <div v-if="sessions.length === 0" class="flex justify-center items-center py-12">
      <div class="text-center">
        <ChatDotRound class="w-16 h-16 text-gray-400 mx-auto mb-4" />
        <p class="text-gray-500 dark:text-gray-400">{{ $t('sessions.no_sessions') }}</p>
      </div>
    </div>

    <div v-else class="overflow-x-auto">
      <table class="min-w-full divide-y divide-gray-200 dark:divide-gray-800">
        <thead class="bg-gray-50 dark:bg-gray-800">
          <tr>
            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">{{ $t('sessions.name') }}</th>
            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">{{ $t('sessions.adapter_name') }}</th>
            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">{{ $t('sessions.session_type') }}</th>
            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">{{ $t('sessions.session_id') }}</th>
            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">{{ $t('sessions.message_count') }}</th>
            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">{{ $t('sessions.actions') }}</th>
          </tr>
        </thead>
        <tbody class="bg-white dark:bg-gray-900 divide-y divide-gray-200 dark:divide-gray-800">
          <tr v-for="session in sessions" :key="resolveSessionId(session)" class="hover:bg-gray-50 dark:hover:bg-gray-700/50">
            <td class="px-6 py-4 whitespace-nowrap">
              <div class="text-sm font-medium text-gray-900 dark:text-gray-100" :title="getDisplayTitleSource(session)">{{ getDisplayTitle(session) }}</div>
            </td>
            <td class="px-6 py-4 whitespace-nowrap">
              <div class="text-sm text-gray-500 dark:text-gray-400">{{ session.adapter_name }}</div>
            </td>
            <td class="px-6 py-4 whitespace-nowrap">
              <span class="px-2 py-1 text-xs rounded-full" :class="getSessionTypeColor(session.session_type)">
                {{ getSessionTypeLabel(session.session_type) }}
              </span>
            </td>
            <td class="px-6 py-4">
              <div class="text-sm text-gray-500 dark:text-gray-400 font-mono break-all max-w-xs">{{ session.session_id || session.id }}</div>
            </td>
            <td class="px-6 py-4 whitespace-nowrap">
              <div class="text-sm text-gray-500 dark:text-gray-400">{{ session.message_count }}</div>
            </td>
            <td class="px-6 py-4 whitespace-nowrap text-sm font-medium">
              <button class="text-blue-600 hover:text-blue-900 dark:hover:text-blue-300 mr-3" @click="editSession(session)">{{ $t('sessions.edit') }}</button>
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
    content-class="max-w-6xl"
    content-style="max-height: 95vh;"
  >
    <div class="bg-white dark:bg-gray-800 rounded-lg shadow-xl flex flex-col max-h-[95vh]">
      <div class="flex justify-between items-center px-6 py-4 border-b border-gray-200 dark:border-gray-700">
        <div class="flex-1 min-w-0">
          <h3 class="text-lg font-semibold text-gray-800 dark:text-gray-100">{{ $t('sessions.modal_title') }}</h3>
          <p class="text-sm text-gray-500 dark:text-gray-400 truncate mt-1">{{ currentSessionId }}</p>
        </div>
        <button class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 ml-4" @click="editorVisible = false">
          <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
          </svg>
        </button>
      </div>
      <div class="px-6 py-4 flex-1 overflow-y-auto">
        <div class="mb-4">
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">{{ $t('sessions.name') }}</label>
          <input v-model="sessionTitle" type="text" class="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100">
        </div>
        <div class="mb-4">
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">{{ $t('sessions.description') }}</label>
          <textarea v-model="sessionDescription" rows="2" class="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 resize-none"></textarea>
        </div>
        <div class="mb-4">
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">{{ $t('sessions.session_data') }}</label>
          <MonacoEditor
            v-model="editorContent"
            language="json"
            :height="350"
            class="border border-gray-300 dark:border-gray-600 rounded-lg overflow-hidden"
          />
        </div>
      </div>
      <div class="px-6 py-4 border-t border-gray-200 dark:border-gray-700 flex justify-between items-center">
        <div class="flex items-center space-x-2 text-sm text-gray-500 dark:text-gray-400">
          <span>{{ $t('sessions.message_count') }}: {{ messageCount }}</span>
        </div>
        <div class="flex space-x-3">
          <button class="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors" @click="editorVisible = false">{{ $t('sessions.modal_cancel') }}</button>
          <button class="px-4 py-2 bg-blue-600 dark:bg-blue-700 text-white rounded-lg hover:bg-blue-700 dark:hover:bg-blue-600 transition-colors" :disabled="saving" @click="handleSave">
            <span v-if="saving">{{ $t('sessions.save') }}...</span>
            <span v-else>{{ $t('sessions.modal_save') }}</span>
          </button>
        </div>
      </div>
    </div>
  </Modal>

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
const confirmModalRef = ref<InstanceType<typeof ConfirmModal>>()
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

function getDisplayTitleSource(session: SessionItem): string {
  return session.title || session.session_id || session.adapter_name || ''
}

function getDisplayTitle(session: SessionItem): string {
  const source = getDisplayTitleSource(session)
  const maxLength = 32
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
  return 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300'
}

function handleNewSession() {
  notify(t('sessions.new') + ' functionality coming soon', 'info')
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
