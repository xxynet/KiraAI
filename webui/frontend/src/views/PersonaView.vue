<template>
  <div>
    <!-- Default Persona Card -->
    <div class="glass-card rounded-lg p-6 cursor-pointer hover:shadow-lg transition-shadow" @click="openEditor">
      <div class="flex justify-between items-start">
        <div>
          <h4 class="text-lg font-semibold text-gray-900 dark:text-white">default</h4>
          <p class="text-sm text-gray-500 mt-1">{{ preview }}</p>
        </div>
        <el-button size="small" @click.stop="openEditor">{{ $t('persona.edit') }}</el-button>
      </div>
    </div>

    <!-- Editor Dialog -->
    <el-dialog v-model="editorVisible" :title="$t('persona.edit')" width="80%" top="5vh" :destroy-on-close="true">
      <div class="flex items-center gap-4 mb-4">
        <span class="text-sm text-gray-600 dark:text-gray-400">{{ $t('persona.format') }}</span>
        <el-select v-model="format" size="small" style="width: 140px" @change="onFormatChange">
          <el-option label="Text" value="text" />
          <el-option label="Markdown" value="markdown" />
          <el-option label="JSON" value="json" />
          <el-option label="YAML" value="yaml" />
        </el-select>
      </div>
      <MonacoEditor
        v-model="content"
        :language="monacoLanguage"
        height="60vh"
      />
      <template #footer>
        <el-button @click="editorVisible = false">{{ $t('persona.cancel') }}</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">{{ $t('persona.save') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { getCurrentPersonaContent, updateCurrentPersonaContent } from '@/api/persona'
import MonacoEditor from '@/components/common/MonacoEditor.vue'

const { t } = useI18n()
const content = ref('')
const format = ref('text')
const editorVisible = ref(false)
const saving = ref(false)

const preview = computed(() => {
  if (!content.value) return t('persona.no_content')
  return content.value.substring(0, 150) + (content.value.length > 150 ? '...' : '')
})

const monacoLanguage = computed(() => {
  const map: Record<string, string> = {
    text: 'plaintext',
    markdown: 'markdown',
    json: 'json',
    yaml: 'yaml',
  }
  return map[format.value] || 'plaintext'
})

function onFormatChange() {
  // Language change is handled reactively through monacoLanguage computed
}

function openEditor() {
  editorVisible.value = true
}

async function loadContent() {
  try {
    const res = await getCurrentPersonaContent()
    content.value = res.data.content || ''
    format.value = res.data.format || 'text'
  } catch { /* silent */ }
}

async function handleSave() {
  saving.value = true
  try {
    await updateCurrentPersonaContent({ content: content.value })
    ElMessage.success(t('persona.save_success'))
    editorVisible.value = false
  } catch {
    ElMessage.error(t('persona.save_failed'))
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  loadContent()
})
</script>
