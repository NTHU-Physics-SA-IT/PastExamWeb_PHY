export const ARCHIVE_REPORT_CUSTOM_MESSAGE_MAX_LENGTH = 500
export const ARCHIVE_REPORT_OTHER_REASON = 'other'

export const ARCHIVE_REPORT_REASONS = Object.freeze([
  { label: '檔案無法開啟或下載', value: 'file_unavailable' },
  { label: '檔案內容錯誤、不完整或畫質不清', value: 'file_quality_or_content' },
  {
    label: '課程、學期、授課教師或考試名稱等資訊錯誤',
    value: 'metadata_incorrect',
  },
  { label: '答案、附件或檔案標示不符', value: 'answer_or_attachment_mismatch' },
  { label: '重複上傳或考古題放置錯誤', value: 'duplicate_or_misplaced' },
  { label: '含有個人資料或隱私資訊', value: 'privacy_information' },
  {
    label: '不當內容、版權或其他疑慮',
    value: 'inappropriate_copyright_or_other_concern',
  },
  { label: '其他', value: ARCHIVE_REPORT_OTHER_REASON },
])

export function buildArchiveReportPayload(reportReason, customMessage = '') {
  return {
    report_reason: reportReason,
    custom_message: String(customMessage).trim() || null,
  }
}
