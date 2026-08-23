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
const existingCourseStatusPillCss =
  adminViewSource.match(
    /\.p-tag\.existing-course-status-pill\.soft-badge\.admin-desktop-status-tag[\s\S]*?\)\s*\{[\s\S]*?\}/
  )?.[0] ?? ''

const sampleCourses = [
  { id: 1, name: '普通物理', category: 'junior' },
  { id: 2, name: '電磁學', category: 'freshman' },
]

const sampleUsers = [
  {
    id: 1,
    name: 'Alice',
    nickname: null,
    email: 'alice@example.com',
    is_admin: true,
    is_local: true,
    account_source: 'local',
    student_id: null,
    department_code: null,
    department_name: null,
  },
  {
    id: 2,
    name: 'Bob',
    nickname: '小波',
    email: 'bob@example.com',
    is_admin: false,
    is_local: false,
    account_source: 'nthu',
    student_id: '112022123',
    department_code: '022',
    nthu_affiliation_kind: 'standard_student',
    nthu_affiliation_label: '一般學生',
    department_name: '物理學系',
  },
]

const sampleNthuAccessPolicy = {
  mode: 'all_nthu',
  allowed_department_codes: [],
  staff_access: 'none',
  allowed_staff_userids: [],
  departments: [
    { code: '022', name: '物理學系', college_code: '02', college_name: '理學院' },
    { code: '025', name: '天文研究所', college_code: '02', college_name: '理學院' },
  ],
}

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
    title_en: 'Maintenance notice',
    body_en: 'Maintenance in progress',
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
    title_en: 'Expired notice',
    body_en: 'Expired',
    severity: 'danger',
    is_active: true,
    starts_at: new Date(now.getTime() - 7200_000).toISOString(),
    ends_at: new Date(now.getTime() - 3600_000).toISOString(),
    created_at: new Date(now.getTime() - 86400_000).toISOString(),
  },
]

const getCoursesMock = vi.hoisted(() => vi.fn())
const getAdminAttentionSummaryMock = vi.hoisted(() => vi.fn())
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
const getNthuAccessPolicyMock = vi.hoisted(() => vi.fn())
const updateNthuAccessPolicyMock = vi.hoisted(() => vi.fn())

const notificationGetAllMock = vi.hoisted(() => vi.fn())
const notificationCreateMock = vi.hoisted(() => vi.fn())
const notificationUpdateMock = vi.hoisted(() => vi.fn())
const notificationRemoveMock = vi.hoisted(() => vi.fn())
const listAdminSubmissionsMock = vi.hoisted(() => vi.fn())
const getSubmissionStatisticsMock = vi.hoisted(() => vi.fn())
const listSubmissionComparisonsMock = vi.hoisted(() => vi.fn())
const approveSubmissionMock = vi.hoisted(() => vi.fn())
const rejectSubmissionMock = vi.hoisted(() => vi.fn())
const takedownSubmissionMock = vi.hoisted(() => vi.fn())
const republishSubmissionMock = vi.hoisted(() => vi.fn())
const updateSubmissionMock = vi.hoisted(() => vi.fn())
const deleteSubmissionMock = vi.hoisted(() => vi.fn())
const downloadArchiveBackupMock = vi.hoisted(() => vi.fn())

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
  getAdminAttentionSummary: getAdminAttentionSummaryMock,
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
  getNthuAccessPolicy: getNthuAccessPolicyMock,
  updateNthuAccessPolicy: updateNthuAccessPolicyMock,
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
    listSubmissionComparisons: listSubmissionComparisonsMock,
    approveSubmission: approveSubmissionMock,
    rejectSubmission: rejectSubmissionMock,
    takedownSubmission: takedownSubmissionMock,
    republishSubmission: republishSubmissionMock,
    updateSubmission: updateSubmissionMock,
    deleteSubmission: deleteSubmissionMock,
    downloadArchiveBackup: downloadArchiveBackupMock,
  },
}))

function createWrapper() {
  return shallowMount(AdminView)
}

function createBackupWrapper() {
  const passthrough = { template: '<div><slot /></div>' }
  return shallowMount(AdminView, {
    global: {
      stubs: {
        Tabs: passthrough,
        TabList: { template: '<div class="tab-list-test"><slot /></div>' },
        Tab: { props: ['value'], template: '<button :data-value="value"><slot /></button>' },
        TabPanels: passthrough,
        TabPanel: {
          props: ['value'],
          template: '<div v-if="value === \'6\'" :data-value="value"><slot /></div>',
        },
      },
    },
  })
}

let consoleErrorSpy

describe('AdminView', () => {
  beforeEach(() => {
    consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    vi.useFakeTimers()
    vi.setSystemTime(now)
    getCoursesMock.mockResolvedValue({ data: sampleCourses })
    getAdminAttentionSummaryMock.mockResolvedValue({
      data: {
        review_center: { new_course_or_category: 0, existing_course: 0, total: 0 },
        report_management: {
          archive_reports: 0,
          comment_reports: 0,
          wish_reports: 0,
          system_issues: 0,
          total: 0,
        },
      },
    })
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
    getNthuAccessPolicyMock.mockResolvedValue({ data: sampleNthuAccessPolicy })
    updateNthuAccessPolicyMock.mockImplementation((policy) =>
      Promise.resolve({
        data: {
          ...sampleNthuAccessPolicy,
          ...policy,
        },
      })
    )

    notificationGetAllMock.mockResolvedValue({ data: sampleNotifications })
    notificationCreateMock.mockResolvedValue()
    notificationUpdateMock.mockResolvedValue()
    notificationRemoveMock.mockResolvedValue()
    listAdminSubmissionsMock.mockResolvedValue({ data: [] })
    listSubmissionComparisonsMock.mockResolvedValue({ data: [] })
    approveSubmissionMock.mockReset()
    rejectSubmissionMock.mockReset()
    takedownSubmissionMock.mockReset()
    republishSubmissionMock.mockReset()
    updateSubmissionMock.mockReset()
    deleteSubmissionMock.mockReset()
    downloadArchiveBackupMock.mockReset()
    approveSubmissionMock.mockResolvedValue({ data: {} })
    rejectSubmissionMock.mockResolvedValue({ data: {} })
    takedownSubmissionMock.mockResolvedValue({ data: {} })
    republishSubmissionMock.mockResolvedValue({ data: {} })
    updateSubmissionMock.mockResolvedValue({ data: {} })
    deleteSubmissionMock.mockResolvedValue({ data: { changed: true } })
    downloadArchiveBackupMock.mockResolvedValue({
      data: new Blob(['backup']),
      headers: { 'content-disposition': 'attachment; filename="PhysArchive_Backup_test.zip"' },
    })
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
    expect(wrapper.vm.filteredUsers).toEqual([
      expect.objectContaining({ id: sampleUsers[0].id, account_source: 'local' }),
    ])

    wrapper.vm.openCreateDialog()
    wrapper.vm.courseForm.name = '量子物理'
    wrapper.vm.courseForm.category = 'freshman'
    await wrapper.vm.saveCourse()

    expect(createCourseMock).toHaveBeenCalledWith({
      name: '量子物理',
      name_en: '',
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
    wrapper.vm.userForm.password = 'StrongPass123'
    wrapper.vm.userForm.is_admin = true
    await wrapper.vm.saveUser()
    expect(createUserMock).toHaveBeenCalledWith({
      name: 'Charlie',
      email: 'charlie@example.com',
      password: 'StrongPass123',
      is_admin: true,
    })

    wrapper.vm.openEditUserDialog(sampleUsers[1])
    await wrapper.vm.$nextTick()
    expect(wrapper.vm.isEditingNthuUser).toBe(true)
    expect(adminTemplateSource.match(/:disabled="isEditingNthuUser"/g)).toHaveLength(2)
    wrapper.vm.userForm.name = 'Bob Updated'
    wrapper.vm.userForm.email = 'bob-updated@example.com'
    wrapper.vm.userForm.password = ''
    wrapper.vm.userForm.is_admin = true
    await wrapper.vm.saveUser()
    expect(updateUserMock).toHaveBeenCalledWith(sampleUsers[1].id, {
      is_admin: true,
    })

    wrapper.vm.confirmDeleteUser(sampleUsers[1])
    expect(deleteUserMock).toHaveBeenCalledWith(sampleUsers[1].id)

    wrapper.vm.openNotificationCreateDialog()
    wrapper.vm.notificationForm.title = '新公告'
    wrapper.vm.notificationForm.body = '內容'
    wrapper.vm.notificationForm.title_en = 'New announcement'
    wrapper.vm.notificationForm.body_en = 'Content'
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

  it('renders the approved backup tab, copy, and aligned content structure', () => {
    const wrapper = createBackupWrapper()
    const tabLabels = Array.from(wrapper.find('.tab-list-test').element.children).map(
      (tab) => tab.textContent
    )

    expect(tabLabels.at(-2)).toBe('垃圾桶')
    expect(tabLabels.at(-1)).toBe('資料備份')
    expect(wrapper.text()).toContain('公開考古題備份')
    expect(wrapper.text()).toContain(
      '將目前網站上有效公開的考古題整理成可離線保存與管理的 ZIP 備份。'
    )
    expect(wrapper.text()).toContain('備份包含')
    expect(wrapper.text()).toContain('備份不包含')
    for (const copy of [
      '有效公開中的考古題 PDF',
      '依課程分類與課程整理的資料夾結構',
      '考古題與課程相關清單及 metadata',
      'manifest.json',
      '_archives.csv',
      'SHA-256 校驗碼',
      '垃圾桶內容',
      '待審核投稿',
      '未通過投稿',
      '已下架或非公開內容',
      '使用者私人資料',
    ]) {
      expect(wrapper.text()).toContain(copy)
    }
    expect(wrapper.text()).toContain('PDF 檔名與儲存')
    expect(wrapper.text()).toContain(
      '此功能是考古題資料的可攜式匯出備份，不取代 VPS Snapshot 或 PostgreSQL 資料庫備份。'
    )
    expect(wrapper.text()).not.toContain(
      '系統會在下載前完成所有檔案檢查；若任何公開 PDF 缺失或無法讀取，將不會產生不完整的成功備份。'
    )

    const contentGrid = wrapper.find('.backup-content-grid')
    expect(contentGrid.exists()).toBe(true)
    expect(contentGrid.findAll('.backup-information-block')).toHaveLength(2)
    expect(contentGrid.find('.backup-file-guidance.backup-content-grid__full-width').exists()).toBe(
      true
    )
    expect(contentGrid.find('.backup-scope-note.backup-content-grid__full-width').exists()).toBe(
      true
    )
    expect(contentGrid.find('.backup-scope-note > .pi-info-circle').exists()).toBe(true)

    wrapper.unmount()
  })

  it('downloads one backup at a time and reports success', async () => {
    let resolveDownload
    downloadArchiveBackupMock.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveDownload = resolve
      })
    )
    const createObjectURLMock = vi.fn(() => 'blob:archive-backup')
    const revokeObjectURLMock = vi.fn()
    const clickMock = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    Object.defineProperty(window.URL, 'createObjectURL', {
      configurable: true,
      value: createObjectURLMock,
    })
    Object.defineProperty(window.URL, 'revokeObjectURL', {
      configurable: true,
      value: revokeObjectURLMock,
    })
    const wrapper = createWrapper()

    const firstDownload = wrapper.vm.downloadArchiveBackup()
    const duplicateDownload = wrapper.vm.downloadArchiveBackup()
    expect(wrapper.vm.backupDownloading).toBe(true)
    expect(downloadArchiveBackupMock).toHaveBeenCalledTimes(1)

    resolveDownload({
      data: new Blob(['backup']),
      headers: { 'content-disposition': 'attachment; filename="PhysArchive_Backup_test.zip"' },
    })
    await firstDownload
    await duplicateDownload
    expect(wrapper.vm.backupDownloading).toBe(false)
    expect(createObjectURLMock).toHaveBeenCalledOnce()
    expect(clickMock).toHaveBeenCalledOnce()
    expect(toastAddMock).toHaveBeenCalledWith(
      expect.objectContaining({ severity: 'success', detail: 'ZIP 備份已開始下載。' })
    )

    vi.advanceTimersByTime(100)
    expect(revokeObjectURLMock).toHaveBeenCalledWith('blob:archive-backup')
    clickMock.mockRestore()
    delete window.URL.createObjectURL
    delete window.URL.revokeObjectURL
    wrapper.unmount()
  })

  it('recovers from backup errors and follows unauthorized handling', async () => {
    const wrapper = createWrapper()
    downloadArchiveBackupMock.mockRejectedValueOnce(new Error('storage unavailable'))

    await wrapper.vm.downloadArchiveBackup()
    expect(wrapper.vm.backupDownloading).toBe(false)
    expect(toastAddMock).toHaveBeenCalledWith(
      expect.objectContaining({
        severity: 'error',
        detail: '無法建立完整備份，請確認公開 PDF 儲存狀態後再試一次。',
      })
    )

    toastAddMock.mockClear()
    isUnauthorizedErrorMock.mockReturnValueOnce(true)
    downloadArchiveBackupMock.mockRejectedValueOnce(new Error('unauthorized'))
    await wrapper.vm.downloadArchiveBackup()
    expect(wrapper.vm.backupDownloading).toBe(false)
    expect(toastAddMock).not.toHaveBeenCalled()

    wrapper.unmount()
  })

  it('loads, validates, and saves the NTHU department access policy', async () => {
    const wrapper = createWrapper()
    await flushPromises()

    await wrapper.vm.loadNthuAccessPolicy()
    expect(getNthuAccessPolicyMock).toHaveBeenCalled()
    expect(wrapper.vm.nthuAccessPolicyForm.mode).toBe('all_nthu')
    expect(wrapper.vm.nthuDepartmentGroups).toEqual([
      expect.objectContaining({
        college_code: '02',
        college_name: '理學院',
        departments: expect.arrayContaining([
          expect.objectContaining({ code: '022', name: '物理學系' }),
        ]),
      }),
    ])

    wrapper.vm.nthuAccessPolicyForm.mode = 'selected_departments'
    wrapper.vm.nthuAccessPolicyForm.allowed_department_codes = []
    updateNthuAccessPolicyMock.mockClear()
    await wrapper.vm.saveNthuAccessPolicy()
    expect(updateNthuAccessPolicyMock).not.toHaveBeenCalled()

    wrapper.vm.nthuAccessPolicyForm.allowed_department_codes = ['022', '025']
    await wrapper.vm.saveNthuAccessPolicy()
    expect(updateNthuAccessPolicyMock).toHaveBeenCalledWith({
      mode: 'selected_departments',
      allowed_department_codes: ['022', '025'],
      staff_access: 'none',
      allowed_staff_userids: [],
    })

    wrapper.vm.nthuAccessPolicyForm.staff_access = 'allowlist'
    wrapper.vm.nthuAccessPolicyForm.allowed_staff_userids = ['W90001']
    wrapper.vm.nthuAccessPolicyForm.mode = 'all_nthu'
    await wrapper.vm.saveNthuAccessPolicy()
    expect(updateNthuAccessPolicyMock).toHaveBeenLastCalledWith({
      mode: 'all_nthu',
      allowed_department_codes: ['022', '025'],
      staff_access: 'allowlist',
      allowed_staff_userids: ['W90001'],
    })
    getNthuAccessPolicyMock.mockResolvedValueOnce({
      data: {
        ...sampleNthuAccessPolicy,
        mode: 'all_nthu',
        allowed_department_codes: ['022', '025'],
        staff_access: 'allowlist',
        allowed_staff_userids: ['W90001'],
      },
    })
    await wrapper.vm.loadNthuAccessPolicy()
    wrapper.vm.nthuAccessPolicyForm.mode = 'selected_departments'
    expect(wrapper.vm.nthuAccessPolicyForm.allowed_department_codes).toEqual(['022', '025'])
    expect(wrapper.vm.nthuAccessPolicyForm.staff_access).toBe('allowlist')
    expect(wrapper.vm.nthuAccessPolicyForm.allowed_staff_userids).toEqual(['W90001'])
    expect(toastAddMock).toHaveBeenLastCalledWith(
      expect.objectContaining({ severity: 'success', detail: 'NTHU 登入範圍已更新。' })
    )

    expect(adminTemplateSource).toContain('設定哪些清大學生可以透過 NTHU OAuth 登入網站')
    expect(adminTemplateSource).toContain("user.student_id || '—'")
    expect(adminTemplateSource).toContain('getNthuIdentitySecondaryLine(user)')
    expect(adminTemplateSource).toContain(':filterPlaceholder="$t(\'搜尋中文系所名稱或代碼\')"')

    wrapper.unmount()
  })

  it('supports staff-only allowlists and rejects duplicate employee IDs', async () => {
    const wrapper = createWrapper()
    await flushPromises()

    wrapper.vm.nthuAccessPolicyForm.mode = 'selected_departments'
    wrapper.vm.nthuAccessPolicyForm.allowed_department_codes = []
    wrapper.vm.nthuAccessPolicyForm.staff_access = 'allowlist'
    wrapper.vm.nthuStaffUseridDraft = ' W90001 '
    wrapper.vm.addNthuStaffUserid()
    expect(wrapper.vm.nthuAccessPolicyForm.allowed_staff_userids).toEqual(['W90001'])

    wrapper.vm.nthuStaffUseridDraft = 'W90001'
    wrapper.vm.addNthuStaffUserid()
    expect(wrapper.vm.nthuStaffUseridError).toContain('已在清單')

    await wrapper.vm.saveNthuAccessPolicy()
    expect(updateNthuAccessPolicyMock).toHaveBeenCalledWith({
      mode: 'selected_departments',
      allowed_department_codes: [],
      staff_access: 'allowlist',
      allowed_staff_userids: ['W90001'],
    })

    wrapper.vm.removeNthuStaffUserid('W90001')
    expect(wrapper.vm.isNthuAccessPolicyValid).toBe(false)
    wrapper.unmount()
  })

  it('has only department and staff allow paths in the custom policy UI', async () => {
    const wrapper = createWrapper()
    await flushPromises()

    wrapper.vm.nthuAccessPolicyForm.mode = 'selected_departments'
    wrapper.vm.nthuAccessPolicyForm.allowed_department_codes = []
    wrapper.vm.nthuAccessPolicyForm.staff_access = 'none'
    wrapper.vm.nthuAccessPolicyForm.allowed_staff_userids = []
    expect(wrapper.vm.isNthuAccessPolicyValid).toBe(false)
    expect(wrapper.vm.nthuAccessPolicyForm).not.toHaveProperty('allowed_special_' + 'affiliations')
    expect(adminTemplateSource).not.toContain('交換生／' + '特殊學生')
    expect(adminTemplateSource).not.toContain('特殊學生' + '身分')
    expect(adminTemplateSource).toContain('自訂登入範圍仍依學生系所與教職員 allowlist')
    expect(adminTemplateSource).toContain(
      '自訂範圍至少需要選擇一個系所，或加入一個允許的員工編號。'
    )
    expect(adminTemplateSource).not.toContain('nthu-special-student')
    wrapper.unmount()
  })

  it('switches account-source tabs and keeps NTHU identity filters scoped to NTHU users', async () => {
    const wrapper = createWrapper()
    await flushPromises()
    const extraUsers = [
      {
        id: 3,
        name: 'Unresolved',
        email: 'special@example.com',
        is_admin: false,
        is_local: false,
        account_source: 'nthu',
        student_id: 'X1106099',
        department_code: null,
        department_name: null,
        nthu_affiliation_kind: 'unresolved',
        nthu_affiliation_label: '未解析',
      },
      {
        id: 4,
        name: 'Staff',
        email: 'staff@example.com',
        is_admin: false,
        is_local: false,
        account_source: 'nthu',
        student_id: 'W90001',
        department_code: null,
        department_name: null,
        nthu_affiliation_kind: 'staff',
        nthu_affiliation_label: '教職員',
      },
    ]
    wrapper.vm.users = [...sampleUsers, ...extraUsers].map((user) => ({
      ...user,
      contributorLevel: { level: 1, name: 'Level 1' },
      contributor_level: 1,
    }))

    expect(wrapper.vm.activeUserSource).toBe('local')
    expect(wrapper.vm.filteredUsers.map((user) => user.name)).toEqual(['Alice'])

    wrapper.vm.activeUserSource = 'nthu'
    wrapper.vm.filterNthuAffiliation = 'standard_student'
    wrapper.vm.filterNthuDepartment = '022'
    expect(wrapper.vm.filteredUsers.map((user) => user.name)).toEqual(['Bob'])
    expect(wrapper.vm.getNthuIdentitySecondaryLine(wrapper.vm.filteredUsers[0])).toBe('物理學系')

    wrapper.vm.filterNthuAffiliation = 'unresolved'
    wrapper.vm.filterNthuDepartment = null
    expect(wrapper.vm.filteredUsers.map((user) => user.name)).toEqual(['Unresolved'])
    expect(wrapper.vm.getNthuIdentitySecondaryLine(wrapper.vm.filteredUsers[0])).toBe('未解析')

    wrapper.vm.filterNthuAffiliation = null
    wrapper.vm.userSearchQuery = '未解析'
    expect(wrapper.vm.filteredUsers.map((user) => user.name)).toEqual(['Unresolved'])

    expect(adminTemplateSource).toContain('<Tab value="local">{{ $t(\'本地帳號\') }}</Tab>')
    expect(adminTemplateSource).toContain('<Tab value="nthu">{{ $t(\'清大 OAuth\') }}</Tab>')
    expect(adminTemplateSource).not.toContain('admin-user-source-filter')
    expect(adminTemplateSource).not.toContain('header="學號 / 員工編號"')
    expect(adminTemplateSource).not.toContain('header="系所 / 類別"')
    expect(adminTemplateSource).not.toContain('header="帳號類型"')
    expect(adminTemplateSource).not.toContain(
      '<span class="admin-tablet-metadata-label">帳號類型</span>'
    )
    expect(adminTemplateSource).toContain(
      'class="admin-tablet-metadata-value nthu-identity nthu-identity--card"'
    )
    expect(adminViewSource).toMatch(
      /\.nthu-identity--card\s*\{[^}]*flex-direction:\s*row;[^}]*flex-wrap:\s*wrap;[^}]*align-items:\s*baseline;/
    )
    wrapper.unmount()
  })

  it('keeps policy load and save failures safe and actionable', async () => {
    const wrapper = createWrapper()
    await flushPromises()

    getNthuAccessPolicyMock.mockRejectedValueOnce(new Error('offline'))
    await wrapper.vm.loadNthuAccessPolicy()
    expect(wrapper.vm.nthuAccessPolicyError).toBe('登入範圍載入失敗，請稍後再試。')

    wrapper.vm.nthuAccessPolicyForm.mode = 'all_nthu'
    updateNthuAccessPolicyMock.mockRejectedValueOnce(new Error('save failed'))
    await wrapper.vm.saveNthuAccessPolicy()
    expect(toastAddMock).toHaveBeenLastCalledWith(
      expect.objectContaining({ severity: 'error', detail: '登入範圍儲存失敗，請稍後再試。' })
    )

    wrapper.unmount()
  })

  it('preserves distinct comparison submission identities returned by the API', async () => {
    const currentSubmissionId = 7001
    const candidateIds = [7002, 7003]
    const comparisons = [
      {
        id: candidateIds[0],
        status: 'approved',
        subject: '普通物理（一）',
        name: 'final',
        professor: '王進維',
        academic_year: 1131,
      },
      {
        id: candidateIds[1],
        status: 'pending',
        subject: '普通物理（一）',
        name: 'final',
        professor: '王進維',
        academic_year: 1131,
      },
    ]
    listSubmissionComparisonsMock.mockResolvedValueOnce({ data: comparisons })
    const wrapper = createWrapper()
    await flushPromises()

    await wrapper.vm.loadArchiveComparison({ id: currentSubmissionId })

    expect(listSubmissionComparisonsMock).toHaveBeenCalledWith(currentSubmissionId)
    expect(wrapper.vm.comparisonArchives.map(({ id }) => id)).toEqual(candidateIds)
    expect(wrapper.vm.comparisonArchives).toEqual(comparisons)
  })

  it('sends an annotation-only diff when an approved review note changes', async () => {
    const request = {
      id: 7050,
      status: 'approved',
      subject: '普通物理（一）',
      category: 'freshman',
      name: 'final',
      academic_year: 1131,
      archive_type: 'final',
      professor: '王進維',
      has_answers: false,
      review_note: null,
    }
    updateSubmissionMock.mockResolvedValueOnce({
      data: { ...request, review_note: 'stage-a-review-note-check' },
    })
    const wrapper = createWrapper()
    await flushPromises()

    await wrapper.vm.openArchiveRequestDialog(request)
    expect(wrapper.vm.canEditSelectedArchiveMetadata).toBe(false)
    expect(wrapper.vm.canEditSelectedArchiveReviewNote).toBe(true)
    expect(adminTemplateSource).toContain(
      '可留空；若未填寫，投稿者將看到「尚無審核留言」。此留言會隨投稿紀錄保留。'
    )

    wrapper.vm.archiveRequestEditForm.review_note = '  stage-a-review-note-check  '
    await wrapper.vm.saveArchiveRequestEdit()

    expect(updateSubmissionMock).toHaveBeenCalledWith(7050, {
      review_note: 'stage-a-review-note-check',
    })
  })

  it('caps attention badges, hides zero, and assigns child presentation classes', async () => {
    const wrapper = createWrapper()
    await flushPromises()

    expect(wrapper.vm.formatAttentionBadge(0)).toBeNull()
    expect(wrapper.vm.formatAttentionBadge(1)).toBe(1)
    expect(wrapper.vm.formatAttentionBadge(99)).toBe(99)
    expect(wrapper.vm.formatAttentionBadge(100)).toBe('99+')
    expect(adminTemplateSource).toContain('class="admin-attention-badge"')
    expect(adminTemplateSource).toContain(
      'class="admin-attention-badge admin-attention-badge--child"'
    )
  })

  it('uses each review row status as the direct review precondition', async () => {
    const wrapper = createWrapper()
    await flushPromises()

    await wrapper.vm.reviewArchiveSubmission({ id: 7101, status: 'pending' }, 'approve')
    await wrapper.vm.reviewArchiveSubmission({ id: 7102, status: 'approved' }, 'reject')
    await wrapper.vm.reviewArchiveSubmission({ id: 7103, status: 'pending' }, 'takedown')
    await wrapper.vm.reviewArchiveSubmission({ id: 7104, status: 'takedown' }, 'republish')

    expect(approveSubmissionMock).toHaveBeenCalledWith(7101, 'pending')
    expect(rejectSubmissionMock).toHaveBeenCalledWith(7102, 'approved')
    expect(takedownSubmissionMock).toHaveBeenCalledWith(7103, 'pending')
    expect(republishSubmissionMock).toHaveBeenCalledWith(7104, 'takedown')
  })

  it('uses comparison candidate status and fails closed when row status is missing', async () => {
    const wrapper = createWrapper()
    await flushPromises()

    await wrapper.vm.takedownComparisonItem({ id: 7201, status: 'approved' })
    await wrapper.vm.reviewArchiveSubmission({ id: 7202 }, 'approve')

    expect(takedownSubmissionMock).toHaveBeenCalledTimes(1)
    expect(takedownSubmissionMock).toHaveBeenCalledWith(7201, 'approved')
    expect(approveSubmissionMock).not.toHaveBeenCalled()
  })

  it('intersects the approved review product matrix with backend authority', async () => {
    const wrapper = createWrapper()
    await flushPromises()
    const actionKeys = (item) => wrapper.vm.getReviewRowActions(item).map(({ key }) => key)

    expect(
      actionKeys({
        status: 'pending',
        available_actions: ['approve', 'takedown', 'reject', 'delete'],
      })
    ).toEqual(['approve', 'takedown', 'reject', 'delete'])
    expect(
      actionKeys({ status: 'pending', available_actions: ['approve', 'reject', 'delete'] })
    ).toEqual(['approve', 'reject', 'delete'])
    expect(actionKeys({ status: 'takedown', available_actions: ['republish', 'delete'] })).toEqual([
      'republish',
      'delete',
    ])
    expect(
      actionKeys({
        status: 'approved',
        available_actions: ['approve', 'takedown', 'reject', 'delete'],
      })
    ).toEqual(['takedown', 'reject', 'delete'])
    expect(
      actionKeys({ status: 'rejected', available_actions: ['approve', 'takedown', 'delete'] })
    ).toEqual(['approve', 'delete'])
    expect(actionKeys({ status: 'deleted', available_actions: ['delete'] })).toEqual([])
    expect(actionKeys({ status: 'pending' })).toEqual([])
    expect(actionKeys({ status: 'pending', available_actions: 'approve' })).toEqual([])
    expect(actionKeys({ status: 'pending', available_actions: ['unknown'] })).toEqual([])

    expect(
      wrapper.vm.getReviewRowActions({ status: 'pending', available_actions: ['takedown'] }).at(0)
    ).toMatchObject({
      label: '下架',
      icon: 'pi pi-eye-slash',
      severity: 'secondary',
    })

    confirmRequireMock.mockClear()
    wrapper.vm.runReviewRowAction(
      {
        id: 7299,
        subject: '已下架課程',
        name: '期中考',
        status: 'takedown',
        available_actions: ['republish', 'delete'],
      },
      'delete'
    )
    expect(confirmRequireMock).toHaveBeenCalledWith(
      expect.objectContaining({
        header: '確認刪除投稿紀錄',
        accept: expect.any(Function),
      })
    )
  })

  it('uses approved rejected terminology and distinguishes review no-ops', async () => {
    rejectSubmissionMock
      .mockResolvedValueOnce({ data: { changed: true } })
      .mockResolvedValueOnce({ data: { changed: false } })
    const wrapper = createWrapper()
    await flushPromises()

    expect(wrapper.vm.getSubmissionLabel('rejected')).toBe('未通過')
    expect(wrapper.vm.getTrashStatusLabel('rejected')).toBe('未通過')

    await wrapper.vm.reviewArchiveSubmission({ id: 7301, status: 'approved' }, 'reject')
    expect(toastAddMock).toHaveBeenLastCalledWith(
      expect.objectContaining({ severity: 'success', detail: '投稿已設為未通過。' })
    )

    await wrapper.vm.reviewArchiveSubmission({ id: 7302, status: 'rejected' }, 'reject')
    expect(toastAddMock).toHaveBeenLastCalledWith(
      expect.objectContaining({
        severity: 'info',
        detail: '投稿狀態未變更，已重新整理最新資料。',
      })
    )
  })

  it('uses informational feedback for an administrator delete no-op', async () => {
    deleteSubmissionMock.mockResolvedValueOnce({ data: { changed: false } })
    listAdminSubmissionsMock.mockResolvedValueOnce({
      data: Array.from({ length: 25 }, (_, index) => ({
        id: index + 1,
        status: 'pending',
        subject: `Physics ${index + 1}`,
        requested_course_name: 'Physics',
        available_actions: [],
      })),
    })
    const wrapper = createWrapper()
    await flushPromises()
    wrapper.vm.reviewSearchQuery = 'Physics'
    await wrapper.vm.$nextTick()
    wrapper.vm.newSubmissionFirst = 10
    wrapper.vm.newSubmissionRows = 10

    await wrapper.vm.deleteArchiveSubmissionAction({ id: 7401 })
    await wrapper.vm.$nextTick()

    expect(toastAddMock).toHaveBeenLastCalledWith(
      expect.objectContaining({
        severity: 'info',
        detail: '此投稿已在垃圾桶中，未重複刪除。',
      })
    )
    expect(listAdminSubmissionsMock).toHaveBeenCalled()
    expect(wrapper.vm.reviewSearchQuery).toBe('Physics')
    expect(wrapper.vm.newSubmissionFirst).toBe(10)
    expect(wrapper.vm.newSubmissionRows).toBe(10)
  })

  it('uses only explicit Trash authority and labels submission parents accurately', async () => {
    const wrapper = createWrapper()
    await flushPromises()

    for (const value of [false, null, undefined, 'true', 1, {}, []]) {
      expect(wrapper.vm.canRestoreTrashItem({ canRestore: value })).toBe(false)
      expect(wrapper.vm.canPermanentDeleteTrashItem({ canPermanentDelete: value })).toBe(false)
    }

    expect(
      wrapper.vm.canRestoreTrashItem({
        canRestore: true,
        dependencies: [{ label: '阻擋還原：仍有相依項目' }],
      })
    ).toBe(true)
    expect(
      wrapper.vm.canPermanentDeleteTrashItem({
        canPermanentDelete: true,
        dependencies: [{ label: '阻擋永久刪除：仍有相依項目' }],
      })
    ).toBe(true)
    expect(
      wrapper.vm.canRestoreTrashItem({
        dependencies: [{ label: '無阻擋' }],
      })
    ).toBe(false)
    expect(
      wrapper.vm.canPermanentDeleteTrashItem({
        dependencies: [{ label: '無阻擋' }],
      })
    ).toBe(false)

    expect(
      wrapper.vm.getTrashContextLine({
        item_type: 'archive_submission',
        parent_type: 'course',
        parent_name: '普通物理',
      })
    ).toBe('關聯課程：普通物理')
    expect(
      wrapper.vm.getTrashContextLine({
        item_type: 'archive_submission',
        parent_type: 'archive',
        parent_name: '期中考',
      })
    ).toBe('關聯考古題：期中考')
    expect(
      wrapper.vm.getTrashContextLine({
        item_type: 'course_submission',
        parent_type: 'course',
        parent_name: '量子力學',
      })
    ).toBe('關聯課程：量子力學')
    expect(
      wrapper.vm.getTrashContextLine({
        item_type: 'course_submission',
        parent_type: null,
        parent_name: null,
      })
    ).toBe('歷史紀錄：未連結課程（保留為獨立歷史紀錄）')

    const legacyCourseRequest = {
      item_type: 'course_submission',
      canRestore: false,
      canPermanentDelete: true,
      dependencies: ['無法還原：舊資料缺少可驗證的原始審核狀態'],
    }
    expect(wrapper.vm.canRestoreTrashItem(legacyCourseRequest)).toBe(false)
    expect(wrapper.vm.canPermanentDeleteTrashItem(legacyCourseRequest)).toBe(true)
    expect(wrapper.vm.getTrashDependencies(legacyCourseRequest)).toEqual([
      expect.objectContaining({
        label: '阻擋還原：舊資料缺少可驗證的原始審核狀態',
        restoreBlocking: true,
        deleteBlocking: false,
      }),
    ])

    wrapper.unmount()
  })

  it('uses compact Admin-context labels without changing fields or sorting', () => {
    expect(adminTemplateSource.match(/\$t\('管理員投稿（審核中心）'\)/g)).toHaveLength(4)
    expect(adminTemplateSource).toContain(
      `field="contributor_level"\n                  :header="$t('投稿等級（使用者管理欄位）')"\n                  sortable`
    )
    expect(adminTemplateSource).toContain(
      `field="is_admin"\n                  :header="$t('管理員權限（使用者管理欄位）')"\n                  sortable`
    )
    expect(adminTemplateSource).toContain(
      `<label for="admin-user-is-admin">{{ $t('管理員權限') }}</label>`
    )
    expect(adminTemplateSource).not.toContain('contributor-level-settings-max')
    expect(adminTemplateSource).not.toContain("$t('最高等級')")
  })

  it('keeps the shared mobile action row breakpoint-agnostic for five actions', () => {
    expect(adminViewSource).not.toMatch(/@media\s*\(max-width:\s*337px\)/)
    expect(adminViewSource).toContain('grid-template-columns: repeat(5, minmax(2.5rem, 1fr))')
    expect(adminViewSource).toMatch(
      /@media \(max-width: 640px\)[\s\S]*?review-card-actions[\s\S]*?flex-wrap: nowrap/
    )
    expect(adminViewSource).toMatch(
      /review-card-actions \.p-button[\s\S]*?flex: 1 1 0[\s\S]*?min-width: 0/
    )
  })

  it('keeps takedown filled, republish outlined, and scopes the dark reject colors', () => {
    expect(adminViewSource).toContain("'review-takedown-action': action.key === 'takedown'")
    expect(adminViewSource).toMatch(
      /takedown:\s*\{[\s\S]*?severity:\s*'secondary',[\s\S]*?\},\s*republish:/
    )
    expect(adminViewSource).toMatch(/republish:\s*\{[\s\S]*?outlined:\s*true,[\s\S]*?\}/)
    expect(adminViewSource).toMatch(
      /html\.dark \.review-action-reject\.p-button\.p-button-danger\s*\{[^}]*background:\s*var\(--p-red-600,[^;]+;[^}]*color:\s*var\(--p-surface-950, #020617\)/
    )
    expect(adminViewSource).toMatch(
      /\.review-takedown-action\.p-button\)\s*\{[^}]*background:\s*var\(--p-surface-700, #374151\)[^}]*color:\s*var\(--p-surface-0, #ffffff\)/
    )
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
    expect(
      adminViewSource.match(/review-mobile-info-label">\{\{ \$t\('審核人'\) \}\}/g)
    ).toHaveLength(2)
    expect(
      adminViewSource.match(/review-mobile-info-label">\{\{ \$t\('審核時間'\) \}\}/g)
    ).toHaveLength(2)
    expect(adminViewSource.match(/label: t\('刪除者'\)/g)).toHaveLength(1)
    expect(adminViewSource.match(/label: t\('刪除時間'\)/g)).toHaveLength(1)
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
    expect(adminTemplateSource.match(/'existing-course-status-pill'/g)).toHaveLength(1)
    expect(adminTemplateSource).toMatch(
      /toggleReviewSort\('existing', 'status'\)[\s\S]*?'existing-course-status-pill'[\s\S]*?getSubmissionStatusClass\(data\.status\)/
    )
    expect(adminViewSource).toContain('Array.from(')
    expect(adminViewSource).not.toContain('writing-mode: vertical-rl')
    expect(adminViewSource).not.toContain('min-inline-size: 4.75rem')
    expect(adminViewSource).toContain('inline-size: fit-content')
    expect(adminViewSource).not.toContain('@container admin-status-cell')
    expect(adminViewSource).toMatch(
      /admin-desktop-status-tag\.soft-badge[\s\S]*?min-height:\s*1\.9rem[\s\S]*?padding:\s*0\.32rem 0\.74rem/
    )
    expect(adminViewSource).toMatch(
      /\.p-tag\.existing-course-status-pill\.soft-badge\.admin-desktop-status-tag[\s\S]*?flex:\s*0 0 auto[\s\S]*?max-inline-size:\s*none[\s\S]*?max-width:\s*none[\s\S]*?block-size:\s*1\.9rem[\s\S]*?padding-block:\s*0\.32rem[\s\S]*?padding-inline:\s*0\.74rem[\s\S]*?border-radius:\s*999px[\s\S]*?font-size:\s*var\(--app-badge-font-size\)[\s\S]*?font-weight:\s*650[\s\S]*?line-height:\s*1\.25[\s\S]*?vertical-align:\s*middle/
    )
    expect(existingCourseStatusPillCss).not.toContain('max-inline-size: 100%')
    expect(existingCourseStatusPillCss).not.toContain('max-width: 100%')
    expect(existingCourseStatusPillCss).not.toMatch(/review-status-(?:pending|approved|takedown)/)
    expect(existingCourseStatusPillCss).not.toMatch(/(?:^|\s)width:\s*\d/)
    expect(adminTemplateSource.match(/class="review-submission-type-cell"/g)).toHaveLength(1)
    expect(adminTemplateSource.match(/'review-desktop-submission-type-tag'/g)).toHaveLength(1)
    expect(adminTemplateSource.match(/class="submission-type-combined-label"/g)).toHaveLength(1)
    expect(adminTemplateSource.match(/submission-type-combined-label__part/g)).toHaveLength(2)
    expect(adminTemplateSource).not.toContain('submission-type-combined-label__separator')
    expect(adminViewSource).toMatch(
      /submission-type-combined-label[\s\S]*?flex-direction:\s*column[\s\S]*?text-align:\s*center[\s\S]*?white-space:\s*nowrap/
    )
    expect(adminViewSource).toMatch(
      /review-card-action-note[\s\S]*?width:\s*max-content[\s\S]*?max-width:\s*100%/
    )
    expect(adminViewSource).toMatch(
      /review-row-action-area[\s\S]*?display:\s*grid[\s\S]*?grid-template-columns:\s*minmax\(0, 1fr\) auto[\s\S]*?align-items:\s*center[\s\S]*?border-top:\s*1px solid color-mix\(in srgb, var\(--border-color\) 78%, transparent\)/
    )
    expect(adminViewSource).toMatch(
      /review-card-action-note\)\s*\{[\s\S]*?grid-column:\s*1[\s\S]*?grid-row:\s*1[\s\S]*?justify-self:\s*start[\s\S]*?width:\s*fit-content[\s\S]*?min-width:\s*0[\s\S]*?margin-inline:\s*0/
    )
    expect(adminViewSource).toMatch(
      /review-card-actions\)\s*\{[\s\S]*?grid-column:\s*2[\s\S]*?grid-row:\s*1[\s\S]*?justify-self:\s*end[\s\S]*?flex-wrap:\s*nowrap[\s\S]*?justify-content:\s*flex-end[\s\S]*?margin:\s*0[\s\S]*?white-space:\s*nowrap/
    )
    expect(adminViewSource).toMatch(
      /@media \(min-width: 1400px\)[\s\S]*?review-row-action-area > \.review-card-actions\)\s*\{[\s\S]*?order:\s*1[\s\S]*?review-row-action-area > \.review-card-action-note\)\s*\{[\s\S]*?order:\s*2/
    )
    expect(adminViewSource).toMatch(
      /@media \(max-width: 640px\)[\s\S]*?review-card-actions\)\s*\{[\s\S]*?justify-content:\s*flex-end/
    )
    expect(adminViewSource).not.toContain('max-width: min(18rem, 100%)')
    expect(adminViewSource.match(/'review-mobile-card-status-badge'/g)).toHaveLength(2)
    expect(adminTemplateSource.match(/trash-name-column/g)).toHaveLength(2)
    expect(adminViewSource).toContain('table-layout: fixed')
    expect(adminViewSource).toContain('@media (max-width: 1399.98px)')
    expect(adminViewSource).toContain('headerClass="trash-deleted-column"')
    expect(adminViewSource).toContain('headerClass="trash-type-column"')
    expect(adminViewSource).toContain(
      'headerClass="admin-desktop-status-column trash-status-column"'
    )
    expect(adminViewSource).toContain('headerClass="trash-actions-column"')
    expect(adminViewSource).toMatch(
      /trash-deleted-column[\s\S]*?width:\s*13%[\s\S]*?trash-type-column[\s\S]*?width:\s*11%[\s\S]*?trash-name-column[\s\S]*?width:\s*25%[\s\S]*?trash-status-column[\s\S]*?width:\s*9%[\s\S]*?trash-dependencies-column[\s\S]*?width:\s*25%[\s\S]*?trash-actions-column[\s\S]*?width:\s*17%/
    )
    expect(adminViewSource).toMatch(
      /\.trash-name-cell small[\s\S]*?min-width:\s*0[\s\S]*?max-width:\s*100%[\s\S]*?white-space:\s*normal[\s\S]*?overflow-wrap:\s*anywhere[\s\S]*?word-break:\s*break-word/
    )
    expect(adminViewSource).toMatch(
      /trash-status-column \.admin-desktop-status-cell[\s\S]*?justify-content:\s*flex-start/
    )
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
    expect(adminViewSource).toContain("{ label: t('系統問題回報'), value: 'system_issue_report' }")
    expect(adminViewSource).toContain("{ label: t('留言回報'), value: 'comment_report' }")
    expect(adminViewSource).toContain("{ label: t('許願回報'), value: 'archive_wish_report' }")
    expect(adminViewSource).toContain("{ label: t('考古題回報'), value: 'archive_report' }")
    expect(wrapper.vm.trashFilterOptions.map((option) => option.value)).toEqual([
      'archive',
      'archive_submission',
      'course_category',
      'course',
      'course_submission',
      'notification',
      'user',
      'archive_report',
      'comment_report',
      'archive_wish_report',
      'system_issue_report',
    ])
    expect(adminTemplateSource).toContain(
      '操作按鈕以後端回傳的可用操作為準；依賴與阻擋文字只用來說明原因。'
    )
    expect(adminTemplateSource).toContain(
      '課程申請是獨立歷史紀錄；關聯課程不存在時仍可正常保留，不代表資料異常。'
    )
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
    expect(wrapper.vm.getTrashStatusLabel('upheld', 'archive_wish_report')).toBe('已刪除')
    expect(wrapper.vm.getTrashStatusSeverity('pending', 'comment_report')).toBe('danger')
    expect(wrapper.vm.getTrashStatusSeverity('upheld', 'comment_report')).toBe('danger')
    expect(wrapper.vm.getTrashStatusSeverity('dismissed', 'comment_report')).toBe('danger')
    expect(wrapper.vm.getTrashStatusSeverity('read', 'system_issue_report')).toBe('danger')
    expect(wrapper.vm.getTrashStatusClass('pending', 'comment_report')).toBe(
      'review-status-deleted'
    )
    expect(wrapper.vm.getTrashStatusSeverity('dismissed', 'archive_wish_report')).toBe('danger')
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
    expect(
      wrapper.vm.getTrashReportDetails({
        item_type: 'archive_wish_report',
        reporter_name: '回報者',
        comment_snapshot: '普通物理 · 王老師 · 114上學期 · 期中考',
      })
    ).toEqual(
      expect.arrayContaining([
        { label: '回報者', value: '回報者' },
        { label: '許願目標', value: '普通物理 · 王老師 · 114上學期 · 期中考' },
      ])
    )
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

    wrapper.vm.userForm.name = 'Short Password'
    wrapper.vm.userForm.email = 'short-password@example.com'
    wrapper.vm.userForm.password = 'secret'
    await wrapper.vm.saveUser()
    expect(createUserMock).not.toHaveBeenCalled()
    expect(wrapper.vm.userFormErrors.password).toBe('密碼至少 8 字')

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

  it('submits Add User only once while a request is in flight', async () => {
    const wrapper = createWrapper()
    await flushPromises()
    createUserMock.mockClear()

    let resolveCreate
    createUserMock.mockImplementationOnce(() => new Promise((resolve) => (resolveCreate = resolve)))
    wrapper.vm.openCreateUserDialog()
    wrapper.vm.userForm.name = 'Single Request'
    wrapper.vm.userForm.email = 'single-request@example.com'
    wrapper.vm.userForm.password = 'StrongPass123'

    const firstRequest = wrapper.vm.saveUser()
    const duplicateRequest = wrapper.vm.saveUser()
    expect(createUserMock).toHaveBeenCalledTimes(1)

    resolveCreate({ data: { id: 101 } })
    await Promise.all([firstRequest, duplicateRequest])
    expect(toastAddMock).toHaveBeenCalledTimes(1)

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
  }, 10_000)

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
      expect(document.documentElement.style.getPropertyValue('--app-effective-font-scale')).toBe(
        scale
      )
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
    wrapper.vm.userForm.password = 'StrongPass123'
    createUserMock.mockRejectedValueOnce({
      response: { status: 400, data: { detail: 'User with this email already exists' } },
    })
    isUnauthorizedErrorMock.mockReturnValueOnce(false)
    await wrapper.vm.saveUser()
    expect(toastAddMock).toHaveBeenCalledWith(
      expect.objectContaining({ detail: '此電子郵件已被其他帳號使用' })
    )

    toastAddMock.mockClear()
    createUserMock.mockRejectedValueOnce(new Error('unauthorized'))
    isUnauthorizedErrorMock.mockReturnValueOnce(true)
    await wrapper.vm.saveUser()
    expect(toastAddMock).not.toHaveBeenCalled()

    wrapper.vm.openNotificationCreateDialog()
    wrapper.vm.notificationForm.title = 'System Notice'
    wrapper.vm.notificationForm.body = 'Content'
    wrapper.vm.notificationForm.title_en = 'System Notice'
    wrapper.vm.notificationForm.body_en = 'Content'
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

    wrapper.vm.activeUserSource = 'nthu'
    wrapper.vm.userSearchQuery = 'bob'
    await wrapper.vm.$nextTick()
    expect(wrapper.vm.filteredUsers).toEqual([
      expect.objectContaining({ id: sampleUsers[1].id, email: sampleUsers[1].email }),
    ])

    wrapper.vm.userSearchQuery = '112022123'
    await wrapper.vm.$nextTick()
    expect(wrapper.vm.filteredUsers).toEqual([expect.objectContaining({ id: sampleUsers[1].id })])

    wrapper.vm.userSearchQuery = '物理學系'
    await wrapper.vm.$nextTick()
    expect(wrapper.vm.filteredUsers).toEqual([expect.objectContaining({ id: sampleUsers[1].id })])

    wrapper.vm.userSearchQuery = '小波'
    await wrapper.vm.$nextTick()
    expect(wrapper.vm.filteredUsers).toEqual([expect.objectContaining({ id: sampleUsers[1].id })])

    wrapper.vm.userSearchQuery = ''
    wrapper.vm.activeUserSource = 'local'
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
