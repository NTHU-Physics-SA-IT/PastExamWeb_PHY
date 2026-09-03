import { describe, it, expect, vi, beforeEach, afterEach, beforeAll } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import pdfPreviewSource from '@/components/PdfPreviewModal.vue?raw'

const unauthorizedCallbacks = vi.hoisted(() => [])
let consoleErrorSpy
let PdfPreviewModal

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

vi.mock('@/utils/useUnauthorizedEvent.js', () => ({
  useUnauthorizedEvent: (handler) => {
    unauthorizedCallbacks.push(handler)
  },
}))

const stubComponent = { template: '<div><slot /></div>' }
const DialogStyleStub = {
  name: 'DialogStyleStub',
  props: {
    contentStyle: { type: Object, default: null },
  },
  template: '<div><slot /></div>',
}

describe('PdfPreviewModal', () => {
  beforeAll(async () => {
    ensureDomMatrix()
    PdfPreviewModal = (await import('@/components/PdfPreviewModal.vue')).default
  }, 20_000)

  beforeEach(() => {
    unauthorizedCallbacks.length = 0
    consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    consoleErrorSpy.mockRestore()
  })

  it('handles pdf events and download workflow', async () => {
    const wrapper = mount(PdfPreviewModal, {
      props: {
        visible: true,
        previewUrl: '',
      },
      global: {
        stubs: {
          Dialog: stubComponent,
          ProgressSpinner: stubComponent,
          Button: stubComponent,
        },
      },
    })

    const vm = wrapper.vm

    vm.handlePdfError(new Error('failed'))
    expect(vm.pdfError).toBe(true)
    expect(wrapper.emitted('error')).toBeTruthy()

    vm.handlePdfLoaded()
    expect(vm.pdfError).toBe(false)
    expect(wrapper.emitted('load')).toBeTruthy()

    vm.onHide()
    expect(wrapper.emitted('hide')).toBeTruthy()

    vm.handleDownload()
    expect(vm.downloading).toBe(true)
    const downloadEmit = wrapper.emitted('download')
    expect(downloadEmit).toBeTruthy()
    const complete = downloadEmit[0][0]
    complete()
    expect(vm.downloading).toBe(false)

    unauthorizedCallbacks.forEach((cb) => cb())
    expect(wrapper.emitted('update:visible')).toBeTruthy()

    wrapper.unmount()
  })

  it('formats raw pre-100 academic term metadata', () => {
    const wrapper = mount(PdfPreviewModal, {
      props: {
        visible: true,
        previewUrl: '',
        academicYear: 992,
      },
      global: {
        stubs: {
          Dialog: stubComponent,
          ProgressSpinner: stubComponent,
          Button: stubComponent,
        },
      },
    })

    expect(wrapper.vm.metaTextItems).toContainEqual({
      key: 'year',
      icon: 'pi-calendar',
      value: '99下學期',
    })
    wrapper.unmount()
  })

  it('handles loading lifecycle for pdf task', async () => {
    const wrapper = mount(PdfPreviewModal, {
      props: {
        visible: true,
        previewUrl: 'https://example.com/file.pdf',
      },
      global: {
        stubs: {
          Dialog: stubComponent,
          ProgressSpinner: stubComponent,
          Button: stubComponent,
        },
      },
    })

    // trigger load with url and expect loading
    await wrapper.setProps({ previewUrl: 'https://example.com/file.pdf' })

    // simulate the native iframe load event
    expect(wrapper.vm.pdfLoading).toBe(true)
    wrapper.vm.handlePdfLoaded()
    expect(wrapper.vm.pdfLoading).toBe(false)
    expect(wrapper.vm.pdfError).toBe(false)

    // simulate the native iframe error event
    wrapper.vm.handlePdfError(new Error('load failed'))
    expect(wrapper.vm.pdfError).toBe(true)
    expect(wrapper.emitted('error')).toBeTruthy()

    // clear url resets loading/error
    await wrapper.setProps({ previewUrl: '' })
    await nextTick()
    expect(wrapper.vm.pdfLoading).toBe(false)
    expect(wrapper.vm.pdfError).toBe(false)

    wrapper.unmount()
  })

  it('can disable discussion panel explicitly', async () => {
    const wrapper = mount(PdfPreviewModal, {
      props: {
        visible: true,
        previewUrl: '',
        courseId: 1,
        archiveId: 2,
        showDiscussion: false,
      },
      global: {
        stubs: {
          Dialog: stubComponent,
          ProgressSpinner: stubComponent,
          Button: stubComponent,
          ArchiveDiscussionPanel: { template: '<div class="discussion-panel-stub"></div>' },
          ArchiveReportPanel: { template: '<div class="archive-report-panel-stub"></div>' },
        },
      },
    })

    expect(wrapper.find('.discussion-panel-stub').exists()).toBe(false)
    wrapper.unmount()
  })

  it('uses Tablet Portrait discussion behavior from Major Breakpoint 768', () => {
    expect(pdfPreviewSource).toContain("window.matchMedia('(width < 768px)')")
    expect(pdfPreviewSource).toContain('@media (width < 768px)')
    expect(pdfPreviewSource).not.toContain('(max-width: 768px)')
  })

  it('顯示明確的考古題檔案缺失訊息', async () => {
    const wrapper = mount(PdfPreviewModal, {
      props: {
        visible: true,
        previewUrl: '',
        error: true,
        errorMessage: '檔案缺失：找不到這份考古題檔案。',
      },
      global: {
        stubs: {
          Dialog: stubComponent,
          ProgressSpinner: stubComponent,
          Button: stubComponent,
        },
      },
    })

    expect(wrapper.text()).toContain('檔案缺失')
    expect(wrapper.text()).toContain('考古題檔案')
    wrapper.unmount()
  })

  it('renders discussion panel when enabled and ids present', async () => {
    const wrapper = mount(PdfPreviewModal, {
      props: {
        visible: true,
        previewUrl: '',
        courseId: 1,
        archiveId: 2,
        showDiscussion: true,
      },
      global: {
        stubs: {
          Dialog: stubComponent,
          ProgressSpinner: stubComponent,
          Button: stubComponent,
          ArchiveDiscussionPanel: { template: '<div class="discussion-panel-stub"></div>' },
          ArchiveReportPanel: { template: '<div class="archive-report-panel-stub"></div>' },
        },
      },
    })

    expect(wrapper.find('.discussion-panel-stub').exists()).toBe(true)
    wrapper.unmount()
  })

  it('keeps the main dialog out of the nested discussion scroll hierarchy', () => {
    const wrapper = mount(PdfPreviewModal, {
      props: {
        visible: true,
        previewUrl: '',
        courseId: 1,
        archiveId: 2,
        showDiscussion: true,
      },
      global: {
        stubs: {
          Dialog: DialogStyleStub,
          ProgressSpinner: stubComponent,
          Button: stubComponent,
          ArchiveDiscussionPanel: { template: '<div class="discussion-panel-stub"></div>' },
          ArchiveReportPanel: { template: '<div class="archive-report-panel-stub"></div>' },
        },
      },
    })

    const dialogs = wrapper.findAllComponents({ name: 'DialogStyleStub' })
    expect(dialogs).toHaveLength(2)
    expect(dialogs[0].props('contentStyle')).toEqual({ flex: '1 1 auto', overflow: 'clip' })
    expect(dialogs[1].props('contentStyle')).toEqual({ flex: '1 1 auto' })
    expect(wrapper.find('.discussion-panel-stub').exists()).toBe(true)
    wrapper.unmount()
  })

  it('switches between discussion and archive report without unmounting discussion', async () => {
    const wrapper = mount(PdfPreviewModal, {
      props: {
        visible: true,
        previewUrl: '',
        courseId: 1,
        archiveId: 2,
        courseName: '電磁學',
        title: '期中考',
      },
      global: {
        stubs: {
          Dialog: stubComponent,
          ProgressSpinner: stubComponent,
          Button: {
            inheritAttrs: false,
            props: ['label'],
            template: '<button v-bind="$attrs">{{ label }}</button>',
          },
          ArchiveDiscussionPanel: {
            template: '<div class="discussion-panel-stub"><textarea value="draft" /></div>',
          },
          ArchiveReportPanel: {
            template: '<div class="archive-report-panel-stub"></div>',
          },
        },
      },
    })

    expect(wrapper.vm.sidePanelMode).toBe('discussion')
    expect(wrapper.find('.archive-report-panel-stub').exists()).toBe(false)
    wrapper.vm.handleArchiveReportClick()
    await nextTick()
    expect(wrapper.vm.sidePanelMode).toBe('exam-report')
    expect(wrapper.find('.discussion-panel-stub').exists()).toBe(true)
    expect(wrapper.find('.archive-report-panel-stub').exists()).toBe(true)

    wrapper.vm.returnToDiscussion()
    await nextTick()
    expect(wrapper.vm.sidePanelMode).toBe('discussion')
    expect(wrapper.find('.discussion-panel-stub textarea').element.value).toBe('draft')
    wrapper.unmount()
  })
})
