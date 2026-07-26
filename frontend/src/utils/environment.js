export const isRecoveryReview =
  String(import.meta.env.VITE_RECOVERY_REVIEW_MODE || '').toLowerCase() === 'true'

export const recoveryReviewLabel = 'Recovery Review｜2026-07-12 舊資料檢視｜唯讀'
