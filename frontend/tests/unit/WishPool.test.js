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
let resizeObserverCallback
let resizeObserverTarget
let resizeObserverDisconnected

vi.mock('@/api', () => ({ wishService: wishServiceMock }))
vi.mock('@/utils/auth', () => ({ getCurrentUser: () => ({ id: 1, is_admin: true }) }))
vi.mock('primevue/useconfirm', () => ({ useConfirm: () => ({ require: confirmRequireMock }) }))
vi.mock('primevue/usetoast', () => ({ useToast: () => ({ add: toastAddMock }) }))

const sampleWish = {
  id: 7,
  title: '量子資訊期末考',
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
  Button: { template: '<button><slot /></button>' },
  Dialog: { template: '<div><slot /></div>' },
  InputNumber: { template: '<input />' },
  InputText: { template: '<input />' },
  Message: { template: '<div><slot /></div>' },
  ProgressSpinner: { template: '<div />' },
  Select: { template: '<select />' },
  Tag: { template: '<span><slot /></span>' },
  Textarea: { template: '<textarea />' },
  InlineCommentReport: {
    props: ['targetType', 'message', 'loading'],
    template: '<div data-test="shared-report">{{ targetType }}:{{ message.content }}</div>',
  },
}

function dispatchPointer(element, type, options) {
  const event = new MouseEvent(type, {
    bubbles: true,
    cancelable: true,
    button: options.button ?? 0,
    clientX: options.clientX,
    clientY: options.clientY,
  })
  Object.defineProperties(event, {
    pointerId: { value: options.pointerId ?? 1 },
    pointerType: { value: options.pointerType ?? 'mouse' },
    isPrimary: { value: true },
  })
  element.dispatchEvent(event)
}

describe('Wish Pool focused interactions', () => {
  beforeEach(() => {
    resizeObserverCallback = null
    resizeObserverTarget = null
    resizeObserverDisconnected = false
    vi.stubGlobal(
      'ResizeObserver',
      class {
        constructor(callback) {
          resizeObserverCallback = callback
        }
        observe(element) {
          resizeObserverTarget = element
        }
        disconnect() {
          resizeObserverDisconnected = true
        }
      }
    )
    confirmRequireMock.mockReset()
    toastAddMock.mockReset()
    wishServiceMock.list
      .mockReset()
      .mockResolvedValue({ data: { items: [{ ...sampleWish }], total: 1 } })
    wishServiceMock.report.mockReset().mockResolvedValue({ data: {} })
    wishServiceMock.remove.mockReset().mockResolvedValue({ data: {} })
    wishServiceMock.toggleHeart
      .mockReset()
      .mockResolvedValue({ data: { hearted: true, heart_count: 1 } })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('reflows the header before the add-wish button reaches the cramped middle state', () => {
    expect(wishPoolSource).toMatch(/container-type:\s*inline-size/)
    expect(wishPoolSource).toMatch(/@container \(max-width:\s*720px\)/)
    expect(wishPoolSource).toMatch(
      /@container \(max-width:\s*720px\)[\s\S]*?\.wish-header\s*\{[^}]*align-items:\s*stretch;[^}]*flex-direction:\s*column;/
    )
    expect(wishPoolSource).toMatch(
      /\.wish-header :deep\(\.p-button\)\s*\{[^}]*flex:\s*0 0 auto;[^}]*white-space:\s*nowrap[;}]/
    )
  })

  it('measures the exact pool viewport and remains free of continuous layout work', () => {
    expect(wishPoolSource).toContain('ref="viewportRef"')
    expect(wishPoolSource).toContain('class="wish-pool-stage"')
    expect(wishPoolSource).toContain('class="wish-pool-world"')
    expect(wishPoolSource).toContain('createResponsiveWishLayout')
    expect(wishPoolSource).toContain('appendResponsiveWishPositions')
    expect(wishPoolSource).toContain('@pointermove="movePan"')
    expect(wishPoolSource).not.toContain('requestAnimationFrame')
    expect(wishPoolSource).toContain('new ResizeObserver')
    expect(wishPoolSource).not.toContain('window.innerWidth')
    expect(wishPoolSource).not.toContain('window.innerHeight')
    expect(wishPoolSource).not.toContain('navigator.userAgent')
    expect(wishPoolSource).toContain("layoutMode.value === 'mobile' ? 0 : camera.x")
    expect(wishPoolSource).toContain("camera.x = layoutMode.value === 'mobile' ? 0")
    expect(wishPoolSource).toMatch(
      /\.wish-pool-stage\s*\{[^}]*position:\s*relative;[^}]*flex:\s*1 1 auto;[^}]*overflow:\s*hidden;[^}]*touch-action:\s*none;/
    )
    expect(wishPoolSource).toContain("'--wish-x':")
    expect(wishPoolSource).toContain("'--wish-y':")
    expect(wishPoolSource).not.toContain("'--wish-y-compact':")
    expect(wishPoolSource).not.toMatch(/calc\([^)]*\*\s*var\(--wish-cell-/)
  })

  it('uses heart-scaled typography and clamps naturally wrapped titles to two lines', () => {
    expect(wishPoolSource).toContain('class="wish-word__title"')
    expect(wishPoolSource).toContain('wishFontSizeRem(wish.heart_count)')
    expect(wishPoolSource).toMatch(/\.wish-item\s*\{[^}]*max-width:\s*min\(15rem,[^;]*;/)
    expect(wishPoolSource).toMatch(
      /\.wish-word__title\s*\{[^}]*display:\s*-webkit-box;[^}]*overflow:\s*hidden;[^}]*overflow-wrap:\s*anywhere;[^}]*-webkit-line-clamp:\s*2;[^}]*white-space:\s*normal;/
    )
    expect(wishPoolSource).toContain("font-family: 'Huninn', 'Noto Sans TC', system-ui, sans-serif")
    expect(wishPoolSource).not.toContain('densityFontBoost')
    expect(wishPoolSource).not.toContain('baseFontSize')
    expect(wishPoolSource).not.toContain('offsetWidth')
  })

  it('reuses discussion icon actions in the Wish detail header', () => {
    expect(wishPoolSource).toContain(
      'class="discussion-action-button discussion-action-like-button"'
    )
    expect(wishPoolSource).toContain('class="discussion-action-button"')
    expect(wishPoolSource).toContain(':class="{ \'is-active\': selected.hearted_by_me }"')
    expect(wishPoolSource).toContain(':aria-pressed="selected.hearted_by_me"')
    expect(wishPoolSource).toContain('@click="toggleHeart()"')
    expect(wishPoolSource).toContain('@click="toggleReport"')
  })

  it('uses the existing fulfilled state for a theme-safe success treatment', () => {
    expect(wishPoolSource).toContain(':class="{ fulfilled: wish.fulfilled }"')
    expect(wishPoolSource).toContain('v-if="wish.fulfilled" class="fulfilled-label"')
    expect(wishPoolSource).toMatch(
      /\.wish-item\.fulfilled\s*\{[^}]*color:\s*var\(--green-600\);[^}]*font-weight:\s*600/
    )
    expect(wishPoolSource).not.toMatch(
      /\.wish-item\.fulfilled\s*\{[^}]*(?:background|box-shadow|border):/
    )
    expect(wishPoolSource).toMatch(/\.fulfilled-label\s*\{[^}]*font-weight:\s*700/)
  })

  async function resizePool(wrapper, viewport) {
    resizeObserverCallback([
      {
        target: resizeObserverTarget,
        contentRect: { width: viewport.width, height: viewport.height },
      },
    ])
    await flushPromises()
    return wrapper
  }

  async function mountPool({ selectWish = true, viewport = { width: 1200, height: 720 } } = {}) {
    const WishPool = (await import('@/components/WishPool.vue')).default
    const wrapper = mount(WishPool, {
      props: { coursesList: {}, courseCategories: [] },
      global: { stubs, mocks: { $t: (key) => key } },
    })
    await flushPromises()
    expect(resizeObserverTarget).toBe(wrapper.get('.wish-pool-stage').element)
    await resizePool(wrapper, viewport)
    if (selectWish) {
      wrapper.vm.selected = wrapper.vm.wishes[0]
      await flushPromises()
    }
    return wrapper
  }

  it('uses the shared report form and canonical confirmation service', async () => {
    const wrapper = await mountPool()

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
      .mockReset()
      .mockResolvedValueOnce({ data: { items: [sampleWish], total: 2 } })
      .mockResolvedValueOnce({ data: { items: [anySemesterWish], total: 2 } })

    const wrapper = await mountPool()
    expect(wrapper.vm.semesterLabel(sampleWish)).toBe('114上學期')
    expect(wrapper.vm.semesterLabel(anySemesterWish)).toBe('不限學期')

    await wrapper.vm.loadMore()
    expect(wishServiceMock.list).toHaveBeenNthCalledWith(2, { limit: 60, offset: 1 })
    expect(wrapper.vm.wishes.map((wish) => wish.id)).toEqual([7, 8])
  })

  it('keeps session scores stable while only geometry reflows across viewport modes', async () => {
    const wrapper = await mountPool()
    const initialLayout = wrapper.vm.positions
    const initialScores = wrapper.vm.sessionScores

    wrapper.vm.$forceUpdate()
    await flushPromises()
    expect(wrapper.vm.positions).toBe(initialLayout)
    expect(wrapper.vm.sessionScores).toBe(initialScores)

    await wrapper.get('.wish-word').trigger('click')
    expect(wrapper.vm.selected.id).toBe(7)
    expect(wrapper.vm.positions).toBe(initialLayout)

    await wrapper.vm.toggleHeart()
    expect(wishServiceMock.toggleHeart).toHaveBeenCalledWith(7)
    expect(wrapper.vm.wishes[0].heart_count).toBe(1)
    expect(wrapper.vm.positions).toBe(initialLayout)
    expect(wrapper.vm.sessionScores).toBe(initialScores)

    wrapper.vm.closeWishDetail()
    await flushPromises()
    expect(wrapper.vm.selected).toBeNull()
    expect(wrapper.vm.positions).toBe(initialLayout)

    await resizePool(wrapper, { width: 767, height: 840 })
    expect(wrapper.vm.positions).not.toBe(initialLayout)
    expect(wrapper.vm.sessionScores).toBe(initialScores)
    expect(wrapper.vm.layoutMode).toBe('mobile')
    expect(wrapper.vm.viewportSize).toEqual({ width: 767, height: 840 })
    expect(wrapper.get('.wish-pool-stage').classes()).toContain('is-mobile-layout')
  })

  it('uses the Archive mobile breakpoint and actual viewport height for the anchor', async () => {
    const wrapper = await mountPool({
      selectWish: false,
      viewport: { width: 390, height: 812 },
    })
    const position = wrapper.vm.positions['7']

    expect(wrapper.vm.layoutMode).toBe('mobile')
    expect(position.mode).toBe('mobile')
    expect(position.anchor).toBe(true)
    expect(position.anchorRatio).toBeCloseTo(0.25, 1)
    expect(wrapper.vm.camera.y + 812 / 2).toBeCloseTo(812 * position.anchorRatio)
  })

  it('votes from the inline heart without opening the Dialog or moving the camera or cell', async () => {
    const wrapper = await mountPool({ selectWish: false })
    const initialPosition = { ...wrapper.vm.positions['7'] }
    const inlineHeart = wrapper.get('.wish-inline-heart')

    dispatchPointer(inlineHeart.element, 'pointerdown', {
      pointerId: 3,
      pointerType: 'mouse',
      button: 0,
      clientX: 25,
      clientY: 25,
    })
    await inlineHeart.trigger('click')
    await flushPromises()

    expect(wishServiceMock.toggleHeart).toHaveBeenCalledWith(7)
    expect(wrapper.vm.selected).toBeNull()
    expect(wrapper.vm.camera).toEqual({ x: 0, y: 0 })
    expect(wrapper.vm.positions['7']).toEqual(initialPosition)
    expect(wrapper.vm.wishes[0]).toMatchObject({ heart_count: 1, hearted_by_me: true })
  })

  it('keeps inline and Dialog hearts synchronized through the shared toggle handler', async () => {
    wishServiceMock.toggleHeart
      .mockResolvedValueOnce({ data: { hearted: true, heart_count: 1 } })
      .mockResolvedValueOnce({ data: { hearted: false, heart_count: 0 } })
    const wrapper = await mountPool({ selectWish: false })

    await wrapper.get('.wish-inline-heart').trigger('click')
    await flushPromises()
    await wrapper.get('.wish-word').trigger('click')
    expect(wrapper.vm.selected).toMatchObject({ heart_count: 1, hearted_by_me: true })

    await wrapper.vm.toggleHeart()
    expect(wishServiceMock.toggleHeart).toHaveBeenNthCalledWith(2, 7)
    expect(wrapper.vm.selected).toMatchObject({ heart_count: 0, hearted_by_me: false })
    expect(wrapper.vm.wishes[0]).toMatchObject({ heart_count: 0, hearted_by_me: false })
  })

  it('adds load-more wishes without moving existing axial assignments', async () => {
    const nextWish = { ...sampleWish, id: 8, title: '電磁學考古題', heart_count: 18 }
    wishServiceMock.list
      .mockReset()
      .mockResolvedValueOnce({ data: { items: [{ ...sampleWish }], total: 2 } })
      .mockResolvedValueOnce({ data: { items: [nextWish], total: 2 } })

    const wrapper = await mountPool()
    const originalPosition = { ...wrapper.vm.positions['7'] }
    await wrapper.vm.loadMore()

    expect(wrapper.vm.positions['7']).toEqual(originalPosition)
    expect(wrapper.vm.positions['8']).toBeDefined()
    expect(wrapper.vm.positions['8']).not.toEqual(originalPosition)
  })

  it('opens a Wish on click but suppresses the click produced by an intentional pan', async () => {
    const wrapper = await mountPool()
    const stage = wrapper.get('.wish-pool-stage')
    const wish = wrapper.get('.wish-word')

    await wish.trigger('click')
    expect(wrapper.vm.selected.id).toBe(7)
    wrapper.vm.closeWishDetail()

    dispatchPointer(stage.element, 'pointerdown', {
      pointerId: 1,
      pointerType: 'mouse',
      button: 0,
      clientX: 20,
      clientY: 20,
    })
    dispatchPointer(stage.element, 'pointermove', {
      pointerId: 1,
      pointerType: 'mouse',
      clientX: 60,
      clientY: 45,
    })
    dispatchPointer(stage.element, 'pointerup', {
      pointerId: 1,
      pointerType: 'mouse',
      clientX: 60,
      clientY: 45,
    })
    await wish.trigger('click')

    expect(wrapper.vm.selected).toBeNull()
    expect(wrapper.vm.camera).toEqual({ x: 40, y: 25 })
  })

  it('locks mobile camera X while diagonal dragging updates only Y', async () => {
    const wrapper = await mountPool({
      selectWish: false,
      viewport: { width: 390, height: 812 },
    })
    const stage = wrapper.get('.wish-pool-stage')
    const initialY = wrapper.vm.camera.y

    dispatchPointer(stage.element, 'pointerdown', {
      pointerId: 4,
      pointerType: 'touch',
      clientX: 40,
      clientY: 100,
    })
    dispatchPointer(stage.element, 'pointermove', {
      pointerId: 4,
      pointerType: 'touch',
      clientX: 90,
      clientY: 35,
    })

    expect(wrapper.vm.camera.x).toBe(0)
    expect(wrapper.vm.camera.y).toBe(initialY - 65)
  })

  it('treats a mobile horizontal swipe as movement without translating or opening a Wish', async () => {
    const wrapper = await mountPool({
      selectWish: false,
      viewport: { width: 390, height: 812 },
    })
    const stage = wrapper.get('.wish-pool-stage')
    const wish = wrapper.get('.wish-word')
    const initialCamera = { ...wrapper.vm.camera }

    dispatchPointer(stage.element, 'pointerdown', {
      pointerId: 5,
      pointerType: 'touch',
      clientX: 25,
      clientY: 100,
    })
    dispatchPointer(stage.element, 'pointermove', {
      pointerId: 5,
      pointerType: 'touch',
      clientX: 75,
      clientY: 100,
    })
    dispatchPointer(stage.element, 'pointerup', {
      pointerId: 5,
      pointerType: 'touch',
      clientX: 75,
      clientY: 100,
    })
    await wish.trigger('click')

    expect(wrapper.vm.camera).toEqual(initialCamera)
    expect(wrapper.vm.selected).toBeNull()
  })

  it('disconnects viewport observation when the Wish Pool unmounts', async () => {
    const wrapper = await mountPool({ selectWish: false })

    wrapper.unmount()

    expect(resizeObserverDisconnected).toBe(true)
  })
})
