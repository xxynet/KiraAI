import { createI18n } from 'vue-i18n'
import en from './en'
import zh from './zh'

const supportedLocales = ['en', 'zh'] as const
let locale = localStorage.getItem('language')

if (!locale || !(supportedLocales as readonly string[]).includes(locale)) {
  const browserLang = navigator.language?.toLowerCase() || ''
  locale = browserLang.startsWith('zh') ? 'zh' : 'en'
  localStorage.setItem('language', locale)
}

const i18n = createI18n({
  legacy: false,
  locale,
  fallbackLocale: 'en',
  messages: { en, zh },
})

export default i18n
