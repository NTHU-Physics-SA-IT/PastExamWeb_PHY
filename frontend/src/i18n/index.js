import { computed } from 'vue'
import { createI18n } from 'vue-i18n'

import { messages } from './messages'

export const DEFAULT_LOCALE = 'zh-TW'
export const SUPPORTED_LOCALES = Object.freeze(['zh-TW', 'en'])
export const LOCALE_STORAGE_KEY = 'pastexam.locale'

function normalizeLocale(value) {
  return SUPPORTED_LOCALES.includes(value) ? value : DEFAULT_LOCALE
}

function readInitialLocale() {
  if (typeof window === 'undefined') return DEFAULT_LOCALE
  return normalizeLocale(window.localStorage.getItem(LOCALE_STORAGE_KEY))
}

export const i18n = createI18n({
  legacy: false,
  globalInjection: true,
  locale: readInitialLocale(),
  fallbackLocale: DEFAULT_LOCALE,
  messages,
})

export function setLocale(value) {
  const locale = normalizeLocale(value)
  i18n.global.locale.value = locale
  if (typeof window !== 'undefined') {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, locale)
  }
  if (typeof document !== 'undefined') {
    document.documentElement.lang = locale
  }
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('pastexam:locale-changed'))
  }
  return locale
}

export function useLocale() {
  const locale = computed({
    get: () => i18n.global.locale.value,
    set: (value) => setLocale(value),
  })
  const isEnglish = computed(() => locale.value === 'en')
  const toggleLocale = () => setLocale(isEnglish.value ? 'zh-TW' : 'en')
  return { locale, isEnglish, setLocale, toggleLocale, supportedLocales: SUPPORTED_LOCALES }
}

export function getMessageTemplate(key) {
  const locale = normalizeLocale(i18n.global.locale.value)
  return messages[locale]?.[key] ?? messages[DEFAULT_LOCALE]?.[key] ?? key
}

setLocale(i18n.global.locale.value)
