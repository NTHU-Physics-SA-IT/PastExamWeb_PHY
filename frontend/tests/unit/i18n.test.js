import { afterEach, describe, expect, it, vi } from 'vitest'

import { DEFAULT_LOCALE, LOCALE_STORAGE_KEY, SUPPORTED_LOCALES, i18n, setLocale } from '@/i18n'

describe('locale authority', () => {
  afterEach(() => {
    setLocale(DEFAULT_LOCALE)
  })

  it('supports exactly zh-TW and en and falls invalid values back to zh-TW', () => {
    expect(SUPPORTED_LOCALES).toEqual(['zh-TW', 'en'])
    expect(setLocale('invalid')).toBe('zh-TW')
    expect(i18n.global.locale.value).toBe('zh-TW')
    expect(document.documentElement.lang).toBe('zh-TW')
    expect(localStorage.getItem(LOCALE_STORAGE_KEY)).toBe('zh-TW')
  })

  it('updates persistence, html lang, and listeners immediately without reload', () => {
    const listener = vi.fn()
    window.addEventListener('pastexam:locale-changed', listener)

    expect(setLocale('en')).toBe('en')
    expect(i18n.global.locale.value).toBe('en')
    expect(document.documentElement.lang).toBe('en')
    expect(localStorage.getItem(LOCALE_STORAGE_KEY)).toBe('en')
    expect(listener).toHaveBeenCalledOnce()

    window.removeEventListener('pastexam:locale-changed', listener)
  })

  it('uses compact English Admin tab labels without changing zh-TW keys', () => {
    setLocale('en')
    expect(i18n.global.t('課程管理')).toBe('Course')
    expect(i18n.global.t('公告管理')).toBe('Announcement')
    expect(i18n.global.t('使用者管理')).toBe('User')
    expect(i18n.global.t('回報管理')).toBe('Report')

    setLocale('zh-TW')
    expect(i18n.global.t('課程管理')).toBe('課程管理')
    expect(i18n.global.t('公告管理')).toBe('公告管理')
    expect(i18n.global.t('使用者管理')).toBe('使用者管理')
    expect(i18n.global.t('回報管理')).toBe('回報管理')
  })
})
