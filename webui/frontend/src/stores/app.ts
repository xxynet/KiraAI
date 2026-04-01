import { defineStore } from 'pinia'
import { ref } from 'vue'
import i18n from '@/i18n'

export const useAppStore = defineStore('app', () => {
  const theme = ref<string>(localStorage.getItem('theme') || 'light')
  const language = ref<string>(localStorage.getItem('language') || 'en')

  const isDark = ref(theme.value === 'dark')

  function setTheme(newTheme: string) {
    theme.value = newTheme
    isDark.value = newTheme === 'dark'
    localStorage.setItem('theme', newTheme)
    if (newTheme === 'dark') {
      document.documentElement.classList.add('dark')
    } else {
      document.documentElement.classList.remove('dark')
    }
  }

  function toggleTheme() {
    setTheme(isDark.value ? 'light' : 'dark')
  }

  function setLanguage(lang: string) {
    language.value = lang
    localStorage.setItem('language', lang)
    i18n.global.locale.value = lang as 'en' | 'zh'
  }

  // Initialize theme on store creation
  setTheme(theme.value)

  return {
    theme,
    language,
    isDark,
    setTheme,
    toggleTheme,
    setLanguage,
  }
})
