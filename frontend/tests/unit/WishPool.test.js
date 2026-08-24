import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import wishPoolSource from '@/components/WishPool.vue?raw'

const wishServiceMock = vi.hoisted(() => ({
  list: vi.fn(),
  report: vi.fn(),
  remove: vi.fn(),
  toggleHeart: vi.fn(),
}))
const confirmRequireMock = vi.hoisted(() => vi.fn())
const toastAddMock = vi.hoisted(() => vi.fn())

vi.mock('@/api', () => ({ wishService: wishServiceMock }))
vi.mock('@/utils/auth', () => ({ getCurrentUser: () => ({ id: 1, is_admin: true }) }))
vi.mock('primevue/useconfirm', () => ({ useConfirm: () => ({ require: confirmRequireMock }) }))
vi.mock('primevue/usetoast', () => ({ useToast: () => ({ add: toastAddMock }) }))

const sampleWish = {
  id: 7,
  title: '量子資訊期末考完整長訊息，泡泡表面只能顯示兩行但詳細視窗必須完整保留',
  subject: '量子資訊',
  professor: 'Prof. Lin',
  academic_year: 1141,
  name: 'final',
  creator_name: 'Alice',
  created_at: '2026-08-18T00:00:00Z',
  heart_count: 0,
  hearted_by_me: false,
  fulfilled: false,
}

const stubs = {
  Button: {
    props: ['label', 'loading', 'disabled'],
    emits: ['click'],
    template:
      '<button :disabled="disabled" @click="$emit(\'click\', $event)">{{ label }}<slot /></button>',
  },
  Dialog: {
    props: ['visible'],
    emits: ['update:visible'],
    template: '<div v-if="visible" data-test="wish-dialog"><slot name="header" /><slot /></div>',
  },
  Message: { template: '<div><slot /></div>' },
  ProgressSpinner: { template: '<div />' },
  Tag: { template: '<span><slot /></span>' },
  InlineCommentReport: {
    props: ['targetType', 'message', 'loading'],
    template: '<div data-test="shared-report">{{ targetType }}:{{ message.content }}</div>',
  },
}

class ResizeObserverMock {
  static instances = []

  constructor(callback) {
    this.callback = callback
    ResizeObserverMock.instances.push(this)
  }

  observe = vi.fn()
  disconnect = vi.fn()
}

const mountedWrappers = []
let frameId = 0
let reducedMotion = false
let requestAnimationFrameMock
let cancelAnimationFrameMock

function installBrowserMocks() {
  window.matchMedia = vi.fn((query) => ({
    matches: query === '(prefers-reduced-motion: reduce)' && reducedMotion,
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }))
  requestAnimationFrameMock = vi.fn(() => ++frameId)
  cancelAnimationFrameMock = vi.fn()
  window.requestAnimationFrame = requestAnimationFrameMock
  window.cancelAnimationFrame = cancelAnimationFrameMock
  globalThis.ResizeObserver = ResizeObserverMock
}

async function mountPool(items = [sampleWish]) {
  wishServiceMock.list.mockResolvedValue({
    data: { items: items.map((wish) => ({ ...wish })), total: items.length },
  })
  const WishPool = (await import('@/components/WishPool.vue')).default
  const wrapper = mount(WishPool, {
    global: { stubs, mocks: { $t: (key) => key } },
  })
  mountedWrappers.push(wrapper)
  await flushPromises()
  return wrapper
}

function installPointerCaptureMocks(viewport) {
  let capturedPointerId = null
  const setPointerCapture = vi.fn((pointerId) => {
    capturedPointerId = pointerId
  })
  const hasPointerCapture = vi.fn((pointerId) => capturedPointerId === pointerId)
  const releasePointerCapture = vi.fn((pointerId) => {
    if (capturedPointerId === pointerId) capturedPointerId = null
  })

  Object.assign(viewport.element, {
    setPointerCapture,
    hasPointerCapture,
    releasePointerCapture,
  })

  return { setPointerCapture, hasPointerCapture, releasePointerCapture }
}

function dispatchPointerEvent(element, type, properties) {
  const event = new Event(type, { bubbles: true, cancelable: true })
  Object.defineProperties(
    event,
    Object.fromEntries(
      Object.entries(properties).map(([key, value]) => [key, { configurable: true, value }])
    )
  )
  element.dispatchEvent(event)
}

describe('Wish Pool bubble presentation and interactions', () => {
  beforeEach(() => {
    frameId = 0
    reducedMotion = false
    ResizeObserverMock.instances = []
    confirmRequireMock.mockReset()
    toastAddMock.mockReset()
    wishServiceMock.list.mockReset()
    wishServiceMock.report.mockReset().mockResolvedValue({ data: {} })
    wishServiceMock.remove.mockReset().mockResolvedValue({ data: {} })
    wishServiceMock.toggleHeart.mockReset().mockResolvedValue({
      data: { hearted: true, heart_count: 1 },
    })
    installBrowserMocks()
  })

  afterEach(() => {
    while (mountedWrappers.length) mountedWrappers.pop().unmount()
    delete globalThis.ResizeObserver
  })

  it('preserves the responsive header controls around the redesigned display area', () => {
    expect(wishPoolSource).toMatch(/container-type:\s*inline-size/)
    expect(wishPoolSource).toMatch(/@container \(max-width:\s*720px\)/)
    expect(wishPoolSource).toContain('@click="emit(\'add-wish\')"')
    expect(wishPoolSource).toContain('class="load-more"')
  })

  it('fills only its assigned content pane while keeping the bubble world clipped', () => {
    expect(wishPoolSource).toMatch(
      /\.wish-pool\s*\{[^}]*display:\s*flex;[^}]*height:\s*100%;[^}]*min-height:\s*0;/s
    )
    expect(wishPoolSource).toMatch(
      /\.wish-bubble-viewport\s*\{[^}]*flex:\s*1 1 auto;[^}]*width:\s*100%;[^}]*height:\s*auto;[^}]*overflow:\s*hidden;/s
    )
    expect(wishPoolSource).not.toMatch(/(?:width|height):\s*100v[wh]/)
    expect(wishPoolSource).not.toMatch(/position:\s*fixed/)
    expect(wishPoolSource).not.toMatch(/\.(?:sidebar|navbar)\b/)
  })

  it('renders circular bubbles with a two-line message and sibling heart control', async () => {
    const wrapper = await mountPool()
    const bubble = wrapper.get('.wish-bubble')
    const openButton = bubble.get('.wish-bubble__open')
    const heartButton = bubble.get('.wish-bubble__heart')

    expect(bubble.attributes('style')).toContain('--bubble-diameter: 116px')
    expect(openButton.text()).toContain(sampleWish.title)
    expect(openButton.find('.wish-bubble__heart').exists()).toBe(false)
    expect(heartButton.text()).toBe('0')
    expect(wishPoolSource).toContain('-webkit-line-clamp: 2')
    expect(wishPoolSource).toMatch(/aspect-ratio:\s*1/)
    expect(wishPoolSource).toMatch(/border-radius:\s*50%/)
  })

  it('opens the existing detail dialog from the bubble and keeps the full message available', async () => {
    const wrapper = await mountPool()

    await wrapper.get('.wish-bubble__open').trigger('click')

    expect(wrapper.get('[data-test="wish-dialog"]').text()).toContain(sampleWish.title)
    expect(wrapper.get('[data-test="wish-dialog"]').text()).toContain('量子資訊')
  })

  it('votes from the heart button without opening the detail dialog and syncs the count', async () => {
    const wrapper = await mountPool()
    const viewport = wrapper.get('.wish-bubble-viewport')
    const { setPointerCapture } = installPointerCaptureMocks(viewport)

    dispatchPointerEvent(wrapper.get('.wish-bubble__heart').element, 'pointerdown', {
      isPrimary: true,
      button: 0,
      pointerId: 1,
      clientX: 20,
      clientY: 20,
    })
    await wrapper.get('.wish-bubble__heart').trigger('click')
    await flushPromises()

    expect(setPointerCapture).not.toHaveBeenCalled()
    expect(wishServiceMock.toggleHeart).toHaveBeenCalledWith(7)
    expect(wrapper.find('[data-test="wish-dialog"]').exists()).toBe(false)
    expect(wrapper.get('.wish-bubble__heart').text()).toBe('1')
    expect(wrapper.get('.wish-bubble').attributes('style')).not.toContain('116px')
  })

  it('distinguishes a tap from camera pan before opening a bubble', async () => {
    const wrapper = await mountPool()
    const viewport = wrapper.get('.wish-bubble-viewport')
    const openButton = wrapper.get('.wish-bubble__open')
    const world = wrapper.get('.wish-bubble-world')
    const { setPointerCapture, releasePointerCapture } = installPointerCaptureMocks(viewport)

    const target = openButton.element
    wrapper.vm.handlePointerDown({
      isPrimary: true,
      button: 0,
      pointerId: 1,
      clientX: 20,
      clientY: 20,
      target,
    })
    expect(setPointerCapture).not.toHaveBeenCalled()
    wrapper.vm.handlePointerMove({
      pointerId: 1,
      clientX: 23,
      clientY: 24,
      preventDefault: vi.fn(),
    })
    wrapper.vm.handlePointerEnd({ pointerId: 1 })
    await openButton.trigger('click')
    expect(setPointerCapture).not.toHaveBeenCalled()
    expect(releasePointerCapture).not.toHaveBeenCalled()
    expect(wrapper.find('[data-test="wish-dialog"]').exists()).toBe(true)

    wrapper.vm.closeWishDetail()
    await wrapper.vm.$nextTick()

    wrapper.vm.handlePointerDown({
      isPrimary: true,
      button: 0,
      pointerId: 2,
      clientX: 30,
      clientY: 30,
      target,
    })
    expect(setPointerCapture).not.toHaveBeenCalled()
    const preventDefault = vi.fn()
    wrapper.vm.handlePointerMove({
      pointerId: 2,
      clientX: 70,
      clientY: 60,
      preventDefault,
    })
    expect(setPointerCapture).toHaveBeenCalledTimes(1)
    expect(setPointerCapture).toHaveBeenCalledWith(2)
    expect(preventDefault).toHaveBeenCalledTimes(1)
    expect(world.attributes('style')).toContain('translate3d(40px, 30px, 0)')
    wrapper.vm.handlePointerEnd({ pointerId: 2 })
    expect(releasePointerCapture).toHaveBeenCalledTimes(1)
    expect(releasePointerCapture).toHaveBeenCalledWith(2)
    viewport.element.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
    expect(wrapper.find('[data-test="wish-dialog"]').exists()).toBe(false)
    await openButton.trigger('click')
    expect(wrapper.find('[data-test="wish-dialog"]').exists()).toBe(true)
  })

  it('preserves camera and bubble state when its assigned content pane resizes', async () => {
    const wrapper = await mountPool()
    const viewport = wrapper.get('.wish-bubble-viewport')
    const openButton = wrapper.get('.wish-bubble__open')
    const world = wrapper.get('.wish-bubble-world')
    installPointerCaptureMocks(viewport)

    wrapper.vm.handlePointerDown({
      isPrimary: true,
      button: 0,
      pointerId: 4,
      clientX: 10,
      clientY: 10,
      target: openButton.element,
    })
    wrapper.vm.handlePointerMove({
      pointerId: 4,
      clientX: 50,
      clientY: 35,
      preventDefault: vi.fn(),
    })
    wrapper.vm.handlePointerEnd({ pointerId: 4 })
    const cameraTransform = world.attributes('style')
    const bubbleTransform = wrapper.get('.wish-bubble').attributes('style')
    const framesBeforeResize = requestAnimationFrameMock.mock.calls.length

    ResizeObserverMock.instances[0].callback([])
    await wrapper.vm.$nextTick()

    expect(world.attributes('style')).toBe(cameraTransform)
    expect(wrapper.get('.wish-bubble').attributes('style')).toBe(bubbleTransform)
    expect(requestAnimationFrameMock).toHaveBeenCalledTimes(framesBeforeResize)
  })

  it('cleans up pointer cancellation and unmount with and without active capture', async () => {
    const wrapper = await mountPool()
    const viewport = wrapper.get('.wish-bubble-viewport')
    const openButton = wrapper.get('.wish-bubble__open')
    const { setPointerCapture, releasePointerCapture } = installPointerCaptureMocks(viewport)
    const target = openButton.element

    wrapper.vm.handlePointerDown({
      isPrimary: true,
      button: 0,
      pointerId: 1,
      clientX: 10,
      clientY: 10,
      target,
    })
    expect(() => wrapper.vm.handlePointerCancel({ pointerId: 1 })).not.toThrow()
    expect(setPointerCapture).not.toHaveBeenCalled()
    expect(releasePointerCapture).not.toHaveBeenCalled()

    wrapper.vm.handlePointerDown({
      isPrimary: true,
      button: 0,
      pointerId: 2,
      clientX: 10,
      clientY: 10,
      target,
    })
    wrapper.vm.handlePointerMove({
      pointerId: 2,
      clientX: 30,
      clientY: 10,
      preventDefault: vi.fn(),
    })
    expect(setPointerCapture).toHaveBeenCalledWith(2)
    expect(() => wrapper.vm.handlePointerCancel({ pointerId: 2 })).not.toThrow()
    expect(releasePointerCapture).toHaveBeenCalledWith(2)

    wrapper.vm.handlePointerDown({
      isPrimary: true,
      button: 0,
      pointerId: 3,
      clientX: 10,
      clientY: 10,
      target,
    })
    wrapper.vm.handlePointerMove({
      pointerId: 3,
      clientX: 30,
      clientY: 10,
      preventDefault: vi.fn(),
    })
    mountedWrappers.pop()
    wrapper.unmount()
    expect(releasePointerCapture).toHaveBeenCalledWith(3)
  })

  it('uses one shared animation frame for multiple bubbles and none in reduced motion', async () => {
    const secondWish = { ...sampleWish, id: 8, title: '電磁學期中考', heart_count: 8 }
    const animatedWrapper = await mountPool([sampleWish, secondWish])
    expect(requestAnimationFrameMock).toHaveBeenCalledTimes(1)

    mountedWrappers.pop()
    animatedWrapper.unmount()
    expect(cancelAnimationFrameMock).toHaveBeenCalledWith(1)
    expect(ResizeObserverMock.instances[0].disconnect).toHaveBeenCalledTimes(1)
    requestAnimationFrameMock.mockClear()
    reducedMotion = true
    await mountPool([sampleWish, secondWish])
    expect(requestAnimationFrameMock).not.toHaveBeenCalled()
  })

  it('uses the shared report form and canonical confirmation service', async () => {
    const wrapper = await mountPool()
    wrapper.vm.selected = wrapper.vm.wishes[0]
    await flushPromises()

    wrapper.vm.toggleReport()
    await flushPromises()
    expect(wrapper.get('[data-test="shared-report"]').text()).toContain('wish:量子資訊期末考')

    await wrapper.vm.submitReport({ report_reason: 'misinformation', custom_message: null })
    expect(wishServiceMock.report).toHaveBeenCalledWith(7, {
      report_reason: 'misinformation',
      custom_message: null,
    })
    expect(toastAddMock).toHaveBeenCalledWith(expect.objectContaining({ severity: 'success' }))

    wrapper.vm.requestRemoveWish()
    expect(confirmRequireMock).toHaveBeenCalledWith(
      expect.objectContaining({
        header: '永久刪除這筆許願？',
        acceptClass: 'p-button-danger',
        defaultFocus: 'reject',
      })
    )
    expect(wishServiceMock.remove).not.toHaveBeenCalled()

    await confirmRequireMock.mock.calls[0][0].accept()
    expect(wishServiceMock.remove).toHaveBeenCalledWith(7)
    expect(wrapper.vm.selected).toBeNull()
  })

  it('presents Any Semester and paginates the server-filtered pool', async () => {
    const anySemesterWish = { ...sampleWish, id: 8, title: '不限學期願望', academic_year: null }
    wishServiceMock.list
      .mockResolvedValueOnce({ data: { items: [{ ...sampleWish }], total: 2 } })
      .mockResolvedValueOnce({ data: { items: [{ ...anySemesterWish }], total: 2 } })

    const WishPool = (await import('@/components/WishPool.vue')).default
    const wrapper = mount(WishPool, { global: { stubs, mocks: { $t: (key) => key } } })
    mountedWrappers.push(wrapper)
    await flushPromises()
    expect(wrapper.vm.semesterLabel(sampleWish)).toBe('114上學期')
    expect(wrapper.vm.semesterLabel(anySemesterWish)).toBe('不限學期')

    await wrapper.vm.loadMore()
    expect(wishServiceMock.list).toHaveBeenNthCalledWith(2, { limit: 60, offset: 1 })
    expect(wrapper.vm.wishes.map((wish) => wish.id)).toEqual([7, 8])
  })
})
