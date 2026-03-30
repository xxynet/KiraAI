<template>
  <div class="max-w-lg">
    <div class="glass-card rounded-lg p-6 space-y-6">
      <!-- Language -->
      <div>
        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
          {{ $t('settings.language') }}
        </label>
        <el-select v-model="form.language" class="w-full">
          <el-option label="English" value="en" />
          <el-option label="中文" value="zh" />
        </el-select>
      </div>

      <!-- Theme -->
      <div>
        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
          {{ $t('settings.theme') }}
        </label>
        <el-select v-model="form.theme" class="w-full">
          <el-option :label="$t('settings.theme_light')" value="light" />
          <el-option :label="$t('settings.theme_dark')" value="dark" />
        </el-select>
      </div>

      <el-button type="primary" :loading="saving" @click="handleSave">
        {{ $t('settings.save') }}
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAppStore } from '@/stores/app'
import { getSettings, updateSettings } from '@/api/settings'
import { ElMessage } from 'element-plus'
import * as monaco from 'monaco-editor'

const { t, locale } = useI18n()
const appStore = useAppStore()
const saving = ref(false)

const form = ref({
  language: appStore.language,
  theme: appStore.theme,
})

onMounted(async () => {
  try {
    const res = await getSettings()
    form.value.language = res.data.language || appStore.language
    form.value.theme = res.data.theme || appStore.theme
  } catch {
    // use local defaults
  }
})

async function handleSave() {
  saving.value = true
  try {
    await updateSettings(form.value)
    appStore.setLanguage(form.value.language)
    locale.value = form.value.language
    appStore.setTheme(form.value.theme)
    monaco.editor.setTheme(form.value.theme === 'dark' ? 'vs-dark' : 'vs')
    ElMessage.success(t('settings.saved'))
  } catch {
    ElMessage.error(t('settings.save_failed'))
  } finally {
    saving.value = false
  }
}
</script>
