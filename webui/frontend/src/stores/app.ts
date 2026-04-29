import { defineStore } from 'pinia'
import { ref } from 'vue'
import i18n from '@/i18n'

const ALLOWED_THEMES = ['light', 'dark'] as const
const ALLOWED_LANGUAGES = ['en', 'zh'] as const
type Theme = (typeof ALLOWED_THEMES)[number]
type Language = (typeof ALLOWED_LANGUAGES)[number]

function sanitizeTheme(value: string | null): Theme {
  return (ALLOWED_THEMES as readonly string[]).includes(value ?? '') ? (value as Theme) : 'light'
}

function sanitizeLanguage(value: string | null): Language {
  return (ALLOWED_LANGUAGES as readonly string[]).includes(value ?? '')
    ? (value as Language)
    : 'en'
}

export const useAppStore = defineStore('app', () => {
  const theme = ref<Theme>(sanitizeTheme(localStorage.getItem('theme')))
  const language = ref<Language>(sanitizeLanguage(localStorage.getItem('language')))

  const isDark = ref(theme.value === 'dark')

  function setTheme(newTheme: string) {
    const validated = sanitizeTheme(newTheme)
    theme.value = validated
    isDark.value = validated === 'dark'
    localStorage.setItem('theme', validated)
    if (validated === 'dark') {
      document.documentElement.classList.add('dark')
    } else {
      document.documentElement.classList.remove('dark')
    }
  }

  function toggleTheme() {
    setTheme(isDark.value ? 'light' : 'dark')
  }

  function setLanguage(lang: string) {
    const validated = sanitizeLanguage(lang)
    language.value = validated
    localStorage.setItem('language', validated)
    i18n.global.locale.value = validated
  }

  // Theme side effects are applied by App.vue on mount via
  // appStore.setTheme(appStore.theme); the store only holds validated state
  // so we don't double-write to the DOM and localStorage on creation.

  return {
    theme,
    language,
    isDark,
    setTheme,
    toggleTheme,
    setLanguage,
  }
})
