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

const { t } = useI18n()
const appStore = useAppStore()
const saving = ref(false)

const allowedLanguages = ['en', 'zh'] as const
const allowedThemes = ['light', 'dark'] as const

function normalizeLanguage(value: unknown): string {
  return (allowedLanguages as readonly string[]).includes(value as string)
    ? (value as string)
    : appStore.language
}

function normalizeTheme(value: unknown): string {
  return (allowedThemes as readonly string[]).includes(value as string)
    ? (value as string)
    : appStore.theme
}

const form = ref({
  language: appStore.language,
  theme: appStore.theme,
})

onMounted(async () => {
  try {
    const res = await getSettings()
    form.value.language = normalizeLanguage(res.data.language)
    form.value.theme = normalizeTheme(res.data.theme)
  } catch {
    // use local defaults
  }
})

async function handleSave() {
  saving.value = true
  try {
    // Normalize again right before persisting, so only whitelisted values
    // are sent to the backend or written to the app store.
    const normalized = {
      language: normalizeLanguage(form.value.language),
      theme: normalizeTheme(form.value.theme),
    }
    form.value = normalized
    await updateSettings(normalized)
    appStore.setLanguage(normalized.language)
    appStore.setTheme(normalized.theme)
    monaco.editor.setTheme(normalized.theme === 'dark' ? 'vs-dark' : 'vs')
    ElMessage.success(t('settings.saved'))
  } catch {
    ElMessage.error(t('settings.save_failed'))
  } finally {
    saving.value = false
  }
}
</script>
