import { api } from './client'

const archiveSubmissionStatuses = new Set([
  'pending',
  'approved',
  'rejected',
  'takedown',
  'deleted',
])

const buildReviewDecision = (expectedStatus, note) => {
  const normalizedStatus = String(expectedStatus || '')
    .trim()
    .toLowerCase()
  if (!archiveSubmissionStatuses.has(normalizedStatus)) {
    throw new TypeError('Archive submission status is required')
  }
  return {
    note,
    expected_status: normalizedStatus,
  }
}

export const archiveService = {
  uploadArchive(formData) {
    return api.post('/archives/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    })
  },

  getArchivePreviewUrl(courseId, archiveId) {
    return api.get(`/courses/${courseId}/archives/${archiveId}/preview`)
  },

  getArchivePreviewFileUrl(courseId, archiveId) {
    return `/api/courses/${courseId}/archives/${archiveId}/preview-file`
  },

  getArchivePreviewFile(courseId, archiveId) {
    return api.get(`/courses/${courseId}/archives/${archiveId}/preview-file`, {
      responseType: 'blob',
    })
  },

  getArchiveDownloadUrl(courseId, archiveId) {
    return api.get(`/courses/${courseId}/archives/${archiveId}/download`)
  },

  downloadArchiveBackup() {
    return api.get('/backups/admin/archive', {
      responseType: 'blob',
      timeout: 0,
    })
  },

  deleteArchive(courseId, archiveId) {
    return api.delete(`/courses/${courseId}/archives/${archiveId}`)
  },

  updateArchive(courseId, archiveId, data) {
    const formData = new FormData()
    Object.entries(data).forEach(([key, value]) => {
      formData.append(key, value)
    })
    return api.patch(`/courses/${courseId}/archives/${archiveId}`, formData)
  },

  updateArchiveCourse(courseId, archiveId, newCourseId) {
    return api.patch(`/courses/${courseId}/archives/${archiveId}/course`, {
      course_id: newCourseId,
    })
  },

  updateArchiveCourseByCategoryAndName(courseId, archiveId, courseName, courseCategory) {
    return api.patch(`/courses/${courseId}/archives/${archiveId}/course`, {
      course_name: courseName,
      course_category: courseCategory,
    })
  },

  listMySubmissions() {
    return api.get('/archives/submissions/me')
  },

  listAdminSubmissions() {
    return api.get('/archives/admin/submissions')
  },

  getSubmissionStatistics(range, mode) {
    return api.get('/archives/admin/submission-statistics', {
      params: { range, mode },
    })
  },

  listSubmissionComparisons(submissionId) {
    return api.get(`/archives/admin/submissions/${submissionId}/comparisons`)
  },

  deleteMySubmission(submissionId) {
    return api.delete(`/archives/submissions/${submissionId}`)
  },

  approveSubmission(submissionId, expectedStatus, note = '') {
    return api.post(
      `/archives/admin/submissions/${submissionId}/approve`,
      buildReviewDecision(expectedStatus, note)
    )
  },

  rejectSubmission(submissionId, expectedStatus, note = '') {
    return api.post(
      `/archives/admin/submissions/${submissionId}/reject`,
      buildReviewDecision(expectedStatus, note)
    )
  },

  takedownSubmission(submissionId, expectedStatus, note = '') {
    return api.post(
      `/archives/admin/submissions/${submissionId}/takedown`,
      buildReviewDecision(expectedStatus, note)
    )
  },

  republishSubmission(submissionId, expectedStatus, note = '') {
    return api.post(
      `/archives/admin/submissions/${submissionId}/republish`,
      buildReviewDecision(expectedStatus, note)
    )
  },

  updateSubmission(submissionId, submissionData) {
    return api.put(`/archives/admin/submissions/${submissionId}`, submissionData)
  },

  deleteSubmission(submissionId) {
    return api.delete(`/archives/admin/submissions/${submissionId}`)
  },

  getSubmissionPreviewFile(submissionId) {
    return api.get(`/archives/admin/submissions/${submissionId}/preview-file`, {
      responseType: 'blob',
    })
  },

  listTrashItems(itemType = null) {
    return api.get('/trash', {
      params: itemType ? { item_type: itemType } : {},
    })
  },

  restoreTrashItem(itemType, itemId) {
    return api.post('/trash/restore', {
      item_type: itemType,
      item_id: itemId,
    })
  },

  permanentlyDeleteTrashItem(itemType, itemId) {
    return api.delete(`/trash/${itemType}/${itemId}`)
  },

  getPermanentDeletionStatus(operationId) {
    return api.get(`/trash/permanent-deletions/${operationId}`)
  },

  retryPermanentDeletion(operationId) {
    return api.post(`/trash/permanent-deletions/${operationId}/retry`)
  },

  permanentlyDeleteTrashScope(itemType = null) {
    return api.delete('/trash/bulk', {
      params: itemType ? { item_type: itemType } : {},
    })
  },
}
