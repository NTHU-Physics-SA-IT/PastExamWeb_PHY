import { afterEach, describe, expect, it } from 'vitest'

import { i18n } from '@/i18n'
import { localizedPersonalNotification } from '@/utils/personalNotificationPresentation'

describe('personal notification presentation', () => {
  afterEach(() => {
    i18n.global.locale.value = 'zh-TW'
  })

  it('renders a known report event entirely in English from stable metadata', () => {
    i18n.global.locale.value = 'en'

    expect(
      localizedPersonalNotification({
        notification_type: 'comment_report_submitted',
        title: '留言回報已成功送出',
        message: '原因：不當或違法內容。請等待管理員審核。',
        metadata: { reason: 'inappropriate_or_illegal', status: 'pending' },
      })
    ).toEqual({
      title: 'Comment report submitted successfully',
      message: 'Reason: Inappropriate or unlawful content. Please wait for administrator review.',
    })
  })

  it('translates system chrome while preserving actor names and user-written content', () => {
    i18n.global.locale.value = 'en'

    expect(
      localizedPersonalNotification({
        notification_type: 'discussion_reply',
        title: '小明 回覆了你的留言',
        message: '這是使用者寫的內容',
        metadata: { actor_name: '小明' },
      })
    ).toEqual({
      title: '小明 replied to your comment',
      message: '這是使用者寫的內容',
    })
  })

  it('keeps the persisted canonical presentation in Chinese mode', () => {
    expect(
      localizedPersonalNotification({
        notification_type: 'comment_report_submitted',
        title: '留言回報已成功送出',
        message: '原因：不當或違法內容。請等待管理員審核。',
        metadata: { reason: 'inappropriate_or_illegal' },
      })
    ).toEqual({
      title: '留言回報已成功送出',
      message: '原因：不當或違法內容。請等待管理員審核。',
    })
  })
})
