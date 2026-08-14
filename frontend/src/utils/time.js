import { formatProductDateTime } from './productTimezone'
import { i18n } from '../i18n'

export function formatExactDateTime24h(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'

  return formatProductDateTime(date)
}

export function formatRelativeOrAbsoluteDateTime(value, locale = i18n.global.locale.value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'

  const now = new Date()
  const diffInMs = Math.max(now - date, 0)
  const diffInHours = Math.floor(diffInMs / (1000 * 60 * 60))
  const diffInDays = Math.floor(diffInHours / 24)

  if (diffInDays === 0) {
    if (diffInHours === 0) {
      const diffInMinutes = Math.floor(diffInMs / (1000 * 60))
      if (diffInMinutes < 1) {
        return locale === 'en' ? 'Just now' : '剛剛'
      } else if (diffInMinutes < 60) {
        if (locale === 'en') {
          return `${diffInMinutes} ${diffInMinutes === 1 ? 'minute' : 'minutes'} ago`
        }
        return `${diffInMinutes} 分鐘前`
      }
    }
    if (locale === 'en') {
      return `${diffInHours} ${diffInHours === 1 ? 'hour' : 'hours'} ago`
    }
    return `${diffInHours} 小時前`
  } else if (diffInDays === 1) {
    return locale === 'en' ? 'Yesterday' : '昨天'
  } else if (diffInDays < 7) {
    if (locale === 'en') return `${diffInDays} days ago`
    return `${diffInDays} 天前`
  }

  return formatExactDateTime24h(date)
}

export function formatRelativeTime(value, locale = i18n.global.locale.value) {
  return formatRelativeOrAbsoluteDateTime(value, locale)
}
