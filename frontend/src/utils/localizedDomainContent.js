import { i18n } from '../i18n'

const normalizedEnglish = (value) => (value == null ? '' : String(value).trim())
const canonical = (value) => (value == null ? '' : String(value))

const localizedContent = (record, canonicalField, englishField) => {
  if (!record) return ''
  const canonicalValue = canonical(record[canonicalField])
  if (i18n.global.locale.value !== 'en') return canonicalValue
  return normalizedEnglish(record[englishField]) || canonicalValue
}

export const localizedAnnouncementTitle = (announcement) =>
  localizedContent(announcement, 'title', 'title_en')

export const localizedAnnouncementContent = (announcement) =>
  localizedContent(announcement, 'body', 'body_en')

export const localizedReportTitle = (report) => localizedContent(report, 'title', 'title_en')

export const localizedReportDescription = (report) =>
  localizedContent(report, 'description', 'description_en')

export const announcementMatchesSearch = (announcement, query) => {
  const normalizedQuery = String(query || '')
    .trim()
    .toLocaleLowerCase()
  if (!normalizedQuery) return true
  return [announcement?.title, announcement?.title_en, announcement?.body, announcement?.body_en]
    .map((value) => canonical(value).toLocaleLowerCase())
    .some((value) => value.includes(normalizedQuery))
}
