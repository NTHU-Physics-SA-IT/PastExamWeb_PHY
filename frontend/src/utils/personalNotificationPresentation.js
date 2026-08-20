import { i18n } from '@/i18n'

const COMMENT_REASON_KEYS = Object.freeze({
  spam_or_duplicate: '垃圾訊息或重複洗版',
  harassment_or_hostility: '攻擊、騷擾或不友善內容',
  inappropriate_or_illegal: '不當或違法內容',
  privacy_violation: '洩漏個人資料或隱私',
  misinformation: '錯誤或誤導資訊',
  other: '其他',
})

const ARCHIVE_REASON_KEYS = Object.freeze({
  file_unavailable_or_corrupt: '檔案無法開啟或檔案損毀',
  metadata_mismatch: '考古題內容與課程／考試資訊不符',
  duplicate_archive: '重複的考古題',
  incomplete_or_low_quality: '檔案模糊、缺頁或內容不完整',
  personal_information: '含有不適合公開的個人資訊',
  other: '其他問題',
})

const SUBMISSION_COPY = Object.freeze({
  archive_submission_approved: ['考古題審核通過', '已通過審核'],
  archive_submission_rejected: ['考古題投稿已退回', '已退回'],
  archive_submission_takedown: ['考古題已下架', '已下架'],
})

const stringValue = (value) => (value == null ? '' : String(value).trim())

function legacyActorName(title, suffix) {
  const value = stringValue(title)
  return value.endsWith(suffix) ? value.slice(0, -suffix.length).trim() : ''
}

function legacyAdminResponse(message, trailingMarker) {
  const value = stringValue(message)
  const prefix = '管理員答覆：'
  const start = value.indexOf(prefix)
  const end = value.lastIndexOf(trailingMarker)
  if (start < 0 || end <= start) return ''
  return value
    .slice(start + prefix.length, end)
    .replace(/。$/, '')
    .trim()
}

function translatedReason(reason, mapping) {
  const key = mapping[stringValue(reason)]
  return key ? i18n.global.t(key) : stringValue(reason)
}

function reportResultLabel(status) {
  return i18n.global.t(status === 'upheld' ? '回報成立' : '回報不成立')
}

function discussionPresentation(item) {
  const metadata = item.metadata || {}
  if (item.notification_type === 'discussion_reply') {
    const actor = stringValue(metadata.actor_name) || legacyActorName(item.title, '回覆了你的留言')
    return {
      title: actor ? i18n.global.t('{actor} 回覆了你的留言', { actor }) : item.title,
      message: item.message,
    }
  }
  if (item.notification_type === 'discussion_like') {
    const actor =
      stringValue(metadata.actor_name) || legacyActorName(item.title, '對你的留言按了愛心')
    return {
      title: actor ? i18n.global.t('{actor} 對你的留言按了愛心', { actor }) : item.title,
      message: item.message,
    }
  }
  return { title: i18n.global.t('你的留言已被管理員置頂'), message: item.message }
}

function commentReportPresentation(item) {
  const metadata = item.metadata || {}
  if (item.notification_type === 'comment_report_submitted') {
    return {
      title: i18n.global.t('留言回報已成功送出'),
      message: i18n.global.t('原因：{reason}。請等待管理員審核。', {
        reason: translatedReason(metadata.reason, COMMENT_REASON_KEYS),
      }),
    }
  }

  const response =
    stringValue(metadata.admin_response) || legacyAdminResponse(item.message, '。處置：')
  return {
    title: i18n.global.t('留言回報審核完成'),
    message: i18n.global.t('審核結果：{result}。管理員答覆：{response}。處置：{disposition}。', {
      result: reportResultLabel(metadata.status),
      response: response || i18n.global.t('未提供答覆'),
      disposition: i18n.global.t(metadata.comment_deleted ? '留言已刪除' : '未刪除留言'),
    }),
  }
}

function archiveReportPresentation(item) {
  const metadata = item.metadata || {}
  const course = stringValue(metadata.course_name_en) || stringValue(metadata.course_name)
  const archive = stringValue(metadata.archive_name)
  if (item.notification_type === 'archive_report_submitted') {
    return {
      title: i18n.global.t('考古題回報已收到'),
      message: i18n.global.t(
        '{course}－{archive}（考古題 #{id}）的回報已收到。原因：{reason}。目前為待審核。',
        {
          course,
          archive,
          id: metadata.archive_id,
          reason: translatedReason(metadata.reason, ARCHIVE_REASON_KEYS),
        }
      ),
    }
  }

  const legacyDispositionMarker = metadata.archive_taken_down ? '。該考古題' : '。管理員已完成處理'
  const response =
    stringValue(metadata.admin_response) ||
    legacyAdminResponse(item.message, legacyDispositionMarker)
  const dispositionKey = metadata.archive_taken_down
    ? '該考古題已下架。'
    : '管理員已完成處理；該考古題未因本次審核下架。'
  return {
    title: i18n.global.t('考古題回報審核完成'),
    message: i18n.global.t(
      '{course}－{archive}（考古題 #{id}）：{result}。管理員答覆：{response}。{disposition}',
      {
        course,
        archive,
        id: metadata.archive_id,
        result: reportResultLabel(metadata.status),
        response: response || i18n.global.t('未提供答覆'),
        disposition: i18n.global.t(dispositionKey),
      }
    ),
  }
}

function wishPresentation(item) {
  const metadata = item.metadata || {}
  if (item.notification_type === 'wish_report_submitted') {
    return {
      title: i18n.global.t('許願回報已成功送出'),
      message: i18n.global.t('原因：{reason}。請等待管理員審核。', {
        reason: translatedReason(metadata.reason, COMMENT_REASON_KEYS),
      }),
    }
  }
  if (item.notification_type === 'wish_report_result') {
    return {
      title: i18n.global.t('許願回報審核完成'),
      message: i18n.global.t('審核結果：{result}。管理員答覆：{response}。', {
        result: reportResultLabel(metadata.status),
        response: stringValue(metadata.admin_response) || i18n.global.t('未提供答覆'),
      }),
    }
  }
  return {
    title: i18n.global.t('考古許願已實現'),
    message: i18n.global.t('另一位使用者已上傳符合「{wishTitle}」的考古題，現在可以使用了。', {
      wishTitle: stringValue(metadata.wish_title),
    }),
  }
}

function submissionPresentation(item) {
  const metadata = item.metadata || {}
  const course = stringValue(metadata.course_name_en) || stringValue(metadata.course_name)
  const archive = stringValue(metadata.archive_name)
  const id = metadata.submission_id ?? item.source_id
  if (item.notification_type === 'archive_submission_republished') {
    return {
      title: i18n.global.t('考古題已重新上架'),
      message: i18n.global.t(
        '{course}－{archive}（投稿編號 #{id}）已重新上架，目前已恢復為「已通過」並公開。請前往「我的投稿狀態」查看詳情。',
        { course, archive, id }
      ),
    }
  }

  const [titleKey, statusKey] = SUBMISSION_COPY[item.notification_type] || []
  if (!titleKey) return { title: item.title, message: item.message }
  return {
    title: i18n.global.t(titleKey),
    message: i18n.global.t(
      '{course}－{archive}（投稿編號 #{id}）{status}。請前往「我的投稿狀態」查看詳情。',
      { course, archive, id, status: i18n.global.t(statusKey) }
    ),
  }
}

export function localizedPersonalNotification(item) {
  if (!item) return { title: '', message: '' }
  if (i18n.global.locale.value !== 'en') {
    return { title: item.title || '', message: item.message || '' }
  }

  if (item.notification_type?.startsWith('discussion_')) return discussionPresentation(item)
  if (item.notification_type?.startsWith('comment_report_')) return commentReportPresentation(item)
  if (item.notification_type?.startsWith('archive_report_')) return archiveReportPresentation(item)
  if (item.notification_type?.startsWith('archive_submission_')) return submissionPresentation(item)
  if (item.notification_type?.startsWith('wish_')) return wishPresentation(item)
  return { title: item.title || '', message: item.message || '' }
}
