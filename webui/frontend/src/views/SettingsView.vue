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
import { useTheme } from '@/composables/useTheme'
import { getSettings, updateSettings } from '@/api/settings'
import { ElMessage } from 'element-plus'

const { t } = useI18n()
const appStore = useAppStore()
const { syncMonacoTheme } = useTheme()
const saving = ref(false)

const allowedLanguages = ['en', 'zh'] as const
const allowedThemes = ['light', 'dark'] as const
type Language = (typeof allowedLanguages)[number]
type Theme = (typeof allowedThemes)[number]

function normalizeLanguage(value: unknown): Language {
  return (allowedLanguages as readonly string[]).includes(value as string)
    ? (value as Language)
    : appStore.language
}

function normalizeTheme(value: unknown): Theme {
  return (allowedThemes as readonly string[]).includes(value as string)
    ? (value as Theme)
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
    // Keep live Monaco editors in sync with the new theme. The helper is
    // a single global call — do not duplicate it per-editor.
    await syncMonacoTheme()
    ElMessage.success(t('settings.saved'))
  } catch {
    ElMessage.error(t('settings.save_failed'))
  } finally {
    saving.value = false
  }
}
</script>
