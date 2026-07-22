<template>
  <div class="min-h-screen flex items-center justify-center relative p-4">
    <div class="onboarding-light-spot onboarding-light-spot-1"></div>
    <div class="onboarding-light-spot onboarding-light-spot-2"></div>
    <div class="onboarding-light-spot onboarding-light-spot-3"></div>

    <button type="button" class="fixed top-4 right-4 z-50 p-2 rounded-lg bg-white/70 backdrop-blur-md border border-white/30 shadow-lg hover:bg-white/90 transition-all duration-200 dark:bg-gray-800/70 dark:border-gray-700/30 dark:hover:bg-gray-800/90" :aria-label="appStore.isDark ? t('header.switch_to_light') : t('header.switch_to_dark')" @click="appStore.toggleTheme">
      <IconSun v-if="appStore.isDark" class="w-6 h-6 text-yellow-500" />
      <IconMoon v-else class="w-6 h-6 text-gray-700" />
    </button>

    <div class="relative z-10 w-full max-w-md">
      <div class="max-h-[calc(100vh-2rem)] flex flex-col bg-white/70 backdrop-blur-xl rounded-2xl shadow-xl border border-white/30 p-8 dark:bg-gray-800/70 dark:border-gray-700/30">
        <div class="text-center mb-8">
          <div class="inline-flex items-center justify-center w-16 h-16 bg-gradient-to-br from-blue-500 to-purple-600 rounded-2xl mb-4 shadow-lg">
            <IconLightning class="w-8 h-8 text-white" />
          </div>
          <h1 class="text-3xl font-bold text-gray-900 mb-2 dark:text-white">{{ t('onboarding.title') }}</h1>
          <p class="text-gray-600 dark:text-gray-400">{{ step === 1 ? t('onboarding.description') : t('onboarding.configuration_description') }}</p>
        </div>

        <div class="flex items-center justify-center gap-2 mb-8" :aria-label="t('onboarding.progress')">
          <span class="w-8 h-1 rounded-full transition-colors" :class="step === 1 ? 'bg-blue-600' : 'bg-blue-200 dark:bg-blue-900'" />
          <span class="w-8 h-1 rounded-full transition-colors" :class="step === 2 ? 'bg-blue-600' : 'bg-blue-200 dark:bg-blue-900'" />
        </div>

        <form v-if="step === 1" class="min-h-0 flex-1 space-y-6 overflow-y-auto pr-1" @submit.prevent="goToConfigurationStep">
          <div>
            <label class="block text-sm font-medium text-gray-700 mb-2 dark:text-gray-300" for="backend-language">{{ t('onboarding.system_language') }}</label>
            <CustomSelect id="backend-language" v-model="language" :options="languageOptions" />
            <p class="mt-2 text-xs text-gray-500 dark:text-gray-400">{{ t('onboarding.system_language_hint') }}</p>
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700 mb-2 dark:text-gray-300" for="timezone">{{ t('onboarding.timezone') }}</label>
            <input id="timezone" v-model="timezone" type="text" class="w-full h-10 border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors" :placeholder="t('onboarding.timezone_placeholder')">
            <p class="mt-2 text-xs text-gray-500 dark:text-gray-400">{{ t('onboarding.timezone_hint') }}</p>
          </div>
          <button type="submit" class="w-full flex justify-center items-center py-3 px-4 border border-transparent rounded-xl shadow-sm text-sm font-medium text-white bg-[#2563eb] hover:bg-[#1d4ed8] focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-[#2563eb] transition-all duration-200 transform hover:scale-[1.02] active:scale-[0.98] dark:bg-blue-600 dark:hover:bg-blue-700 dark:focus:ring-blue-500">
            {{ t('onboarding.next') }}
          </button>
        </form>

        <div v-else class="min-h-0 flex-1 space-y-4 overflow-y-auto pr-1">
          <p class="text-sm text-gray-600 dark:text-gray-400">{{ t('onboarding.configuration_hint') }}</p>
          <button v-for="item in configurationItems" :key="item.key" type="button" class="w-full flex items-center gap-4 p-4 text-left rounded-xl border border-gray-200 bg-white/70 hover:border-blue-400 hover:bg-blue-50/70 transition-colors dark:border-gray-700 dark:bg-gray-800/70 dark:hover:border-blue-500 dark:hover:bg-gray-700" @click="openConfiguration(item.key)">
            <span class="flex items-center justify-center w-8 h-8 rounded-full bg-blue-100 text-sm font-semibold text-blue-700 dark:bg-blue-900/50 dark:text-blue-300">{{ item.order }}</span>
            <span class="flex-1"><span class="block font-medium text-gray-900 dark:text-white">{{ t(item.titleKey) }}</span><span class="block mt-1 text-xs text-gray-500 dark:text-gray-400">{{ t(item.descriptionKey) }}</span></span>
            <span class="text-blue-600 dark:text-blue-400" aria-hidden="true">→</span>
          </button>
          <div class="flex gap-3 pt-2">
            <button type="button" class="flex-1 py-3 px-4 border border-gray-300 rounded-xl text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-700" @click="step = 1">{{ t('onboarding.back') }}</button>
            <button type="button" class="flex-1 flex justify-center items-center py-3 px-4 border border-transparent rounded-xl shadow-sm text-sm font-medium text-white bg-[#2563eb] hover:bg-[#1d4ed8] transition-all duration-200 disabled:opacity-50 dark:bg-blue-600 dark:hover:bg-blue-700" :disabled="loading" @click="handleSubmit">
              <span>{{ loading ? t('onboarding.saving') : t('onboarding.finish') }}</span>
              <IconSpinner v-if="loading" class="animate-spin ml-2 h-5 w-5 text-white" />
            </button>
          </div>
        </div>

        <div v-if="errorMessage" class="mt-4 p-4 bg-red-50 border border-red-200 rounded-xl dark:bg-red-900/20 dark:border-red-800/30">
          <div class="flex items-center"><IconInfo class="w-5 h-5 text-red-600 mr-2 dark:text-red-400" /><span class="text-sm text-red-700 dark:text-red-300">{{ errorMessage }}</span></div>
        </div>
        <div class="mt-8 text-center"><p class="text-xs text-gray-500 dark:text-gray-400">KiraAI WebUI</p></div>
      </div>
    </div>

    <Modal v-model="configurationModalVisible" content-class="max-w-6xl" content-style="max-height: 90vh">
      <div class="bg-white dark:bg-gray-900 rounded-lg shadow-xl w-full flex flex-col" style="max-height: 90vh;">
        <div class="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <h2 class="text-lg font-semibold text-gray-800 dark:text-gray-100">{{ selectedConfigurationTitle }}</h2>
          <button type="button" class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300" :aria-label="t('onboarding.close_configuration')" @click="configurationModalVisible = false">
            <IconClose class="w-6 h-6" />
          </button>
        </div>
        <div class="flex-1 overflow-y-auto p-6"><component :is="selectedConfigurationComponent" v-if="selectedConfigurationComponent" :initial-tab="selectedConfiguration === 'models' ? 'models' : undefined" /></div>
      </div>
    </Modal>
  </div>
</template>

<script setup lang="ts">
import axios from 'axios'
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { markOnboardingCompleted } from '@/router'
import { useI18n } from 'vue-i18n'
import { completeOnboarding } from '@/api/onboarding'
import CustomSelect from '@/components/common/CustomSelect.vue'
import Modal from '@/components/common/Modal.vue'
import ProviderView from '@/views/ProviderView.vue'
import AdapterView from '@/views/AdapterView.vue'
import ConfigView from '@/views/ConfigView.vue'
import PersonaView from '@/views/PersonaView.vue'
import { IconClose, IconInfo, IconLightning, IconMoon, IconSpinner, IconSun } from '@/components/icons'
import { useAppStore } from '@/stores/app'

const { t } = useI18n()
const router = useRouter()
const appStore = useAppStore()
const language = ref<'en' | 'zh'>(appStore.language)
const languageOptions = [{ value: 'zh', label: t('onboarding.chinese') }, { value: 'en', label: t('onboarding.english') }]
const timezone = ref(Intl.DateTimeFormat().resolvedOptions().timeZone || '')
const loading = ref(false)
const errorMessage = ref('')
const step = ref<1 | 2>(1)
const configurationModalVisible = ref(false)
const selectedConfiguration = ref<'provider' | 'models' | 'adapter' | 'persona' | null>(null)
const configurationItems = [
  { key: 'provider' as const, order: 1, titleKey: 'onboarding.provider', descriptionKey: 'onboarding.provider_hint' },
  { key: 'models' as const, order: 2, titleKey: 'onboarding.default_models', descriptionKey: 'onboarding.default_models_hint' },
  { key: 'adapter' as const, order: 3, titleKey: 'onboarding.adapter', descriptionKey: 'onboarding.adapter_hint' },
  { key: 'persona' as const, order: 4, titleKey: 'onboarding.persona', descriptionKey: 'onboarding.persona_hint' },
]
const selectedConfigurationTitle = computed(() => {
  const item = configurationItems.find(({ key }) => key === selectedConfiguration.value)
  return item ? t(item.titleKey) : ''
})
const configurationComponents = {
  provider: ProviderView,
  models: ConfigView,
  adapter: AdapterView,
  persona: PersonaView,
}
const selectedConfigurationComponent = computed(() =>
  selectedConfiguration.value ? configurationComponents[selectedConfiguration.value] : null,
)

function goToConfigurationStep() { step.value = 2 }
function openConfiguration(key: 'provider' | 'models' | 'adapter' | 'persona') { selectedConfiguration.value = key; configurationModalVisible.value = true }
async function handleSubmit() {
  if (loading.value) return
  loading.value = true
  errorMessage.value = ''
  try {
    await completeOnboarding({ lang: language.value, timezone: timezone.value || null })
    markOnboardingCompleted()
    await router.push('/overview')
  } catch (error: unknown) {
    const detail = axios.isAxiosError(error) ? error.response?.data?.detail : null
    errorMessage.value = typeof detail === 'string' && detail.trim() ? detail : t('onboarding.save_error')
  } finally { loading.value = false }
}
</script>

<style>
.onboarding-light-spot { position: fixed; border-radius: 50%; filter: blur(80px); opacity: 0.6; animation: onboarding-float 8s ease-in-out infinite; pointer-events: none; }
.onboarding-light-spot-1 { width: 300px; height: 300px; background: radial-gradient(circle, rgb(59 130 246 / .4) 0%, transparent 70%); top: 10%; left: 10%; }
.onboarding-light-spot-2 { width: 250px; height: 250px; background: radial-gradient(circle, rgb(147 197 253 / .4) 0%, transparent 70%); top: 60%; right: 15%; animation-delay: 2s; }
.onboarding-light-spot-3 { width: 200px; height: 200px; background: radial-gradient(circle, rgb(167 139 250 / .4) 0%, transparent 70%); bottom: 15%; left: 25%; animation-delay: 4s; }
@keyframes onboarding-float { 0%, 100% { transform: translateY(0) scale(1); } 50% { transform: translateY(-20px) scale(1.05); } }
.dark .onboarding-light-spot { opacity: 0.3; }
.dark .onboarding-light-spot-1 { background: radial-gradient(circle, rgb(59 130 246 / .3) 0%, transparent 70%); }
.dark .onboarding-light-spot-2 { background: radial-gradient(circle, rgb(99 102 241 / .3) 0%, transparent 70%); }
.dark .onboarding-light-spot-3 { background: radial-gradient(circle, rgb(139 92 246 / .3) 0%, transparent 70%); }
</style>
