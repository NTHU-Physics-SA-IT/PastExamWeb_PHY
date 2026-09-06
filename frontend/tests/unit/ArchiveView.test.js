import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { ref, nextTick } from 'vue'
import ArchiveView from '@/views/Archive.vue'
import { setLocale } from '@/i18n'

const trackEventMock = vi.hoisted(() => vi.fn())
const isUnauthorizedErrorMock = vi.hoisted(() => vi.fn())
const getCurrentUserMock = vi.hoisted(() =>
  vi.fn(() => ({
    id: 10,
    is_admin: true,
  }))
)
const isAuthenticatedMock = vi.hoisted(() => vi.fn(() => true))

const listCoursesMock = vi.hoisted(() => vi.fn())
const listCategoriesMock = vi.hoisted(() => vi.fn())
const getCourseArchivesMock = vi.hoisted(() => vi.fn())
const getArchiveDownloadUrlMock = vi.hoisted(() => vi.fn())
const getArchivePreviewUrlMock = vi.hoisted(() => vi.fn())
const getArchivePreviewFileMock = vi.hoisted(() => vi.fn())
const getOwnerPendingPreviewFileMock = vi.hoisted(() => vi.fn())
const withdrawOwnerPendingSubmissionMock = vi.hoisted(() => vi.fn())
const deleteArchiveMock = vi.hoisted(() => vi.fn())
const updateArchiveMock = vi.hoisted(() => vi.fn())
const updateArchiveCourseMock = vi.hoisted(() => vi.fn())
const updateArchiveCourseByCategoryAndNameMock = vi.hoisted(() => vi.fn())
const listMySubmissionsMock = vi.hoisted(() => vi.fn())

const toastAddMock = vi.hoisted(() => vi.fn())
const confirmRequireMock = vi.hoisted(() => vi.fn())
const archiveIsDarkThemeMock = ref(false)
const archiveEffectiveThemeMock = ref('light')

let originalCreateObjectURL
let originalRevokeObjectURL
let originalFetch
let consoleErrorSpy
let anchorClickSpy

const sampleCourses = {
  fundamental: [
    { id: 'c1', name: 'Calculus I', name_en: 'Calculus I (English)' },
    { id: 'c2', name: 'Linear Algebra' },
  ],
  required: [{ id: 'c3', name: 'Data Structures' }],
  experience: [],
  optional: [],
  'math-department': [],
  freshman: [
    { id: 'c1', name: 'Calculus I', name_en: 'Calculus I (English)' },
    { id: 'c2', name: 'Linear Algebra' },
  ],
  sophomore: [{ id: 'c3', name: 'Data Structures' }],
  junior: [],
  senior: [],
  graduate: [],
  interdisciplinary: [],
}

const baseArchives = [
  {
    id: 'a1',
    academic_year: '2023',
    name: 'Midterm',
    archive_type: 'midterm',
    professor: 'Prof. Chen',
    has_answers: true,
    uploader_id: 10,
    download_count: 3,
    source_submission_ids: [44],
  },
  {
    id: 'a2',
    academic_year: '2022',
    name: 'Final',
    archive_type: 'final',
    professor: 'Prof. Wang',
    has_answers: false,
    uploader_id: 11,
    download_count: 1,
  },
]

const updatedArchives = baseArchives.map((archive, index) => ({
  ...archive,
  download_count: archive.download_count + index + 1,
}))

const ownerPendingSubmission = {
  item_kind: 'pending_submission',
  submission_id: 71,
  course_id: 'c1',
  academic_year: 20231,
  name: 'midterm2',
  archive_type: 'midterm',
  professor: 'Prof. Owner',
  has_answers: false,
  status: 'pending',
  can_preview: true,
  can_edit: true,
  can_withdraw: true,
}

vi.mock('@/api', () => ({
  courseService: {
    listCourses: listCoursesMock,
    listCategories: listCategoriesMock,
    getCourseArchives: getCourseArchivesMock,
  },
  archiveService: {
    getArchiveDownloadUrl: getArchiveDownloadUrlMock,
    getArchivePreviewUrl: getArchivePreviewUrlMock,
    getArchivePreviewFile: getArchivePreviewFileMock,
    getOwnerPendingPreviewFile: getOwnerPendingPreviewFileMock,
    withdrawOwnerPendingSubmission: withdrawOwnerPendingSubmissionMock,
    deleteArchive: deleteArchiveMock,
    updateArchive: updateArchiveMock,
    updateArchiveCourse: updateArchiveCourseMock,
    updateArchiveCourseByCategoryAndName: updateArchiveCourseByCategoryAndNameMock,
    listMySubmissions: listMySubmissionsMock,
  },
}))

vi.mock('@/components/PdfPreviewModal.vue', () => ({
  default: {
    name: 'PdfPreviewModal',
    template: '<div><slot /></div>',
    props: [
      'visible',
      'previewUrl',
      'courseId',
      'archiveId',
      'loading',
      'error',
      'showDownload',
      'christmas',
    ],
    emits: ['update:visible', 'download', 'hide', 'error'],
  },
}))

vi.mock('@/components/UploadArchiveDialog.vue', () => ({
  default: {
    name: 'UploadArchiveDialog',
    template: '<div class="upload-archive-dialog-stub"></div>',
    props: ['modelValue', 'mode', 'submissionId', 'prefill', 'christmas'],
    emits: ['update:modelValue', 'upload-success', 'stale'],
  },
}))

vi.mock('@/utils/auth', () => ({
  getCurrentUser: getCurrentUserMock,
  isAuthenticated: isAuthenticatedMock,
}))

vi.mock('@/utils/useTheme', () => ({
  useTheme: () => ({
    isDarkTheme: archiveIsDarkThemeMock,
    effectiveTheme: archiveEffectiveThemeMock,
  }),
}))

vi.mock('@/utils/analytics', () => ({
  trackEvent: trackEventMock,
  EVENTS: {
    FILTER_ARCHIVES: 'filter-archives',
    SEARCH_COURSE: 'search-course',
    SELECT_COURSE: 'select-course',
    DOWNLOAD_ARCHIVE: 'download-archive',
    PREVIEW_ARCHIVE: 'preview-archive',
    EDIT_ARCHIVE: 'edit-archive',
    DELETE_ARCHIVE: 'delete-archive',
    UPLOAD_ARCHIVE: 'upload-archive',
    TOGGLE_SIDEBAR: 'toggle-sidebar',
  },
}))

vi.mock('@/utils/http', () => ({
  isUnauthorizedError: isUnauthorizedErrorMock,
}))

const slotDivTemplate = '<div><slot /></div>'
const componentStubs = {
  InputText: { template: slotDivTemplate },
  Button: { template: slotDivTemplate },
  PanelMenu: { template: slotDivTemplate },
  Drawer: { template: slotDivTemplate },
  Tag: { template: slotDivTemplate },
  Toolbar: { template: '<div><slot name="start" /></div>' },
  Select: { template: slotDivTemplate },
  Checkbox: { template: slotDivTemplate },
  ProgressSpinner: { template: '<div class="spinner"><slot /></div>' },
  Accordion: { template: slotDivTemplate },
  AccordionPanel: { template: slotDivTemplate },
  AccordionHeader: { template: slotDivTemplate },
  AccordionContent: { template: slotDivTemplate },
  DataTable: { template: slotDivTemplate },
  Column: { template: '<template />' },
  Tabs: { template: slotDivTemplate },
  TabList: { template: slotDivTemplate },
  TabPanels: { template: slotDivTemplate },
  TabPanel: { template: slotDivTemplate },
  Dialog: { template: slotDivTemplate },
  AutoComplete: { template: slotDivTemplate },
  DatePicker: { template: slotDivTemplate },
  Divider: { template: '<div></div>' },
}

describe('ArchiveView', () => {
  beforeEach(() => {
    consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    vi.useFakeTimers()
    globalThis.localStorage?.clear?.()
    sessionStorage.clear()
    trackEventMock.mockReset()
    getCurrentUserMock.mockReturnValue({ id: 10, is_admin: true })
    isAuthenticatedMock.mockReturnValue(true)
    isUnauthorizedErrorMock.mockReturnValue(false)
    archiveIsDarkThemeMock.value = false
    archiveEffectiveThemeMock.value = 'light'
    listCoursesMock.mockResolvedValue({ data: sampleCourses })
    listCategoriesMock.mockResolvedValue({ data: [] })
    getCourseArchivesMock.mockReset()
    getCourseArchivesMock
      .mockResolvedValueOnce({ data: baseArchives })
      .mockResolvedValueOnce({ data: updatedArchives })
      .mockResolvedValue({ data: baseArchives })

    getArchiveDownloadUrlMock.mockResolvedValue({
      data: { url: 'https://example.com/archive.pdf' },
    })
    getArchivePreviewUrlMock.mockResolvedValue({
      data: { url: 'https://example.com/preview.pdf' },
    })
    getArchivePreviewFileMock.mockResolvedValue({ data: new Blob(['dummy']) })
    getOwnerPendingPreviewFileMock.mockResolvedValue({ data: new Blob(['pending']) })
    withdrawOwnerPendingSubmissionMock.mockResolvedValue({ data: { success: true } })
    deleteArchiveMock.mockResolvedValue()
    updateArchiveMock.mockResolvedValue()
    updateArchiveCourseMock.mockResolvedValue()
    updateArchiveCourseByCategoryAndNameMock.mockResolvedValue()
    listMySubmissionsMock.mockResolvedValue({ data: [] })
    toastAddMock.mockReset()
    confirmRequireMock.mockReset()
    confirmRequireMock.mockImplementation(({ accept }) => accept && accept())

    originalFetch = globalThis.fetch
    originalCreateObjectURL = window.URL.createObjectURL
    originalRevokeObjectURL = window.URL.revokeObjectURL
    globalThis.fetch = vi.fn(() =>
      Promise.resolve({
        blob: () => Promise.resolve(new Blob(['dummy'])),
      })
    )
    window.URL.createObjectURL = vi.fn(() => 'blob:url')
    window.URL.revokeObjectURL = vi.fn()
    anchorClickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    window.innerWidth = 1024
  })

  it('opts authenticated owners into pending rows without mixing archive and submission ids', async () => {
    getCurrentUserMock.mockReturnValue({ id: 10, is_admin: false })
    isAuthenticatedMock.mockReturnValue(true)
    getCourseArchivesMock.mockReset()
    getCourseArchivesMock.mockResolvedValue({
      data: [
        { ...baseArchives[0], item_kind: 'archive', archive_id: 'a1' },
        ownerPendingSubmission,
      ],
    })

    const wrapper = mount(ArchiveView, {
      global: {
        provide: {
          toast: { add: toastAddMock },
          confirm: { require: confirmRequireMock },
          sidebarVisible: ref(true),
        },
        stubs: componentStubs,
      },
    })
    await flushPromises()
    wrapper.vm.filterBySubject({ label: 'Calculus I', id: 'c1' })
    await flushPromises()

    expect(getCourseArchivesMock).toHaveBeenLastCalledWith('c1', {
      includeOwnerPending: true,
    })
    const rows = wrapper.vm.groupedArchives.flatMap((group) => group.list)
    const pending = rows.find((row) => row.itemKind === 'pending_submission')
    expect(pending).toMatchObject({ id: null, archiveId: null, submissionId: 71 })
    expect(wrapper.text()).toContain('midterm2')
    expect(wrapper.text()).toContain('待審核')
    expect(wrapper.text()).toContain('投稿編號：#71')
    expect(wrapper.findAll('.archive-action-preview')).toHaveLength(2)
    expect(wrapper.findAll('.archive-action-edit')).toHaveLength(1)
    expect(wrapper.findAll('.archive-action-delete')).toHaveLength(2)
    expect(wrapper.findAll('.archive-action-download')).toHaveLength(1)

    await wrapper.vm.previewArchive(pending)
    expect(getOwnerPendingPreviewFileMock).toHaveBeenCalledWith(71)
    expect(wrapper.vm.selectedArchive.previewUrl).toBe('blob:url')
    expect(wrapper.vm.isPendingSubmission(wrapper.vm.selectedArchive)).toBe(true)
    expect(wrapper.findComponent({ name: 'PdfPreviewModal' }).props('showDownload')).toBe(false)

    await wrapper.vm.openEditDialog(pending)
    await nextTick()
    expect(wrapper.vm.showPendingEditDialog).toBe(true)
    expect(wrapper.vm.pendingEditSubmission).toMatchObject({
      submissionId: 71,
      course_id: 'c1',
      name: 'midterm2',
    })
    const editDialog = wrapper
      .findAllComponents({ name: 'UploadArchiveDialog' })
      .find((dialog) => dialog.props('mode') === 'edit')
    expect(editDialog.props()).toMatchObject({ mode: 'edit', submissionId: 71 })

    wrapper.vm.confirmDelete(pending)
    await flushPromises()
    expect(withdrawOwnerPendingSubmissionMock).toHaveBeenCalledWith(71)
    expect(deleteArchiveMock).not.toHaveBeenCalled()

    wrapper.vm.closePreview()
    expect(window.URL.revokeObjectURL).toHaveBeenCalledWith('blob:url')
    wrapper.unmount()
  })

  it('keeps anonymous and admin archive requests out of the owner pending overlay', async () => {
    const mountForCurrentIdentity = () =>
      mount(ArchiveView, {
        global: {
          provide: {
            toast: { add: toastAddMock },
            confirm: { require: confirmRequireMock },
            sidebarVisible: ref(true),
          },
          stubs: componentStubs,
        },
      })

    getCurrentUserMock.mockReturnValue(null)
    isAuthenticatedMock.mockReturnValue(false)
    let wrapper = mountForCurrentIdentity()
    await flushPromises()
    wrapper.vm.filterBySubject({ label: 'Calculus I', id: 'c1' })
    await flushPromises()
    expect(getCourseArchivesMock).toHaveBeenLastCalledWith('c1', {
      includeOwnerPending: false,
    })
    wrapper.unmount()

    getCurrentUserMock.mockReturnValue({ id: 1, is_admin: true })
    isAuthenticatedMock.mockReturnValue(true)
    wrapper = mountForCurrentIdentity()
    await flushPromises()
    wrapper.vm.filterBySubject({ label: 'Calculus I', id: 'c1' })
    await flushPromises()
    expect(getCourseArchivesMock).toHaveBeenLastCalledWith('c1', {
      includeOwnerPending: false,
    })
    wrapper.unmount()
  })

  it('refreshes and invalidates pending actions after stale state conflicts', async () => {
    getCurrentUserMock.mockReturnValue({ id: 10, is_admin: false })
    isAuthenticatedMock.mockReturnValue(true)
    getCourseArchivesMock.mockReset()
    getCourseArchivesMock.mockResolvedValue({ data: [ownerPendingSubmission] })
    withdrawOwnerPendingSubmissionMock.mockRejectedValueOnce({
      response: {
        status: 409,
        data: { detail: { code: 'archive_submission_stale_state' } },
      },
    })
    const wrapper = mount(ArchiveView, {
      global: {
        provide: {
          toast: { add: toastAddMock },
          confirm: { require: confirmRequireMock },
          sidebarVisible: ref(true),
        },
        stubs: componentStubs,
      },
    })
    await flushPromises()
    wrapper.vm.filterBySubject({ label: 'Calculus I', id: 'c1' })
    await flushPromises()
    const pending = wrapper.vm.groupedArchives[0].list[0]

    getOwnerPendingPreviewFileMock.mockRejectedValueOnce({
      response: {
        status: 409,
        data: { detail: { code: 'archive_submission_stale_state' } },
      },
    })
    const callsBeforePreview = getCourseArchivesMock.mock.calls.length
    await wrapper.vm.previewArchive(pending)
    expect(wrapper.vm.showPreview).toBe(false)
    expect(getCourseArchivesMock.mock.calls.length).toBe(callsBeforePreview + 1)
    expect(toastAddMock).toHaveBeenCalledWith(
      expect.objectContaining({ detail: '投稿狀態已變更，無法再預覽' })
    )

    const callsBeforeWithdraw = getCourseArchivesMock.mock.calls.length
    await wrapper.vm.withdrawPendingSubmission(pending)
    expect(getCourseArchivesMock.mock.calls.length).toBe(callsBeforeWithdraw + 1)
    expect(toastAddMock).toHaveBeenCalledWith(
      expect.objectContaining({ detail: '投稿狀態已變更，無法再刪除' })
    )

    wrapper.vm.pendingEditSubmission = { submissionId: 71 }
    wrapper.vm.showPendingEditDialog = true
    await wrapper.vm.handlePendingEditStale()
    expect(wrapper.vm.showPendingEditDialog).toBe(false)
    expect(wrapper.vm.pendingEditSubmission).toBe(null)

    wrapper.vm.pendingEditSubmission = { submissionId: 71 }
    wrapper.vm.showPendingEditDialog = true
    const callsBeforeSuccess = getCourseArchivesMock.mock.calls.length
    await wrapper.vm.handlePendingEditSuccess()
    expect(getCourseArchivesMock.mock.calls.length).toBe(callsBeforeSuccess + 1)
    expect(wrapper.vm.showPendingEditDialog).toBe(false)
    wrapper.unmount()
  })

  afterEach(() => {
    setLocale('zh-TW')
    consoleErrorSpy?.mockRestore()
    vi.useRealTimers()
    vi.clearAllMocks()
    globalThis.fetch = originalFetch
    window.URL.createObjectURL = originalCreateObjectURL
    window.URL.revokeObjectURL = originalRevokeObjectURL
    anchorClickSpy.mockRestore()
  })

  it('formats pre-100 and 100-plus academic term groups without changing raw ordering', async () => {
    getCourseArchivesMock.mockReset()
    getCourseArchivesMock.mockResolvedValue({
      data: [
        { ...baseArchives[0], id: 'term-992', academic_year: 992 },
        { ...baseArchives[1], id: 'term-1002', academic_year: 1002 },
      ],
    })
    const wrapper = mount(ArchiveView, {
      global: {
        provide: {
          toast: { add: toastAddMock },
          confirm: { require: confirmRequireMock },
          sidebarVisible: ref(true),
        },
        stubs: componentStubs,
      },
    })

    await flushPromises()
    wrapper.vm.filterBySubject({ label: 'Calculus I', id: 'c1' })
    await flushPromises()

    expect(wrapper.vm.groupedArchives.map(({ year }) => year)).toEqual([1002, 992])
    expect(wrapper.text()).toContain('99下學期')
    expect(wrapper.text()).toContain('100下學期')
    expect(wrapper.vm.years).toEqual([
      { name: '100下學期', code: '1002' },
      { name: '99下學期', code: '992' },
    ])

    wrapper.unmount()
  })

  it('applies the Christmas presentation only for the active Christmas theme', async () => {
    archiveEffectiveThemeMock.value = 'christmas'
    const wrapper = mount(ArchiveView, {
      global: {
        provide: {
          toast: { add: toastAddMock },
          confirm: { require: confirmRequireMock },
          sidebarVisible: ref(true),
        },
        stubs: componentStubs,
      },
    })

    expect(wrapper.classes()).toContain('archive-christmas')
    expect(wrapper.classes()).not.toContain('archive-dark')
    expect(wrapper.get('.archive-edit-dialog').classes()).toContain('archive-edit-dialog-christmas')
    expect(wrapper.getComponent({ name: 'PdfPreviewModal' }).props('christmas')).toBe(true)
    expect(
      wrapper
        .findAllComponents({ name: 'UploadArchiveDialog' })
        .map((dialog) => dialog.props('christmas'))
    ).toEqual([true, true, true])

    archiveEffectiveThemeMock.value = 'dark'
    archiveIsDarkThemeMock.value = true
    await nextTick()

    expect(wrapper.classes()).not.toContain('archive-christmas')
    expect(wrapper.classes()).toContain('archive-dark')
    expect(wrapper.get('.archive-edit-dialog').classes()).not.toContain(
      'archive-edit-dialog-christmas'
    )
    expect(wrapper.getComponent({ name: 'PdfPreviewModal' }).props('christmas')).toBe(false)
    expect(
      wrapper
        .findAllComponents({ name: 'UploadArchiveDialog' })
        .map((dialog) => dialog.props('christmas'))
    ).toEqual([false, false, false])

    wrapper.unmount()
  })

  it('uses the Route 1 information-card and unified action semantics for Christmas archives', async () => {
    archiveEffectiveThemeMock.value = 'christmas'
    const wrapper = mount(ArchiveView, {
      global: {
        provide: {
          toast: { add: toastAddMock },
          confirm: { require: confirmRequireMock },
          sidebarVisible: ref(true),
        },
        stubs: componentStubs,
      },
    })

    await flushPromises()
    wrapper.vm.filterBySubject({ label: 'Calculus I', id: 'c1' })
    await flushPromises()

    const archiveCards = wrapper.findAll('.archive-record-card')
    expect(archiveCards).toHaveLength(2)
    expect(
      archiveCards.every((card) => card.classes().includes('archive-record-card--information'))
    ).toBe(true)

    const examTypeTags = wrapper.findAll('.exam-type-tag')
    expect(examTypeTags.map((tag) => tag.text())).toEqual(['期中考', '期末考'])

    const neutralActions = wrapper.findAll('.archive-action-neutral')
    expect(neutralActions).toHaveLength(6)
    expect(neutralActions.map((action) => action.attributes('aria-label')).sort()).toEqual([
      '下載',
      '下載',
      '編輯',
      '編輯',
      '預覽',
      '預覽',
    ])

    const dangerActions = wrapper.findAll('.archive-action-danger')
    expect(dangerActions).toHaveLength(2)
    expect(dangerActions.every((action) => action.attributes('aria-label') === '刪除')).toBe(true)

    wrapper.unmount()
  })

  it('uses one deep blue-gray Christmas color for every academic-term header', () => {
    const archiveViewSource = readFileSync(
      resolve(globalThis.process.cwd(), 'src/views/Archive.vue'),
      'utf8'
    )
    const semesterHeaderRule = archiveViewSource.match(
      /\.archive-christmas :deep\(\.p-accordionheader\) \{([\s\S]*?)\n\}/
    )
    const semesterSnowRule = archiveViewSource.match(
      /\.archive-christmas :deep\(\.p-accordionheader\)::before,[\s\S]*?\.archive-christmas :deep\(\.p-accordionheader\)::after \{([\s\S]*?)\n\}/
    )
    const semesterSurfaceRule = archiveViewSource.match(
      /\.archive-christmas :deep\(\.p-accordionpanel\),[\s\S]*?\.archive-christmas :deep\(\.p-accordioncontent-content\) \{([\s\S]*?)\n\}/
    )
    const semesterSurfacePseudoRule = archiveViewSource.match(
      /\.archive-christmas :deep\(\.p-accordionpanel\)::before,[\s\S]*?\.archive-christmas :deep\(\.p-accordioncontent-content\)::after \{([\s\S]*?)\n\}/
    )

    expect(semesterHeaderRule).not.toBeNull()
    expect(semesterHeaderRule[1]).toContain('background: #293f52 !important;')
    expect(semesterHeaderRule[1]).toContain('background-image: none !important;')
    expect(semesterHeaderRule[1]).toContain('box-shadow: none !important;')
    expect(semesterHeaderRule[1]).not.toContain('gradient')
    expect(semesterSnowRule?.[1]).toContain('content: none !important;')
    expect(semesterSnowRule?.[1]).toContain('background-image: none !important;')
    expect(semesterSurfaceRule?.[1]).toContain('background: #102f35 !important;')
    expect(semesterSurfaceRule?.[1]).toContain('background-image: none !important;')
    expect(semesterSurfaceRule?.[1]).toContain('backdrop-filter: none !important;')
    expect(semesterSurfaceRule?.[1]).toContain('mix-blend-mode: normal;')
    expect(semesterSurfaceRule?.[1]).toContain('opacity: 1;')
    expect(semesterSurfacePseudoRule?.[1]).toContain('content: none !important;')
    expect(semesterSurfacePseudoRule?.[1]).toContain('background-image: none !important;')
  })

  it('uses the shared page gradient once for selected courses and solid blue-gray archive records', () => {
    const archiveViewSource = readFileSync(
      resolve(globalThis.process.cwd(), 'src/views/Archive.vue'),
      'utf8'
    )
    const selectedCourseContainerRule = archiveViewSource.match(
      /\.archive-christmas :deep\(\.active-course-menu-item\) \{([\s\S]*?)\n\}/
    )
    const selectedCourseRule = archiveViewSource.match(
      /\.archive-christmas :deep\(\.active-course-menu-item \.p-panelmenu-item-content\),[\s\S]*?\.active-course-menu-item > \.p-panelmenu-item-link\) \{([\s\S]*?)\n\}/
    )
    const selectedSearchResultRule = archiveViewSource.match(
      /\.archive-christmas \.active-course-search-result \{([\s\S]*?)\n\}/
    )
    const mobileSelectedCourseSurfaceRule = archiveViewSource.match(
      /:global\(\.mobile-drawer\.mobile-drawer-christmas \.active-course-menu-item\),\s*:global\(\.mobile-drawer\.mobile-drawer-christmas \.active-course-search-result\) \{([\s\S]*?)\n {2}\}/
    )
    const mobileSelectedCourseContentRule = archiveViewSource.match(
      /:global\(\s*\.mobile-drawer\.mobile-drawer-christmas \.active-course-menu-item \.p-panelmenu-item-content\s*\),\s*:global\(\.mobile-drawer\.mobile-drawer-christmas \.active-course-menu-item \.p-panelmenu-item-link\) \{([\s\S]*?)\n {2}\}/
    )
    const selectedCourseContainerPseudoRule = archiveViewSource.match(
      /\.archive-christmas :deep\(\.active-course-menu-item\)::before,[\s\S]*?\.archive-christmas :deep\(\.active-course-menu-item\)::after \{([\s\S]*?)\n\}/
    )
    const selectedCoursePseudoRule = archiveViewSource.match(
      /\.archive-christmas :deep\(\.active-course-menu-item \.p-panelmenu-item-content\)::before,[\s\S]*?\.archive-christmas \.active-course-search-result::after \{([\s\S]*?)\n\}/
    )
    const archiveRecordRule = archiveViewSource.match(
      /\.archive-christmas \.archive-record-card \{([\s\S]*?)\n\}/
    )

    expect(selectedCourseContainerRule?.[1]).toContain(
      'background-color: var(--christmas-page-background-color) !important;'
    )
    expect(selectedCourseContainerRule?.[1]).toContain(
      'background-image: var(--christmas-page-background-gradient) !important;'
    )
    expect(selectedCourseContainerRule?.[1]).toContain('box-shadow: none !important;')
    expect(selectedCourseContainerPseudoRule?.[1]).toContain('content: none !important;')
    expect(selectedCourseContainerPseudoRule?.[1]).toContain('background-image: none !important;')
    expect(selectedCourseRule?.[1]).toContain('background: transparent !important;')
    expect(selectedCourseRule?.[1]).toContain('background-image: none !important;')
    expect(selectedCourseRule?.[1]).toContain('box-shadow: none !important;')
    expect(selectedCourseRule?.[1]).toContain('backdrop-filter: none !important;')
    expect(selectedCourseRule?.[1]).toContain('filter: none !important;')
    expect(selectedCourseRule?.[1]).not.toContain('gradient')
    expect(selectedSearchResultRule?.[1]).toContain(
      'background-color: var(--christmas-page-background-color) !important;'
    )
    expect(selectedSearchResultRule?.[1]).toContain(
      'background-image: var(--christmas-page-background-gradient) !important;'
    )
    expect(selectedCoursePseudoRule?.[1]).toContain('content: none !important;')
    expect(selectedCoursePseudoRule?.[1]).toContain('background-image: none !important;')
    expect(mobileSelectedCourseSurfaceRule?.[1]).toContain(
      'background-color: var(--christmas-page-background-color) !important;'
    )
    expect(mobileSelectedCourseSurfaceRule?.[1]).toContain(
      'background-image: var(--christmas-page-background-gradient) !important;'
    )
    expect(mobileSelectedCourseSurfaceRule?.[1]).toContain('box-shadow: none !important;')
    expect(mobileSelectedCourseContentRule?.[1]).toContain('background: transparent !important;')
    expect(mobileSelectedCourseContentRule?.[1]).toContain('background-image: none !important;')
    expect(archiveRecordRule?.[1]).toContain('background: #3e5f72 !important;')
    expect(archiveRecordRule?.[1]).toContain('background-image: none !important;')
    expect(archiveRecordRule?.[1]).toContain('box-shadow: none;')
    expect(archiveRecordRule?.[1]).toContain('backdrop-filter: none;')
    expect(archiveRecordRule?.[1]).toContain('filter: none;')
    expect(archiveRecordRule?.[1]).toContain('mix-blend-mode: normal;')
    expect(archiveRecordRule?.[1]).toContain('opacity: 1;')
    expect(archiveRecordRule?.[1]).not.toContain('gradient')
    expect(archiveViewSource).not.toMatch(/\.archive-record-card(?::nth|--(?:final|quiz|midterm))/)
    expect(archiveViewSource.match(/@media/g) || []).toHaveLength(11)

    const classicSemesterHeaderRule = archiveViewSource.match(
      /(?<!archive-christmas ):deep\(\.p-accordionheader\) \{([\s\S]*?)\n\}/
    )
    const classicArchiveRecordRule = archiveViewSource.match(
      /(?<!archive-christmas )\.archive-record-card \{([\s\S]*?)\n\}/
    )
    expect(classicSemesterHeaderRule?.[1]).toContain('background: #f0f7f4;')
    expect(classicArchiveRecordRule?.[1]).toContain('background: #ffffff;')
    expect(archiveViewSource).toContain('.archive-christmas .exam-type-tag--midterm {')
    expect(archiveViewSource).toContain('.archive-christmas .exam-type-tag--quiz {')
    expect(archiveViewSource).toContain('archive-action-preview archive-action-neutral')
    expect(archiveViewSource).toContain('archive-action-download archive-action-neutral')
  })

  it('lets the desktop sidebar share the page background and gives the mobile drawer its gradient', () => {
    const archiveViewSource = readFileSync(
      resolve(globalThis.process.cwd(), 'src/views/Archive.vue'),
      'utf8'
    )
    const desktopSidebarRule = archiveViewSource.match(
      /\.archive-christmas \.sidebar \{([\s\S]*?)\n\}/
    )
    const mobileSidebarRule = archiveViewSource.match(
      /:global\(\.mobile-drawer\.mobile-drawer-christmas \.p-drawer-content\),[\s\S]*?\.p-sidebar-content\) \{([\s\S]*?)\n\}/
    )
    const mobileSidebarShellRule = archiveViewSource.match(
      /:global\(\.mobile-drawer\.mobile-drawer-christmas\.p-drawer\),[\s\S]*?\.p-sidebar\) \{([\s\S]*?)\n\}/
    )
    const desktopUploadSectionRule = archiveViewSource.match(
      /\.archive-christmas \.upload-section \{([\s\S]*?)\n\}/
    )
    const mobileUploadSectionRule = archiveViewSource.match(
      /:global\(\.mobile-drawer\.mobile-drawer-christmas \.mobile-upload-section\) \{([\s\S]*?)\n\}/
    )

    expect(desktopSidebarRule?.[1]).toContain('background: transparent;')
    expect(desktopSidebarRule?.[1]).toContain('background-image: none;')
    expect(desktopSidebarRule?.[1]).toContain('border-right-color: transparent;')
    expect(desktopSidebarRule?.[1]).toContain('box-shadow: none;')
    expect(desktopUploadSectionRule?.[1]).toContain('border-top-color: transparent;')
    expect(desktopUploadSectionRule?.[1]).toContain('background: transparent;')
    expect(mobileSidebarShellRule?.[1]).toContain(
      'background-color: var(--christmas-page-background-color) !important;'
    )
    expect(mobileSidebarShellRule?.[1]).toContain(
      'background-image: var(--christmas-page-background-gradient) !important;'
    )
    expect(mobileSidebarShellRule?.[1]).toContain('border-right-color: transparent !important;')
    expect(mobileSidebarShellRule?.[1]).toContain('box-shadow: none;')
    expect(mobileSidebarRule?.[1]).toContain(
      'background-color: var(--christmas-page-background-color) !important;'
    )
    expect(mobileSidebarRule?.[1]).toContain(
      'background-image: var(--christmas-page-background-gradient) !important;'
    )
    expect(mobileUploadSectionRule?.[1]).toContain('border-top-color: transparent !important;')
    expect(mobileUploadSectionRule?.[1]).toContain('background: transparent !important;')
    expect(mobileUploadSectionRule?.[1]).toContain('box-shadow: none;')
  })

  it('lets the course title bar share the continuous Christmas page background', () => {
    const archiveViewSource = readFileSync(
      resolve(globalThis.process.cwd(), 'src/views/Archive.vue'),
      'utf8'
    )
    const subjectHeaderRule = archiveViewSource.match(
      /\.archive-christmas \.subject-header \{([\s\S]*?)\n\}/
    )
    const subjectHeaderPseudoRule = archiveViewSource.match(
      /\.archive-christmas \.subject-header::after \{([\s\S]*?)\n\}/
    )

    expect(subjectHeaderRule?.[1]).toContain('border-bottom-color: transparent;')
    expect(subjectHeaderRule?.[1]).toContain('background: transparent;')
    expect(subjectHeaderRule?.[1]).toContain('box-shadow: none;')
    expect(subjectHeaderRule?.[1]).not.toContain('gradient')
    expect(subjectHeaderPseudoRule?.[1]).toContain('content: none;')
    expect(subjectHeaderPseudoRule?.[1]).toContain('background: none;')
  })

  it('gives every Christmas archive filter and its popup a contrasting festive palette', () => {
    const archiveViewSource = readFileSync(
      resolve(globalThis.process.cwd(), 'src/views/Archive.vue'),
      'utf8'
    )
    const styleSource = readFileSync(resolve(globalThis.process.cwd(), 'src/style.css'), 'utf8')
    const filterSelects = archiveViewSource.match(
      /<Select\s+inputId="archive-filter-(?:year|professor|type)"[\s\S]*?\/>/g
    )

    expect(filterSelects).toHaveLength(3)
    filterSelects.forEach((select) => {
      expect(select).toContain("'archive-filter-overlay-christmas': effectiveTheme === 'christmas'")
    })

    const closedFilterRule = archiveViewSource.match(
      /\.archive-christmas \.archive-filter-controls :deep\(\.p-select\) \{([\s\S]*?)\n\}/
    )
    expect(closedFilterRule?.[1]).toContain('background: #e7dcc4;')
    expect(closedFilterRule?.[1]).toContain('color: #294f47;')

    const popupRule = styleSource.match(/body \.archive-filter-overlay-christmas \{([\s\S]*?)\n\}/)
    expect(popupRule?.[1]).toContain('background: #e7dcc4;')
    expect(styleSource).toContain(
      'body .archive-filter-overlay-christmas .p-select-option-selected {'
    )
  })

  it('uses the upload dialog cream background for Christmas submission history', () => {
    const archiveViewSource = readFileSync(
      resolve(globalThis.process.cwd(), 'src/views/Archive.vue'),
      'utf8'
    )
    const styleSource = readFileSync(resolve(globalThis.process.cwd(), 'src/style.css'), 'utf8')
    const dialogRootRule = styleSource.match(
      /body \.p-dialog\.my-submissions-dialog-christmas \{([\s\S]*?)\n\}/
    )
    const dialogSurfacesRule = styleSource.match(
      /body \.p-dialog\.my-submissions-dialog-christmas \.p-dialog-header,[\s\S]*?\.p-dialog-content \{([\s\S]*?)\n\}/
    )

    expect(archiveViewSource).toContain(
      "'my-submissions-dialog-christmas': effectiveTheme === 'christmas'"
    )
    expect(dialogRootRule?.[1]).toContain('overflow: hidden;')
    expect(dialogRootRule?.[1]).toContain('border-radius: 0.9rem;')
    expect(dialogRootRule?.[1]).toContain('background: #f5eedc;')
    expect(dialogSurfacesRule?.[1]).toContain('background: #f5eedc !important;')
    expect(dialogSurfacesRule?.[1]).toContain('color: #173d37;')
  })

  it('uses warm Christmas panels for submission history content', () => {
    const styleSource = readFileSync(resolve(globalThis.process.cwd(), 'src/style.css'), 'utf8')
    const contentPanelsRule = styleSource.match(
      /body \.p-dialog\.my-submissions-dialog-christmas \.submission-summary,[\s\S]*?\.submission-empty \{([\s\S]*?)\n\}/
    )

    expect(contentPanelsRule?.[1]).toContain('background: #eadfd9;')
    expect(contentPanelsRule?.[1]).toContain('border-color: rgba(107, 53, 60, 0.2);')
  })

  it('scopes every edit-form popup panel to the Christmas overlay presentation', () => {
    const archiveViewSource = readFileSync(
      resolve(globalThis.process.cwd(), 'src/views/Archive.vue'),
      'utf8'
    )
    const styleSource = readFileSync(resolve(globalThis.process.cwd(), 'src/style.css'), 'utf8')
    const overlayClassBindings = archiveViewSource.match(
      /'archive-edit-overlay-christmas': effectiveTheme === 'christmas'/g
    )

    expect(overlayClassBindings).toHaveLength(5)
    expect(styleSource).toContain('body .archive-edit-overlay-christmas {')
    expect(styleSource).toContain(
      'body .archive-edit-overlay-christmas .p-datepicker-year-selected'
    )
    const examTypeSelect = archiveViewSource.match(
      /<Select\s+inputId="archive-edit-type"[\s\S]*?\/>/
    )?.[0]

    expect(examTypeSelect).toContain("'data-christmas-snow-control':")
    expect(examTypeSelect).toContain("effectiveTheme === 'christmas' ? 'true' : undefined")
  })

  it('reuses the Christmas preview and download treatments for edit-dialog actions', () => {
    const styleSource = readFileSync(resolve(globalThis.process.cwd(), 'src/style.css'), 'utf8')
    const cancelRule = styleSource.match(
      /body \.p-dialog\.archive-edit-dialog-christmas \.p-button\.archive-edit-cancel-button(?:,[^{]+)? \{([\s\S]*?)\n\}/
    )
    const saveRule = styleSource.match(
      /body \.p-dialog\.archive-edit-dialog-christmas \.p-button\.archive-edit-save-button \{([\s\S]*?)\n\}/
    )

    expect(cancelRule?.[1]).toContain('background: #d7edf5;')
    expect(cancelRule?.[1]).toContain('color: #245368;')
    expect(saveRule?.[1]).toContain('background: linear-gradient(135deg, #3d8a64, #2d6c52);')
    expect(saveRule?.[1]).toContain('color: #f5fff7;')
    expect(styleSource).toContain('0 0 0.72rem rgba(255, 201, 59, 0.34)')
  })

  it('uses the Christmas download treatment for desktop and mobile secondary sidebar actions', () => {
    const archiveViewSource = readFileSync(
      resolve(globalThis.process.cwd(), 'src/views/Archive.vue'),
      'utf8'
    )
    const sidebarActionClasses = archiveViewSource.match(
      /class="w-full archive-sidebar-download-action"/g
    )
    const desktopRule = archiveViewSource.match(
      /\.archive-christmas\s+\.upload-section\s+:deep\(\.p-button\.p-button-secondary\.p-button-outlined\.archive-sidebar-download-action\) \{([\s\S]*?)\n\}/
    )
    const mobileRule = archiveViewSource.match(
      /:global\(\s*\.mobile-drawer\.mobile-drawer-christmas\s+\.mobile-upload-section\s+\.p-button\.p-button-secondary\.p-button-outlined\.archive-sidebar-download-action\s*\) \{([\s\S]*?)\n\}/
    )

    expect(sidebarActionClasses).toHaveLength(4)
    expect(desktopRule?.[1]).toContain('background: linear-gradient(135deg, #3d8a64, #2d6c52);')
    expect(mobileRule?.[1]).toContain(
      'background: linear-gradient(135deg, #3d8a64, #2d6c52) !important;'
    )
    expect(archiveViewSource).toContain('0 0 0.34rem rgba(255, 218, 94, 0.58)')
    expect(archiveViewSource).toContain('0 0 0.72rem rgba(255, 201, 59, 0.34)')
  })

  it('uses the standard Christmas glow for desktop and mobile upload actions', () => {
    const archiveViewSource = readFileSync(
      resolve(globalThis.process.cwd(), 'src/views/Archive.vue'),
      'utf8'
    )
    const desktopHoverRule = archiveViewSource.match(
      /\.archive-christmas\s+\.upload-section\s+:deep\(\.p-button\.p-button-success:hover\),[\s\S]*?\{([\s\S]*?)\n\}/
    )
    const mobileHoverRule = archiveViewSource.match(
      /:global\(\.mobile-drawer\.mobile-drawer-christmas \.mobile-upload-section \.p-button-success:hover\),[\s\S]*?\{([\s\S]*?)\n\}/
    )

    expect(desktopHoverRule?.[1]).toContain('border-color: rgba(255, 226, 143, 0.9);')
    expect(desktopHoverRule?.[1]).toContain('0 0 0.34rem rgba(255, 218, 94, 0.58)')
    expect(desktopHoverRule?.[1]).toContain('0 0 0.72rem rgba(255, 201, 59, 0.34)')
    expect(desktopHoverRule?.[1]).toContain('text-shadow: 0 0 0.2rem rgba(255, 209, 72, 0.62);')
    expect(mobileHoverRule?.[1]).toContain('border-color: rgba(255, 226, 143, 0.9) !important;')
    expect(mobileHoverRule?.[1]).toContain('0 0 0.34rem rgba(255, 218, 94, 0.58)')
    expect(mobileHoverRule?.[1]).toContain('0 0 0.72rem rgba(255, 201, 59, 0.34) !important')
    expect(mobileHoverRule?.[1]).toContain(
      'text-shadow: 0 0 0.2rem rgba(255, 209, 72, 0.62) !important;'
    )
  })

  it('renders each archive when exam metadata matches but ids differ', async () => {
    const matchingArchives = [
      {
        ...baseArchives[0],
        id: 'matching-a',
        academic_year: '20231',
        name: 'Midterm',
        archive_type: 'midterm',
        professor: 'Prof. Chen',
        object_name: 'archives/matching-a.pdf',
      },
      {
        ...baseArchives[0],
        id: 'matching-b',
        academic_year: '20231',
        name: 'Midterm',
        archive_type: 'midterm',
        professor: 'Prof. Chen',
        object_name: 'archives/matching-b.pdf',
      },
    ]
    getCourseArchivesMock.mockReset()
    getCourseArchivesMock.mockResolvedValue({ data: matchingArchives })
    getArchiveDownloadUrlMock.mockImplementation((_courseId, archiveId) =>
      Promise.resolve({
        data: { url: `https://example.com/${archiveId}.pdf` },
      })
    )
    getArchivePreviewUrlMock.mockImplementation((_courseId, archiveId) =>
      Promise.resolve({ data: `${archiveId}-preview` })
    )
    globalThis.fetch = vi.fn()
    const wrapper = mount(ArchiveView, {
      global: {
        provide: {
          toast: { add: toastAddMock },
          confirm: { require: confirmRequireMock },
          sidebarVisible: ref(true),
        },
        stubs: componentStubs,
      },
    })

    await flushPromises()
    wrapper.vm.filterBySubject({ label: 'Calculus I', id: 'c1' })
    await flushPromises()

    const renderedIds = wrapper.vm.groupedArchives.flatMap((group) =>
      group.list.map((archive) => archive.id)
    )
    const archiveCards = wrapper.findAll('.archive-record-card')
    const downloadActions = wrapper.findAll('.archive-action-download')
    expect(renderedIds).toEqual(['matching-a', 'matching-b'])
    expect(archiveCards).toHaveLength(2)
    expect(archiveCards.every((card) => card.text().includes('Midterm'))).toBe(true)
    expect(downloadActions).toHaveLength(2)
    expect(downloadActions.every((action) => action.attributes('aria-label') === '下載')).toBe(true)

    await wrapper.vm.downloadArchive(wrapper.vm.groupedArchives[0].list[0])
    await wrapper.vm.downloadArchive(wrapper.vm.groupedArchives[0].list[1])
    await flushPromises()

    expect(getArchiveDownloadUrlMock).toHaveBeenNthCalledWith(1, 'c1', 'matching-a')
    expect(getArchiveDownloadUrlMock).toHaveBeenNthCalledWith(2, 'c1', 'matching-b')
    expect(globalThis.fetch).not.toHaveBeenCalled()
    expect(anchorClickSpy).toHaveBeenCalledTimes(2)
    expect(anchorClickSpy.mock.instances.map((link) => link.href)).toEqual([
      'https://example.com/matching-a.pdf',
      'https://example.com/matching-b.pdf',
    ])
    expect(anchorClickSpy.mock.instances.map((link) => link.download)).toEqual([
      '20231_Calculus I_Prof. Chen_Midterm.pdf',
      '20231_Calculus I_Prof. Chen_Midterm.pdf',
    ])

    await wrapper.vm.previewArchive(wrapper.vm.groupedArchives[0].list[0])
    await wrapper.vm.previewArchive(wrapper.vm.groupedArchives[0].list[1])
    await flushPromises()

    expect(getArchivePreviewUrlMock).toHaveBeenNthCalledWith(1, 'c1', 'matching-a')
    expect(getArchivePreviewUrlMock).toHaveBeenNthCalledWith(2, 'c1', 'matching-b')
    expect(getArchivePreviewFileMock).not.toHaveBeenCalled()
    expect(window.URL.createObjectURL).not.toHaveBeenCalled()
    expect(wrapper.vm.selectedArchive.id).toBe('matching-b')

    vi.runAllTimers()
    wrapper.unmount()
  })

  it('keeps the newest signed preview when requests resolve out of order', async () => {
    const wrapper = mount(ArchiveView, {
      global: {
        provide: {
          toast: { add: toastAddMock },
          confirm: { require: confirmRequireMock },
          sidebarVisible: ref(true),
        },
        stubs: componentStubs,
      },
    })

    await flushPromises()
    wrapper.vm.filterBySubject({ label: 'Calculus I', id: 'c1' })
    await flushPromises()

    let resolveFirst
    let resolveSecond
    getArchivePreviewUrlMock.mockReset()
    getArchivePreviewUrlMock
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveFirst = resolve
          })
      )
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveSecond = resolve
          })
      )

    const [firstArchive, secondArchive] = wrapper.vm.groupedArchives.flatMap((group) => group.list)
    const firstPreview = wrapper.vm.previewArchive(firstArchive)
    const secondPreview = wrapper.vm.previewArchive(secondArchive)

    resolveSecond({ data: { url: 'https://example.com/newest.pdf' } })
    await secondPreview
    expect(wrapper.vm.selectedArchive.id).toBe('a2')
    expect(wrapper.vm.selectedArchive.previewUrl).toBe('https://example.com/newest.pdf')

    resolveFirst({ data: { url: 'https://example.com/stale.pdf' } })
    await firstPreview
    expect(wrapper.vm.selectedArchive.id).toBe('a2')
    expect(wrapper.vm.selectedArchive.previewUrl).toBe('https://example.com/newest.pdf')
    expect(wrapper.vm.previewLoading).toBe(false)

    wrapper.unmount()
  })

  it('handles core archive interactions', async () => {
    const sidebarInjected = ref(true)

    const wrapper = mount(ArchiveView, {
      global: {
        provide: {
          toast: { add: toastAddMock },
          confirm: { require: confirmRequireMock },
          sidebarVisible: sidebarInjected,
        },
        stubs: componentStubs,
      },
    })

    await flushPromises()
    vi.runAllTimers()
    await flushPromises()

    const initialIssueContextRaw = sessionStorage.getItem('pastexam-issue-context')
    expect(initialIssueContextRaw).toBeTruthy()
    const initialIssueContext = JSON.parse(initialIssueContextRaw)
    expect(initialIssueContext.page).toBe('archive')

    const vm = wrapper.vm
    expect(vm.courseCategories.map(({ key }) => key)).toEqual([
      'fundamental',
      'required',
      'experience',
      'optional',
      'graduate',
      'math-department',
    ])
    expect(new Set(vm.courseCategories.map(({ name }) => name)).size).toBe(6)

    vm.filterBySubject({ label: 'Calculus I', id: 'c1' })
    await flushPromises()
    vi.runAllTimers()
    await flushPromises()

    expect(getCourseArchivesMock).toHaveBeenCalled()
    expect(vm.selectedSubject).toBe('Calculus I')
    expect(vm.groupedArchives.length).toBeGreaterThan(0)
    const subjectHeadingRow = wrapper.get('.subject-heading-row')
    expect(subjectHeadingRow.find('.subject-tag').text()).toContain('基礎')
    const subjectTitleStack = subjectHeadingRow.get('.subject-title-stack')
    expect(subjectTitleStack.text()).toContain('Calculus I')
    const subjectSummary = subjectHeadingRow.get('.subject-summary')
    expect(subjectSummary.text()).toContain('共 2 份考古題')
    expect(subjectSummary.findAll('.subject-summary-item')).toHaveLength(2)
    expect(subjectSummary.get('.subject-summary-separator').text()).toBe('・')
    const subjectEnglishName = subjectTitleStack.get('.subject-english-name')
    expect(subjectEnglishName.text()).toBe('Calculus I (English)')
    expect(wrapper.findAll('.archive-filter-controls .filter-select')).toHaveLength(3)
    expect(wrapper.get('.archive-filter-controls .answer-filter').text()).toContain('附解答')
    expect(wrapper.text()).toContain('投稿編號：#44')

    const issueContextAfterSelect = JSON.parse(sessionStorage.getItem('pastexam-issue-context'))
    expect(issueContextAfterSelect.course).toEqual({ id: 'c1', name: 'Calculus I' })

    vm.filters.year = '2023'
    vm.filters.professor = 'Prof. Chen'
    vm.filters.type = 'midterm'
    vm.filters.hasAnswers = true
    await nextTick()

    vm.searchQuery = 'calc'
    vi.runAllTimers()
    await flushPromises()

    const issueContextAfterFilters = JSON.parse(sessionStorage.getItem('pastexam-issue-context'))
    expect(issueContextAfterFilters.filters).toEqual(
      expect.objectContaining({
        year: '2023',
        professor: 'Prof. Chen',
        type: 'midterm',
        hasAnswers: true,
        searchQuery: 'calc',
      })
    )

    const archiveItem = vm.groupedArchives[0].list[0]
    await vm.downloadArchive(archiveItem)
    await flushPromises()

    expect(getArchiveDownloadUrlMock).toHaveBeenCalled()
    expect(toastAddMock).toHaveBeenCalled()

    await vm.previewArchive(archiveItem)
    await flushPromises()
    expect(vm.showPreview).toBe(true)
    expect(vm.selectedArchive.previewUrl).toBe('https://example.com/preview.pdf')

    const issueContextAfterPreview = JSON.parse(sessionStorage.getItem('pastexam-issue-context'))
    expect(issueContextAfterPreview.preview).toEqual(
      expect.objectContaining({
        open: true,
        archiveId: archiveItem.id,
      })
    )

    vm.handlePreviewError()
    expect(vm.previewError).toBe(true)

    const onDownloadComplete = vi.fn()
    await vm.handlePreviewDownload(onDownloadComplete)
    expect(onDownloadComplete).toHaveBeenCalled()

    vm.closePreview()
    expect(vm.showPreview).toBe(false)
    await nextTick()
    const issueContextAfterClosePreview = JSON.parse(
      sessionStorage.getItem('pastexam-issue-context')
    )
    expect(issueContextAfterClosePreview.preview?.open).toBe(false)

    vm.confirmDelete(archiveItem)
    await flushPromises()
    expect(deleteArchiveMock).toHaveBeenCalled()

    await vm.openEditDialog(archiveItem)
    vm.editForm.shouldTransfer = true
    vm.editForm.targetCategory = 'freshman'
    vm.editForm.targetCourseId = 'c2'
    await vm.handleEdit()

    await vm.openEditDialog(archiveItem)
    vm.editForm.shouldTransfer = true
    vm.editForm.targetCategory = 'freshman'
    vm.editForm.targetCourse = 'New Course'
    vm.editForm.targetCourseId = null
    await vm.handleEdit()

    await vm.handleUploadSuccess()
    expect(listCoursesMock.mock.calls.length).toBeGreaterThanOrEqual(3)

    expect(vm.getCategoryTag('基礎必修')).toBe('基礎')
    expect(vm.formatDownloadCount(0)).toBe('0')
    expect(vm.formatDownloadCount(12)).toBe('12')

    const initialSidebar = sidebarInjected.value
    vm.toggleSidebar()
    expect(sidebarInjected.value).toBe(!initialSidebar)

    await vm.syncArchiveDownloadCount('a1')
    expect(getCourseArchivesMock.mock.calls.length).toBeGreaterThanOrEqual(5)

    wrapper.unmount()
  })

  it('handles error and unauthorized branches gracefully', async () => {
    const sidebarInjected = ref(true)

    const wrapper = mount(ArchiveView, {
      global: {
        provide: {
          toast: { add: toastAddMock },
          confirm: { require: confirmRequireMock },
          sidebarVisible: sidebarInjected,
        },
        stubs: componentStubs,
      },
    })

    await flushPromises()

    toastAddMock.mockClear()
    listCoursesMock.mockReset()
    listCoursesMock.mockRejectedValueOnce(new Error('unauthorized'))
    isUnauthorizedErrorMock.mockReturnValueOnce(true)
    await wrapper.vm.fetchCourses()
    expect(toastAddMock).not.toHaveBeenCalled()

    toastAddMock.mockClear()
    listCoursesMock.mockRejectedValueOnce(new Error('fail'))
    isUnauthorizedErrorMock.mockReturnValueOnce(false)
    await wrapper.vm.fetchCourses()
    expect(toastAddMock).toHaveBeenCalledWith(
      expect.objectContaining({ detail: '無法載入課程資料' })
    )

    listCoursesMock.mockReset()
    listCoursesMock.mockResolvedValue({ data: sampleCourses })

    wrapper.vm.selectedCourse = 'c1'
    wrapper.vm.selectedSubject = 'Calculus I'

    toastAddMock.mockClear()
    getCourseArchivesMock.mockReset()
    getCourseArchivesMock.mockRejectedValueOnce(new Error('archives'))
    isUnauthorizedErrorMock.mockReturnValueOnce(false)
    await wrapper.vm.fetchArchives()
    expect(toastAddMock).toHaveBeenCalledWith(
      expect.objectContaining({ detail: '無法載入考古題資料' })
    )

    toastAddMock.mockClear()
    getArchiveDownloadUrlMock.mockRejectedValueOnce(new Error('unauthorized'))
    isUnauthorizedErrorMock.mockReturnValueOnce(true)
    await wrapper.vm.downloadArchive(baseArchives[0])
    expect(toastAddMock).not.toHaveBeenCalled()
    expect(wrapper.vm.downloadingId).toBeNull()

    toastAddMock.mockClear()
    getArchiveDownloadUrlMock.mockRejectedValueOnce(new Error('download'))
    isUnauthorizedErrorMock.mockReturnValueOnce(false)
    await wrapper.vm.downloadArchive(baseArchives[0])
    expect(toastAddMock).toHaveBeenCalledWith(
      expect.objectContaining({ detail: '無法取得下載連結' })
    )

    toastAddMock.mockClear()
    getArchivePreviewUrlMock.mockRejectedValueOnce(new Error('preview'))
    isUnauthorizedErrorMock.mockReturnValueOnce(false)
    await wrapper.vm.previewArchive(baseArchives[0])
    expect(wrapper.vm.previewError).toBe(true)
    expect(toastAddMock).toHaveBeenCalledWith(
      expect.objectContaining({ detail: '無法取得預覽連結' })
    )

    toastAddMock.mockClear()
    deleteArchiveMock.mockRejectedValueOnce(new Error('delete'))
    isUnauthorizedErrorMock.mockReturnValueOnce(false)
    await wrapper.vm.deleteArchive({ ...baseArchives[0], year: '2023' })
    expect(toastAddMock).toHaveBeenCalledWith(
      expect.objectContaining({ detail: '發生錯誤，請稍後再試' })
    )

    toastAddMock.mockClear()
    getArchiveDownloadUrlMock.mockRejectedValueOnce(new Error('preview-download'))
    isUnauthorizedErrorMock.mockReturnValueOnce(false)
    wrapper.vm.selectedArchive = { ...baseArchives[0] }
    wrapper.vm.selectedCourse = 'c1'
    wrapper.vm.selectedSubject = 'Calculus I'
    await wrapper.vm.handlePreviewDownload(() => {})
    expect(toastAddMock).toHaveBeenCalledWith(
      expect.objectContaining({ detail: '無法取得下載連結' })
    )

    wrapper.unmount()
  })

  it('shows a backend-authorized submission number to a regular archive owner', async () => {
    getCurrentUserMock.mockReturnValue({ id: 10, is_admin: false })
    getCourseArchivesMock.mockReset()
    getCourseArchivesMock.mockResolvedValue({
      data: [{ ...baseArchives[0], source_submission_ids: [45] }],
    })
    const sidebarInjected = ref(true)
    const wrapper = mount(ArchiveView, {
      global: {
        provide: {
          toast: { add: toastAddMock },
          confirm: { require: confirmRequireMock },
          sidebarVisible: sidebarInjected,
        },
        stubs: componentStubs,
      },
    })

    await flushPromises()
    wrapper.vm.filterBySubject({ label: 'Calculus I', id: 'c1' })
    await flushPromises()

    expect(wrapper.vm.isAdmin).toBe(false)
    expect(wrapper.text()).toContain('投稿編號：#45')
    wrapper.unmount()
  })

  it('covers edit helpers and mobile menu utilities', async () => {
    const sidebarInjected = ref(true)

    const wrapper = mount(ArchiveView, {
      global: {
        provide: {
          toast: { add: toastAddMock },
          confirm: { require: confirmRequireMock },
          sidebarVisible: sidebarInjected,
        },
        stubs: componentStubs,
      },
    })

    await flushPromises()

    const vm = wrapper.vm

    vm.uploadFormProfessors = [
      { name: 'Prof. Chen', code: 'Prof. Chen' },
      { name: 'Prof. Wang', code: 'Prof. Wang' },
    ]

    vm.searchEditProfessor({ query: 'chen' })
    expect(vm.availableEditProfessors).toEqual([expect.objectContaining({ name: 'Prof. Chen' })])

    vm.onEditProfessorSelect({ value: { name: 'Prof. Hsu' } })
    expect(vm.editForm.professor).toBe('Prof. Hsu')

    vm.editForm.targetCategory = 'freshman'
    vm.selectedCourse = 'c1'
    await nextTick()

    vm.coursesList.freshman = [
      { id: 'c1', name: 'Current course', order_index: 0 },
      { id: 'c2', name: 'Backend first', order_index: 99 },
      { id: 'c4', name: 'Backend second', order_index: -1 },
    ]
    await nextTick()
    expect(vm.allAvailableCoursesForTransfer.map(({ id }) => id)).toEqual(['c2', 'c4'])

    vm.searchTargetCourse({ query: 'linear' })
    expect(vm.availableCoursesForTransfer).toEqual([])

    vm.searchTargetCourse({ query: 'backend' })
    expect(vm.availableCoursesForTransfer.map(({ id }) => id)).toEqual(['c2', 'c4'])

    vm.onTargetCourseSelect({ value: { label: 'Backend first', id: 'c2' } })
    expect(vm.editForm.targetCourseId).toBe('c2')

    vm.onTargetCourseSelect({ value: 'New Course' })
    expect(vm.editForm.targetCourse).toBe('New Course')
    expect(vm.editForm.targetCourseId).toBeNull()

    vm.editForm.targetCourse = 'Backend first'
    await nextTick()
    expect(vm.editForm.targetCourseId).toBe('c2')

    vm.editForm.targetCourse = 'Brand New'
    await nextTick()
    expect(vm.editForm.targetCourseId).toBeNull()

    vm.closeEditDialog()
    expect(vm.showEditDialog).toBe(false)
    expect(vm.editForm.id).toBeNull()

    vm.checkAuthentication()
    expect(vm.isAuthenticatedRef).toBe(true)
    expect(vm.userData?.id).toBe(10)

    const mobileMenu = vm.mobileMenuItems
    expect(Array.isArray(mobileMenu)).toBe(true)

    wrapper.unmount()
  })

  it('keeps transfer suggestions in management order across locales', async () => {
    const wrapper = mount(ArchiveView, {
      global: {
        provide: {
          toast: { add: toastAddMock },
          confirm: { require: confirmRequireMock },
          sidebarVisible: ref(true),
        },
        stubs: componentStubs,
      },
    })
    await flushPromises()

    const vm = wrapper.vm
    vm.selectedCourse = 40
    vm.editForm.targetCategory = 'fundamental'
    vm.coursesList.fundamental = [
      { id: 40, order_index: 0, name: '目前課程', name_en: 'Current Course' },
      { id: 30, order_index: 1, name: '書卷獎必修課', name_en: 'Zeta Course' },
      { id: 20, order_index: 2, name: '普通化學(一)', name_en: 'Alpha Course' },
      { id: 10, order_index: 3, name: '微積分(一)', name_en: 'Beta Course' },
    ]
    await nextTick()

    setLocale('zh-TW')
    vm.searchTargetCourse({ query: '' })
    const zhIds = vm.availableCoursesForTransfer.map(({ id }) => id)
    const zhLabels = vm.availableCoursesForTransfer.map(({ label }) => label)

    setLocale('en')
    await nextTick()
    vm.searchTargetCourse({ query: '' })
    const enIds = vm.availableCoursesForTransfer.map(({ id }) => id)
    const enLabels = vm.availableCoursesForTransfer.map(({ label }) => label)

    expect(zhIds).toEqual([30, 20, 10])
    expect(enIds).toEqual([30, 20, 10])
    expect(enIds).toEqual(zhIds)
    expect(zhLabels).toEqual(['書卷獎必修課', '普通化學(一)', '微積分(一)'])
    expect(enLabels).toEqual(['Zeta Course', 'Alpha Course', 'Beta Course'])
    expect(zhIds).not.toContain(40)
    expect(enIds).not.toContain(40)

    wrapper.unmount()
  })

  it('submits edit and transfer atomically and preserves the dialog on failure', async () => {
    const wrapper = mount(ArchiveView, {
      global: {
        provide: {
          toast: { add: toastAddMock },
          confirm: { require: confirmRequireMock },
          sidebarVisible: ref(true),
        },
        stubs: componentStubs,
      },
    })
    await flushPromises()

    const vm = wrapper.vm
    const initialCourseLoads = listCoursesMock.mock.calls.length
    vm.selectedCourse = 'c1'
    vm.showEditDialog = true
    vm.editForm = {
      id: 'a1',
      name: '保留名稱',
      professor: '保留教授',
      type: 'midterm',
      hasAnswers: true,
      academicYear: new Date('2023-01-01T00:00:00Z'),
      shouldTransfer: true,
      targetCategory: 'freshman',
      targetCourse: '',
      targetCourseId: null,
    }
    await nextTick()
    vm.editForm.targetCourseId = 'missing-course'
    const preservedForm = {
      name: vm.editForm.name,
      professor: vm.editForm.professor,
      targetCategory: vm.editForm.targetCategory,
      targetCourse: vm.editForm.targetCourse,
      targetCourseId: vm.editForm.targetCourseId,
    }
    updateArchiveMock.mockRejectedValueOnce({
      response: {
        status: 404,
        data: {
          detail: {
            code: 'archive_move_target_course_not_found',
            message: '目標課程不存在，請先建立課程。',
            reload_required: false,
          },
        },
      },
    })

    await vm.handleEdit()
    await flushPromises()

    expect(vm.showEditDialog).toBe(true)
    expect(vm.editForm).toMatchObject(preservedForm)
    expect(listCoursesMock).toHaveBeenCalledTimes(initialCourseLoads)
    expect(toastAddMock).toHaveBeenCalledTimes(1)
    expect(toastAddMock).toHaveBeenLastCalledWith(
      expect.objectContaining({
        severity: 'error',
        summary: '更新失敗',
        detail: '目標課程不存在，請先建立課程。',
      })
    )
    expect(toastAddMock).not.toHaveBeenCalledWith(expect.objectContaining({ severity: 'success' }))
    expect(updateArchiveMock).toHaveBeenCalledWith(
      'c1',
      'a1',
      expect.objectContaining({ target_course_id: 'missing-course' })
    )
    expect(updateArchiveCourseMock).not.toHaveBeenCalled()
    expect(updateArchiveCourseByCategoryAndNameMock).not.toHaveBeenCalled()

    wrapper.unmount()
  })

  it('rejects free-text transfer targets before changing archive metadata', async () => {
    const wrapper = mount(ArchiveView, {
      global: {
        provide: {
          toast: { add: toastAddMock },
          confirm: { require: confirmRequireMock },
          sidebarVisible: ref(true),
        },
        stubs: componentStubs,
      },
    })
    await flushPromises()
    updateArchiveMock.mockClear()
    wrapper.vm.editForm = {
      id: 'a1',
      name: '不可部分更新',
      professor: '教授',
      type: 'final',
      hasAnswers: false,
      academicYear: new Date('2026-01-01T00:00:00Z'),
      shouldTransfer: true,
      targetCategory: 'freshman',
      targetCourse: '不存在的新課程',
      targetCourseId: null,
    }

    await wrapper.vm.handleEdit()

    expect(updateArchiveMock).not.toHaveBeenCalled()
    expect(toastAddMock).toHaveBeenLastCalledWith(
      expect.objectContaining({ detail: '請從現有課程清單選擇目標課程。' })
    )
    wrapper.unmount()
  })

  it('keeps owner submission status informational without a delete action', () => {
    const archiveViewSource = readFileSync(
      resolve(globalThis.process.cwd(), 'src/views/Archive.vue'),
      'utf8'
    )

    expect(archiveViewSource).not.toContain('deleteMySubmission')
    expect(archiveViewSource).not.toContain('owner_self_delete_consumed')
  })

  it('aligns Archive CSS and drawer logic at Major Breakpoint 768', () => {
    const archiveViewSource = readFileSync(
      resolve(globalThis.process.cwd(), 'src/views/Archive.vue'),
      'utf8'
    )

    expect(archiveViewSource).toContain('const mobile = window.innerWidth < 768')
    expect(archiveViewSource.match(/@media \(width < 768px\)/g)).toHaveLength(3)
    expect(archiveViewSource).toContain('@media (width >= 768px)')
    expect(archiveViewSource).not.toContain('@media (max-width: 768px)')
    expect(archiveViewSource).not.toContain('@media (min-width: 769px)')
  })

  it('keeps administrator identity separate from the ordinary submission-family contract', async () => {
    listMySubmissionsMock.mockResolvedValue({
      data: [
        {
          id: 71,
          status: 'approved',
          is_admin_upload: true,
          course_name: '普通物理(二)',
          name: '期中考',
          academic_year: '20242',
          professor: '王教授',
        },
        {
          id: 72,
          status: 'approved',
          is_admin_upload: true,
          requested_course_name: '普通物理(二)',
          course_name: '普通物理(二)',
          name: '期末考',
          academic_year: '20242',
          professor: '李教授',
        },
        {
          id: 73,
          status: 'approved',
          is_admin_upload: true,
          requested_category_key: 'fundamental',
          requested_course_name: '普通物理(二)',
          course_name: '普通物理(二)',
          name: '小考',
          academic_year: '20242',
          professor: '陳教授',
        },
        {
          id: 74,
          status: 'approved',
          is_admin_upload: false,
          course_name: '普通物理(二)',
          name: '期中考',
          academic_year: '20242',
          professor: '王教授',
        },
        {
          id: 75,
          status: 'approved',
          is_admin_upload: false,
          requested_course_name: '普通物理(二)',
          course_name: '普通物理(二)',
          name: '期末考',
          academic_year: '20242',
          professor: '李教授',
        },
        {
          id: 76,
          status: 'approved',
          is_admin_upload: false,
          requested_category_key: 'fundamental',
          requested_course_name: '普通物理(二)',
          course_name: '普通物理(二)',
          name: '小考',
          academic_year: '20242',
          professor: '陳教授',
        },
      ],
    })
    setLocale('en')
    const wrapper = mount(ArchiveView, {
      global: {
        provide: {
          toast: { add: toastAddMock },
          confirm: { require: confirmRequireMock },
          sidebarVisible: ref(true),
        },
        stubs: componentStubs,
      },
    })
    await flushPromises()
    await wrapper.vm.openSubmissionStatus()
    await flushPromises()

    const identityBadges = wrapper.findAll('.submission-admin-badge')
    let familyBadges = wrapper.findAll('.my-submission-type-badge')
    const metadataBadges = wrapper.findAll('.my-submission-meta-chip')
    expect(identityBadges).toHaveLength(3)
    expect(familyBadges).toHaveLength(6)
    expect(metadataBadges).toHaveLength(12)
    for (const identityBadge of identityBadges) {
      expect(identityBadge.text()).toBe('Administrator')
      expect(identityBadge.classes()).toEqual(
        expect.arrayContaining(['soft-badge', 'soft-badge--admin', 'submission-admin-badge'])
      )
    }
    const expectedEnglishFamilies = [
      ['Existing Course Submission', 'soft-badge--type'],
      ['New Course Request', 'soft-badge--new-course'],
      ['New Category + New Course', 'soft-badge--new-course-category'],
      ['Existing Course Submission', 'soft-badge--type'],
      ['New Course Request', 'soft-badge--new-course'],
      ['New Category + New Course', 'soft-badge--new-course-category'],
    ]
    for (const [index, familyBadge] of familyBadges.entries()) {
      const [expectedText, expectedClass] = expectedEnglishFamilies[index]
      expect(familyBadge.text()).toBe(expectedText)
      expect(familyBadge.classes()).toEqual(
        expect.arrayContaining(['submission-meta-chip', 'my-submission-type-badge', expectedClass])
      )
      expect(familyBadge.classes()).not.toContain('soft-badge--admin')
    }
    expect(familyBadges[0].classes()).toEqual(familyBadges[3].classes())
    expect(familyBadges[1].classes()).toEqual(familyBadges[4].classes())
    expect(familyBadges[2].classes()).toEqual(familyBadges[5].classes())
    expect(
      metadataBadges.filter((badge) => badge.classes().includes('soft-badge--type'))
    ).toHaveLength(6)
    expect(
      metadataBadges.filter((badge) => badge.classes().includes('soft-badge--info'))
    ).toHaveLength(6)

    setLocale('zh-TW')
    await nextTick()
    expect(identityBadges.every((badge) => badge.text() === '管理員投稿')).toBe(true)
    familyBadges = wrapper.findAll('.my-submission-type-badge')
    expect(familyBadges.map((badge) => badge.text())).toEqual([
      '既有課程投稿',
      '新課程申請',
      '新分類 + 新課程',
      '既有課程投稿',
      '新課程申請',
      '新分類 + 新課程',
    ])
    wrapper.unmount()
  })

  it('covers remaining utility branches', async () => {
    const sidebarInjected = ref(true)

    const wrapper = mount(ArchiveView, {
      global: {
        provide: {
          toast: { add: toastAddMock },
          confirm: { require: confirmRequireMock },
          sidebarVisible: sidebarInjected,
        },
        stubs: componentStubs,
      },
    })

    await flushPromises()

    // getCurrentCategory fallback when no course selected
    wrapper.vm.selectedCourse = null
    expect(wrapper.vm.getCurrentCategory).toBe('')

    // Unauthorized preview download branch
    wrapper.vm.selectedCourse = 'c1'
    wrapper.vm.selectedSubject = 'Calculus I'
    wrapper.vm.selectedArchive = { id: 'a1', year: '2023', professor: 'Prof', name: 'Midterm' }
    getArchiveDownloadUrlMock.mockRejectedValueOnce(new Error('unauthorized'))
    isUnauthorizedErrorMock.mockReturnValueOnce(true)
    const onComplete = vi.fn()
    await wrapper.vm.handlePreviewDownload(onComplete)
    expect(onComplete).toHaveBeenCalled()
    expect(toastAddMock).not.toHaveBeenCalled()

    // checkAuthentication when user missing
    isAuthenticatedMock.mockReturnValueOnce(true)
    getCurrentUserMock.mockReturnValueOnce(null)
    wrapper.vm.checkAuthentication()
    expect(wrapper.vm.isAuthenticatedRef).toBe(false)
    expect(wrapper.vm.userData).toBeNull()

    // Mobile menu command toggles sidebar
    const menu = wrapper.vm.mobileMenuItems
    expect(menu.length).toBeGreaterThan(0)
    const firstCourse = menu[0].items?.[0]
    if (firstCourse?.command) {
      sidebarInjected.value = true
      firstCourse.command()
      expect(sidebarInjected.value).toBe(false)
    }

    wrapper.unmount()
  })
})
