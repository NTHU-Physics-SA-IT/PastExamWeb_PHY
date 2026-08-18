function localizedAnnouncementField(notification, field, locale) {
  const canonicalValue = notification?.[field] || ''
  if (
    !String(locale || '')
      .toLowerCase()
      .startsWith('en')
  )
    return canonicalValue

  return notification?.[`${field}_en`]?.trim() || canonicalValue
}

export function localizedAnnouncementTitle(notification, locale) {
  return localizedAnnouncementField(notification, 'title', locale)
}

export function localizedAnnouncementBody(notification, locale) {
  return localizedAnnouncementField(notification, 'body', locale)
}
