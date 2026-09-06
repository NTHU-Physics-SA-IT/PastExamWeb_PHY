import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'

const pdfStates = vi.hoisted(() => [])

vi.mock('@tato30/vue-pdf/minimal', async () => {
  const { defineComponent: defineVueComponent, shallowRef: makeShallowRef } = await import('vue')
  return {
    usePDF: (source, options) => {
      const state = {
        source,
        options,
        pdf: makeShallowRef(),
        pages: makeShallowRef(0),
      }
      pdfStates.push(state)
      return state
    },
    VuePDF: defineVueComponent({
      name: 'VuePDF',
      props: {
        pdf: { type: Object, default: null },
        page: { type: Number, default: 1 },
        width: { type: Number, default: 0 },
      },
      emits: ['loaded'],
      template:
        '<div class="vue-pdf-stub" :data-rendered-page="page" @click="$emit(\'loaded\', { width, height: width * 1.4 })"><slot /></div>',
    }),
  }
})

import PdfDocumentViewer from '@/components/PdfDocumentViewer.vue'

let intersectionCallback
let observedElements
let resizeCallback

function makeTask() {
  return { destroy: vi.fn().mockResolvedValue(undefined) }
}

async function resolveDocument(state, pageCount, task = makeTask()) {
  state.pages.value = pageCount
  state.pdf.value = task
  await nextTick()
  await nextTick()
  return task
}

describe('PdfDocumentViewer', () => {
  beforeEach(() => {
    pdfStates.length = 0
    intersectionCallback = null
    observedElements = []
    resizeCallback = null

    class IntersectionObserverMock {
      constructor(callback) {
        intersectionCallback = callback
      }

      observe(element) {
        observedElements.push(element)
      }

      unobserve() {}

      disconnect() {}
    }

    class ResizeObserverMock {
      constructor(callback) {
        resizeCallback = callback
      }

      observe() {}

      disconnect() {}
    }

    vi.stubGlobal('IntersectionObserver', IntersectionObserverMock)
    vi.stubGlobal('ResizeObserver', ResizeObserverMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('loads a document and activates later pages only near the viewport', async () => {
    const wrapper = mount(PdfDocumentViewer, {
      props: { source: 'blob:first-document' },
      attachTo: document.body,
    })
    Object.defineProperty(wrapper.element, 'clientWidth', { configurable: true, value: 900 })
    resizeCallback()
    await nextTick()

    expect(wrapper.attributes('aria-busy')).toBe('true')
    expect(pdfStates[0].source).toBe('blob:first-document')
    await resolveDocument(pdfStates[0], 3)

    expect(wrapper.find('[data-pdf-page="1"] .vue-pdf-stub').exists()).toBe(true)
    expect(wrapper.find('[data-pdf-page="2"] .vue-pdf-stub').exists()).toBe(false)
    expect(observedElements.map((element) => element.dataset.pdfPage)).toEqual(['2', '3'])

    const pageTwo = observedElements.find((element) => element.dataset.pdfPage === '2')
    intersectionCallback([{ isIntersecting: true, target: pageTwo }])
    await nextTick()

    expect(wrapper.find('[data-pdf-page="2"] .vue-pdf-stub').exists()).toBe(true)
    await wrapper.find('[data-pdf-page="2"] .vue-pdf-stub').trigger('click')
    expect(wrapper.find('[data-pdf-page="2"]').attributes('data-page-loaded')).toBe('true')
    await wrapper.find('[data-pdf-page="1"] .vue-pdf-stub').trigger('click')
    expect(wrapper.emitted('load')).toHaveLength(1)
    expect(wrapper.attributes('aria-busy')).toBe('false')

    wrapper.unmount()
  })

  it('destroys the old task and ignores stale errors when the source changes', async () => {
    const wrapper = mount(PdfDocumentViewer, {
      props: { source: 'https://example.com/first.pdf' },
      attachTo: document.body,
    })
    Object.defineProperty(wrapper.element, 'clientWidth', { configurable: true, value: 700 })
    resizeCallback()
    const oldState = pdfStates[0]
    const oldTask = await resolveDocument(oldState, 2)

    await wrapper.setProps({ source: 'blob:replacement' })
    expect(oldTask.destroy).toHaveBeenCalledOnce()
    expect(pdfStates[1].source).toBe('blob:replacement')
    expect(wrapper.findAll('.pdf-page-shell')).toHaveLength(0)

    oldState.options.onError(new Error('destroyed old task'))
    await nextTick()
    expect(wrapper.emitted('error')).toBeUndefined()

    await resolveDocument(pdfStates[1], 1)
    expect(wrapper.findAll('.pdf-page-shell')).toHaveLength(1)
    wrapper.unmount()
  })

  it('emits a document error without exposing worker details', async () => {
    const wrapper = mount(PdfDocumentViewer, {
      props: { source: 'https://example.com/broken.pdf' },
    })

    pdfStates[0].options.onError(new Error('worker internals'))
    await nextTick()

    expect(wrapper.emitted('error')).toHaveLength(1)
    expect(wrapper.attributes('aria-busy')).toBe('false')
    expect(wrapper.text()).not.toContain('worker internals')
    expect(wrapper.findAll('.pdf-page-shell')).toHaveLength(0)
    wrapper.unmount()
  })
})
