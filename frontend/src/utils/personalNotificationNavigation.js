const NAVIGABLE_SOURCE_TYPES = new Set([
  'archive_submission',
  'archive_discussion_thread',
  'archive_report',
])

function positiveIntegerId(value) {
  if (typeof value === 'string') {
    if (!/^[0-9]+$/.test(value)) return null
    value = Number(value)
  }

  return Number.isSafeInteger(value) && value > 0 ? value : null
}

function metadataFor(item) {
  const metadata = item?.metadata
  return metadata && typeof metadata === 'object' && !Array.isArray(metadata) ? metadata : null
}

export function isNavigablePersonalNotificationSourceType(sourceType) {
  return NAVIGABLE_SOURCE_TYPES.has(sourceType)
}

export function buildPersonalNotificationRoute(item) {
  if (!item || typeof item !== 'object' || Array.isArray(item)) return null
  if (
    item.source_available !== true ||
    !isNavigablePersonalNotificationSourceType(item.source_type)
  ) {
    return null
  }

  const metadata = item.metadata == null ? {} : metadataFor(item)
  if (!metadata) return null

  if (item.source_type === 'archive_submission') {
    const submissionId = positiveIntegerId(item.source_id)
    if (!submissionId) return null

    if (Object.hasOwn(metadata, 'submission_id')) {
      const metadataSubmissionId = positiveIntegerId(metadata.submission_id)
      if (metadataSubmissionId !== submissionId) return null
    }

    return {
      path: '/archive',
      query: { showSubmissionStatus: '1', submissionId },
    }
  }

  const courseId = positiveIntegerId(metadata.course_id)
  const archiveId = positiveIntegerId(metadata.archive_id)
  if (!courseId || !archiveId) return null

  if (item.source_type === 'archive_report') {
    return {
      path: '/archive',
      query: { courseId, archiveId },
    }
  }

  const threadId = positiveIntegerId(item.source_id)
  const messageId = positiveIntegerId(item.source_message_id)
  if (!threadId || !messageId) return null

  return {
    path: '/archive',
    query: { courseId, archiveId, threadId, messageId },
  }
}
