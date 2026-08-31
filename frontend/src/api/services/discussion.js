import { api, bindUnauthorizedWebSocket, buildWebSocketUrl } from './client'

const WS_TICKET_PATTERN = /^[A-Za-z0-9_-]{43,256}$/

export const discussionService = {
  listArchiveMessages(courseId, archiveId, { limit = 50, beforeId } = {}) {
    return api.get(`/courses/${courseId}/archives/${archiveId}/discussion/messages`, {
      params: {
        limit,
        before_id: beforeId,
      },
    })
  },

  deleteArchiveMessage(courseId, archiveId, messageId) {
    return api.delete(`/courses/${courseId}/archives/${archiveId}/discussion/${messageId}`)
  },

  pinArchiveMessage(courseId, archiveId, messageId, pinned) {
    const formData = new FormData()
    formData.append('pinned', pinned)
    return api.patch(
      `/courses/${courseId}/archives/${archiveId}/discussion/${messageId}/pin`,
      formData
    )
  },

  likeArchiveMessage(courseId, archiveId, messageId) {
    return api.put(`/courses/${courseId}/archives/${archiveId}/discussion/${messageId}/like`)
  },

  unlikeArchiveMessage(courseId, archiveId, messageId) {
    return api.delete(`/courses/${courseId}/archives/${archiveId}/discussion/${messageId}/like`)
  },

  reportArchiveMessage(courseId, archiveId, messageId, payload) {
    return api.post(
      `/reports/courses/${courseId}/archives/${archiveId}/comments/${messageId}`,
      payload
    )
  },

  async openArchiveDiscussionWebSocket(courseId, archiveId) {
    const response = await api.post(
      `/courses/${courseId}/archives/${archiveId}/discussion/ws-ticket`
    )
    const ticket = response?.data?.ticket
    if (typeof ticket !== 'string' || !WS_TICKET_PATTERN.test(ticket)) return null
    const url = buildWebSocketUrl(`/courses/${courseId}/archives/${archiveId}/discussion/ws`, {
      queryParams: { ticket },
    })
    if (!url) return null
    return bindUnauthorizedWebSocket(new WebSocket(url))
  },
}
