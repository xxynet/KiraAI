<template>
  <div>
    <!-- Default Persona Card -->
    <div class="glass-card rounded-lg p-6 cursor-pointer hover:shadow-lg transition-shadow" @click="openEditor">
      <div class="flex justify-between items-start">
        <div>
          <h4 class="text-lg font-semibold text-gray-900 dark:text-white">{{ $t('persona.default_title') }}</h4>
          <p class="text-sm text-gray-500 mt-1">{{ preview }}</p>
        </div>
        <el-button size="small" @click.stop="openEditor">{{ $t('persona.edit') }}</el-button>
      </div>
    </div>

    <!-- Editor Dialog -->
    <el-dialog v-model="editorVisible" :title="$t('persona.edit')" width="80%" top="5vh" :destroy-on-close="true">
      <div class="flex items-center gap-4 mb-4">
        <span class="text-sm text-gray-600 dark:text-gray-400">{{ $t('persona.format') }}</span>
        <el-select v-model="draftFormat" size="small" style="width: 140px">
          <el-option label="Text" value="text" />
          <el-option label="Markdown" value="markdown" />
          <el-option label="JSON" value="json" />
          <el-option label="YAML" value="yaml" />
        </el-select>
      </div>
      <MonacoEditor
        v-model="draftContent"
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
const draftContent = ref('')
const draftFormat = ref('text')
const editorVisible = ref(false)
const saving = ref(false)
const contentLoaded = ref(false)

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
  return map[draftFormat.value] || 'plaintext'
})

function openEditor() {
  if (!contentLoaded.value) return
  draftContent.value = content.value
  draftFormat.value = format.value
  editorVisible.value = true
}

async function loadContent() {
  try {
    const res = await getCurrentPersonaContent()
    content.value = res.data.content || ''
    format.value = res.data.format || 'text'
    contentLoaded.value = true
  } catch (err) {
    console.error('loadContent failed:', err)
    contentLoaded.value = true
  }
}

async function handleSave() {
  saving.value = true
  try {
    await updateCurrentPersonaContent({ content: draftContent.value, format: draftFormat.value })
    content.value = draftContent.value
    format.value = draftFormat.value
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
