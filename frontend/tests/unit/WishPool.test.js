import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import wishPoolSource from '@/components/WishPool.vue?raw'

const wishServiceMock = vi.hoisted(() => ({
  list: vi.fn(),
  report: vi.fn(),
  remove: vi.fn(),
  toggleHeart: vi.fn(),
}))
const homepageSloganServiceMock = vi.hoisted(() => ({ submit: vi.fn() }))
const confirmRequireMock = vi.hoisted(() => vi.fn())
const toastAddMock = vi.hoisted(() => vi.fn())
let resizeObserverCallback
let resizeObserverTarget
let resizeObserverDisconnected

vi.mock('@/api', () => ({
  homepageSloganService: homepageSloganServiceMock,
  wishService: wishServiceMock,
}))
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

function sampleWishes(count) {
  return Array.from({ length: count }, (_, index) => ({
    ...sampleWish,
    id: index + 1,
    title: `許願 ${index + 1}`,
    heart_count: index,
  }))
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
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: false }))
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
    homepageSloganServiceMock.submit.mockReset().mockResolvedValue({ data: { id: 12 } })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('uses the audited container boundary and two-column narrow header actions', () => {
    expect(wishPoolSource).toMatch(/container-type:\s*inline-size/)
    expect(wishPoolSource).toMatch(/@container \(max-width:\s*680px\)/)
    expect(wishPoolSource).toMatch(
      /@container \(max-width:\s*680px\)[\s\S]*?\.wish-header\s*\{[^}]*align-items:\s*stretch;[^}]*flex-direction:\s*column;/
    )
    expect(wishPoolSource).toMatch(
      /@container \(max-width:\s*680px\)[\s\S]*?\.wish-header__actions\s*\{[^}]*display:\s*grid;[^}]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\);[^}]*width:\s*100%;/
    )
    expect(wishPoolSource).toMatch(
      /@container \(max-width:\s*680px\)[\s\S]*?\.wish-header :deep\(\.p-button\)\s*\{[^}]*width:\s*100%;[^}]*min-width:\s*0;[^}]*justify-content:\s*center;/
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
    expect(wishPoolSource).toContain("navigationMode.value === 'desktop'")
    expect(wishPoolSource).toContain('@scroll.passive="handleNativeScroll"')
    expect(wishPoolSource).toContain('@wheel.passive="markNavigationInteraction"')
    expect(wishPoolSource).not.toContain('requestAnimationFrame')
    expect(wishPoolSource).toContain(':data-wish-q="positions[wish.id]?.q"')
    expect(wishPoolSource).toContain(':data-wish-r="positions[wish.id]?.r"')
    expect(wishPoolSource).not.toContain('heartSide')
    expect(wishPoolSource).not.toContain('wishMobileDistribution')
    expect(wishPoolSource).toContain("'is-tablet-scroll': navigationMode === 'tablet'")
    expect(wishPoolSource).toContain("'is-mobile-scroll': navigationMode === 'mobile'")
    expect(wishPoolSource).toMatch(
      /\.wish-pool-stage\.is-native-scroll\s*\{[^}]*scrollbar-width:\s*none;[^}]*-ms-overflow-style:\s*none;[^}]*-webkit-overflow-scrolling:\s*touch;/
    )
    expect(wishPoolSource).toMatch(
      /\.wish-pool-stage\.is-native-scroll::-webkit-scrollbar\s*\{[^}]*display:\s*none;/
    )
    expect(wishPoolSource).toMatch(
      /\.wish-pool-stage\.is-tablet-scroll,\s*\.wish-pool-stage\.is-mobile-scroll\s*\{[^}]*overflow:\s*auto;[^}]*touch-action:\s*auto;/
    )
    expect(wishPoolSource).toMatch(
      /\.wish-navigation-hint\s*\{[^}]*position:\s*absolute;[^}]*pointer-events:\s*none;/
    )
    expect(wishPoolSource).toMatch(
      /\.wish-overlay-controls\s*\{[^}]*position:\s*absolute;[^}]*inset:\s*0;[^}]*pointer-events:\s*none;/
    )
    expect(wishPoolSource).toMatch(
      /\.wish-return-button\.p-button\)\s*\{[^}]*right:\s*1rem;[^}]*bottom:\s*calc\(3\.25rem[^;]*;[^}]*pointer-events:\s*auto;/
    )
    expect(wishPoolSource).toContain('icon="pi pi-arrows-alt"')
    expect(wishPoolSource).not.toContain(':label="navigationMode')
    expect(wishPoolSource).toMatch(
      /\.wish-return-button\.p-button\)\s*\{[^}]*width:\s*2\.75rem;[^}]*height:\s*2\.75rem;[^}]*border-radius:\s*50%;/
    )
    expect(wishPoolSource).toMatch(
      /\.wish-return-button\.p-button\)\s*\{[^}]*border:\s*1px solid\s*color-mix\(in srgb, var\(--p-primary-color\) 38%, var\(--border-color\)\) !important;/
    )
    expect(wishPoolSource).toContain('v-show="returnControlVisible"')
    expect(wishPoolSource).toContain('Boolean(wishes.value.length)')
    expect(wishPoolSource).toContain('!showReturnControl.value')
    expect(wishPoolSource).toContain('@click.stop="returnToExplorationOrigin"')
    expect(wishPoolSource).toContain("window.matchMedia?.('(prefers-reduced-motion: reduce)')")
    expect(wishPoolSource).toContain("'--wish-x':")
    expect(wishPoolSource).toContain("'--wish-y':")
    expect(wishPoolSource).not.toContain("'--wish-y-compact':")
    expect(wishPoolSource).not.toMatch(/calc\([^)]*\*\s*var\(--wish-cell-/)
  })

  it('uses heart-scaled typography and clamps naturally wrapped titles to two lines', () => {
    expect(wishPoolSource).toContain('class="wish-word__title"')
    expect(wishPoolSource).toContain('wishFontSizeRem(wish.heart_count)')
    expect(wishPoolSource).toMatch(
      /\.wish-item\s*\{[^}]*max-width:\s*min\(var\(--wish-item-max-width, 15rem\),[^;]*;/
    )
    expect(wishPoolSource).toMatch(
      /\.wish-word__title\s*\{[^}]*display:\s*-webkit-box;[^}]*overflow:\s*hidden;[^}]*overflow-wrap:\s*anywhere;[^}]*-webkit-line-clamp:\s*2;[^}]*white-space:\s*normal;/
    )
    expect(wishPoolSource).toContain("font-family: 'Huninn', 'Noto Sans TC', system-ui, sans-serif")
    expect(wishPoolSource).not.toContain('densityFontBoost')
    expect(wishPoolSource).not.toContain('baseFontSize')
    expect(wishPoolSource).not.toContain('offsetWidth')
    expect(wishPoolSource).not.toContain('getBoundingClientRect')
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

  it('submits a plain homepage slogan from the secondary Wish Pool action', async () => {
    expect(wishPoolSource).toContain("$t('投稿首頁 slogan')")
    expect(wishPoolSource).toContain("$t('例如：書卷沒有，考古這有')")
    expect(wishPoolSource).toContain('outlined')
    const wrapper = await mountPool({ selectWish: false })
    wrapper.vm.openSloganDialog()
    wrapper.vm.sloganContent = '  新的標語  '
    await wrapper.vm.submitSlogan()
    expect(homepageSloganServiceMock.submit).toHaveBeenCalledWith('新的標語')
    expect(toastAddMock).toHaveBeenCalledWith(
      expect.objectContaining({
        summary: '投稿成功',
        detail: '期待有一天可以在首頁看到你的 slogan！',
      })
    )
    expect(wrapper.vm.sloganDialogVisible).toBe(false)
  })

  it('shows the existing creator_name only inside the admin Wish detail metadata', async () => {
    expect(wishPoolSource).toContain('v-if="isAdmin" class="wish-creator"')
    expect(wishPoolSource).toContain("$t('許願者：{name}', { name: selected.creator_name })")
    const wrapper = await mountPool()
    expect(wrapper.get('.wish-creator').text()).toContain('Alice')
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

  async function mountPoolState({ settle = true } = {}) {
    const WishPool = (await import('@/components/WishPool.vue')).default
    const wrapper = mount(WishPool, {
      props: { coursesList: {}, courseCategories: [] },
      global: {
        stubs,
        mocks: {
          $t: (key, params = {}) =>
            key.replace(/\{(\w+)\}/g, (placeholder, name) => params[name] ?? placeholder),
        },
      },
    })
    if (settle) await flushPromises()
    return wrapper
  }

  async function mountPool({ selectWish = true, viewport = { width: 1200, height: 720 } } = {}) {
    const wrapper = await mountPoolState()
    expect(resizeObserverTarget).toBe(wrapper.get('.wish-pool-stage').element)
    await resizePool(wrapper, viewport)
    if (selectWish) {
      wrapper.vm.selected = wrapper.vm.wishes[0]
      await flushPromises()
    }
    return wrapper
  }

  it('keeps the Wish Pool empty message hidden while the initial request is unresolved', async () => {
    wishServiceMock.list.mockReset().mockReturnValue(new Promise(() => {}))

    const wrapper = await mountPoolState({ settle: false })

    expect(wrapper.find('.wish-spinner').exists()).toBe(true)
    expect(wrapper.find('.wish-empty-state').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('池水靜靜地等著，等一個願望落下第一圈漣漪。')
    wrapper.unmount()
  })

  it('shows an accessible Send empty state only after a successful empty response', async () => {
    wishServiceMock.list.mockReset().mockResolvedValue({ data: { items: [], total: 0 } })

    const wrapper = await mountPoolState()
    const emptyState = wrapper.get('.wish-empty-state')
    const icon = emptyState.get('.wish-empty-state__icon')
    const message = emptyState.get('.wish-empty-state__message')
    const messageLead = message.get('.wish-empty-state__message-lead')
    const messageContinuation = message.get('.wish-empty-state__message-continuation')
    const mobileBreak = message.get('.wish-empty-state__mobile-break')

    expect(emptyState.text()).toBe('池水靜靜地等著，等一個願望落下第一圈漣漪。')
    expect(message.text()).toBe('池水靜靜地等著，等一個願望落下第一圈漣漪。')
    expect(messageLead.text()).toBe('池水靜靜地等著，等一個願望')
    expect(messageContinuation.text()).toBe('落下第一圈漣漪。')
    expect(mobileBreak.attributes('aria-hidden')).toBe('true')
    expect(icon.classes()).toEqual(expect.arrayContaining(['pi', 'pi-send', 'text-6xl']))
    expect(icon.attributes('aria-hidden')).toBe('true')
    expect(message.classes()).toEqual(expect.arrayContaining(['text-xl', 'font-medium']))
    expect(wrapper.find('.wish-pool-stage').exists()).toBe(false)
    expect(wrapper.find('.wish-pool-world').exists()).toBe(false)
    expect(wrapper.vm.positions).toEqual({})
    expect(resizeObserverTarget).toBeNull()
  })

  it('keeps the existing load error separate from the Wish Pool empty state', async () => {
    wishServiceMock.list.mockReset().mockRejectedValue(new Error('network unavailable'))

    const wrapper = await mountPoolState()

    expect(wrapper.text()).toContain('許願池載入失敗，請稍後再試。')
    expect(wrapper.find('.wish-empty-state').exists()).toBe(false)
    expect(wrapper.find('.wish-pool-stage').exists()).toBe(false)
  })

  it('does not render the empty state when the successful response contains a Wish', async () => {
    const wrapper = await mountPool({ selectWish: false })

    expect(wrapper.find('.wish-empty-state').exists()).toBe(false)
    expect(wrapper.findAll('.wish-node')).toHaveLength(1)
  })

  it('keeps existing Wishes visible when load more succeeds without adding items', async () => {
    wishServiceMock.list
      .mockReset()
      .mockResolvedValueOnce({ data: { items: [sampleWish], total: 2 } })
      .mockResolvedValueOnce({ data: { items: [], total: 2 } })
    const wrapper = await mountPool({ selectWish: false })

    await wrapper.vm.loadMore()
    await flushPromises()

    expect(wrapper.find('.wish-empty-state').exists()).toBe(false)
    expect(wrapper.findAll('.wish-node')).toHaveLength(1)
    expect(wrapper.vm.wishes).toEqual([sampleWish])
  })

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
    const initialCells = Object.fromEntries(
      Object.entries(initialLayout).map(([id, { q, r }]) => [id, { q, r }])
    )

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
    expect(
      Object.fromEntries(
        Object.entries(wrapper.vm.positions).map(([id, { q, r }]) => [id, { q, r }])
      )
    ).toEqual(initialCells)
    expect(wrapper.vm.sessionScores).toBe(initialScores)
    expect(wrapper.vm.layoutMode).toBe('honeycomb')
    expect(wrapper.vm.viewportSize).toEqual({ width: 767, height: 840 })
    expect(wrapper.get('.wish-pool-stage').classes()).toContain('is-mobile-scroll')
  })

  it('updates only the voted title font at the 30-heart cap without moving the layout', async () => {
    const highHeartWish = { ...sampleWish, heart_count: 29 }
    const untouchedWish = { ...sampleWish, id: 8, title: '不應被改動的許願', heart_count: 12 }
    wishServiceMock.list.mockReset().mockResolvedValue({
      data: { items: [highHeartWish, untouchedWish], total: 2 },
    })
    wishServiceMock.toggleHeart.mockReset().mockResolvedValue({
      data: { hearted: true, heart_count: 30 },
    })
    const wrapper = await mountPool({
      selectWish: false,
      viewport: { width: 820, height: 1180 },
    })
    const stage = wrapper.get('.wish-pool-stage').element
    stage.scrollLeft = 72
    stage.scrollTop = 64
    const initialPositions = wrapper.vm.positions
    const initialScores = wrapper.vm.sessionScores
    const initialCamera = { ...wrapper.vm.camera }
    const initialUntouchedWish = { ...wrapper.vm.wishes[1] }
    const highHeartTitle = wrapper.get('[data-wish-id="7"] .wish-word')

    expect(highHeartTitle.attributes('style')).not.toContain('font-size: 3.45rem')
    await wrapper.get('[data-wish-id="7"] .wish-inline-heart').trigger('click')
    await flushPromises()

    expect(highHeartTitle.attributes('style')).toContain('font-size: 3.45rem')
    expect(wrapper.vm.wishes[0]).toMatchObject({ heart_count: 30, hearted_by_me: true })
    expect(wrapper.vm.wishes[1]).toEqual(initialUntouchedWish)
    expect(wrapper.vm.positions).toBe(initialPositions)
    expect(wrapper.vm.sessionScores).toBe(initialScores)
    expect(wrapper.vm.camera).toEqual(initialCamera)
    expect(stage.scrollLeft).toBe(72)
    expect(stage.scrollTop).toBe(64)
  })

  it('keeps API DOM order while assigning unique Honeycomb cells on Mobile', async () => {
    const mobileWishes = sampleWishes(6)
    wishServiceMock.list.mockReset().mockResolvedValue({
      data: { items: mobileWishes, total: mobileWishes.length },
    })
    const wrapper = await mountPool({
      selectWish: false,
      viewport: { width: 390, height: 812 },
    })

    expect(wrapper.vm.layoutMode).toBe('honeycomb')
    expect(wrapper.vm.navigationMode).toBe('mobile')
    expect(wrapper.vm.camera).toEqual({ x: 0, y: 0 })
    expect(wrapper.findAll('.wish-node').map((node) => node.attributes('data-wish-id'))).toEqual(
      mobileWishes.map(({ id }) => String(id))
    )
    const cells = Object.values(wrapper.vm.positions).map(({ q, r }) => `${q}:${r}`)
    expect(new Set(cells).size).toBe(mobileWishes.length)
    expect(new Set(Object.values(wrapper.vm.positions).map(({ x }) => x)).size).toBeGreaterThan(1)
    expect(wrapper.get('.wish-pool-stage').classes()).not.toContain('is-vertical-distribution')
  })

  it('uses the same Honeycomb model with native 2D scroll for Tablet Portrait', async () => {
    const wrapper = await mountPool({
      selectWish: false,
      viewport: { width: 820, height: 1180 },
    })
    expect(wrapper.vm.layoutMode).toBe('honeycomb')
    expect(wrapper.vm.navigationMode).toBe('tablet')
    expect(wrapper.vm.positions['7']).toMatchObject({
      q: expect.any(Number),
      r: expect.any(Number),
    })
    expect(wrapper.get('.wish-pool-stage').classes()).toContain('is-tablet-scroll')
    expect(wrapper.vm.worldGeometry.width).toBeGreaterThan(820)
    expect(wrapper.vm.worldGeometry.height).toBeGreaterThan(1180)
    expect(wrapper.find('.wish-navigation-hint').exists()).toBe(false)
    expect(wrapper.get('.wish-return-button').isVisible()).toBe(true)
    expect(wrapper.get('.wish-return-button').classes()).toContain('is-at-origin')
    expect(wrapper.get('.wish-overlay-controls').find('.wish-return-button').exists()).toBe(true)
    expect(wrapper.get('.wish-pool-world').find('.wish-return-button').exists()).toBe(false)
  })

  it.each([
    [375, 812, 'honeycomb', 'mobile'],
    [390, 844, 'honeycomb', 'mobile'],
    [402, 874, 'honeycomb', 'mobile'],
    [429, 869, 'honeycomb', 'mobile'],
    [768, 1024, 'honeycomb', 'tablet'],
    [834, 1210, 'honeycomb', 'tablet'],
    [1023, 768, 'honeycomb', 'tablet'],
    [1024, 768, 'honeycomb', 'desktop'],
    [1025, 768, 'honeycomb', 'desktop'],
    [1440, 900, 'honeycomb', 'desktop'],
  ])(
    'selects the intended responsive contract at %d×%d',
    async (width, height, expectedLayout, expectedNavigation) => {
      const wrapper = await mountPool({ selectWish: false, viewport: { width, height } })

      expect(wrapper.vm.layoutMode).toBe(expectedLayout)
      expect(wrapper.vm.navigationMode).toBe(expectedNavigation)
      wrapper.unmount()
    }
  )

  it('keeps Mobile cells and session scores stable through a heart toggle', async () => {
    const mobileWishes = sampleWishes(6)
    wishServiceMock.list.mockReset().mockResolvedValue({
      data: { items: mobileWishes, total: mobileWishes.length },
    })
    const wrapper = await mountPool({
      selectWish: false,
      viewport: { width: 390, height: 844 },
    })
    const positions = wrapper.vm.positions
    const scores = wrapper.vm.sessionScores
    const domOrder = wrapper.findAll('.wish-node').map((node) => node.attributes('data-wish-id'))
    const initialFontSize = wrapper.get('.wish-word').attributes('style')

    await wrapper.get('.wish-inline-heart').trigger('click')
    await flushPromises()

    expect(wrapper.get('.wish-word').attributes('style')).not.toBe(initialFontSize)
    expect(wrapper.vm.positions).toBe(positions)
    expect(wrapper.vm.sessionScores).toBe(scores)
    expect(wrapper.findAll('.wish-node').map((node) => node.attributes('data-wish-id'))).toEqual(
      domOrder
    )
  })

  it('keeps Mobile Honeycomb cells stable through Dialog, theme, and ordinary rerenders', async () => {
    const wrapper = await mountPool({
      selectWish: false,
      viewport: { width: 402, height: 874 },
    })
    const positions = wrapper.vm.positions

    await wrapper.get('.wish-word').trigger('click')
    wrapper.vm.closeWishDetail()
    document.documentElement.classList.add('app-dark')
    wrapper.vm.$forceUpdate()
    await flushPromises()
    document.documentElement.classList.remove('app-dark')

    expect(wrapper.vm.positions).toBe(positions)
  })

  it('shows the native-navigation hint until the user explores the Honeycomb world', async () => {
    const wrapperWithOneWish = await mountPool({
      selectWish: false,
      viewport: { width: 390, height: 812 },
    })
    expect(wrapperWithOneWish.find('.wish-navigation-hint').exists()).toBe(false)
    wrapperWithOneWish.unmount()

    const manyWishes = sampleWishes(12)
    wishServiceMock.list.mockReset().mockResolvedValue({
      data: { items: manyWishes, total: manyWishes.length },
    })
    const wrapper = await mountPool({
      selectWish: false,
      viewport: { width: 390, height: 812 },
    })

    expect(wrapper.get('.wish-navigation-hint').text()).toContain('拖曳以查看更多')

    const stage = wrapper.get('.wish-pool-stage').element
    stage.scrollLeft = wrapper.vm.explorationOrigin.x + 80
    stage.scrollTop = wrapper.vm.explorationOrigin.y + 80
    dispatchPointer(stage, 'pointerdown', { pointerId: 6, pointerType: 'touch' })
    stage.dispatchEvent(new Event('scroll'))
    await flushPromises()

    expect(wrapper.find('.wish-navigation-hint').exists()).toBe(false)
  })

  it('returns Mobile native 2D scroll to its centered origin with motion preference respected', async () => {
    const manyWishes = sampleWishes(12)
    wishServiceMock.list.mockReset().mockResolvedValue({
      data: { items: manyWishes, total: manyWishes.length },
    })
    const wrapper = await mountPool({
      selectWish: false,
      viewport: { width: 390, height: 812 },
    })
    const stage = wrapper.get('.wish-pool-stage').element
    const scrollTo = vi.fn(({ left = stage.scrollLeft, top = stage.scrollTop }) => {
      stage.scrollLeft = left
      stage.scrollTop = top
    })
    stage.scrollTo = scrollTo
    const origin = { ...wrapper.vm.explorationOrigin }
    expect(wrapper.get('.wish-return-button').isVisible()).toBe(true)
    expect(wrapper.get('.wish-return-button').classes()).toContain('is-at-origin')
    stage.scrollLeft = origin.x + 100
    stage.scrollTop = origin.y + 100
    dispatchPointer(stage, 'pointerdown', { pointerId: 8, pointerType: 'touch' })
    stage.dispatchEvent(new Event('scroll'))
    await flushPromises()

    const returnButton = wrapper.get('.wish-return-button')
    expect(returnButton.attributes('aria-label')).toBe('回到中央')
    await returnButton.trigger('click')
    expect(scrollTo).toHaveBeenLastCalledWith({
      left: origin.x,
      top: origin.y,
      behavior: 'smooth',
    })
    expect(returnButton.classes()).toContain('is-at-origin')

    window.matchMedia.mockReturnValue({ matches: true })
    stage.scrollLeft = origin.x + 100
    stage.scrollTop = origin.y + 100
    dispatchPointer(stage, 'pointerdown', { pointerId: 9, pointerType: 'touch' })
    stage.dispatchEvent(new Event('scroll'))
    await flushPromises()
    await wrapper.get('.wish-return-button').trigger('click')
    expect(scrollTo).toHaveBeenLastCalledWith({
      left: origin.x,
      top: origin.y,
      behavior: 'auto',
    })
  })

  it('returns Tablet native 2D scroll to its centered origin without moving Wishes', async () => {
    const manyWishes = sampleWishes(20)
    wishServiceMock.list.mockReset().mockResolvedValue({
      data: { items: manyWishes, total: manyWishes.length },
    })
    const wrapper = await mountPool({
      selectWish: false,
      viewport: { width: 820, height: 1180 },
    })
    const stage = wrapper.get('.wish-pool-stage').element
    const initialPositions = wrapper.vm.positions
    const scrollTo = vi.fn(({ left, top }) => {
      stage.scrollLeft = left
      stage.scrollTop = top
    })
    stage.scrollTo = scrollTo
    const origin = { ...wrapper.vm.explorationOrigin }
    stage.scrollLeft = origin.x + 90
    stage.scrollTop = origin.y + 90
    dispatchPointer(stage, 'pointerdown', { pointerId: 10, pointerType: 'touch' })
    stage.dispatchEvent(new Event('scroll'))
    await flushPromises()

    const returnButton = wrapper.get('.wish-return-button')
    expect(returnButton.attributes('aria-label')).toBe('回到中央')
    await returnButton.trigger('click')

    expect(scrollTo).toHaveBeenLastCalledWith({
      left: origin.x,
      top: origin.y,
      behavior: 'smooth',
    })
    expect(wrapper.vm.positions).toBe(initialPositions)
    expect(returnButton.classes()).toContain('is-at-origin')

    window.matchMedia.mockReturnValue({ matches: true })
    stage.scrollLeft = origin.x + 90
    stage.scrollTop = origin.y + 90
    dispatchPointer(stage, 'pointerdown', { pointerId: 12, pointerType: 'touch' })
    stage.dispatchEvent(new Event('scroll'))
    await flushPromises()
    await wrapper.get('.wish-return-button').trigger('click')
    expect(scrollTo).toHaveBeenLastCalledWith({
      left: origin.x,
      top: origin.y,
      behavior: 'auto',
    })
  })

  it('shows desktop exploration helpers and returns the camera to its initial origin', async () => {
    const manyWishes = sampleWishes(20)
    wishServiceMock.list.mockReset().mockResolvedValue({
      data: { items: manyWishes, total: manyWishes.length },
    })
    const wrapper = await mountPool({ selectWish: false })
    const stage = wrapper.get('.wish-pool-stage')
    const returnButton = wrapper.get('.wish-return-button')

    expect(wrapper.get('.wish-navigation-hint').text()).toContain('拖曳以查看更多')
    expect(returnButton.isVisible()).toBe(true)
    expect(returnButton.classes()).toContain('is-at-origin')
    dispatchPointer(stage.element, 'pointerdown', {
      pointerId: 11,
      pointerType: 'mouse',
      clientX: 20,
      clientY: 20,
    })
    dispatchPointer(stage.element, 'pointermove', {
      pointerId: 11,
      pointerType: 'mouse',
      clientX: 100,
      clientY: 80,
    })
    await flushPromises()

    expect(returnButton.attributes('aria-label')).toBe('回到中央')
    expect(returnButton.classes()).not.toContain('is-at-origin')
    expect(wishPoolSource).not.toContain(':label="navigationMode')
    await returnButton.trigger('click')
    expect(wrapper.vm.camera).toEqual(wrapper.vm.explorationOrigin)
    expect(returnButton.isVisible()).toBe(true)
    expect(returnButton.classes()).toContain('is-at-origin')
  })

  it('preserves tablet native scroll through heart, Dialog, and ordinary rerenders', async () => {
    const wrapper = await mountPool({
      selectWish: false,
      viewport: { width: 820, height: 1180 },
    })
    const stage = wrapper.get('.wish-pool-stage').element
    stage.scrollLeft = 72
    stage.scrollTop = 0

    await wrapper.get('.wish-inline-heart').trigger('click')
    await flushPromises()
    await wrapper.get('.wish-word').trigger('click')
    wrapper.vm.closeWishDetail()
    wrapper.vm.$forceUpdate()
    await flushPromises()

    expect(stage.scrollLeft).toBe(72)
    expect(stage.scrollTop).toBe(0)
  })

  it('restores the same seeded Honeycomb cells after Portrait to Landscape to Portrait', async () => {
    const manyWishes = Array.from({ length: 40 }, (_, index) => ({
      ...sampleWish,
      id: index + 1,
      title: `許願 ${index + 1}`,
      heart_count: index,
    }))
    wishServiceMock.list.mockReset().mockResolvedValue({
      data: { items: manyWishes, total: manyWishes.length },
    })
    const wrapper = await mountPool({
      selectWish: false,
      viewport: { width: 820, height: 1180 },
    })
    const initialScores = wrapper.vm.sessionScores
    const cellCoordinates = (positions) =>
      Object.fromEntries(
        Object.entries(positions).map(([id, { q, r, x, y }]) => [id, { q, r, x, y }])
      )
    const initialCells = cellCoordinates(wrapper.vm.positions)

    await resizePool(wrapper, { width: 980, height: 720 })
    expect(wrapper.vm.layoutMode).toBe('honeycomb')
    expect(wrapper.vm.navigationMode).toBe('tablet')
    await resizePool(wrapper, { width: 834, height: 1210 })

    expect(wrapper.vm.layoutMode).toBe('honeycomb')
    expect(wrapper.vm.navigationMode).toBe('tablet')
    expect(wrapper.vm.sessionScores).toBe(initialScores)
    expect(cellCoordinates(wrapper.vm.positions)).toEqual(initialCells)
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

  it('adds load-more wishes without moving existing Tablet cells or scroll position', async () => {
    const initialWishes = sampleWishes(12)
    const nextWishes = [
      { ...sampleWish, id: 13, title: '電磁學考古題', heart_count: 18 },
      { ...sampleWish, id: 14, title: '熱統考古題', heart_count: 2 },
    ]
    wishServiceMock.list
      .mockReset()
      .mockResolvedValueOnce({ data: { items: initialWishes, total: 14 } })
      .mockResolvedValueOnce({ data: { items: nextWishes, total: 14 } })

    const wrapper = await mountPool({ viewport: { width: 820, height: 1180 } })
    const stage = wrapper.get('.wish-pool-stage').element
    stage.scrollLeft = 0
    stage.scrollTop = 64
    const originalPosition = { ...wrapper.vm.positions['1'] }
    await wrapper.vm.loadMore()
    await flushPromises()

    expect(wrapper.vm.positions['1']).toEqual(originalPosition)
    expect(wrapper.vm.positions['13']).toBeDefined()
    expect(wrapper.vm.positions['13']).not.toEqual(originalPosition)
    expect(stage.scrollLeft).toBe(0)
    expect(stage.scrollTop).toBe(64)

    await resizePool(wrapper, { width: 820, height: 1260 })
    expect(wrapper.vm.positions['1']).toMatchObject({
      q: originalPosition.q,
      r: originalPosition.r,
    })
    expect(stage.scrollLeft).toBe(0)
    expect(stage.scrollTop).toBe(64)
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

  it('leaves Mobile two-axis movement to native scrolling without camera updates', async () => {
    const wrapper = await mountPool({
      selectWish: false,
      viewport: { width: 390, height: 812 },
    })
    const stage = wrapper.get('.wish-pool-stage')
    const initialCamera = { ...wrapper.vm.camera }

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

    expect(wrapper.vm.navigationMode).toBe('mobile')
    expect(wrapper.vm.camera).toEqual(initialCamera)
    expect(wrapper.get('.wish-pool-stage').classes()).toContain('is-mobile-scroll')
  })

  it('does not route Tablet pointer movement through the custom desktop camera', async () => {
    const wrapper = await mountPool({
      selectWish: false,
      viewport: { width: 820, height: 1180 },
    })
    const stage = wrapper.get('.wish-pool-stage')
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
      clientY: 35,
    })

    expect(wrapper.vm.navigationMode).toBe('tablet')
    expect(wrapper.vm.camera).toEqual(initialCamera)
    expect(wrapper.get('.wish-pool-stage').classes()).toContain('is-tablet-scroll')
  })

  it('disconnects viewport observation when the Wish Pool unmounts', async () => {
    const wrapper = await mountPool({ selectWish: false })

    wrapper.unmount()

    expect(resizeObserverDisconnected).toBe(true)
  })
})
