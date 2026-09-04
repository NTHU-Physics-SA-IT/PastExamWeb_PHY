import { describe, it, expect, vi, beforeEach } from 'vitest'
import { courseService } from '@/api/services/courses.js'
import { archiveService } from '@/api/services/archives.js'
import { notificationService } from '@/api/services/notifications.js'
import { authService, buildNthuLoginUrl } from '@/api/services/auth.js'
import { memeService } from '@/api/services/meme.js'
import { statisticsService } from '@/api/services/statistics.js'
import { discussionService } from '@/api/services/discussion.js'
import { userService } from '@/api/services/users.js'
import * as adminService from '@/api/services/admin.js'
import { homepageSloganService } from '@/api/services/homepageSlogans.js'

const getMock = vi.hoisted(() => vi.fn())
const postMock = vi.hoisted(() => vi.fn())
const deleteMock = vi.hoisted(() => vi.fn())
const patchMock = vi.hoisted(() => vi.fn())
const putMock = vi.hoisted(() => vi.fn())
const interceptors = vi.hoisted(() => ({
  request: { use: vi.fn() },
  response: { use: vi.fn() },
}))

vi.mock('@/api/services/client', () => ({
  api: {
    get: getMock,
    post: postMock,
    delete: deleteMock,
    patch: patchMock,
    put: putMock,
    interceptors,
    defaults: { baseURL: '/api' },
  },
  bindUnauthorizedWebSocket: (ws) => ws,
  buildWebSocketUrl: (path, { queryParams } = {}) => {
    const url = new URL(`ws://localhost${path}`)
    for (const [key, value] of Object.entries(queryParams || {})) url.searchParams.set(key, value)
    return url.toString()
  },
}))

describe('API service wrappers', () => {
  beforeEach(() => {
    getMock.mockReset()
    postMock.mockReset()
    deleteMock.mockReset()
    patchMock.mockReset()
    putMock.mockReset()
  })

  it('courseService proxies to API client', () => {
    courseService.listPublicCourses()
    expect(getMock).toHaveBeenCalledWith('/courses/public', { params: {} })

    courseService.listPublicCourses(' General Physics ')
    expect(getMock).toHaveBeenCalledWith('/courses/public', {
      params: { search: 'General Physics' },
    })

    courseService.listPublicCategories()
    expect(getMock).toHaveBeenCalledWith('/courses/public/categories')

    courseService.getPublicCourseArchives('course-1')
    expect(getMock).toHaveBeenCalledWith('/courses/public/course-1/archives')

    courseService.listCourses()
    expect(getMock).toHaveBeenCalledWith('/courses', { params: {} })

    courseService.getCourseArchives('course-1')
    expect(getMock).toHaveBeenCalledWith('/courses/course-1/archives')

    courseService.getCourseArchives('course-1', { includeOwnerPending: true })
    expect(getMock).toHaveBeenCalledWith('/courses/course-1/archives', {
      params: { include_owner_pending: true },
    })

    courseService.getAllCourses()
    expect(getMock).toHaveBeenCalledWith('/courses/admin/courses')

    courseService.createCourse({ name: '普通物理' })
    expect(postMock).toHaveBeenCalledWith('/courses/admin/courses', { name: '普通物理' })

    courseService.updateCourse('course-1', { name: 'Updated' })
    expect(putMock).toHaveBeenCalledWith('/courses/admin/courses/course-1', { name: 'Updated' })

    courseService.deleteCourse('course-1')
    expect(deleteMock).toHaveBeenCalledWith('/courses/admin/courses/course-1')
  })

  it('archiveService proxies to API client', () => {
    const formData = new FormData()
    archiveService.uploadArchive(formData)
    expect(postMock).toHaveBeenCalledWith(
      '/archives/upload',
      formData,
      expect.objectContaining({
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 30_000,
      })
    )

    archiveService.getArchivePreviewUrl('course-1', 'arch-1')
    expect(getMock).toHaveBeenCalledWith('/courses/course-1/archives/arch-1/preview')

    archiveService.getArchiveDownloadUrl('course-1', 'arch-1')
    expect(getMock).toHaveBeenCalledWith('/courses/course-1/archives/arch-1/download')

    archiveService.downloadArchiveBackup()
    expect(getMock).toHaveBeenCalledWith('/backups/admin/archive', {
      responseType: 'blob',
      timeout: 0,
    })

    archiveService.deleteArchive('course-1', 'arch-1')
    expect(deleteMock).toHaveBeenCalledWith('/courses/course-1/archives/arch-1')

    archiveService.getOwnerPendingPreviewFile(41)
    expect(getMock).toHaveBeenCalledWith('/archives/submissions/41/pending/preview-file', {
      responseType: 'blob',
    })

    archiveService.withdrawOwnerPendingSubmission(41)
    expect(postMock).toHaveBeenCalledWith('/archives/submissions/41/withdraw')

    const replacementFile = new File(['pdf'], 'replacement.pdf', { type: 'application/pdf' })
    archiveService.editOwnerPendingSubmission(41, {
      course_id: 9,
      professor: 'Prof. Lin',
      academic_year: 1141,
      archive_type: 'midterm',
      sequence: 2,
      has_answers: true,
      owner_id: 999,
      status: 'approved',
      object_name: 'forbidden.pdf',
      file: replacementFile,
    })
    const [, pendingEditBody, pendingEditConfig] = patchMock.mock.calls.at(-1)
    expect(patchMock.mock.calls.at(-1)[0]).toBe('/archives/submissions/41/pending')
    expect(Object.fromEntries(pendingEditBody.entries())).toEqual({
      course_id: '9',
      professor: 'Prof. Lin',
      academic_year: '1141',
      archive_type: 'midterm',
      sequence: '2',
      has_answers: 'true',
      file: replacementFile,
    })
    expect(pendingEditConfig).toEqual({
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 30_000,
    })

    archiveService.updateArchive('course-1', 'arch-1', { name: 'Exam' })
    expect(patchMock).toHaveBeenCalledWith(
      '/courses/course-1/archives/arch-1',
      expect.any(FormData)
    )

    archiveService.updateArchiveCourse('course-1', 'arch-1', 'course-2')
    expect(patchMock).toHaveBeenCalledWith('/courses/course-1/archives/arch-1/course', {
      course_id: 'course-2',
    })

    archiveService.updateArchiveCourseByCategoryAndName('course-1', 'arch-1', 'Linear', 'freshman')
    expect(patchMock).toHaveBeenCalledWith('/courses/course-1/archives/arch-1/course', {
      course_name: 'Linear',
      course_category: 'freshman',
    })

    archiveService.getSubmissionStatistics('24h', 'time')
    expect(getMock).toHaveBeenCalledWith('/archives/admin/submission-statistics', {
      params: { range: '24h', mode: 'time' },
    })
  })

  it('archive review requests include status and backend revision preconditions', () => {
    archiveService.approveSubmission(101, 'pending', 'asr-v1:approve', 'approve note')
    expect(postMock).toHaveBeenLastCalledWith('/archives/admin/submissions/101/approve', {
      note: 'approve note',
      expected_status: 'pending',
      expected_revision: 'asr-v1:approve',
    })

    archiveService.rejectSubmission(102, 'approved', 'asr-v1:reject', 'reject note')
    expect(postMock).toHaveBeenLastCalledWith('/archives/admin/submissions/102/reject', {
      note: 'reject note',
      expected_status: 'approved',
      expected_revision: 'asr-v1:reject',
    })

    archiveService.takedownSubmission(103, 'pending', 'takedown note')
    expect(postMock).toHaveBeenLastCalledWith('/archives/admin/submissions/103/takedown', {
      note: 'takedown note',
      expected_status: 'pending',
    })

    archiveService.republishSubmission(104, 'takedown', 'republish note')
    expect(postMock).toHaveBeenLastCalledWith('/archives/admin/submissions/104/republish', {
      note: 'republish note',
      expected_status: 'takedown',
    })
  })

  it('archive submission preview sends the backend revision precondition', () => {
    archiveService.getSubmissionPreviewFile(105, 'asr-v1:preview')
    expect(getMock).toHaveBeenLastCalledWith('/archives/admin/submissions/105/preview-file', {
      params: { expected_revision: 'asr-v1:preview' },
      responseType: 'blob',
    })
  })

  it('archive review requests fail closed before transport when status is missing', () => {
    expect(() => archiveService.approveSubmission(101, null)).toThrow(
      'Archive submission status is required'
    )
    expect(() => archiveService.rejectSubmission(102, '')).toThrow(
      'Archive submission status is required'
    )
    expect(() => archiveService.takedownSubmission(103, 'unknown')).toThrow(
      'Archive submission status is required'
    )
    expect(() => archiveService.republishSubmission(104)).toThrow(
      'Archive submission status is required'
    )
    expect(postMock).not.toHaveBeenCalled()
  })

  it('notification service proxies', () => {
    notificationService.getActive()
    expect(getMock).toHaveBeenCalledWith('/notifications/active')

    notificationService.getAll()
    expect(getMock).toHaveBeenCalledWith('/notifications')

    notificationService.getAllAdmin()
    expect(getMock).toHaveBeenCalledWith('/notifications/admin/notifications')

    notificationService.create({ title: 'New' })
    expect(postMock).toHaveBeenCalledWith('/notifications/admin/notifications', { title: 'New' })

    notificationService.update(1, { title: 'Updated' })
    expect(putMock).toHaveBeenCalledWith('/notifications/admin/notifications/1', {
      title: 'Updated',
    })

    notificationService.remove(1)
    expect(deleteMock).toHaveBeenCalledWith('/notifications/admin/notifications/1')

    notificationService.deletePersonal(7)
    expect(deleteMock).toHaveBeenCalledWith('/notifications/personal/7')

    notificationService.deleteAllPersonal()
    expect(deleteMock).toHaveBeenCalledWith('/notifications/personal')
  })

  it('homepage slogan service keeps public, user, and admin routes distinct', () => {
    homepageSloganService.getSelected()
    expect(getMock).toHaveBeenCalledWith('/homepage-slogans/selected')
    homepageSloganService.submit('A slogan')
    expect(postMock).toHaveBeenCalledWith('/homepage-slogans', { content: 'A slogan' })
    homepageSloganService.listAdmin({ status: 'pending' })
    expect(getMock).toHaveBeenCalledWith('/homepage-slogans/admin', {
      params: { status: 'pending' },
    })
    homepageSloganService.updateAdmin(4, {
      status: 'enabled',
      occurrence_level: 'normal',
    })
    expect(patchMock).toHaveBeenCalledWith('/homepage-slogans/admin/4', {
      status: 'enabled',
      occurrence_level: 'normal',
    })
    homepageSloganService.removeAdmin(4)
    expect(deleteMock).toHaveBeenCalledWith('/homepage-slogans/admin/4')
  })

  it('auth service proxies', async () => {
    postMock.mockResolvedValueOnce({ data: { token: 'abc' } })
    const data = await authService.localLogin('user', 'pass')
    expect(postMock).toHaveBeenCalledWith('/auth/login', expect.any(FormData))
    expect(data).toEqual({ token: 'abc' })

    postMock.mockResolvedValueOnce({ data: { access_token: 'application-jwt' } })
    await expect(authService.exchangeNthuCode('one-time-code')).resolves.toEqual({
      access_token: 'application-jwt',
    })
    expect(postMock).toHaveBeenCalledWith('/auth/nthu/exchange', {
      code: 'one-time-code',
    })
    expect(buildNthuLoginUrl()).toBe('/api/auth/nthu/login')

    authService.logout()
    expect(postMock).toHaveBeenCalledWith('/auth/logout')
  })

  it('meme service proxies', () => {
    memeService.getRandomMeme()
    expect(getMock).toHaveBeenCalledWith('/meme')
  })

  it('statistics service handles success and error', async () => {
    const response = { data: { count: 1 } }
    getMock.mockResolvedValueOnce(response)
    await expect(statisticsService.getSystemStatistics()).resolves.toBe(response)

    const error = new Error('fail')
    getMock.mockRejectedValueOnce(error)
    await expect(statisticsService.getSystemStatistics()).rejects.toThrow('fail')
  })

  it('discussion service proxies and exchanges REST auth for a WebSocket ticket', async () => {
    const firstTicket = 'a'.repeat(43)
    const secondTicket = 'b'.repeat(43)
    discussionService.listArchiveMessages('course-1', 'arch-1')
    expect(getMock).toHaveBeenCalledWith('/courses/course-1/archives/arch-1/discussion/messages', {
      params: { limit: 50, before_id: undefined },
    })

    discussionService.deleteArchiveMessage('course-1', 'arch-1', 123)
    expect(deleteMock).toHaveBeenCalledWith('/courses/course-1/archives/arch-1/discussion/123')

    discussionService.likeArchiveMessage('course-1', 'arch-1', 123)
    expect(putMock).toHaveBeenCalledWith('/courses/course-1/archives/arch-1/discussion/123/like')

    discussionService.unlikeArchiveMessage('course-1', 'arch-1', 123)
    expect(deleteMock).toHaveBeenCalledWith('/courses/course-1/archives/arch-1/discussion/123/like')

    const originalWebSocket = globalThis.WebSocket
    const webSocketMock = vi.fn(function WebSocket(url) {
      return { url }
    })
    globalThis.WebSocket = webSocketMock

    postMock.mockResolvedValueOnce({ data: { ticket: firstTicket, expires_in: 30 } })
    const ws = await discussionService.openArchiveDiscussionWebSocket('course-1', 'arch-1')
    expect(postMock).toHaveBeenCalledWith('/courses/course-1/archives/arch-1/discussion/ws-ticket')
    expect(webSocketMock).toHaveBeenCalledWith(
      expect.stringContaining('/courses/course-1/archives/arch-1/discussion/ws')
    )
    expect(ws.url).toContain('/courses/course-1/archives/arch-1/discussion/ws')
    expect(ws.url).toContain(`ticket=${firstTicket}`)
    expect(ws.url).not.toContain('token=')

    postMock.mockResolvedValueOnce({ data: { ticket: secondTicket, expires_in: 30 } })
    const secondWs = await discussionService.openArchiveDiscussionWebSocket('course-1', 'arch-1')
    expect(secondWs.url).toContain(`ticket=${secondTicket}`)
    expect(secondWs.url).not.toContain(firstTicket)

    postMock.mockResolvedValueOnce({ data: { ticket: 'header.payload.signature' } })
    await expect(
      discussionService.openArchiveDiscussionWebSocket('course-1', 'arch-1')
    ).resolves.toBeNull()

    postMock.mockRejectedValueOnce(new Error('ticket unavailable'))
    await expect(
      discussionService.openArchiveDiscussionWebSocket('course-1', 'arch-1')
    ).rejects.toThrow('ticket unavailable')
    expect(webSocketMock).toHaveBeenCalledTimes(2)

    globalThis.WebSocket = originalWebSocket
  })

  it('user service proxies', () => {
    userService.getMe()
    expect(getMock).toHaveBeenCalledWith('/users/me')

    userService.updateMyNickname('Nick')
    expect(patchMock).toHaveBeenCalledWith('/users/me/nickname', { nickname: 'Nick' })
  })

  it('admin service exports call API client', () => {
    adminService.getCourses()
    expect(getMock).toHaveBeenCalledWith('/courses/admin/courses')

    adminService.createCourse({ name: 'New' })
    expect(postMock).toHaveBeenCalledWith('/courses/admin/courses', { name: 'New' })

    adminService.updateCourse(1, { name: 'Updated' })
    expect(putMock).toHaveBeenCalledWith('/courses/admin/courses/1', { name: 'Updated' })

    adminService.deleteCourse(1)
    expect(deleteMock).toHaveBeenCalledWith('/courses/admin/courses/1')

    adminService.getUsers()
    expect(getMock).toHaveBeenCalledWith('/users/admin/users')

    adminService.getOnlineStatistics('24h')
    expect(getMock).toHaveBeenCalledWith('/users/admin/online-statistics', {
      params: { range: '24h' },
    })

    const signal = new AbortController().signal
    adminService.getUserOnlineDuration(2, {
      mode: 'hourly',
      date: '2026-07-15',
      signal,
    })
    expect(getMock).toHaveBeenCalledWith('/users/admin/users/2/online-duration', {
      signal,
      params: { mode: 'hourly', date: '2026-07-15' },
    })

    adminService.getUserOnlineDuration(2, { mode: 'daily', days: 90 })
    expect(getMock).toHaveBeenCalledWith('/users/admin/users/2/online-duration', {
      signal: undefined,
      params: { mode: 'daily', days: 90 },
    })

    adminService.createUser({ name: 'Alice' })
    expect(postMock).toHaveBeenCalledWith('/users/admin/users', { name: 'Alice' })

    adminService.updateUser(2, { name: 'Bob' })
    expect(putMock).toHaveBeenCalledWith('/users/admin/users/2', { name: 'Bob' })

    adminService.deleteUser(2)
    expect(deleteMock).toHaveBeenCalledWith('/users/admin/users/2')
  })
})
