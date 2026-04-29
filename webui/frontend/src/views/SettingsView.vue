<template>
  <div>
    <div class="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
      <h3 class="text-lg font-semibold text-gray-800 dark:text-gray-200 mb-6">
        {{ $t('settings.title') }}
      </h3>
      <div class="space-y-6">
        <!-- Custom CSS -->
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

        <!-- Custom JS -->
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
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { notify } from '@/composables/useNotification'
import MonacoEditor from '@/components/common/MonacoEditor.vue'

const { t } = useI18n()
const saving = ref(false)

const customCSS = ref('')
const customJS = ref('')

onMounted(() => {
  customCSS.value = localStorage.getItem('custom_css') || ''
  customJS.value = localStorage.getItem('custom_js') || ''
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
