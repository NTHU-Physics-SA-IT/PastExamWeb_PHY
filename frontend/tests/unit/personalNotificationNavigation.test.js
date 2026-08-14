import { describe, expect, it } from 'vitest'
import { buildPersonalNotificationRoute } from '@/utils/personalNotificationNavigation'

describe('buildPersonalNotificationRoute', () => {
  it('builds an archive submission route from the canonical source ID', () => {
    expect(
      buildPersonalNotificationRoute({
        source_available: true,
        source_type: 'archive_submission',
        source_id: '42',
      })
    ).toEqual({
      path: '/archive',
      query: { showSubmissionStatus: '1', submissionId: 42 },
    })
  })

  it('rejects invalid or mismatched archive submission IDs', () => {
    expect(
      buildPersonalNotificationRoute({
        source_available: true,
        source_type: 'archive_submission',
        source_id: 42,
        metadata: { submission_id: 43 },
      })
    ).toBeNull()
    expect(
      buildPersonalNotificationRoute({
        source_available: true,
        source_type: 'archive_submission',
        source_id: ' 42 ',
        metadata: {},
      })
    ).toBeNull()
  })

  it('builds a discussion route from canonical source and message IDs', () => {
    expect(
      buildPersonalNotificationRoute({
        source_available: true,
        source_type: 'archive_discussion_thread',
        source_id: 7,
        source_message_id: '9',
        metadata: { course_id: 2, archive_id: '3' },
      })
    ).toEqual({
      path: '/archive',
      query: { courseId: 2, archiveId: 3, threadId: 7, messageId: 9 },
    })
  })

  it('rejects an incomplete or malformed discussion route', () => {
    expect(
      buildPersonalNotificationRoute({
        source_available: true,
        source_type: 'archive_discussion_thread',
        source_id: 7,
        source_message_id: 9,
        metadata: { course_id: [], archive_id: 3 },
      })
    ).toBeNull()
    expect(
      buildPersonalNotificationRoute({
        source_available: true,
        source_type: 'archive_discussion_thread',
        source_id: 7,
        metadata: { course_id: 2, archive_id: 3 },
      })
    ).toBeNull()
  })

  it('builds an archive report route from valid destination metadata', () => {
    expect(
      buildPersonalNotificationRoute({
        source_available: true,
        source_type: 'archive_report',
        metadata: { course_id: 2, archive_id: 3 },
      })
    ).toEqual({ path: '/archive', query: { courseId: 2, archiveId: 3 } })
  })

  it('rejects incomplete or malformed archive report metadata', () => {
    expect(
      buildPersonalNotificationRoute({
        source_available: true,
        source_type: 'archive_report',
        metadata: { course_id: 2, archive_id: 0 },
      })
    ).toBeNull()
    expect(
      buildPersonalNotificationRoute({
        source_available: true,
        source_type: 'archive_report',
        metadata: { course_id: Infinity, archive_id: 3 },
      })
    ).toBeNull()
  })

  it('rejects navigation when the backend marks the source unavailable', () => {
    expect(
      buildPersonalNotificationRoute({
        source_available: false,
        source_type: 'archive_report',
        metadata: { course_id: 2, archive_id: 3 },
      })
    ).toBeNull()
  })

  it('rejects detail-only, source-less, and unknown source types', () => {
    for (const item of [
      { source_available: false, source_type: 'comment_report', metadata: {} },
      { source_available: true, source_type: null, metadata: {} },
      { source_available: true, source_type: 'legacy_unknown', metadata: {} },
    ]) {
      expect(buildPersonalNotificationRoute(item)).toBeNull()
    }
  })
})
