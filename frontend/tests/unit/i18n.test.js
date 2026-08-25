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

  it('uses the compact Pending review label only in English', () => {
    setLocale('en')
    expect(i18n.global.t('待審核')).toBe('Pending')

    setLocale('zh-TW')
    expect(i18n.global.t('待審核')).toBe('待審核')
  })

  it('uses compact Admin presentation labels without changing zh-TW wording', () => {
    i18n.global.locale.value = 'en'
    expect(i18n.global.t('管理員投稿（身分標籤）')).toBe('Administrator')
    expect(i18n.global.t('投稿等級（使用者管理欄位）')).toBe('Level')
    expect(i18n.global.t('管理員權限（使用者管理欄位）')).toBe('Admin')
    expect(i18n.global.t('管理員投稿')).toBe('Administrator Upload')
    expect(i18n.global.t('管理員權限')).toBe('Administrator Access')

    i18n.global.locale.value = 'zh-TW'
    expect(i18n.global.t('管理員投稿（身分標籤）')).toBe('管理員投稿')
    expect(i18n.global.t('投稿等級（使用者管理欄位）')).toBe('投稿等級')
    expect(i18n.global.t('管理員權限（使用者管理欄位）')).toBe('管理員權限')
  })

  it('uses compact English homepage actions without changing zh-TW wording', () => {
    setLocale('en')
    expect(i18n.global.t('清華校務系統登入')).toBe('Sign in with NTHU')
    expect(i18n.global.t('本地帳號登入')).toBe('Local Login')
    expect(i18n.global.t('瀏覽公開課程目錄')).toBe('Browse Course Catalog')

    setLocale('zh-TW')
    expect(i18n.global.t('清華校務系統登入')).toBe('清華校務系統登入')
    expect(i18n.global.t('本地帳號登入')).toBe('本地帳號登入')
    expect(i18n.global.t('瀏覽公開課程目錄')).toBe('瀏覽公開課程目錄')
  })

  it('localizes optional Wish semester presentation', () => {
    setLocale('en')
    expect(i18n.global.t('考試學期（選填）')).toBe('Exam Semester (Optional)')
    expect(i18n.global.t('不限學期')).toBe('Any Semester')

    setLocale('zh-TW')
    expect(i18n.global.t('考試學期（選填）')).toBe('考試學期（選填）')
    expect(i18n.global.t('不限學期')).toBe('不限學期')
  })
})
