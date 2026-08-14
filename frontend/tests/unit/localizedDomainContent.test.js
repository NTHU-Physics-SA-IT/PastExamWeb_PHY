import { afterEach, describe, expect, it } from 'vitest'
import { i18n } from '@/i18n'
import {
  announcementMatchesSearch,
  localizedAnnouncementContent,
  localizedAnnouncementTitle,
  localizedReportDescription,
  localizedReportTitle,
} from '@/utils/localizedDomainContent'

const announcement = {
  title: '中文公告',
  title_en: ' English announcement ',
  body: '中文內容',
  body_en: ' English content ',
}
const report = {
  title: '使用者原始標題',
  title_en: ' English report ',
  description: '使用者原始內容',
  description_en: ' English description ',
}

afterEach(() => {
  i18n.global.locale.value = 'zh-TW'
})

describe('localized domain content', () => {
  it('always preserves canonical Chinese content in zh-TW', () => {
    i18n.global.locale.value = 'zh-TW'
    expect(localizedAnnouncementTitle(announcement)).toBe('中文公告')
    expect(localizedAnnouncementContent(announcement)).toBe('中文內容')
    expect(localizedReportTitle(report)).toBe('使用者原始標題')
    expect(localizedReportDescription(report)).toBe('使用者原始內容')
  })

  it('uses trimmed English presentation metadata in English', () => {
    i18n.global.locale.value = 'en'
    expect(localizedAnnouncementTitle(announcement)).toBe('English announcement')
    expect(localizedAnnouncementContent(announcement)).toBe('English content')
    expect(localizedReportTitle(report)).toBe('English report')
    expect(localizedReportDescription(report)).toBe('English description')
  })

  it('falls back to the unmodified canonical content when English is blank', () => {
    i18n.global.locale.value = 'en'
    expect(localizedAnnouncementTitle({ ...announcement, title_en: '  ' })).toBe('中文公告')
    expect(localizedAnnouncementContent({ ...announcement, body_en: null })).toBe('中文內容')
    expect(localizedReportTitle({ ...report, title_en: null })).toBe('使用者原始標題')
    expect(localizedReportDescription({ ...report, description_en: '\n' })).toBe('使用者原始內容')
  })

  it('searches canonical and English announcement title/content metadata', () => {
    expect(announcementMatchesSearch(announcement, '公告')).toBe(true)
    expect(announcementMatchesSearch(announcement, '內容')).toBe(true)
    expect(announcementMatchesSearch(announcement, 'ANNOUNCEMENT')).toBe(true)
    expect(announcementMatchesSearch(announcement, 'english content')).toBe(true)
    expect(announcementMatchesSearch(announcement, 'missing')).toBe(false)
  })
})
