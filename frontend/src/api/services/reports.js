import { api } from './client'

export const reportService = {
  createSystemIssue(payload) {
    return api.post('/reports/system-issues', payload)
  },
  listSystemIssues(params) {
    return api.get('/reports/admin/system-issues', { params })
  },
  getSystemIssue(id) {
    return api.get(`/reports/admin/system-issues/${id}`)
  },
  updateSystemIssueReadState(id, isRead) {
    return api.patch(`/reports/admin/system-issues/${id}/read-state`, { is_read: isRead })
  },
  deleteSystemIssue(id) {
    return api.delete(`/reports/admin/system-issues/${id}`)
  },
  listCommentReports(params) {
    return api.get('/reports/admin/comments', { params })
  },
  getCommentReport(id) {
    return api.get(`/reports/admin/comments/${id}`)
  },
  deleteCommentReport(id) {
    return api.delete(`/reports/admin/comments/${id}`)
  },
  reviewCommentReport(id, payload) {
    return api.patch(`/reports/admin/comments/${id}`, payload)
  },
  createArchiveReport(courseId, archiveId, payload) {
    return api.post(`/reports/courses/${courseId}/archives/${archiveId}`, payload)
  },
  getPendingArchiveReport(courseId, archiveId) {
    return api.get(`/reports/courses/${courseId}/archives/${archiveId}/pending`)
  },
  listArchiveReports(params) {
    return api.get('/reports/admin/archives', { params })
  },
  getArchiveReport(id) {
    return api.get(`/reports/admin/archives/${id}`)
  },
  deleteArchiveReport(id) {
    return api.delete(`/reports/admin/archives/${id}`)
  },
  reviewArchiveReport(id, payload) {
    return api.patch(`/reports/admin/archives/${id}`, payload)
  },
}
