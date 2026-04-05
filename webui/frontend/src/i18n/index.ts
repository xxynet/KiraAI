import { createI18n } from 'vue-i18n'
import en from './en'
import zh from './zh'

const supportedLocales = ['en', 'zh'] as const
const storedLocale = localStorage.getItem('language')
const locale = storedLocale && supportedLocales.includes(storedLocale as any) ? storedLocale : 'en'

const i18n = createI18n({
  legacy: false,
  locale,
  fallbackLocale: 'en',
  messages: { en, zh },
})

export default i18n
