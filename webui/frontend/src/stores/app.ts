import { defineStore } from 'pinia'
import { ref } from 'vue'
import i18n from '@/i18n'

const ALLOWED_THEMES = ['light', 'dark'] as const
const ALLOWED_LANGUAGES = ['en', 'zh'] as const
type Theme = (typeof ALLOWED_THEMES)[number]
type Language = (typeof ALLOWED_LANGUAGES)[number]

const THEME_TRANSITION_DURATION = 250
let themeTransitionTimer: number | undefined

function sanitizeTheme(value: string | null): Theme {
  return (ALLOWED_THEMES as readonly string[]).includes(value ?? '') ? (value as Theme) : 'light'
}

function getInitialTheme(): Theme {
  const storedTheme = localStorage.getItem('theme')
  if ((ALLOWED_THEMES as readonly string[]).includes(storedTheme ?? '')) {
    return storedTheme as Theme
  }

  return window.matchMedia?.('(prefers-color-scheme: dark)')?.matches ? 'dark' : 'light'
}

function sanitizeLanguage(value: string | null): Language {
  return (ALLOWED_LANGUAGES as readonly string[]).includes(value ?? '')
    ? (value as Language)
    : 'en'
}

export const useAppStore = defineStore('app', () => {
  const theme = ref<Theme>(getInitialTheme())
  const language = ref<Language>(sanitizeLanguage(localStorage.getItem('language')))

  const isDark = ref(theme.value === 'dark')

  function setTheme(newTheme: string, animate = false) {
    const validated = sanitizeTheme(newTheme)
    theme.value = validated
    isDark.value = validated === 'dark'
    localStorage.setItem('theme', validated)

    const root = document.documentElement
    const shouldAnimate = animate && !window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (shouldAnimate) {
      root.classList.add('theme-transition')
      // Ensure the browser applies the transition before changing theme colors.
      void root.offsetWidth
    }

    if (validated === 'dark') {
      root.classList.add('dark')
    } else {
      root.classList.remove('dark')
    }

    if (shouldAnimate) {
      if (themeTransitionTimer !== undefined) {
        window.clearTimeout(themeTransitionTimer)
      }
      themeTransitionTimer = window.setTimeout(() => {
        root.classList.remove('theme-transition')
        themeTransitionTimer = undefined
      }, THEME_TRANSITION_DURATION)
    }
  }

  function toggleTheme() {
    setTheme(isDark.value ? 'light' : 'dark', true)
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
