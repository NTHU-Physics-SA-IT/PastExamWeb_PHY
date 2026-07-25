import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { shallowMount, flushPromises } from '@vue/test-utils'
import AdminView from '@/views/Admin.vue'
import { applyFontSizePreference } from '@/utils/fontSizePreference'

const adminViewSource = readFileSync(
  resolve(globalThis.process.cwd(), 'src/views/Admin.vue'),
  'utf8'
)
const adminTemplateSource = adminViewSource.split('<script setup>')[0]

const sampleCourses = [
  { id: 1, name: '普通物理', category: 'junior' },
  { id: 2, name: '電磁學', category: 'freshman' },
]

const sampleUsers = [
  { id: 1, name: 'Alice', email: 'alice@example.com', is_admin: true, is_local: true },
  { id: 2, name: 'Bob', email: 'bob@example.com', is_admin: false, is_local: false },
]

const now = new Date()
const onlineRangeConfig = {
  '24h': [10, 144],
  '48h': [20, 144],
  '72h': [30, 144],
  '7d': [240, 42],
  '30d': [720, 60],
  '90d': [1440, 90],
}
const makeOnlineStatistics = (range = '24h', counts = {}) => {
  const [bucketMinutes, bucketCount] = onlineRangeConfig[range]
  const end = new Date(now)
  end.setMinutes(0, 0, 0)
  const points = Array.from({ length: bucketCount }, (_, index) => {
    const start = new Date(end.getTime() - (bucketCount - index) * bucketMinutes * 60_000)
    const bucketEnd = new Date(start.getTime() + bucketMinutes * 60_000)
    return {
      start: start.toISOString(),
      end: bucketEnd.toISOString(),
      at: index === bucketCount - 1 ? end.toISOString() : bucketEnd.toISOString(),
      count: counts[index] ?? 0,
      has_data: true,
    }
  })
  const values = points.map(({ count }) => count)
  return {
    range,
    bucket_minutes: bucketMinutes,
    timezone: 'UTC',
    online_timeout_seconds: 300,
    current_online: values.at(-1) ?? 0,
    peak_online: Math.max(0, ...values),
    average_online: values.reduce((sum, value) => sum + value, 0) / values.length,
    history_started_at: points[0].start,
    points,
  }
}
const makeSubmissionStatistics = (range = '24h', counts = {}) => {
  const [bucketMinutes, bucketCount] = onlineRangeConfig[range]
  const mode = range.endsWith('h') ? 'time' : 'date'
  const currentStart = new Date(now)
  currentStart.setUTCMinutes(
    Math.floor(currentStart.getUTCMinutes() / bucketMinutes) * bucketMinutes,
    0,
    0
  )
  const firstStart = new Date(currentStart.getTime() - (bucketCount - 1) * bucketMinutes * 60_000)
  const points = Array.from({ length: bucketCount }, (_, index) => {
    const start = new Date(firstStart.getTime() + index * bucketMinutes * 60_000)
    return {
      start: start.toISOString(),
      end: new Date(start.getTime() + bucketMinutes * 60_000).toISOString(),
      count: counts[index] ?? 0,
    }
  })
  const values = points.map(({ count }) => count)
  const total = values.reduce((sum, value) => sum + value, 0)
  return {
    mode,
    range,
    timezone: 'Asia/Taipei',
    bucket_minutes: bucketMinutes,
    range_start: points[0].start,
    range_end: points.at(-1).end,
    summary: {
      total,
      peak: Math.max(0, ...values),
      average: Number((total / bucketCount).toFixed(1)),
    },
    points,
  }
}
const sampleNotifications = [
  {
    id: 1,
    title: '維護通知',
    body: '系統維護中',
    severity: 'info',
    is_active: true,
    starts_at: new Date(now.getTime() - 3600_000).toISOString(),
    ends_at: new Date(now.getTime() + 3600_000).toISOString(),
    created_at: now.toISOString(),
    updated_by_username: 'admin',
  },
  {
    id: 2,
    title: '過期公告',
    body: '過期',
    severity: 'danger',
    is_active: true,
    starts_at: new Date(now.getTime() - 7200_000).toISOString(),
    ends_at: new Date(now.getTime() - 3600_000).toISOString(),
    created_at: new Date(now.getTime() - 86400_000).toISOString(),
  },
]

const getCoursesMock = vi.hoisted(() => vi.fn())
const createCourseMock = vi.hoisted(() => vi.fn())
const updateCourseMock = vi.hoisted(() => vi.fn())
const deleteCourseMock = vi.hoisted(() => vi.fn())
const listAdminCategoriesMock = vi.hoisted(() => vi.fn())
const getAllCoursesMock = vi.hoisted(() => vi.fn())

const getUsersMock = vi.hoisted(() => vi.fn())
const getOnlineStatisticsMock = vi.hoisted(() => vi.fn())
const getUserSubmissionStatsMock = vi.hoisted(() => vi.fn())
const getUserOnlineDurationMock = vi.hoisted(() => vi.fn())
const createUserMock = vi.hoisted(() => vi.fn())
const updateUserMock = vi.hoisted(() => vi.fn())
const deleteUserMock = vi.hoisted(() => vi.fn())

const notificationGetAllMock = vi.hoisted(() => vi.fn())
const notificationCreateMock = vi.hoisted(() => vi.fn())
const notificationUpdateMock = vi.hoisted(() => vi.fn())
const notificationRemoveMock = vi.hoisted(() => vi.fn())
const listAdminSubmissionsMock = vi.hoisted(() => vi.fn())
const getSubmissionStatisticsMock = vi.hoisted(() => vi.fn())

const trackEventMock = vi.hoisted(() => vi.fn())
const isUnauthorizedErrorMock = vi.hoisted(() => vi.fn(() => false))

const confirmRequireMock = vi.hoisted(() => vi.fn((options) => options.accept && options.accept()))
const toastAddMock = vi.hoisted(() => vi.fn())

vi.mock('primevue/useconfirm', () => ({
  useConfirm: () => ({
    require: confirmRequireMock,
  }),
}))

vi.mock('primevue/usetoast', () => ({
  useToast: () => ({
    add: toastAddMock,
  }),
}))

vi.mock('@/utils/auth', () => ({
  getCurrentUser: () => ({ id: 99 }),
}))

vi.mock('@/utils/http', () => ({
  isUnauthorizedError: isUnauthorizedErrorMock,
}))

vi.mock('@/utils/analytics', () => ({
  trackEvent: trackEventMock,
  EVENTS: {
    CREATE_COURSE: 'create-course',
    UPDATE_COURSE: 'update-course',
    DELETE_COURSE: 'delete-course',
    CREATE_USER: 'create-user',
    UPDATE_USER: 'update-user',
    DELETE_USER: 'delete-user',
    CREATE_NOTIFICATION: 'create-notification',
    UPDATE_NOTIFICATION: 'update-notification',
    DELETE_NOTIFICATION: 'delete-notification',
    SWITCH_TAB: 'switch-tab',
  },
}))

vi.mock('@/api', () => ({
  getCourses: getCoursesMock,
  createCourse: createCourseMock,
  updateCourse: updateCourseMock,
  deleteCourse: deleteCourseMock,
  getUsers: getUsersMock,
  getOnlineStatistics: getOnlineStatisticsMock,
  getUserSubmissionStats: getUserSubmissionStatsMock,
  getUserOnlineDuration: getUserOnlineDurationMock,
  createUser: createUserMock,
  updateUser: updateUserMock,
  deleteUser: deleteUserMock,
  notificationService: {
    getAllAdmin: notificationGetAllMock,
    create: notificationCreateMock,
    update: notificationUpdateMock,
    remove: notificationRemoveMock,
  },
  courseService: {
    listAdminCategories: listAdminCategoriesMock,
    getAllCourses: getAllCoursesMock,
  },
  archiveService: {
    listAdminSubmissions: listAdminSubmissionsMock,
    getSubmissionStatistics: getSubmissionStatisticsMock,
  },
}))

function createWrapper() {
  return shallowMount(AdminView)
}

let consoleErrorSpy

describe('AdminView', () => {
  beforeEach(() => {
    consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    vi.useFakeTimers()
    vi.setSystemTime(now)
    getCoursesMock.mockResolvedValue({ data: sampleCourses })
    listAdminCategoriesMock.mockResolvedValue({
      data: [{ id: 1, key: 'freshman', name: '基礎必修', label: '基礎', is_active: true }],
    })
    getAllCoursesMock.mockResolvedValue({ data: sampleCourses })
    createCourseMock.mockResolvedValue()
    updateCourseMock.mockResolvedValue()
    deleteCourseMock.mockResolvedValue()

    getUsersMock.mockResolvedValue({ data: sampleUsers })
    getOnlineStatisticsMock.mockImplementation((range) => {
      const bucketCount = onlineRangeConfig[range][1]
      return Promise.resolve({ data: makeOnlineStatistics(range, { [bucketCount - 1]: 2 }) })
    })
    createUserMock.mockResolvedValue()
    updateUserMock.mockResolvedValue()
    deleteUserMock.mockResolvedValue()

    notificationGetAllMock.mockResolvedValue({ data: sampleNotifications })
    notificationCreateMock.mockResolvedValue()
    notificationUpdateMock.mockResolvedValue()
    notificationRemoveMock.mockResolvedValue()
    listAdminSubmissionsMock.mockResolvedValue({ data: [] })
    getSubmissionStatisticsMock.mockImplementation((range) =>
      Promise.resolve({ data: makeSubmissionStatistics(range, { 0: 2, 1: 1 }) })
    )

    trackEventMock.mockReset()
    toastAddMock.mockReset()
    confirmRequireMock.mockClear()
    isUnauthorizedErrorMock.mockReturnValue(false)

    if (!globalThis.localStorage) {
      const store = new Map()
      globalThis.localStorage = {
        getItem: vi.fn((key) => store.get(key) ?? null),
        setItem: vi.fn((key, value) => store.set(key, String(value))),
        removeItem: vi.fn((key) => store.delete(key)),
        clear: vi.fn(() => store.clear()),
      }
    }
    globalThis.localStorage?.clear?.()
  })

  afterEach(() => {
    consoleErrorSpy?.mockRestore()
    vi.useRealTimers()
    vi.resetModules()
  })

  it('loads data and handles admin actions', async () => {
    const wrapper = createWrapper()

    await flushPromises()

    expect(listAdminCategoriesMock).toHaveBeenCalled()
    expect(getAllCoursesMock).toHaveBeenCalled()
    expect(getUsersMock).not.toHaveBeenCalled()
    expect(wrapper.vm.filteredCourses.length).toBe(2)

    await wrapper.vm.handleTabChange('1')
    await wrapper.vm.loadUsers()
    await flushPromises()

    expect(getUsersMock).toHaveBeenCalled()
    expect(wrapper.vm.filteredUsers.length).toBe(2)

    wrapper.vm.openCreateDialog()
    wrapper.vm.courseForm.name = '量子物理'
    wrapper.vm.courseForm.category = 'freshman'
    await wrapper.vm.saveCourse()

    expect(createCourseMock).toHaveBeenCalledWith({
      name: '量子物理',
      category: 'freshman',
    })
    expect(trackEventMock).toHaveBeenCalledWith('create-course', expect.any(Object))

    wrapper.vm.openEditDialog(sampleCourses[0])
    wrapper.vm.courseForm.name = '普通物理進階'
    await wrapper.vm.saveCourse()
    expect(updateCourseMock).toHaveBeenCalled()

    wrapper.vm.confirmDeleteCourse(sampleCourses[0])
    expect(deleteCourseMock).toHaveBeenCalledWith(sampleCourses[0].id)

    wrapper.vm.openCreateUserDialog()
    wrapper.vm.userForm.name = 'Charlie'
    wrapper.vm.userForm.email = 'charlie@example.com'
    wrapper.vm.userForm.password = 'secret'
    wrapper.vm.userForm.is_admin = true
    await wrapper.vm.saveUser()
    expect(createUserMock).toHaveBeenCalledWith({
      name: 'Charlie',
      email: 'charlie@example.com',
      password: 'secret',
      is_admin: true,
    })

    wrapper.vm.openEditUserDialog(sampleUsers[1])
    wrapper.vm.userForm.name = 'Bob Updated'
    wrapper.vm.userForm.password = ''
    await wrapper.vm.saveUser()
    expect(updateUserMock).toHaveBeenCalledWith(sampleUsers[1].id, {
      name: 'Bob Updated',
      email: sampleUsers[1].email,
      is_admin: sampleUsers[1].is_admin,
    })

    wrapper.vm.confirmDeleteUser(sampleUsers[1])
    expect(deleteUserMock).toHaveBeenCalledWith(sampleUsers[1].id)

    wrapper.vm.openNotificationCreateDialog()
    wrapper.vm.notificationForm.title = '新公告'
    wrapper.vm.notificationForm.body = '內容'
    wrapper.vm.notificationForm.starts_at = new Date(now.getTime() - 1000)
    wrapper.vm.notificationForm.ends_at = new Date(now.getTime() + 1000)
    await wrapper.vm.saveNotification()
    expect(notificationCreateMock).toHaveBeenCalled()
    expect(wrapper.vm.notifications.length).toBe(2)
    expect(wrapper.vm.filteredNotifications.length).toBe(2)

    wrapper.vm.openNotificationEditDialog(sampleNotifications[0])
    wrapper.vm.notificationForm.body = '更新內容'
    await wrapper.vm.saveNotification()
    expect(notificationUpdateMock).toHaveBeenCalledWith(
      sampleNotifications[0].id,
      expect.objectContaining({ body: '更新內容' })
    )

    wrapper.vm.confirmDeleteNotification(sampleNotifications[0])
    expect(notificationRemoveMock).toHaveBeenCalledWith(sampleNotifications[0].id)
    expect(notificationGetAllMock).toHaveBeenCalled()

    expect(wrapper.vm.getCategoryName('freshman')).toBe('基礎必修')
    expect(wrapper.vm.getNotificationSeverity('danger')).toBe('danger')
    expect(wrapper.vm.getNotificationSeverityLabel('info')).toBe('一般')
    expect(wrapper.vm.isNotificationEffective(sampleNotifications[0])).toBe(true)
    expect(wrapper.vm.isNotificationEffective(sampleNotifications[1])).toBe(false)
    expect(wrapper.vm.formatAdminActorTime('invalid')).toBe('—')
    expect(wrapper.vm.formatAdminActorTime(now.toISOString())).not.toBe('—')

    wrapper.unmount()
  })

  it('keeps desktop actor-time columns while restoring compact mobile metadata', async () => {
    const wrapper = createWrapper()
    await flushPromises()

    expect(adminViewSource).toContain("toggleReviewSort('new', 'submitted_at')")
    expect(adminViewSource).toContain("toggleReviewSort('existing', 'submitted_at')")
    expect(adminViewSource).toContain("toggleReviewSort('new', 'reviewed_at')")
    expect(adminViewSource).toContain("toggleReviewSort('existing', 'reviewed_at')")
    expect(adminViewSource).toContain("toggleTrashSort('deleted_at')")
    expect(adminViewSource).not.toContain('header="審核人"')
    expect(adminViewSource).not.toContain('header="審核時間"')
    expect(adminViewSource).not.toContain("toggleTrashSort('deleted_by')")
    expect(adminViewSource).not.toContain('<span class="review-mobile-info-label">申請人</span>')
    expect(adminViewSource).not.toContain('<span class="review-mobile-info-label">投稿人</span>')
    expect(adminViewSource.match(/review-mobile-info-label">審核人/g)).toHaveLength(2)
    expect(adminViewSource.match(/review-mobile-info-label">審核時間/g)).toHaveLength(2)
    expect(adminViewSource.match(/label: '刪除者'/g)).toHaveLength(1)
    expect(adminViewSource.match(/label: '刪除時間'/g)).toHaveLength(1)
    expect(adminViewSource).not.toContain('admin-actor-time--mobile')
    expect(adminViewSource).toContain('admin-actor-time--notification')
    expect(adminViewSource).toContain('notification-mobile-update__value')
    expect(adminViewSource).not.toContain('hasNotificationUpdater')
    expect(
      adminTemplateSource.match(/getNotificationUpdaterLabel\((?:data|notification)\)/g)
    ).toHaveLength(6)
    expect(adminViewSource.match(/review-desktop-course-cell/g).length).toBeGreaterThanOrEqual(2)
    expect(
      adminTemplateSource.match(
        /review-desktop-course-cell__name[\s\S]*?review-desktop-course-cell__admin-row/g
      )
    ).toHaveLength(2)
    expect(adminViewSource.match(/admin-desktop-status-tag/g).length).toBeGreaterThanOrEqual(3)
    expect(adminTemplateSource.match(/class="admin-desktop-status-label"/g)).toHaveLength(3)
    expect(adminTemplateSource.match(/'admin-desktop-status-tag'/g)).toHaveLength(3)
    expect(adminViewSource).toContain('Array.from(')
    expect(adminViewSource).not.toContain('writing-mode: vertical-rl')
    expect(adminViewSource).not.toContain('min-inline-size: 4.75rem')
    expect(adminViewSource).toContain('inline-size: fit-content')
    expect(adminViewSource).toContain('@container admin-status-cell (max-width: 3.75rem)')
    expect(adminViewSource).toMatch(
      /admin-desktop-status-label[\s\S]*?flex-direction: row[\s\S]*?@container admin-status-cell[\s\S]*?flex-direction: column/
    )
    expect(adminTemplateSource.match(/class="review-submission-type-cell"/g)).toHaveLength(1)
    expect(adminTemplateSource.match(/'review-desktop-submission-type-tag'/g)).toHaveLength(1)
    expect(adminTemplateSource.match(/class="submission-type-combined-label"/g)).toHaveLength(1)
    expect(adminTemplateSource).toContain('class="submission-type-combined-label__separator"')
    expect(adminTemplateSource).toContain('＋')
    expect(adminViewSource).toContain('@container review-submission-type-cell (max-width: 7.25rem)')
    expect(adminViewSource).toMatch(
      /submission-type-combined-label__separator[\s\S]*?display: none/
    )
    expect(adminViewSource.match(/'review-mobile-card-status-badge'/g)).toHaveLength(2)
    expect(adminTemplateSource.match(/trash-name-column/g)).toHaveLength(2)
    expect(adminViewSource).toContain('width: clamp(14rem, 18vw, 18rem)')
    expect(adminViewSource).toContain('overflow-wrap: anywhere')
    expect(adminTemplateSource).toContain("'trash-name-title__text'")
    expect(adminTemplateSource.match(/class="trash-user-email"/g)).toHaveLength(2)
    expect(
      adminTemplateSource.match(/data\.item_type === 'user' && data\.user_email/g)
    ).toHaveLength(2)
    expect(adminTemplateSource).toContain(':title="data.user_email"')
    expect(adminTemplateSource).not.toContain('{{ data.display_name }} ({{ data.user_email }})')
    expect(adminViewSource).toMatch(
      /\.trash-user-email[\s\S]*?color: var\(--text-secondary\)[\s\S]*?font-size: var\(--app-font-size-sm\)[\s\S]*?overflow-wrap: anywhere/
    )
    expect(adminTemplateSource).toMatch(
      /trash-mobile-card-title-block[\s\S]*?trash-user-email[\s\S]*?trash-mobile-card-badges/
    )
    expect(adminTemplateSource).not.toContain('trash-mobile-card trash-name-column')
    expect(adminTemplateSource.match(/class="trash-tree-prefix"/g)).toHaveLength(2)
    expect(adminTemplateSource).toContain('getTrashNameIndent(data)')
    expect(adminViewSource).toContain('headerClass="trash-dependencies-column"')
    expect(adminViewSource).toContain('width: clamp(17rem, 22vw, 23rem)')
    expect(adminViewSource).toContain("{ label: '系統問題回報', value: 'system_issue_report' }")
    expect(adminViewSource).toContain("{ label: '留言回報', value: 'comment_report' }")
    expect(adminViewSource).toContain("{ label: '考古題回報', value: 'archive_report' }")
    expect(wrapper.vm.trashFilterOptions.map((option) => option.value)).toEqual([
      'archive',
      'archive_submission',
      'course_category',
      'course',
      'notification',
      'user',
      'system_issue_report',
      'comment_report',
      'archive_report',
    ])
    expect(adminViewSource).toContain('永久刪除後無法復原。')
    expect(adminTemplateSource).toContain('getTrashReportDetails(data)')
    expect(
      wrapper.vm.getTrashReportDetails({
        item_type: 'system_issue_report',
        report_type: 'bug',
        reporter_name: '回報者',
        github_issue_number: 123,
      })
    ).toEqual(
      expect.arrayContaining([
        { label: '問題類型', value: '程式錯誤' },
        { label: '回報者', value: '回報者' },
        { label: '說明', value: '本地摘要' },
      ])
    )
    expect(
      wrapper.vm
        .getTrashReportDetails({ item_type: 'system_issue_report', github_issue_number: 123 })
        .some((detail) => detail.label === 'GitHub 連結')
    ).toBe(false)
    expect(wrapper.vm.getTrashStatusLabel('pending', 'comment_report')).toBe('已刪除')
    expect(wrapper.vm.getTrashStatusLabel('upheld', 'comment_report')).toBe('已刪除')
    expect(wrapper.vm.getTrashStatusLabel('dismissed', 'comment_report')).toBe('已刪除')
    expect(wrapper.vm.getTrashStatusLabel('unread', 'system_issue_report')).toBe('已刪除')
    expect(wrapper.vm.getTrashStatusLabel(null, 'archive_report')).toBe('已刪除')
    expect(wrapper.vm.getTrashStatusSeverity('pending', 'comment_report')).toBe('danger')
    expect(wrapper.vm.getTrashStatusSeverity('upheld', 'comment_report')).toBe('danger')
    expect(wrapper.vm.getTrashStatusSeverity('dismissed', 'comment_report')).toBe('danger')
    expect(wrapper.vm.getTrashStatusSeverity('read', 'system_issue_report')).toBe('danger')
    expect(wrapper.vm.getTrashStatusClass('pending', 'comment_report')).toBe(
      'review-status-deleted'
    )
    expect(
      wrapper.vm.getTrashReportDetails({
        item_type: 'comment_report',
        reporter_name: '回報者',
        comment_author_name: '留言者',
        comment_snapshot: '留言摘要',
        course_name: '課程',
        archive_name: '考古題',
      })
    ).toEqual(
      expect.arrayContaining([
        { label: '回報者', value: '回報者' },
        { label: '留言者', value: '留言者' },
        { label: '課程／考古題', value: '課程 · 考古題' },
      ])
    )
    expect(
      wrapper.vm
        .getTrashReportDetails({ item_type: 'comment_report', comment_snapshot: '留言摘要' })
        .some((detail) => detail.label === '留言摘要' || detail.value === '留言摘要')
    ).toBe(false)
    expect(adminTemplateSource.match(/class="trash-mobile-card-footer"/g)).toHaveLength(1)
    expect(adminTemplateSource).toMatch(
      /trash-mobile-card-footer[\s\S]*?trash-mobile-dependencies[\s\S]*?trash-mobile-card-actions/
    )
    expect(adminTemplateSource).not.toContain('trash-mobile-primary-metadata')
    expect(adminTemplateSource).not.toContain('trash-mobile-deletion-metadata')
    expect(adminTemplateSource).toMatch(
      /class="trash-mobile-info-grid"[\s\S]*?v-for="metadata in getTrashMobileMetadata\(data\)"[\s\S]*?trash-mobile-info-item--row-start/
    )
    expect(adminViewSource).toMatch(
      /\.trash-mobile-info-grid\s*\{[^}]*display:\s*grid;[^}]*grid-template-columns:\s*repeat\(2, minmax\(0, 1fr\)\);[^}]*width:\s*100%;[^}]*min-width:\s*0;/
    )
    expect(adminViewSource).toMatch(
      /@media \(min-width: 900px\) and \(max-width: 1399px\)[\s\S]*?\.trash-mobile-info-grid\s*\{[^}]*grid-template-columns:\s*repeat\(3, minmax\(0, 1fr\)\);/
    )
    expect(adminViewSource).toMatch(
      /@media \(min-width: 900px\) and \(max-width: 1399px\)[\s\S]*?\.trash-mobile-info-item--row-start\s*\{[^}]*grid-column:\s*1;/
    )
    expect(adminViewSource).toMatch(
      /@media \(max-width: 360px\)[\s\S]*?\.trash-mobile-info-grid\s*\{[^}]*grid-template-columns:\s*1fr;/
    )
    expect(adminTemplateSource).not.toMatch(/trash-mobile-info-(?:item|placeholder)[^>]*hidden/)
    const archiveSubmissionMetadata = wrapper.vm.getTrashMobileMetadata({
      item_type: 'archive_submission',
      id: 64,
      academic_term: '114上學期',
      course_name: '量子力學測試課程',
      deleted_by_name: 'admin',
      deleted_at: '2026-07-04T08:07:00Z',
    })
    expect(archiveSubmissionMetadata.map((item) => item.label)).toEqual([
      '投稿編號',
      '學期',
      '課程',
      '刪除者',
      '刪除時間',
    ])
    expect(archiveSubmissionMetadata[2]).toMatchObject({
      label: '課程',
      startNewRow: true,
    })
    const registeredTrashTypes = wrapper.vm.trashFilterOptions.map((option) => option.value)
    for (const itemType of registeredTrashTypes) {
      const labels = wrapper.vm
        .getTrashMobileMetadata({ item_type: itemType })
        .map((item) => item.label)
      expect(labels.slice(-2)).toEqual(['刪除者', '刪除時間'])
    }
    expect(adminViewSource).toMatch(
      /\.trash-mobile-card-footer\s*\{[\s\S]*?border-top:\s*1px solid color-mix/
    )
    expect(adminViewSource).toContain('.trash-mobile-card.trash-row--relation-group-even')
    expect(adminViewSource).toContain('.trash-mobile-card.trash-row--relation-group-odd')

    expect(wrapper.vm.getReviewRequesterLabel({ requester_name: '申請者' })).toBe('申請者')
    expect(wrapper.vm.getReviewRequesterLabel({})).toBe('—')
    expect(wrapper.vm.getReviewReviewerDisplay({})).toBe('尚未審核')
    expect(
      wrapper.vm.getReviewReviewerDisplay({
        reviewer_name: '管理員',
        reviewed_at: '2026-07-20T05:32:00Z',
      })
    ).toBe('管理員')
    expect(wrapper.vm.getNotificationUpdaterLabel({})).toBe('—')
    expect(wrapper.vm.getNotificationUpdaterLabel({ updated_by_username: 'editor' })).toBe('editor')
    expect(wrapper.vm.getTrashDeletedByLabel({ deleted_by_name: '刪除管理員 A' })).toBe(
      '刪除管理員 A'
    )
    expect(wrapper.vm.getTrashDeletedByLabel({})).toBe('—')
    const actorTime = wrapper.vm.formatAdminActorTime('2020-07-20T05:32:00Z')
    expect(actorTime).toBe('2020/07/20 13:32')
    expect(actorTime).not.toMatch(/上午|下午/)
    expect(
      wrapper.vm.formatAdminActorTime(new Date(now.getTime() - 5 * 60_000).toISOString())
    ).toBe('5 分鐘前')

    const reviewRows = [
      {
        id: 2,
        created_at: '2026-07-20T02:00:00Z',
        reviewed_at: '2026-07-20T04:00:00Z',
      },
      {
        id: 1,
        created_at: '2026-07-20T01:00:00Z',
        reviewed_at: '2026-07-20T03:00:00Z',
      },
      { id: 3, created_at: '2026-07-20T03:00:00Z', reviewed_at: null },
    ]
    wrapper.vm.toggleReviewSort('new', 'submitted_at')
    expect(wrapper.vm.sortArchiveReviewItems(reviewRows, 'new').map(({ id }) => id)).toEqual([
      1, 2, 3,
    ])
    wrapper.vm.toggleReviewSort('new', 'reviewed_at')
    expect(wrapper.vm.sortArchiveReviewItems(reviewRows, 'new').map(({ id }) => id)).toEqual([
      1, 2, 3,
    ])

    wrapper.vm.toggleTrashSort('deleted_at')
    expect(
      wrapper.vm
        .sortTrashItems([
          { id: 2, deleted_at: '2026-07-20T02:00:00Z' },
          { id: 1, deleted_at: '2026-07-20T01:00:00Z' },
        ])
        .map(({ id }) => id)
    ).toEqual([1, 2])

    wrapper.unmount()
  })

  it('validates forms and handles failure branches', async () => {
    const wrapper = createWrapper()

    await flushPromises()

    createCourseMock.mockClear()
    createUserMock.mockClear()
    notificationCreateMock.mockClear()
    toastAddMock.mockClear()

    wrapper.vm.openCreateDialog()
    wrapper.vm.courseForm.name = '   '
    wrapper.vm.courseForm.category = ''
    await wrapper.vm.saveCourse()
    expect(createCourseMock).not.toHaveBeenCalled()
    expect(wrapper.vm.courseFormErrors).toMatchObject({
      name: '課程名稱是必填欄位',
      category: '分類是必填欄位',
    })

    wrapper.vm.openCreateUserDialog()
    wrapper.vm.userForm.name = ' '
    wrapper.vm.userForm.email = 'invalid-email'
    wrapper.vm.userForm.password = ''
    await wrapper.vm.saveUser()
    expect(createUserMock).not.toHaveBeenCalled()
    expect(wrapper.vm.userFormErrors).toMatchObject({
      name: '使用者名稱是必填欄位',
      email: '電子郵件格式不正確',
      password: '密碼是必填欄位',
    })

    wrapper.vm.openNotificationCreateDialog()
    wrapper.vm.notificationForm.title = ' '
    wrapper.vm.notificationForm.body = ''
    wrapper.vm.notificationForm.starts_at = new Date(now.getTime() + 10_000)
    wrapper.vm.notificationForm.ends_at = new Date(now.getTime() - 10_000)
    await wrapper.vm.saveNotification()
    expect(notificationCreateMock).not.toHaveBeenCalled()
    expect(wrapper.vm.notificationFormErrors).toMatchObject({
      title: '公告標題是必填欄位',
      body: '公告內容是必填欄位',
      ends_at: '結束時間需晚於生效時間',
    })

    toastAddMock.mockClear()
    isUnauthorizedErrorMock.mockReturnValueOnce(true)
    getAllCoursesMock.mockRejectedValueOnce(new Error('unauthorized'))
    await wrapper.vm.loadCourses()
    expect(toastAddMock).not.toHaveBeenCalled()
    expect(wrapper.vm.courseLoadError).toContain('登入階段已過期')

    isUnauthorizedErrorMock.mockReturnValue(false)
    getAllCoursesMock.mockResolvedValueOnce({ data: { courses: sampleCourses } })
    await wrapper.vm.loadCourses()
    expect(wrapper.vm.courseLoadError).toContain('課程資料載入失敗')
    expect(toastAddMock).toHaveBeenCalledWith(expect.objectContaining({ detail: '載入課程失敗' }))

    toastAddMock.mockClear()
    isUnauthorizedErrorMock.mockReturnValueOnce(false)
    getUsersMock.mockRejectedValueOnce(new Error('boom'))
    await wrapper.vm.loadUsers()
    expect(toastAddMock).toHaveBeenCalledWith(expect.objectContaining({ detail: '載入使用者失敗' }))
    expect(wrapper.vm.userStatsLoadError).toContain('使用者統計載入失敗')

    toastAddMock.mockClear()
    getUsersMock.mockResolvedValueOnce({ data: { users: sampleUsers } })
    await wrapper.vm.loadUsers()
    expect(wrapper.vm.userStatsLoadError).toContain('使用者統計載入失敗')
    expect(toastAddMock).toHaveBeenCalledWith(expect.objectContaining({ detail: '載入使用者失敗' }))

    toastAddMock.mockClear()
    isUnauthorizedErrorMock.mockReturnValueOnce(true)
    getUsersMock.mockRejectedValueOnce(new Error('unauthorized'))
    await wrapper.vm.loadUsers()
    expect(wrapper.vm.userStatsLoadError).toContain('登入階段已過期')
    expect(toastAddMock).not.toHaveBeenCalled()

    isUnauthorizedErrorMock.mockReturnValue(false)
    getUsersMock.mockResolvedValueOnce({ data: sampleUsers })
    await wrapper.vm.loadUsers()
    expect(wrapper.vm.userStatsLoadError).toBe('')

    toastAddMock.mockClear()
    isUnauthorizedErrorMock.mockReturnValueOnce(false)
    notificationGetAllMock.mockRejectedValueOnce(new Error('fail'))
    await wrapper.vm.loadNotifications()
    expect(toastAddMock).toHaveBeenCalledWith(expect.objectContaining({ detail: '載入公告失敗' }))

    expect(wrapper.vm.formatAdminActorTime(null)).toBe('—')
    expect(wrapper.vm.formatDateTime(null)).toBe('從未登入')
    expect(wrapper.vm.formatDateTime(new Date(now.getTime() - 30_000).toISOString())).toBe('剛剛')
    expect(wrapper.vm.formatDateTime(new Date(now.getTime() - 10 * 60_000).toISOString())).toBe(
      '10 分鐘前'
    )
    expect(wrapper.vm.formatDateTime(new Date(now.getTime() - 2 * 60 * 60_000).toISOString())).toBe(
      '2 小時前'
    )
    expect(
      wrapper.vm.formatDateTime(new Date(now.getTime() - 24 * 60 * 60_000).toISOString())
    ).toBe('昨天')
    expect(
      wrapper.vm.formatDateTime(new Date(now.getTime() - 3 * 24 * 60 * 60_000).toISOString())
    ).toBe('3 天前')
    expect(
      wrapper.vm.formatDateTime(new Date(now.getTime() - 10 * 24 * 60 * 60_000).toISOString())
    ).toMatch(/\d{4}\//)

    notificationGetAllMock.mockReset()
    notificationGetAllMock.mockResolvedValue({ data: sampleNotifications })
    trackEventMock.mockClear()

    wrapper.vm.notifications = []
    await wrapper.vm.handleTabChange('2')

    expect(localStorage.getItem('admin-current-tab')).toBe('2')
    expect(trackEventMock).toHaveBeenCalledWith(
      'switch-tab',
      expect.objectContaining({ tab: 'notifications' })
    )

    await flushPromises()
    expect(notificationGetAllMock).toHaveBeenCalledTimes(1)

    wrapper.unmount()
  })

  it('maps online statistics for every supported range', async () => {
    const wrapper = createWrapper()
    await flushPromises()
    wrapper.vm.userInsightsView = 'login-hour'

    const hourRanges = [
      [24, 144, 10, '統計最近 24 小時內，每 10 分鐘取樣一次的同時在線使用者人數。'],
      [48, 144, 20, '統計最近 48 小時內，每 20 分鐘取樣一次的同時在線使用者人數。'],
      [72, 144, 30, '統計最近 72 小時內，每 30 分鐘取樣一次的同時在線使用者人數。'],
    ]
    for (const [range, bucketCount, bucketMinutes, description] of hourRanges) {
      wrapper.vm.setActiveLoginRange(range)
      await flushPromises()
      expect(wrapper.vm.loginChartData.buckets).toHaveLength(bucketCount)
      expect(wrapper.vm.loginChartData.labels).toHaveLength(bucketCount)
      expect(wrapper.vm.loginChartData.counts).toHaveLength(bucketCount)
      expect(wrapper.vm.loginChartData.bucketMinutes).toBe(bucketMinutes)
      expect(wrapper.vm.loginDistributionDescription).toBe(description)
      const nonZeroBuckets = wrapper.vm.loginChartData.buckets.filter(({ count }) => count > 0)
      expect(nonZeroBuckets).toHaveLength(1)
      expect(nonZeroBuckets[0].count).toBe(2)
      expect(wrapper.vm.onlineStatisticsSummary).toMatchObject({ current: 2, peak: 2 })
      expect(wrapper.vm.loginChartData.buckets[0].showLabel).toBe(true)
      expect(wrapper.vm.loginChartData.buckets.at(-1).showLabel).toBe(true)
      expect(wrapper.vm.loginChartData.buckets[0].labelLines).toBeInstanceOf(Array)
      expect(wrapper.vm.loginChartData.buckets.at(-1).labelLines).toBeInstanceOf(Array)
      const midnightBucket = wrapper.vm.loginChartData.buckets.find(
        ({ isMultiline }) => isMultiline
      )
      expect(midnightBucket?.labelLines[0]).toBe('00 時')
      expect(midnightBucket?.labelLines[1]).toMatch(/^\d{2}\/\d{2}$/)
      expect(nonZeroBuckets[0].fullLabel).toContain('取樣')
    }

    wrapper.vm.userInsightsView = 'login-date'
    await wrapper.vm.$nextTick()
    const dateRanges = [
      [7, 42, 4 * 60, '統計最近 7 日內，每 4 小時取樣一次的同時在線使用者人數。'],
      [30, 60, 12 * 60, '統計最近 30 日內，每 12 小時取樣一次的同時在線使用者人數。'],
      [90, 90, 24 * 60, '統計最近 90 日內，每日取樣一次的同時在線使用者人數。'],
    ]
    for (const [range, bucketCount, bucketMinutes, description] of dateRanges) {
      wrapper.vm.setActiveLoginRange(range)
      await flushPromises()
      expect(wrapper.vm.loginChartData.buckets).toHaveLength(bucketCount)
      expect(wrapper.vm.loginChartData.labels).toHaveLength(bucketCount)
      expect(wrapper.vm.loginChartData.counts).toHaveLength(bucketCount)
      expect(wrapper.vm.loginChartData.bucketMinutes).toBe(bucketMinutes)
      expect(wrapper.vm.loginDistributionDescription).toBe(description)
      expect(wrapper.vm.loginChartData.buckets[0].showLabel).toBe(true)
      expect(wrapper.vm.loginChartData.buckets.at(-1).showLabel).toBe(true)
      expect(wrapper.vm.loginChartData.buckets.at(-1).labelLines[0]).toMatch(/^\d{2}\/\d{2}$/)
      expect(wrapper.vm.loginChartData.buckets.filter(({ count }) => count > 0)).toEqual([
        expect.objectContaining({ count: 2 }),
      ])
    }

    wrapper.unmount()
  })

  it('keeps online API errors separate from empty history', async () => {
    const wrapper = createWrapper()
    await flushPromises()
    const empty = makeOnlineStatistics('24h')
    empty.history_started_at = null
    getOnlineStatisticsMock.mockResolvedValueOnce({ data: empty })
    await wrapper.vm.loadOnlineStatistics()
    expect(wrapper.vm.onlineStatisticsError).toBe('')
    expect(wrapper.vm.onlineStatistics.history_started_at).toBeNull()

    const zeroData = makeOnlineStatistics('24h')
    getOnlineStatisticsMock.mockResolvedValueOnce({ data: zeroData })
    await wrapper.vm.loadOnlineStatistics()
    expect(wrapper.vm.onlineStatisticsSummary).toEqual({ current: 0, peak: 0, average: '0.0' })

    getOnlineStatisticsMock.mockRejectedValueOnce(new Error('network'))
    await wrapper.vm.loadOnlineStatistics()
    expect(wrapper.vm.onlineStatistics).toBeNull()
    expect(wrapper.vm.onlineStatisticsSummary).toBeNull()
    expect(wrapper.vm.onlineStatisticsError).toContain('在線統計載入失敗')

    wrapper.unmount()
  })

  it('maps review submission statistics for every range and isolates API errors', async () => {
    const wrapper = createWrapper()
    await flushPromises()

    for (const [range, bucketCount, bucketMinutes, description] of [
      [24, 144, 10, '統計最近 24 小時內，每 10 分鐘區間的投稿筆數。'],
      [48, 144, 20, '統計最近 48 小時內，每 20 分鐘區間的投稿筆數。'],
      [72, 144, 30, '統計最近 72 小時內，每 30 分鐘區間的投稿筆數。'],
    ]) {
      wrapper.vm.setActiveReviewSubmissionRange(range)
      await flushPromises()
      expect(wrapper.vm.reviewSubmissionStatistics.points).toHaveLength(bucketCount)
      expect(wrapper.vm.reviewSubmissionStatistics.bucket_minutes).toBe(bucketMinutes)
      expect(wrapper.vm.reviewSubmissionStatistics.summary).toEqual({
        total: 3,
        peak: 2,
        average: Number((3 / bucketCount).toFixed(1)),
      })
      expect(wrapper.vm.reviewSubmissionDescription).toBe(description)
      expect(wrapper.vm.reviewSubmissionChartData.buckets[0].showLabel).toBe(true)
      expect(wrapper.vm.reviewSubmissionChartData.buckets.at(-1).showLabel).toBe(true)
    }

    wrapper.vm.reviewSubmissionView = 'date'
    await flushPromises()
    for (const [range, bucketCount, bucketMinutes, description] of [
      [7, 42, 240, '統計最近 7 日內，每 4 小時區間的投稿筆數。'],
      [30, 60, 720, '統計最近 30 日內，每 12 小時區間的投稿筆數。'],
      [90, 90, 1440, '統計最近 90 日內，每日的投稿筆數。'],
    ]) {
      wrapper.vm.setActiveReviewSubmissionRange(range)
      await flushPromises()
      expect(wrapper.vm.reviewSubmissionStatistics.points).toHaveLength(bucketCount)
      expect(wrapper.vm.reviewSubmissionStatistics.bucket_minutes).toBe(bucketMinutes)
      expect(wrapper.vm.reviewSubmissionDescription).toBe(description)
      expect(wrapper.vm.reviewSubmissionChartData.buckets.at(-1).labelLines[0]).toMatch(
        /^\d{2}\/\d{2}$/
      )
    }

    getSubmissionStatisticsMock.mockRejectedValueOnce(new Error('network'))
    await wrapper.vm.loadReviewSubmissionStatistics()
    expect(wrapper.vm.reviewSubmissionStatistics).toBeNull()
    expect(wrapper.vm.reviewSubmissionStatisticsError).toContain('投稿統計載入失敗')
    expect(wrapper.vm.reviewLoadError).toBe('')

    wrapper.unmount()
  })

  it('rejects malformed online statistics contracts', async () => {
    const wrapper = createWrapper()
    await flushPromises()
    getOnlineStatisticsMock.mockResolvedValueOnce({ data: { range: '24h', points: [] } })
    await wrapper.vm.loadOnlineStatistics()
    expect(wrapper.vm.onlineStatistics).toBeNull()
    expect(wrapper.vm.onlineStatisticsError).toContain('在線統計載入失敗')

    wrapper.unmount()
  })

  it('keeps online chart data stable while applying 50, 100 and 150 percent font scales', async () => {
    const wrapper = createWrapper()
    await flushPromises()
    await wrapper.vm.loadReviewSubmissionStatistics()
    const counts = [...wrapper.vm.loginChartData.counts]
    const reviewCounts = wrapper.vm.reviewSubmissionChartData.buckets.map(({ count }) => count)

    for (const [percent, scale] of [
      [50, '0.45'],
      [100, '0.9'],
      [150, '1.35'],
    ]) {
      applyFontSizePreference(percent)
      expect(document.documentElement.style.getPropertyValue('--app-font-scale')).toBe(scale)
      expect(wrapper.vm.loginChartData.counts).toEqual(counts)
      expect(wrapper.vm.reviewSubmissionChartData.buckets.map(({ count }) => count)).toEqual(
        reviewCounts
      )
    }

    wrapper.unmount()
  })

  it('handles create and delete error branches with unauthorized checks', async () => {
    const wrapper = createWrapper()

    await flushPromises()

    toastAddMock.mockClear()

    wrapper.vm.openCreateDialog()
    wrapper.vm.courseForm.name = 'Linear Algebra'
    wrapper.vm.courseForm.category = 'freshman'
    createCourseMock.mockRejectedValueOnce(new Error('create-fail'))
    isUnauthorizedErrorMock.mockReturnValueOnce(false)
    await wrapper.vm.saveCourse()
    expect(toastAddMock).toHaveBeenCalledWith(expect.objectContaining({ detail: '課程新增失敗' }))

    toastAddMock.mockClear()
    createCourseMock.mockRejectedValueOnce(new Error('unauthorized'))
    isUnauthorizedErrorMock.mockReturnValueOnce(true)
    await wrapper.vm.saveCourse()
    expect(toastAddMock).not.toHaveBeenCalled()

    wrapper.vm.openCreateUserDialog()
    wrapper.vm.userForm.name = 'Dave'
    wrapper.vm.userForm.email = 'dave@example.com'
    wrapper.vm.userForm.password = 'secret'
    createUserMock.mockRejectedValueOnce(new Error('user-fail'))
    isUnauthorizedErrorMock.mockReturnValueOnce(false)
    await wrapper.vm.saveUser()
    expect(toastAddMock).toHaveBeenCalledWith(expect.objectContaining({ detail: '使用者新增失敗' }))

    toastAddMock.mockClear()
    createUserMock.mockRejectedValueOnce(new Error('unauthorized'))
    isUnauthorizedErrorMock.mockReturnValueOnce(true)
    await wrapper.vm.saveUser()
    expect(toastAddMock).not.toHaveBeenCalled()

    wrapper.vm.openNotificationCreateDialog()
    wrapper.vm.notificationForm.title = 'System Notice'
    wrapper.vm.notificationForm.body = 'Content'
    notificationCreateMock.mockRejectedValueOnce(new Error('notify-fail'))
    isUnauthorizedErrorMock.mockReturnValueOnce(false)
    await wrapper.vm.saveNotification()
    expect(toastAddMock).toHaveBeenCalledWith(expect.objectContaining({ detail: '公告新增失敗' }))

    toastAddMock.mockClear()
    notificationCreateMock.mockRejectedValueOnce(new Error('unauthorized'))
    isUnauthorizedErrorMock.mockReturnValueOnce(true)
    wrapper.vm.notificationForm.title = 'System Notice'
    wrapper.vm.notificationForm.body = 'Content'
    await wrapper.vm.saveNotification()
    expect(toastAddMock).not.toHaveBeenCalled()

    toastAddMock.mockClear()
    deleteCourseMock.mockRejectedValueOnce(new Error('delete-fail'))
    isUnauthorizedErrorMock.mockReturnValueOnce(false)
    await wrapper.vm.deleteCourseAction({ id: 3, name: 'Course', category: 'junior' })
    expect(toastAddMock).toHaveBeenCalledWith(expect.objectContaining({ detail: '課程刪除失敗' }))

    trackEventMock.mockClear()
    localStorage.clear()
    await wrapper.vm.handleTabChange('1')
    expect(localStorage.getItem('admin-current-tab')).toBe('1')
    expect(trackEventMock).toHaveBeenCalledWith('switch-tab', { tab: 'users' })

    wrapper.unmount()
  })

  it('covers filtering utilities and helper branches', async () => {
    const wrapper = createWrapper()

    await flushPromises()

    await wrapper.vm.loadNotifications()
    await flushPromises()

    await wrapper.vm.handleTabChange('1')
    await flushPromises()

    wrapper.vm.searchQuery = '普通'
    await wrapper.vm.$nextTick()
    expect(wrapper.vm.filteredCourses).toEqual([sampleCourses[0]])

    wrapper.vm.searchQuery = ''
    await wrapper.vm.$nextTick()
    wrapper.vm.filterCategory = 'freshman'
    await wrapper.vm.$nextTick()
    expect(wrapper.vm.filteredCourses).toEqual([sampleCourses[1]])

    wrapper.vm.userSearchQuery = 'bob'
    await wrapper.vm.$nextTick()
    expect(wrapper.vm.filteredUsers).toEqual([
      expect.objectContaining({ id: sampleUsers[1].id, email: sampleUsers[1].email }),
    ])

    wrapper.vm.userSearchQuery = ''
    await wrapper.vm.$nextTick()
    wrapper.vm.filterUserType = true
    await wrapper.vm.$nextTick()
    expect(wrapper.vm.filteredUsers).toEqual([
      expect.objectContaining({ id: sampleUsers[0].id, email: sampleUsers[0].email }),
    ])

    wrapper.vm.notificationSearchQuery = '維護'
    wrapper.vm.notificationSeverityFilter = 'info'
    await wrapper.vm.$nextTick()
    expect(wrapper.vm.filteredNotifications).toHaveLength(1)

    wrapper.vm.notificationSearchQuery = ''
    wrapper.vm.notificationSeverityFilter = 'danger'
    await wrapper.vm.$nextTick()
    expect(wrapper.vm.filteredNotifications).toHaveLength(1)

    const originalSetItem = localStorage.setItem
    localStorage.setItem = vi.fn(() => {
      throw new Error('storage disabled')
    })
    expect(() => wrapper.vm.saveTabToStorage('0')).not.toThrow()
    localStorage.setItem = originalSetItem

    expect(wrapper.vm.toDate('invalid')).toBeNull()
    expect(wrapper.vm.toDate(now.toISOString())).toBeInstanceOf(Date)

    updateUserMock.mockClear()
    wrapper.vm.openEditUserDialog(sampleUsers[0])
    wrapper.vm.userForm.password = 'new-secret'
    await wrapper.vm.saveUser()
    expect(updateUserMock).toHaveBeenLastCalledWith(
      sampleUsers[0].id,
      expect.objectContaining({ password: 'new-secret' })
    )

    toastAddMock.mockClear()
    deleteUserMock.mockRejectedValueOnce(new Error('forbidden'))
    isUnauthorizedErrorMock.mockReturnValueOnce(true)
    await wrapper.vm.deleteUserAction(sampleUsers[0])
    expect(toastAddMock).not.toHaveBeenCalled()

    toastAddMock.mockClear()
    notificationRemoveMock.mockRejectedValueOnce(new Error('unauthorized'))
    isUnauthorizedErrorMock.mockReturnValueOnce(true)
    await wrapper.vm.deleteNotificationAction(sampleNotifications[0])
    expect(toastAddMock).not.toHaveBeenCalled()

    toastAddMock.mockClear()
    wrapper.vm.closeCourseDialog()
    wrapper.vm.closeUserDialog()
    wrapper.vm.closeNotificationDialog()
    expect(wrapper.vm.showCourseDialog).toBe(false)
    expect(wrapper.vm.showUserDialog).toBe(false)
    expect(wrapper.vm.showNotificationDialog).toBe(false)

    wrapper.unmount()
  })
})
