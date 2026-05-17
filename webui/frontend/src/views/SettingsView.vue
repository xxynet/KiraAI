<template>
  <div>
    <!-- Title -->
    <div class="flex items-center mb-6">
      <h3 class="text-lg font-semibold text-gray-800 dark:text-gray-100">{{ $t('settings.title') }}</h3>
    </div>

    <!-- Tabs -->
    <div class="flex space-x-4 mb-6 border-b border-gray-200 dark:border-gray-700">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        type="button"
        class="px-3 py-2 text-sm font-medium border-b-2 focus:outline-none transition-colors duration-150"
        :class="activeTab === tab.key ? 'border-blue-600 dark:border-blue-500 text-blue-600 dark:text-blue-500' : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 hover:border-gray-300 dark:hover:border-gray-600'"
        @click="activeTab = tab.key"
      >
        {{ tab.label }}
      </button>
    </div>

    <!-- Custom CSS/JS Tab -->
    <div v-show="activeTab === 'custom'" class="space-y-6">
      <div>
        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
          {{ $t('settings.custom_css') }}
        </label>
        <div class="border border-gray-300 dark:border-gray-600 rounded-lg overflow-hidden" style="height: 300px;">
          <MonacoEditor
            v-model="customCSS"
            language="css"
            :height="300"
          />
        </div>
      </div>

      <div>
        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
          {{ $t('settings.custom_js') }}
        </label>
        <div class="border border-gray-300 dark:border-gray-600 rounded-lg overflow-hidden" style="height: 300px;">
          <MonacoEditor
            v-model="customJS"
            language="javascript"
            :height="300"
          />
        </div>
      </div>

      <div class="flex justify-end">
        <button
          type="button"
          class="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          :disabled="saving"
          @click="handleSave"
        >
          {{ saving ? '...' : $t('settings.save') }}
        </button>
      </div>
    </div>

    <!-- About Tab -->
    <div v-show="activeTab === 'about'" class="space-y-6">
      <div class="flex flex-col items-center py-8">
        <div class="w-20 h-20 rounded-2xl bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center mb-4 shadow-lg">
          <span class="text-3xl font-bold text-white">K</span>
        </div>
        <h2 class="text-2xl font-bold text-gray-800 dark:text-gray-100">KiraAI</h2>
        <p class="text-sm text-gray-500 dark:text-gray-400 mt-1">{{ $t('settings.about_tagline') }}</p>
      </div>

      <div class="max-w-md mx-auto space-y-4">
        <div class="bg-gray-50 dark:bg-gray-700/50 rounded-lg p-4 space-y-3">
          <div class="flex justify-between items-center">
            <span class="text-sm text-gray-500 dark:text-gray-400">{{ $t('settings.about_version') }}</span>
            <span class="text-sm font-medium text-gray-800 dark:text-gray-200">{{ projectVersion }}</span>
          </div>
          <div class="flex justify-between items-center">
            <span class="text-sm text-gray-500 dark:text-gray-400">{{ $t('settings.about_license') }}</span>
            <span class="text-sm font-medium text-gray-800 dark:text-gray-200">AGPL-3.0</span>
          </div>
          <div class="flex justify-between items-center">
            <span class="text-sm text-gray-500 dark:text-gray-400">{{ $t('settings.about_repo') }}</span>
            <a
              href="https://github.com/xxynet/KiraAI"
              target="_blank"
              class="text-sm font-medium text-blue-600 dark:text-blue-400 hover:underline"
            >
              GitHub
            </a>
          </div>
          <div class="flex justify-between items-center">
            <span class="text-sm text-gray-500 dark:text-gray-400">{{ $t('header.docs') }}</span>
            <a
              :href="$t('header.docs_url')"
              target="_blank"
              class="text-sm font-medium text-blue-600 dark:text-blue-400 hover:underline"
            >
              {{ $t('header.docs_url') }}
            </a>
          </div>
        </div>

        <div class="bg-gray-50 dark:bg-gray-700/50 rounded-lg p-4 space-y-3">
          <h4 class="text-sm font-semibold text-gray-700 dark:text-gray-300">{{ $t('settings.about_community') }}</h4>
          <div class="flex justify-between items-center">
            <span class="text-sm text-gray-500 dark:text-gray-400">QQ {{ $t('settings.about_group') }}</span>
            <span class="text-sm font-medium text-gray-800 dark:text-gray-200">874381335</span>
          </div>
          <div class="flex justify-between items-center">
            <span class="text-sm text-gray-500 dark:text-gray-400">Discord</span>
            <a
              href="https://discord.gg/mRNmVmFHn3"
              target="_blank"
              class="text-sm font-medium text-blue-600 dark:text-blue-400 hover:underline"
            >
              KiraAI
            </a>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { notify } from '@/composables/useNotification'
import apiClient from '@/api/client'
import MonacoEditor from '@/components/common/MonacoEditor.vue'

const { t } = useI18n()
const saving = ref(false)
const activeTab = ref('custom')

const projectVersion = ref('dev')

const tabs = computed(() => [
  { key: 'custom', label: t('settings.tab_custom') },
  { key: 'about', label: t('settings.tab_about') },
])

const customCSS = ref('')
const customJS = ref('')

onMounted(() => {
  customCSS.value = localStorage.getItem('custom_css') || ''
  customJS.value = localStorage.getItem('custom_js') || ''

  apiClient.get('/version').then(({ data }) => {
    if (data?.version) projectVersion.value = data.version
  }).catch(() => {})
})

function applyCustomCSS() {
  const css = customCSS.value
  let tag = document.getElementById('custom-user-css')
  if (!tag) {
    tag = document.createElement('style')
    tag.id = 'custom-user-css'
    document.head.appendChild(tag)
  }
  tag.textContent = css
}

function applyCustomJS() {
  const js = customJS.value
  const oldTag = document.getElementById('custom-user-js')
  if (oldTag) oldTag.remove()
  if (!js) return
  const tag = document.createElement('script')
  tag.id = 'custom-user-js'
  tag.textContent = js
  document.body.appendChild(tag)
}

async function handleSave() {
  saving.value = true
  try {
    localStorage.setItem('custom_css', customCSS.value)
    localStorage.setItem('custom_js', customJS.value)
    applyCustomCSS()
    applyCustomJS()

    notify(t('settings.saved'), 'success')
  } catch {
    notify(t('settings.save_failed'), 'error')
  } finally {
    saving.value = false
  }
}
</script>
