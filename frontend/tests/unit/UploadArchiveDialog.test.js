import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, it, expect, vi, beforeEach, afterEach, beforeAll } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const courseServiceMock = vi.hoisted(() => ({
  getCourseArchives: vi.fn(),
}))

const archiveServiceMock = vi.hoisted(() => ({
  uploadArchive: vi.fn(),
  editOwnerPendingSubmission: vi.fn(),
  getOwnerPendingPreviewFile: vi.fn(),
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
  it('shows the fixed PDF normalization notice without adding interaction', () => {
    const wrapper = mountDialog()

    expect(wrapper.text()).toContain('PDF 處理說明：為確保檔案相容性與安全性')
    wrapper.unmount()
  })

  it('formats pre-100 academic term selections', () => {
    const wrapper = mountDialog()

    expect(wrapper.vm.formatSemester(992)).toBe('99下學期')
    expect(wrapper.vm.formatSemester(1002)).toBe('100下學期')

    wrapper.unmount()
  })

  it('uses the edit-inspired Christmas shell and snowy glowing next actions in both modes', () => {
    const componentSource = readFileSync(
      resolve(globalThis.process.cwd(), 'src/components/UploadArchiveDialog.vue'),
      'utf8'
    )
    const styleSource = readFileSync(resolve(globalThis.process.cwd(), 'src/style.css'), 'utf8')
    const nextActionClasses = componentSource.match(/class="archive-upload-next-button"/g)
    const backActionClasses = componentSource.match(/class="archive-upload-back-button"/g)
    const snowOptIns = componentSource.match(
      /:data-christmas-snow-control="christmas \? 'true' : undefined"/g
    )
    const stepSnowPtBindings = componentSource.match(/:pt="christmasStepPt"/g)
    const stepSnowOptOut = componentSource.match(
      /'data-christmas-snow': props\.christmas \? 'off' : undefined/g
    )
    const nextActionRule = styleSource.match(
      /body \.p-dialog\.archive-upload-dialog-christmas \.p-button\.archive-upload-next-button \{([\s\S]*?)\n\}/
    )
    const nextActionHoverRule = styleSource.match(
      /body\s+\.p-dialog\.archive-upload-dialog-christmas\s+\.p-button\.archive-upload-next-button:not\(:disabled\):hover,[\s\S]*?\{([\s\S]*?)\n\}/
    )
    const backActionRule = styleSource.match(
      /body \.p-dialog\.archive-upload-dialog-christmas \.p-button\.archive-upload-back-button \{([\s\S]*?)\n\}/
    )
    const backActionHoverRule = styleSource.match(
      /body\s+\.p-dialog\.archive-upload-dialog-christmas\s+\.p-button\.archive-upload-back-button:hover,[\s\S]*?\{([\s\S]*?)\n\}/
    )
    const uploadContentRule = styleSource.match(
      /body \.p-dialog\.archive-upload-dialog-christmas \.p-dialog-content \{([\s\S]*?)\n\}/
    )
    const uploadStepperSurfaceRule = styleSource.match(
      /body \.p-dialog\.archive-upload-dialog-christmas \.p-stepper,\nbody \.p-dialog\.archive-upload-dialog-christmas \.p-steplist,\nbody \.p-dialog\.archive-upload-dialog-christmas \.p-steppanels,\nbody \.p-dialog\.archive-upload-dialog-christmas \.p-steppanel \{([\s\S]*?)\n\}/
    )
    const stepSnowResetRule = styleSource.match(
      /body \.p-dialog\.archive-upload-dialog-christmas \.p-step-header::after \{([\s\S]*?)\n\}/
    )
    const filePickerSnowResetRule = styleSource.match(
      /body\s+\.p-dialog\.archive-upload-dialog-christmas\s+\.p-button\.archive-upload-file-picker-button::after \{([\s\S]*?)\n\}/
    )
    const fileUploadSurfaceRule = styleSource.match(
      /body \.p-dialog\.archive-upload-dialog-christmas \.p-fileupload \{([\s\S]*?)\n\}/
    )
    const fileUploadContentRule = styleSource.match(
      /body \.p-dialog\.archive-upload-dialog-christmas \.p-fileupload-header,[\s\S]*?\.p-fileupload-content \{([\s\S]*?)\n\}/
    )

    expect(componentSource).toContain("'archive-upload-dialog-christmas': christmas")
    expect(componentSource).toContain("'archive-edit-dialog-christmas': christmas")
    expect(componentSource).not.toContain(
      "'archive-upload-dialog-christmas': christmas && !isWishMode"
    )
    expect(componentSource.match(/'archive-edit-overlay-christmas': christmas/g)).toHaveLength(5)
    expect(nextActionClasses).toHaveLength(3)
    expect(backActionClasses).toHaveLength(3)
    expect(snowOptIns).toHaveLength(3)
    expect(stepSnowPtBindings).toHaveLength(4)
    expect(stepSnowOptOut).toHaveLength(1)
    expect(nextActionRule?.[1]).toContain('background: linear-gradient(135deg, #3d8a64, #2d6c52);')
    expect(nextActionHoverRule?.[1]).toContain('border-color: rgba(255, 226, 143, 0.9);')
    expect(nextActionHoverRule?.[1]).toContain('0 0 0.34rem rgba(255, 218, 94, 0.58)')
    expect(nextActionHoverRule?.[1]).toContain('0 0 0.72rem rgba(255, 201, 59, 0.34)')
    expect(nextActionHoverRule?.[1]).toContain('text-shadow: 0 0 0.2rem rgba(255, 209, 72, 0.62);')
    expect(backActionRule?.[1]).toContain('color: #245368;')
    expect(backActionRule?.[1]).toContain('background: #d7edf5;')
    expect(backActionHoverRule?.[1]).toContain('background: #e5f4f9;')
    expect(backActionHoverRule?.[1]).toContain('0 0 0.34rem rgba(255, 218, 94, 0.58)')
    expect(uploadContentRule?.[1]).toContain('background: #f5eedc !important;')
    expect(uploadStepperSurfaceRule?.[1]).toContain('background: #f5eedc !important;')
    expect(stepSnowResetRule?.[1]).toContain('display: none;')
    expect(stepSnowResetRule?.[1]).toContain('content: none;')
    expect(componentSource).toContain('class="archive-upload-file-picker-button"')
    expect(componentSource).toContain(`:data-christmas-snow="christmas ? 'off' : undefined"`)
    expect(filePickerSnowResetRule?.[1]).toContain('display: none;')
    expect(filePickerSnowResetRule?.[1]).toContain('content: none;')
    expect(fileUploadSurfaceRule?.[1]).toContain('background: #f5eedc !important;')
    expect(fileUploadContentRule?.[1]).toContain('background: #f5eedc !important;')
  })

  it('preserves the backend category and course ordering contract', async () => {
    const wrapper = mountDialog({
      courseCategories: [
        { id: 2, key: 'second', name: 'Backend first category', order_index: 99 },
        { id: 1, key: 'first', name: 'Backend second category', order_index: -1 },
      ],
      coursesList: {
        second: [
          { id: 'later-index', name: 'Backend first course', order_index: 99 },
          { id: 'earlier-index', name: 'Backend second course', order_index: -1 },
        ],
      },
    })
    wrapper.vm.form.category = 'second'
    await flushPromises()

    expect(wrapper.vm.categoryOptions.map(({ value }) => value)).toEqual(['second', 'first'])
    expect(wrapper.vm.subjectOptions.map(({ code }) => code)).toEqual([
      'later-index',
      'earlier-index',
    ])
  })

  beforeAll(async () => {
    ensureDomMatrix()
    UploadArchiveDialog = (await import('@/components/UploadArchiveDialog.vue')).default
  }, 20_000)

  beforeEach(() => {
    trackEventMock.mockReset()
    toastAddMock.mockReset()
    archiveServiceMock.uploadArchive.mockResolvedValue()
    archiveServiceMock.editOwnerPendingSubmission.mockReset()
    archiveServiceMock.editOwnerPendingSubmission.mockResolvedValue({ data: {} })
    archiveServiceMock.getOwnerPendingPreviewFile.mockReset()
    archiveServiceMock.getOwnerPendingPreviewFile.mockResolvedValue({ data: new Blob(['current']) })
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

  it.each([
    ['midterm', 'midterm2', 2],
    ['quiz', 'quiz3', 3],
    ['final', 'final', null],
  ])('prefills constrained edit mode for %s submissions', async (type, name, sequence) => {
    const wrapper = mountDialog({
      modelValue: false,
      mode: 'edit',
      submissionId: 71,
      prefill: {
        submissionId: 71,
        course_id: 'c1',
        subject: 'Calculus I',
        category: 'freshman',
        professor: 'Prof. Lin',
        academic_year: 1141,
        archive_type: type,
        name,
        has_answers: true,
      },
    })
    await wrapper.setProps({ modelValue: true })
    await flushPromises()

    expect(wrapper.vm.dialogTitle).toBe('編輯考古投稿')
    expect(wrapper.text()).not.toContain('申請新增課程')
    expect(wrapper.text()).not.toContain('同時申請新增課程分類')
    expect(wrapper.vm.form).toEqual(
      expect.objectContaining({
        subjectId: 'c1',
        professor: 'Prof. Lin',
        academicYear: 1141,
        type,
        examNumber: sequence,
        hasAnswers: true,
        file: null,
      })
    )
    expect(wrapper.vm.generatedFilename).toBe(name)
    expect(wrapper.vm.canUpload).toBe(true)
    expect(wrapper.text()).toContain('保留目前檔案')
    wrapper.unmount()
  })

  it('submits metadata-only edits and allowlisted optional PDF replacements', async () => {
    const wrapper = mountDialog({
      modelValue: false,
      mode: 'edit',
      submissionId: 71,
      prefill: {
        course_id: 'c1',
        subject: 'Calculus I',
        category: 'freshman',
        professor: 'Prof. Lin',
        academic_year: 1141,
        archive_type: 'midterm',
        name: 'midterm2',
        has_answers: false,
        object_name: 'must-not-leak.pdf',
        owner_id: 10,
        status: 'pending',
      },
    })
    await wrapper.setProps({ modelValue: true })
    await flushPromises()

    await wrapper.vm.handleUpload()
    expect(pdfLoadMock).not.toHaveBeenCalled()
    expect(archiveServiceMock.editOwnerPendingSubmission).toHaveBeenLastCalledWith(71, {
      course_id: 'c1',
      professor: 'Prof. Lin',
      academic_year: 1141,
      archive_type: 'midterm',
      sequence: 2,
      has_answers: false,
      other_name: undefined,
      file: undefined,
    })
    expect(wrapper.emitted('upload-success')).toBeTruthy()

    await wrapper.setProps({ modelValue: false })
    await wrapper.setProps({ modelValue: true })
    await flushPromises()
    const replacement = {
      name: 'replacement.pdf',
      size: 1024,
      arrayBuffer: () => Promise.resolve(new ArrayBuffer(8)),
    }
    wrapper.vm.form.file = replacement
    wrapper.vm.previewUploadFile()
    expect(wrapper.vm.previewingCurrentFile).toBe(false)
    expect(wrapper.vm.uploadPreviewUrl).toBe('blob:url')
    await wrapper.vm.handleUpload()
    const replacementPayload = archiveServiceMock.editOwnerPendingSubmission.mock.calls.at(-1)[1]
    expect(replacementPayload.file).toBeInstanceOf(File)
    expect(replacementPayload.file.name).toBe('replacement.pdf')
    expect(replacementPayload).not.toHaveProperty('object_name')
    expect(replacementPayload).not.toHaveProperty('owner_id')
    expect(replacementPayload).not.toHaveProperty('status')
    wrapper.unmount()
  })

  it('previews current PDF, restores keep-current state, and cleans stale URLs', async () => {
    const wrapper = mountDialog({
      mode: 'edit',
      submissionId: 71,
      prefill: {
        course_id: 'c1',
        subject: 'Calculus I',
        category: 'freshman',
        professor: 'Prof. Lin',
        academic_year: 1141,
        archive_type: 'final',
        name: 'final',
      },
    })
    wrapper.vm.applyPrefill()
    await flushPromises()

    await wrapper.vm.previewCurrentFile()
    expect(archiveServiceMock.getOwnerPendingPreviewFile).toHaveBeenCalledWith(71)
    expect(wrapper.vm.uploadPreviewUrl).toBe('blob:url')

    wrapper.vm.form.file = { name: 'replacement.pdf', size: 512 }
    wrapper.vm.clearSelectedFile()
    expect(wrapper.vm.form.file).toBeNull()

    archiveServiceMock.editOwnerPendingSubmission.mockRejectedValueOnce({
      response: {
        status: 409,
        data: { detail: { code: 'archive_submission_stale_state' } },
      },
    })
    await wrapper.vm.handleUpload()
    expect(wrapper.emitted('stale')).toBeTruthy()
    expect(wrapper.emitted('update:modelValue').at(-1)).toEqual([false])
    expect(globalThis.URL.revokeObjectURL).toHaveBeenCalledWith('blob:url')
    expect(toastAddMock).toHaveBeenCalledWith(
      expect.objectContaining({ detail: '投稿狀態已變更，無法再編輯' })
    )
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

  it.each([
    ['midterm', 'midterm1', 1],
    ['midterm', 'midterm2', 2],
    ['quiz', 'quiz3', 3],
  ])(
    'keeps the %s %s exam number while applying Help Upload prefill',
    async (type, name, number) => {
      const wrapper = mountDialog({
        modelValue: false,
        sourceWishId: 52,
        prefill: {
          id: 52,
          course_id: 'c1',
          subject: 'Calculus I',
          category: 'freshman',
          professor: 'Prof. Lin',
          academic_year: 1141,
          archive_type: type,
          name,
        },
      })

      await wrapper.setProps({ modelValue: true })
      await flushPromises()

      expect(wrapper.vm.form.type).toBe(type)
      expect(wrapper.vm.form.examNumber).toBe(number)
      expect(wrapper.vm.generatedFilename).toBe(name)
      expect(wrapper.vm.canGoToStep3).toBe(true)

      wrapper.unmount()
    }
  )

  it('distinguishes an existing Archive from a duplicate Wish', async () => {
    const wrapper = mountDialog({ mode: 'wish' })
    const vm = wrapper.vm
    Object.assign(vm.form, {
      category: 'freshman',
      subject: { name: 'Calculus I', code: 'c1' },
      subjectId: 'c1',
      professor: 'Prof. Lin',
      academicYear: null,
      type: 'final',
      wishTitle: 'Need final',
    })
    await flushPromises()
    wishServiceMock.create.mockRejectedValueOnce({
      response: { data: { detail: { code: 'wish_target_already_available' } } },
    })

    await vm.handleUpload()

    expect(toastAddMock).toHaveBeenCalledWith(
      expect.objectContaining({
        severity: 'warn',
        summary: '考古已存在',
        detail: '這份考古已經存在，不需要再許願。',
      })
    )
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
