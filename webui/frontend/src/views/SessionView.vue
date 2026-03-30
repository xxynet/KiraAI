<template>
  <div>
    <div v-if="sessions.length === 0" class="text-center py-12 text-gray-400">
      <el-icon :size="48"><ChatDotRound /></el-icon>
      <p class="mt-2 text-sm">{{ $t('sessions.no_sessions') }}</p>
    </div>

    <div v-else class="glass-card rounded-lg overflow-hidden">
      <el-table :data="sessions" stripe class="w-full">
        <el-table-column prop="title" :label="$t('sessions.name')" min-width="180">
          <template #default="{ row }">
            <span class="font-medium">{{ row.title || row.session_id || row.adapter_name }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="adapter_name" :label="$t('sessions.adapter_name')" width="150" />
        <el-table-column prop="session_type" :label="$t('sessions.session_type')" width="130">
          <template #default="{ row }">
            <el-tag :type="row.session_type === 'dm' ? '' : 'success'" size="small">
              {{ row.session_type === 'dm' ? $t('sessions.type_dm') : $t('sessions.type_gm') }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="session_id" :label="$t('sessions.session_id')" min-width="200">
          <template #default="{ row }">
            <span class="text-xs font-mono text-gray-500 break-all">{{ row.session_id || row.id }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="message_count" :label="$t('sessions.message_count')" width="120" align="center" />
        <el-table-column :label="$t('sessions.actions')" width="160" align="center">
          <template #default="{ row }">
            <el-button size="small" link type="primary" @click="editSession(row)">{{ $t('sessions.edit') }}</el-button>
            <el-button size="small" link type="danger" @click="handleDelete(row)">{{ $t('sessions.delete') }}</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- Session Editor Dialog -->
    <el-dialog
      v-model="editorVisible"
      :title="$t('sessions.edit')"
      width="80%"
      top="5vh"
      :destroy-on-close="true"
    >
      <div class="mb-4">
        <p class="text-sm text-gray-500">{{ currentSessionId }}</p>
        <p class="text-xs text-gray-400">{{ $t('sessions.message_count') }}: {{ messageCount }}</p>
      </div>
      <el-form label-position="top" class="mb-4">
        <el-form-item :label="$t('sessions.title')">
          <el-input v-model="sessionTitle" />
        </el-form-item>
      </el-form>
      <MonacoEditor
        v-model="editorContent"
        language="json"
        height="50vh"
      />
      <template #footer>
        <el-button @click="editorVisible = false">{{ $t('sessions.cancel') }}</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">{{ $t('sessions.save') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ChatDotRound } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getSessions, getSession, updateSession, deleteSession } from '@/api/session'
import MonacoEditor from '@/components/common/MonacoEditor.vue'
import type { SessionItem } from '@/types'

const { t } = useI18n()
const sessions = ref<SessionItem[]>([])
const editorVisible = ref(false)
const editorContent = ref('')
const currentSessionId = ref('')
const sessionTitle = ref('')
const messageCount = ref(0)
const saving = ref(false)

async function loadSessions() {
  try {
    const res = await getSessions()
    sessions.value = res.data.sessions || res.data || []
  } catch { /* silent */ }
}

async function editSession(session: SessionItem) {
  currentSessionId.value = session.id
  try {
    const res = await getSession(session.id)
    const data = res.data
    sessionTitle.value = data.title || ''
    messageCount.value = data.messages?.length || 0
    editorContent.value = JSON.stringify(data.messages || [], null, 2)
    editorVisible.value = true
  } catch {
    ElMessage.error(t('sessions.load_failed'))
  }
}

async function handleSave() {
  saving.value = true
  try {
    let messages: any[]
    try {
      messages = JSON.parse(editorContent.value)
    } catch {
      ElMessage.error(t('sessions.invalid_json'))
      saving.value = false
      return
    }
    await updateSession(currentSessionId.value, {
      title: sessionTitle.value,
      messages,
    })
    ElMessage.success(t('sessions.save_success'))
    editorVisible.value = false
    await loadSessions()
  } catch {
    ElMessage.error(t('sessions.save_failed'))
  } finally {
    saving.value = false
  }
}

async function handleDelete(session: SessionItem) {
  try {
    await ElMessageBox.confirm(t('sessions.delete_confirm'), t('sessions.delete'), { type: 'warning' })
    await deleteSession(session.id)
    ElMessage.success(t('sessions.delete_success'))
    await loadSessions()
  } catch { /* cancelled */ }
}

onMounted(() => {
  loadSessions()
})
</script>
