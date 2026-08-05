export const ARCHIVE_REPORT_DETAIL_MAX_LENGTH = 1000
export const ARCHIVE_REPORT_OTHER_REASON = 'other'

export const ARCHIVE_REPORT_REASONS = Object.freeze([
  { label: '檔案無法開啟或檔案損毀', value: 'file_unavailable_or_corrupt' },
  { label: '考古題內容與課程／考試資訊不符', value: 'metadata_mismatch' },
  { label: '重複的考古題', value: 'duplicate_archive' },
  { label: '檔案模糊、缺頁或內容不完整', value: 'incomplete_or_low_quality' },
  { label: '含有不適合公開的個人資訊', value: 'personal_information' },
  { label: '其他問題', value: ARCHIVE_REPORT_OTHER_REASON },
])
