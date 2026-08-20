import { describe, it, expect, vi, beforeEach, afterEach, beforeAll } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const courseServiceMock = vi.hoisted(() => ({
  getCourseArchives: vi.fn(),
}))

const archiveServiceMock = vi.hoisted(() => ({
  uploadArchive: vi.fn(),
}))

const wishServiceMock = vi.hoisted(() => ({
  create: vi.fn(),
}))

const trackEventMock = vi.hoisted(() => vi.fn())
const toastAddMock = vi.hoisted(() => vi.fn())
const isUnauthorizedErrorMock = vi.hoisted(() => vi.fn(() => false))

let originalURL
let consoleErrorSpy
let UploadArchiveDialog

const ensureDomMatrix = vi.hoisted(() => () => {
  if (typeof globalThis.DOMMatrix === 'undefined') {
    class DOMMatrixPolyfill {
      constructor() {
        this.a = 1
        this.b = 0
        this.c = 0
        this.d = 1
        this.e = 0
        this.f = 0
      }
      multiplySelf() {
        return this
      }
      translateSelf() {
        return this
      }
      scaleSelf() {
        return this
      }
      rotateSelf() {
        return this
      }
    }
    globalThis.DOMMatrix = DOMMatrixPolyfill
    globalThis.DOMMatrixReadOnly = DOMMatrixPolyfill
  }
})

const pdfLoadMock = vi.hoisted(() =>
  vi.fn(async () => ({
    setTitle: vi.fn(),
    setAuthor: vi.fn(),
    setSubject: vi.fn(),
    setKeywords: vi.fn(),
    setProducer: vi.fn(),
    setCreator: vi.fn(),
    setCreationDate: vi.fn(),
    setModificationDate: vi.fn(),
    save: vi.fn(async () => new Uint8Array([1, 2, 3])),
  }))
)

vi.mock('@/api', () => ({
  courseService: courseServiceMock,
  archiveService: archiveServiceMock,
  wishService: wishServiceMock,
}))

vi.mock('primevue/usetoast', () => ({
  useToast: () => ({
    add: toastAddMock,
  }),
}))

vi.mock('pdf-lib', () => ({
  PDFDocument: {
    load: pdfLoadMock,
  },
}))

vi.mock('@/utils/analytics', () => ({
  trackEvent: trackEventMock,
  EVENTS: {
    PREVIEW_ARCHIVE: 'preview-archive',
  },
}))

vi.mock('@/utils/http', () => ({
  isUnauthorizedError: isUnauthorizedErrorMock,
}))

const sampleCourses = {
  freshman: [
    { id: 'c1', name: 'Calculus I' },
    { id: 'c2', name: 'Physics' },
  ],
  sophomore: [],
  junior: [],
  senior: [],
  graduate: [],
  interdisciplinary: [],
}

const courseCategories = [{ id: 1, key: 'freshman', name: '基礎必修', order_index: 0 }]

const stubComponent = { template: '<div><slot /></div>' }

const componentStubs = {
  Dialog: stubComponent,
  Stepper: stubComponent,
  StepList: stubComponent,
  StepPanel: stubComponent,
  StepPanels: stubComponent,
  Step: stubComponent,
  Button: stubComponent,
  Select: stubComponent,
  AutoComplete: stubComponent,
  DatePicker: stubComponent,
  InputText: stubComponent,
  Checkbox: stubComponent,
  FileUpload: stubComponent,
  Divider: stubComponent,
  PdfPreviewModal: stubComponent,
  ProgressSpinner: stubComponent,
}

function mountDialog(props = {}) {
  return mount(UploadArchiveDialog, {
    props: {
      modelValue: true,
      coursesList: sampleCourses,
      courseCategories,
      ...props,
    },
    global: {
      stubs: componentStubs,
    },
  })
}

describe('UploadArchiveDialog', () => {
  beforeAll(async () => {
    ensureDomMatrix()
    UploadArchiveDialog = (await import('@/components/UploadArchiveDialog.vue')).default
  }, 20_000)

  beforeEach(() => {
    trackEventMock.mockReset()
    toastAddMock.mockReset()
    archiveServiceMock.uploadArchive.mockResolvedValue()
    wishServiceMock.create.mockReset()
    wishServiceMock.create.mockResolvedValue()
    courseServiceMock.getCourseArchives.mockResolvedValue({
      data: [{ professor: 'Prof. Lin' }, { professor: 'Prof. Chen' }, { professor: 'Prof. Lin' }],
    })
    isUnauthorizedErrorMock.mockReturnValue(false)
    pdfLoadMock.mockClear()
    consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    originalURL = globalThis.URL
    globalThis.URL = {
      createObjectURL: vi.fn(() => 'blob:url'),
      revokeObjectURL: vi.fn(),
    }
  })

  afterEach(() => {
    if (consoleErrorSpy) {
      consoleErrorSpy.mockRestore()
    }
    globalThis.URL = originalURL
  })

  it('validates and uploads archive successfully', async () => {
    const wrapper = mountDialog()
    const vm = wrapper.vm

    vm.form.category = 'freshman'
    await flushPromises()
    vm.form.subject = { name: 'Calculus I', code: 'c1' }
    vm.form.filename = 'midterm1'
    vm.form.type = 'midterm'
    vm.form.examNumber = 1
    vm.form.academicYear = new Date('2023-01-01')

    vm.validateFilename()
    expect(vm.isFilenameValid).toBe(true)

    expect(vm.subjectOptions).toEqual([
      { name: 'Calculus I', canonicalName: 'Calculus I', code: 'c1' },
      { name: 'Physics', canonicalName: 'Physics', code: 'c2' },
    ])

    await flushPromises()
    expect(vm.form.subjectId).toBe('c1')
    vm.form.professor = 'Prof. Lin'

    await vm.fetchProfessorsForSubject('c1')
    expect(courseServiceMock.getCourseArchives).toHaveBeenCalledWith('c1')

    vm.searchProfessor({ query: '' })
    expect(vm.availableProfessors.length).toBe(2)

    vm.searchProfessor({ query: 'lin' })
    expect(vm.availableProfessors.length).toBe(1)

    const fakeFile = {
      name: 'midterm.pdf',
      size: 2048,
      arrayBuffer: () => Promise.resolve(new ArrayBuffer(8)),
    }

    vm.form.file = fakeFile

    vm.previewUploadFile()
    expect(vm.showUploadPreview).toBe(true)
    expect(trackEventMock).toHaveBeenCalledWith('preview-archive', expect.any(Object))

    await vm.handleUpload()
    await flushPromises()

    expect(pdfLoadMock).toHaveBeenCalled()
    expect(archiveServiceMock.uploadArchive).toHaveBeenCalled()
    expect(toastAddMock).toHaveBeenCalledWith(
      expect.objectContaining({ severity: 'success', summary: '已送出審核' })
    )
    expect(wrapper.emitted('upload-success')).toBeTruthy()

    wrapper.unmount()
  })

  it('rejects an oversized PDF with a visible validation error', async () => {
    const wrapper = mountDialog()
    const vm = wrapper.vm
    const clear = vi.fn()
    vm.fileUpload = { clear }

    vm.onFileSelect({
      files: [{ name: 'oversized.pdf', size: 20 * 1024 * 1024 + 1 }],
    })
    await flushPromises()

    expect(vm.form.file).toBeNull()
    expect(vm.fileValidationError).toBe('PDF 檔案超過 20 MB 大小上限')
    expect(clear).toHaveBeenCalled()
  })

  it('reuses new-course and new-category requests in wish mode', async () => {
    const wrapper = mountDialog({ mode: 'wish' })
    const vm = wrapper.vm

    expect(wrapper.text()).toContain('申請新增課程')
    expect(wrapper.text()).toContain('同時申請新增課程分類')
    expect(wrapper.get('#archive-wish-title').attributes('placeholder')).toBe(
      '例如: 王道維普物一 midterm1'
    )

    vm.form.requestNewCourse = true
    await flushPromises()
    vm.form.requestNewCategory = true
    await flushPromises()

    Object.assign(vm.form, {
      requestedCourseName: '量子資訊',
      requestedCourseNameEn: 'Quantum Information',
      requestedCategoryKey: 'quantum-info',
      requestedCategoryName: '量子資訊',
      requestedCategoryNameEn: 'Quantum Information',
      requestedCategoryLabel: '量資',
      requestedCategoryLabelEn: 'QInfo',
      academicYear: null,
      type: 'final',
      wishTitle: '量子資訊期末考',
    })
    await flushPromises()
    vm.form.professor = 'Prof. Lin'
    await flushPromises()

    expect(Boolean(vm.canGoToStep2)).toBe(true)
    expect(vm.canUpload).toBe(true)
    expect(wrapper.text()).toContain('量子資訊（quantum-info）')
    expect(wrapper.text()).toContain('Quantum Information')
    expect(wrapper.text()).toContain('量資 / QInfo')

    await vm.handleUpload()

    expect(wishServiceMock.create).toHaveBeenCalledWith(
      expect.objectContaining({
        academic_year: null,
        course_id: null,
        subject: '量子資訊',
        category: 'quantum-info',
        requested_course_name: '量子資訊',
        requested_course_name_en: 'Quantum Information',
        requested_category_key: 'quantum-info',
        requested_category_name: '量子資訊',
        requested_category_name_en: 'Quantum Information',
        requested_category_label: '量資',
        requested_category_label_en: 'QInfo',
      })
    )

    wrapper.unmount()
  })

  it('preserves requested catalog snapshots when helping upload a wish', async () => {
    const wrapper = mountDialog({
      modelValue: false,
      sourceWishId: 42,
      prefill: {
        id: 42,
        subject: '量子資訊',
        category: 'quantum-info',
        requested_course_name: '量子資訊',
        requested_course_name_en: 'Quantum Information',
        requested_category_key: 'quantum-info',
        requested_category_name: '量子資訊',
        requested_category_name_en: 'Quantum Information',
        requested_category_label: '量資',
        requested_category_label_en: 'QInfo',
        professor: 'Prof. Lin',
        academic_year: 1141,
        archive_type: 'final',
        name: 'final',
      },
    })

    await wrapper.setProps({ modelValue: true })
    await flushPromises()

    expect(wrapper.vm.form).toEqual(
      expect.objectContaining({
        requestNewCourse: true,
        requestNewCategory: true,
        requestedCourseName: '量子資訊',
        requestedCourseNameEn: 'Quantum Information',
        requestedCategoryKey: 'quantum-info',
        requestedCategoryName: '量子資訊',
        requestedCategoryNameEn: 'Quantum Information',
        requestedCategoryLabel: '量資',
        requestedCategoryLabelEn: 'QInfo',
        subjectId: null,
      })
    )
    expect(
      wrapper.findAll('.semester-option').every((option) => !option.attributes('disabled'))
    ).toBe(true)
    await wrapper.find('.semester-option').trigger('click')
    expect(wrapper.vm.form.academicYear).not.toBe(1141)

    wrapper.unmount()
  })

  it('covers helper utilities, watchers, and error branches', async () => {
    const wrapper = mountDialog()
    const vm = wrapper.vm

    expect(vm.getCategoryName('freshman')).toBe('基礎必修')
    expect(vm.getCategoryName('unknown')).toBe('unknown')
    expect(vm.getTypeName('final')).toBe('期末考')
    expect(vm.formatFileSize(0)).toBe('0 Bytes')
    expect(vm.formatFileSize(2048)).toContain('KB')

    courseServiceMock.getCourseArchives.mockRejectedValueOnce(new Error('fetch error'))
    await vm.fetchProfessorsForSubject('c1')
    expect(vm.uploadFormProfessors).toEqual([])
    courseServiceMock.getCourseArchives.mockResolvedValue({ data: [] })

    vm.uploadFormProfessors = [
      { name: 'Prof. Lin', code: 'Prof. Lin' },
      { name: 'Prof. Chen', code: 'Prof. Chen' },
    ]
    vm.searchProfessor({ query: 'lin' })
    expect(vm.availableProfessors).toEqual([expect.objectContaining({ name: 'Prof. Lin' })])

    vm.onProfessorSelect({ value: 'Prof. Hsu' })
    expect(vm.form.professor).toBeNull()

    vm.onProfessorSelect({ value: { name: 'Prof. Hsu' } })
    expect(vm.form.professor).toBe('Prof. Hsu')

    vm.handleUploadPreviewError()
    expect(vm.uploadPreviewError).toBe(true)

    const clearSpy = vi.fn()
    vm.fileUpload = { clear: clearSpy }
    const file = {
      name: 'calc.pdf',
      size: 100,
      arrayBuffer: () => Promise.resolve(new ArrayBuffer(4)),
    }
    vm.onFileSelect({ files: [file] })
    await flushPromises()
    expect(clearSpy).toHaveBeenCalled()
    expect(vm.form.file).toEqual(file)

    vm.form.category = 'freshman'
    await flushPromises()
    expect(vm.form.subject).toBeNull()

    vm.form.subject = 'Calculus I'
    vm.form.subjectId = 'c1'
    await flushPromises()
    vm.form.subject = null
    await flushPromises()
    expect(vm.uploadFormProfessors).toEqual([])

    vm.fileUpload = { clear: vi.fn() }
    await wrapper.setProps({ modelValue: false })
    await flushPromises()
    expect(vm.form.category).toBeNull()
    expect(vm.uploadStep).toBe('1')

    wrapper.unmount()
  })

  it('handles upload failures and unauthorized responses', async () => {
    const wrapper = mountDialog()
    const vm = wrapper.vm

    Object.assign(vm.form, {
      category: 'freshman',
      subject: 'Calculus I',
      subjectId: 'c1',
      professor: 'Prof. Lin',
      filename: 'midterm1',
      type: 'midterm',
      examNumber: 1,
      hasAnswers: true,
      academicYear: new Date('2024-01-01'),
    })

    const failingFile = {
      name: 'midterm.pdf',
      size: 1024,
      arrayBuffer: () => Promise.resolve(new ArrayBuffer(8)),
    }
    vm.form.file = failingFile

    archiveServiceMock.uploadArchive.mockRejectedValueOnce(new Error('upload failed'))
    await vm.handleUpload()
    await flushPromises()
    expect(toastAddMock).toHaveBeenCalledWith(
      expect.objectContaining({ severity: 'error', summary: '上傳失敗' })
    )

    toastAddMock.mockClear()
    archiveServiceMock.uploadArchive.mockRejectedValueOnce(new Error('unauthorized'))
    isUnauthorizedErrorMock.mockReturnValueOnce(true)
    await vm.handleUpload()
    await flushPromises()
    expect(toastAddMock).not.toHaveBeenCalled()
    expect(vm.uploading).toBe(false)

    wrapper.unmount()
  })

  it('manages preview lifecycle, validation, and clearing helpers', () => {
    const wrapper = mountDialog()
    const vm = wrapper.vm

    vm.form.filename = 'InvalidName'
    vm.validateFilename()
    expect(vm.isFilenameValid).toBe(false)

    vm.form.type = 'other'
    vm.form.otherName = 'validname1'
    vm.validateFilename()
    expect(vm.isFilenameValid).toBe(true)

    vm.form.category = null
    expect(vm.subjectOptions).toEqual([])

    vm.form.file = { name: 'archive.pdf', size: 512 }
    globalThis.URL.createObjectURL.mockImplementationOnce(() => {
      throw new Error('preview error')
    })
    vm.previewUploadFile()
    expect(vm.uploadPreviewError).toBe(true)
    expect(toastAddMock).toHaveBeenCalledWith(
      expect.objectContaining({ severity: 'error', summary: '預覽失敗' })
    )

    toastAddMock.mockClear()
    vm.form.file = { name: 'archive.pdf', size: 512 }
    vm.previewUploadFile()
    expect(vm.showUploadPreview).toBe(true)

    vm.closeUploadPreview()
    expect(globalThis.URL.revokeObjectURL).toHaveBeenCalled()
    expect(vm.showUploadPreview).toBe(false)

    const fileUploadClearSpy = vi.fn()
    vm.fileUpload = { clear: fileUploadClearSpy }
    vm.form.file = { name: 'tmp.pdf' }
    const removeSpy = vi.fn()
    vm.clearSelectedFile(removeSpy)
    expect(removeSpy).toHaveBeenCalledWith(0)
    expect(fileUploadClearSpy).toHaveBeenCalled()
    expect(vm.form.file).toBeNull()

    wrapper.unmount()
  })
})
