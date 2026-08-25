import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import HomeView from '@/views/Home.vue'
import homeSource from '@/views/Home.vue?raw'
import { setLocale } from '@/i18n'

const statisticsPayload = vi.hoisted(() => ({
  totalUsers: 120,
  totalDownloads: 45,
  onlineUsers: 7,
  totalArchives: 15,
  totalCourses: 8,
  activeToday: 3,
}))

const statisticsServiceMock = vi.hoisted(() => ({
  getSystemStatistics: vi.fn(),
}))
const homepageSloganServiceMock = vi.hoisted(() => ({
  getSelected: vi.fn(),
}))

const routerPushMock = vi.hoisted(() => vi.fn())

vi.mock('@/api', () => ({
  homepageSloganService: homepageSloganServiceMock,
  statisticsService: statisticsServiceMock,
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: routerPushMock }),
}))

vi.mock('@/composables/useFormulaPhysics', () => ({
  useFormulaPhysics: vi.fn(),
}))

let prefersReducedMotion = false
let desktopHeroLayout = false
const matchMediaMock = vi.fn((query) => ({
  matches:
    (query === '(prefers-reduced-motion: reduce)' && prefersReducedMotion) ||
    (query === '(min-width: 1181px)' && desktopHeroLayout),
  media: query,
  addEventListener: vi.fn(),
  removeEventListener: vi.fn(),
}))

let nextAnimationFrameId = 1
let animationFrameCallbacks
const requestAnimationFrameMock = vi.fn((callback) => {
  const frameId = nextAnimationFrameId
  nextAnimationFrameId += 1
  animationFrameCallbacks.set(frameId, callback)
  return frameId
})
const cancelAnimationFrameMock = vi.fn((frameId) => {
  animationFrameCallbacks.delete(frameId)
})

function runAnimationFrame(timestamp) {
  const callbacks = [...animationFrameCallbacks.values()]
  animationFrameCallbacks.clear()
  callbacks.forEach((callback) => callback(timestamp))
}

class ResizeObserverMock {
  observe() {}
  disconnect() {}
}

const originalMatchMedia = window.matchMedia
const originalRequestAnimationFrame = window.requestAnimationFrame
const originalCancelAnimationFrame = window.cancelAnimationFrame
const originalResizeObserver = globalThis.ResizeObserver
const originalScrollIntoView = HTMLElement.prototype.scrollIntoView
const originalGetBoundingClientRect = HTMLElement.prototype.getBoundingClientRect
const originalGetScreenCTM = SVGElement.prototype.getScreenCTM

describe('HomeView', () => {
  beforeEach(() => {
    prefersReducedMotion = false
    desktopHeroLayout = false
    nextAnimationFrameId = 1
    animationFrameCallbacks = new Map()
    window.matchMedia = matchMediaMock
    window.requestAnimationFrame = requestAnimationFrameMock
    window.cancelAnimationFrame = cancelAnimationFrameMock
    globalThis.ResizeObserver = ResizeObserverMock
    SVGElement.prototype.getScreenCTM = vi.fn(() => null)
    statisticsServiceMock.getSystemStatistics.mockReset()
    homepageSloganServiceMock.getSelected.mockReset().mockResolvedValue({ data: null })
    routerPushMock.mockReset()
    statisticsServiceMock.getSystemStatistics.mockResolvedValue({
      data: { data: statisticsPayload },
    })
  })

  it('uses the selected slogan and keeps the safe fallback when loading fails', async () => {
    homepageSloganServiceMock.getSelected.mockResolvedValueOnce({
      data: { id: 9, content: '新的首頁標語' },
    })
    const selectedWrapper = mount(HomeView)
    await flushPromises()
    expect(selectedWrapper.get('.subtitle').text()).toBe('新的首頁標語')
    selectedWrapper.unmount()

    homepageSloganServiceMock.getSelected.mockRejectedValueOnce(new Error('unavailable'))
    const fallbackWrapper = mount(HomeView)
    await flushPromises()
    expect(fallbackWrapper.get('.subtitle').text()).toBe('書卷沒有，考古這有')
    fallbackWrapper.unmount()
  })

  afterEach(() => {
    vi.clearAllMocks()
    delete window.__pastexam
    window.matchMedia = originalMatchMedia || matchMediaMock
    window.requestAnimationFrame = originalRequestAnimationFrame
    window.cancelAnimationFrame = originalCancelAnimationFrame
    globalThis.ResizeObserver = originalResizeObserver
    HTMLElement.prototype.scrollIntoView = originalScrollIntoView
    HTMLElement.prototype.getBoundingClientRect = originalGetBoundingClientRect
    if (originalGetScreenCTM) {
      SVGElement.prototype.getScreenCTM = originalGetScreenCTM
    } else {
      delete SVGElement.prototype.getScreenCTM
    }
    setLocale('zh-TW')
  })

  it('restores the hero title lockup to 100% scale at tablet and mobile widths', () => {
    expect(homeSource).toMatch(
      /@media \(max-width: 768px\)[\s\S]*?\.hero-title-lockup\s*\{[^}]*transform:\s*scale\(1\.1111\)/
    )
    expect(homeSource).toMatch(
      /@media \(max-width: 768px\)[\s\S]*?h1\s*\{[^}]*font-size:\s*clamp\(1\.7rem, 7\.8vw, 2\.15rem\)/
    )
    expect(homeSource).toMatch(
      /@media \(max-width: 768px\)[\s\S]*?\.title-campus\s*\{[^}]*font-size:\s*0\.666rem/
    )
  })

  it('uses the existing responsive tiers for the centered hero action composition', () => {
    expect(homeSource).toContain('class="hero-action-divider"')
    expect(homeSource).toMatch(/\.hero-action-divider\s*\{[^}]*display:\s*none;/)
    expect(homeSource).toMatch(
      /@media \(max-width: 1180px\)[\s\S]*?\.hero-actions\s*\{[^}]*flex-direction:\s*column;[^}]*align-items:\s*center;/
    )
    expect(homeSource).toMatch(
      /@media \(max-width: 1180px\)[\s\S]*?\.hero-actions\s+:deep\(\.p-button\)\s*\{[^}]*width:\s*100%;[^}]*min-height:\s*3\.15rem;/
    )
    expect(homeSource).toMatch(
      /@media \(max-width: 1180px\)[\s\S]*?\.hero-action-divider\s*\{[^}]*display:\s*block;[^}]*width:\s*100%;/
    )
    expect(homeSource).toMatch(
      /@media \(max-width: 560px\)[\s\S]*?\.title-line\s*\{[^}]*display:\s*block;/
    )
    expect(homeSource).not.toMatch(
      /@media \(max-width: 560px\)[\s\S]*?\.subtitle\s*\{[^}]*display:\s*none;/
    )
    expect(homeSource).toMatch(
      /@media \(max-width: 1180px\)[\s\S]*?\.hero-actions\s+:deep\(\.p-button:nth-child\(2\)\)[\s\S]*?border-width:\s*1px;[^}]*border-style:\s*solid;[^}]*background:\s*transparent;/
    )
    expect(homeSource).toMatch(
      /@media \(max-width: 1180px\)[\s\S]*?\.hero-actions\s+:deep\(\.p-button\.p-button-secondary\.p-button-outlined:last-child\)\s*\{[^}]*border-color:\s*transparent;/
    )
  })

  it('uses one catalog action with a deferred desktop placement target', () => {
    expect(homeSource).toContain("const catalogActionLabel = computed(() => t('瀏覽公開課程目錄'))")
    expect(homeSource).toMatch(
      /<Teleport\s+defer\s+to="#desktop-catalog-action"\s+:disabled="!isDesktopHeroLayout">/
    )
    expect(homeSource).toContain('id="desktop-catalog-action"')
    expect(homeSource).toContain("window.matchMedia('(min-width: 1181px)')")
    expect(homeSource).toMatch(
      /@media \(min-width: 1181px\)[\s\S]*?\.hero-layout\s*\{[^}]*display:\s*grid;[^}]*align-items:\s*center;/
    )
    expect(homeSource).toMatch(
      /@media \(min-width: 1181px\)[\s\S]*?\.dashboard-strip\s*\{[^}]*position:\s*relative;[^}]*top:\s*auto;[^}]*transform:\s*none;/
    )
    expect(homeSource).toMatch(
      /@media \(min-width: 1181px\)[\s\S]*?\.desktop-catalog-target\s*\{[^}]*justify-self:\s*start;/
    )
    expect(homeSource).toMatch(
      /@media \(min-width: 1181px\)[\s\S]*?\.hero-actions\s+:deep\(\.p-button:nth-child\(2\)\)[\s\S]*?border-width:\s*1px;[^}]*background:\s*transparent;/
    )
    expect(homeSource).toMatch(
      /@media \(min-width: 1181px\)[\s\S]*?\.desktop-catalog-target::before\s*\{[^}]*width:\s*100%;[^}]*height:\s*1px;/
    )
  })

  it('derives the desktop mass-core entry offset from the boundary between 理 and 考', async () => {
    desktopHeroLayout = true
    HTMLElement.prototype.getBoundingClientRect = vi.fn(function () {
      if (this.classList.contains('title-line-leading')) {
        return {
          bottom: 300,
          height: 100,
          left: 100,
          right: 260,
          top: 200,
          width: 160,
          x: 100,
          y: 200,
          toJSON: () => ({}),
        }
      }
      if (this.classList.contains('title-line-trailing')) {
        return {
          bottom: 300,
          height: 100,
          left: 300,
          right: 500,
          top: 200,
          width: 200,
          x: 300,
          y: 200,
          toJSON: () => ({}),
        }
      }
      return originalGetBoundingClientRect.call(this)
    })
    SVGElement.prototype.getScreenCTM = vi.fn(function () {
      if (!this.classList.contains('mass-core-entry')) return null
      return { a: 2, b: 0, c: 0, d: 2, e: 10, f: 20 }
    })

    const wrapper = mount(HomeView, {
      global: { stubs: { Teleport: true } },
    })
    await flushPromises()

    const entry = wrapper.get('.mass-core-entry')
    const circle = wrapper.get('.mass-core')
    expect(circle.attributes()).toMatchObject({ cx: '760', cy: '380', r: '92' })
    expect(entry.classes()).toContain('mass-core-entry-ready')
    expect(entry.classes()).toContain('mass-core-entry-animate')
    expect(entry.element.style.getPropertyValue('--mass-core-entry-x')).toBe('-625px')
    expect(entry.element.style.getPropertyValue('--mass-core-entry-y')).toBe('-265px')

    entry.element.dispatchEvent(new Event('animationend'))
    expect(entry.classes()).not.toContain('mass-core-entry-animate')
    expect(entry.element.style.getPropertyValue('--mass-core-entry-x')).toBe('')
    expect(entry.element.style.getPropertyValue('--mass-core-entry-y')).toBe('')

    wrapper.unmount()
  })

  it('keeps mass-core entry neutral outside desktop or when reduced motion is requested', async () => {
    const tabletWrapper = mount(HomeView)
    await flushPromises()
    expect(tabletWrapper.get('.mass-core-entry').classes()).toContain('mass-core-entry-ready')
    expect(tabletWrapper.get('.mass-core-entry').classes()).not.toContain('mass-core-entry-animate')
    tabletWrapper.unmount()

    desktopHeroLayout = true
    prefersReducedMotion = true
    const reducedMotionWrapper = mount(HomeView, {
      global: { stubs: { Teleport: true } },
    })
    await flushPromises()
    expect(reducedMotionWrapper.get('.mass-core-entry').classes()).toContain(
      'mass-core-entry-ready'
    )
    expect(reducedMotionWrapper.get('.mass-core-entry').classes()).not.toContain(
      'mass-core-entry-animate'
    )
    reducedMotionWrapper.unmount()
  })

  it('scopes each CTA sweep to its intended visual content and disables motion when requested', () => {
    expect(homeSource).toMatch(
      /\.hero-actions\s+:deep\(\.p-button\)::before\s*\{[\s\S]*?z-index:\s*2;[\s\S]*?pointer-events:\s*none;[\s\S]*?transform:\s*translateX\(0\)\s+skewX\(-18deg\);[\s\S]*?transition:\s*none;/
    )
    expect(homeSource).toMatch(
      /\.hero-actions\s+:deep\(\.p-button:not\(:disabled\):hover\)::before\s*\{[\s\S]*?transform:\s*translateX\(510%\)\s+skewX\(-18deg\);[\s\S]*?transition:\s*transform\s+1s/
    )
    expect(homeSource).toMatch(/:deep\(\.catalog-action\)::before\s*\{[^}]*display:\s*none;/)
    expect(homeSource).toMatch(
      /:deep\(\.catalog-action\.p-button\.p-button-secondary\.p-button-outlined:not\(:disabled\):hover\)\s*\{[^}]*border-color:\s*transparent;[^}]*background:\s*transparent;[^}]*box-shadow:\s*none;/
    )
    expect(homeSource).toContain("'data-catalog-label': catalogActionLabel")
    expect(homeSource).toMatch(
      /:deep\(\.catalog-action \.p-button-label\)::before\s*\{[\s\S]*?width:\s*0;[\s\S]*?overflow:\s*hidden;[\s\S]*?content:\s*attr\(data-catalog-label\);[\s\S]*?transition:\s*width\s+300ms\s+ease-out;/
    )
    expect(homeSource).toMatch(
      /:deep\(\.catalog-action \.p-button-label\)::after\s*\{[\s\S]*?left:\s*0;[\s\S]*?width:\s*0;[\s\S]*?transition:\s*width\s+300ms\s+ease-out;/
    )
    expect(homeSource).toMatch(
      /:deep\(\.catalog-action:not\(:disabled\):hover \.p-button-label\)::before,[\s\S]*?:deep\(\.catalog-action:not\(:disabled\):hover \.p-button-label\)::after[\s\S]*?\{[^}]*width:\s*100%;/
    )
    expect(homeSource).not.toMatch(
      /:deep\(\.catalog-action:hover \.p-button-(?:icon|label)\)\s*\{[^}]*transform:/
    )
    expect(homeSource).toMatch(
      /@media \(prefers-reduced-motion: reduce\)\s*\{[\s\S]*?\.hero-actions\s+:deep\(\.p-button\)::before\s*\{[^}]*display:\s*none;/
    )
    expect(homeSource).toMatch(
      /@media \(prefers-reduced-motion: reduce\)\s*\{[\s\S]*?:deep\(\.catalog-action \.p-button-label\)::before,[\s\S]*?:deep\(\.catalog-action \.p-button-label\)::after\s*\{[^}]*transition:\s*none;/
    )
  })

  it('renders the physics landing page and fetched statistics', async () => {
    const wrapper = mount(HomeView)
    await flushPromises()

    expect(wrapper.text()).toContain('清大物理')
    expect(wrapper.find('.eyebrow').text()).toBe('PHYS ARCHIVE')
    const heroActions = wrapper.findAll('.hero-actions button')
    expect(heroActions.map((button) => button.text())).toEqual([
      '清華校務系統登入',
      '本地帳號登入',
      '瀏覽公開課程目錄',
    ])
    expect(heroActions[0].classes()).toEqual(heroActions[1].classes())
    expect(heroActions[0].classes()).not.toContain('p-button-secondary')
    expect(heroActions[0].classes()).not.toContain('p-button-outlined')
    expect(heroActions[2].classes()).toContain('p-button-secondary')
    expect(heroActions[2].classes()).toContain('p-button-outlined')
    expect(wrapper.text()).not.toContain('登入開始使用')
    expect(wrapper.findAll('.theory-card')).toHaveLength(22)

    const statCards = wrapper.findAll('.stat-card')
    expect(statCards).toHaveLength(6)
    expect(statCards[0].text()).toContain('考古題')

    expect(wrapper.vm.animatedValues.totalArchives).toBe('0')
    expect(wrapper.vm.animatedValues.totalUsers).toBe('0')
    expect(requestAnimationFrameMock).toHaveBeenCalledTimes(1)

    runAnimationFrame(100)
    runAnimationFrame(1900)
    await wrapper.vm.$nextTick()

    expect(statCards[0].text()).toContain(String(statisticsPayload.totalArchives))
    expect(statCards[3].text()).toContain('使用者')
    expect(statCards[3].text()).toContain(String(statisticsPayload.totalUsers))

    wrapper.unmount()
  })

  it('uses one fixed-duration timeline for zero and large targets', async () => {
    statisticsServiceMock.getSystemStatistics.mockResolvedValueOnce({
      data: {
        data: {
          totalUsers: 100_000,
          totalDownloads: 0,
          onlineUsers: 4,
          totalArchives: 72,
          totalCourses: 8,
          activeToday: 1,
        },
      },
    })

    const wrapper = mount(HomeView)
    await flushPromises()

    expect(wrapper.vm.animatedValues.totalUsers).toBe('0')
    expect(wrapper.vm.animatedValues.totalDownloads).toBe('0')

    runAnimationFrame(200)
    runAnimationFrame(1100)
    await wrapper.vm.$nextTick()
    expect(Number(wrapper.vm.animatedValues.totalUsers.replaceAll(',', ''))).toBeGreaterThan(0)
    expect(Number(wrapper.vm.animatedValues.totalUsers.replaceAll(',', ''))).toBeLessThan(100_000)

    runAnimationFrame(2000)
    await wrapper.vm.$nextTick()
    expect(wrapper.vm.animatedValues.totalUsers).toBe('100,000')
    expect(wrapper.vm.animatedValues.totalDownloads).toBe('0')
    expect(animationFrameCallbacks.size).toBe(0)

    wrapper.unmount()
  })

  it('updates all metrics on one preallocated reactive timeline', async () => {
    const wrapper = mount(HomeView)
    await flushPromises()

    const animatedState = wrapper.vm.animatedValues
    const initialValues = { ...animatedState }
    runAnimationFrame(100)
    const firstFrameValues = { ...wrapper.vm.animatedValues }
    runAnimationFrame(110)
    await wrapper.vm.$nextTick()

    expect(firstFrameValues).toEqual(initialValues)
    expect(wrapper.vm.animatedValues).toBe(animatedState)
    expect(Object.keys(statisticsPayload).every((key) => key in wrapper.vm.animatedValues)).toBe(
      true
    )
    expect(requestAnimationFrameMock).toHaveBeenCalledTimes(3)

    runAnimationFrame(1900)
    await wrapper.vm.$nextTick()
    expect(wrapper.vm.animatedValues.totalUsers).toBe('120')
    expect(animationFrameCallbacks.size).toBe(0)

    wrapper.unmount()
  })

  it('keeps counter frame updates out of the Home component render effect', async () => {
    let homeUpdateCount = 0
    const wrapper = mount(HomeView, {
      global: {
        mixins: [
          {
            updated() {
              if (this.$options.name === 'HomeView') homeUpdateCount += 1
            },
          },
        ],
      },
    })
    await flushPromises()
    homeUpdateCount = 0

    runAnimationFrame(100)
    runAnimationFrame(400)
    await wrapper.vm.$nextTick()

    expect(homeUpdateCount).toBe(0)
    expect(wrapper.vm.animatedValues.totalArchives).not.toBe('0')

    runAnimationFrame(1900)
    await wrapper.vm.$nextTick()
    expect(homeUpdateCount).toBe(1)

    wrapper.unmount()
  })

  it('enables metrics sheen only after completion and a fresh pointer entry', async () => {
    const wrapper = mount(HomeView)
    await flushPromises()

    const dashboard = wrapper.get('.dashboard-strip')
    const firstCard = wrapper.get('.stat-card')
    expect(dashboard.attributes('data-metrics-animation-complete')).toBe('false')
    expect(dashboard.classes()).not.toContain('metrics-hover-ready')

    await firstCard.trigger('pointerenter')
    expect(dashboard.classes()).not.toContain('metrics-hover-ready')

    runAnimationFrame(100)
    runAnimationFrame(1900)
    await wrapper.vm.$nextTick()
    expect(dashboard.attributes('data-metrics-animation-complete')).toBe('true')
    expect(dashboard.classes()).not.toContain('metrics-hover-ready')

    await firstCard.trigger('pointerleave')
    await firstCard.trigger('pointerenter')
    expect(dashboard.classes()).toContain('metrics-hover-ready')

    wrapper.unmount()
  })

  it('completes metrics hover readiness immediately for reduced motion', async () => {
    prefersReducedMotion = true
    const wrapper = mount(HomeView)
    await flushPromises()

    const dashboard = wrapper.get('.dashboard-strip')
    expect(dashboard.attributes('data-metrics-animation-complete')).toBe('true')
    await wrapper.get('.stat-card').trigger('pointerenter')
    expect(dashboard.classes()).toContain('metrics-hover-ready')

    wrapper.unmount()
  })

  it('completes metrics hover readiness without RAF when all targets are zero', async () => {
    statisticsServiceMock.getSystemStatistics.mockResolvedValueOnce({
      data: {
        data: Object.fromEntries(Object.keys(statisticsPayload).map((key) => [key, 0])),
      },
    })
    const wrapper = mount(HomeView)
    await flushPromises()

    const dashboard = wrapper.get('.dashboard-strip')
    expect(requestAnimationFrameMock).not.toHaveBeenCalled()
    expect(dashboard.attributes('data-metrics-animation-complete')).toBe('true')
    await wrapper.get('.stat-card').trigger('pointerenter')
    expect(dashboard.classes()).toContain('metrics-hover-ready')

    wrapper.unmount()
  })

  it('uses the login sheen motion only for ready cards on fine hover pointers', () => {
    expect(homeSource).toMatch(
      /@media \(hover: hover\) and \(pointer: fine\)[\s\S]*?\.metrics-hover-ready \.stat-card:hover::before\s*\{[\s\S]*?translateX\(510%\) skewX\(-18deg\);[\s\S]*?transition:\s*transform 1s cubic-bezier\(0\.22, 1, 0\.36, 1\);/
    )
    expect(homeSource).toMatch(
      /\.stat-card::before\s*\{[\s\S]*?rgba\(255, 255, 255, 0\.42\) 50%,[\s\S]*?pointer-events:\s*none;/
    )
    expect(homeSource).toMatch(
      /@media \(prefers-reduced-motion: reduce\)[\s\S]*?\.stat-card::before\s*\{[^}]*display:\s*none;/
    )
  })

  it('keeps the animated statistics cards compositor-friendly', () => {
    const statCardRule = homeSource.match(/\.stat-card\s*\{([^}]*)\}/)?.[1] ?? ''
    const updateFunction =
      homeSource.match(
        /function updateAnimatedValues[\s\S]*?\n}\n\nfunction prefersReducedMotion/
      )?.[0] ?? ''

    expect(homeSource).not.toContain('COUNTER_RENDER_INTERVAL_MS')
    expect(homeSource).toContain('const animatedValues = shallowRef({')
    expect(homeSource).toContain('const numberFormatter = computed(')
    expect(updateFunction).not.toContain('const nextValues = {}')
    expect(updateFunction.match(/triggerRef\(animatedValues\)/g)).toHaveLength(1)
    expect(statCardRule).toContain('contain: layout style')
    expect(statCardRule).toContain('transform: translate3d(0, 12px, 0)')
    expect(statCardRule).not.toContain('backdrop-filter')
  })

  it('shows final values immediately when reduced motion is requested', async () => {
    prefersReducedMotion = true

    const wrapper = mount(HomeView)
    await flushPromises()

    expect(wrapper.vm.animatedValues.totalArchives).toBe('15')
    expect(wrapper.vm.animatedValues.totalUsers).toBe('120')
    expect(requestAnimationFrameMock).not.toHaveBeenCalled()

    wrapper.unmount()
  })

  it('replays only for a new Home component lifecycle', async () => {
    const firstWrapper = mount(HomeView)
    await flushPromises()
    expect(requestAnimationFrameMock).toHaveBeenCalledTimes(1)

    firstWrapper.vm.$forceUpdate()
    await firstWrapper.vm.$nextTick()
    expect(requestAnimationFrameMock).toHaveBeenCalledTimes(1)

    firstWrapper.unmount()
    expect(cancelAnimationFrameMock).toHaveBeenCalledTimes(1)

    const secondWrapper = mount(HomeView)
    await flushPromises()
    expect(requestAnimationFrameMock).toHaveBeenCalledTimes(2)

    secondWrapper.unmount()
  })

  it('preserves the loading state until the statistics response arrives', async () => {
    let resolveStatistics
    statisticsServiceMock.getSystemStatistics.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveStatistics = resolve
      })
    )

    const wrapper = mount(HomeView)
    await wrapper.vm.$nextTick()

    expect(wrapper.vm.statsLoaded).toBe(false)
    expect(wrapper.vm.animatedValues.totalArchives).toBe(0)
    expect(requestAnimationFrameMock).not.toHaveBeenCalled()

    resolveStatistics({ data: { data: statisticsPayload } })
    await flushPromises()

    expect(wrapper.vm.statsLoaded).toBe(true)
    expect(wrapper.vm.animatedValues.totalArchives).toBe('0')
    expect(requestAnimationFrameMock).toHaveBeenCalledTimes(1)

    wrapper.unmount()
  })

  it('renders compact English hero actions without changing their structure', async () => {
    setLocale('en')
    const wrapper = mount(HomeView)
    await flushPromises()

    const heroActions = wrapper.findAll('.hero-actions button')
    expect(heroActions.map((button) => button.text())).toEqual([
      'Sign in with NTHU',
      'Local Login',
      'Browse Course Catalog',
    ])
    expect(heroActions).toHaveLength(3)
    expect(heroActions[0].classes()).toEqual(heroActions[1].classes())
    expect(heroActions[2].classes()).toContain('p-button-secondary')

    wrapper.unmount()
  })

  it('opens the shared local login modal from the local account action', async () => {
    const openLoginModal = vi.fn()
    window.__pastexam = { openLoginModal }
    const wrapper = mount(HomeView)
    await flushPromises()

    await wrapper.get('button[aria-label="本地帳號登入"]').trigger('click')
    expect(openLoginModal).toHaveBeenCalledOnce()

    wrapper.unmount()
  })

  it('starts NTHU login once through the shared Navbar action', async () => {
    const openLoginModal = vi.fn()
    const startNthuLogin = vi.fn()
    window.__pastexam = { openLoginModal, startNthuLogin }
    const wrapper = mount(HomeView)
    await flushPromises()

    await wrapper.get('button[aria-label="清華校務系統登入"]').trigger('click')

    expect(startNthuLogin).toHaveBeenCalledOnce()
    expect(openLoginModal).not.toHaveBeenCalled()

    wrapper.unmount()
  })

  it('routes the secondary hero action to the public course catalog', async () => {
    const scrollIntoView = vi.fn()
    HTMLElement.prototype.scrollIntoView = scrollIntoView
    const wrapper = mount(HomeView)
    await flushPromises()

    await wrapper.get('button[aria-label="瀏覽公開課程目錄"]').trigger('click')

    expect(routerPushMock).toHaveBeenCalledWith({ name: 'PublicCourses' })
    expect(scrollIntoView).not.toHaveBeenCalled()
    expect(wrapper.text()).not.toContain('清大物理系歷屆考古題與解答')
    expect(wrapper.text()).not.toContain('NTHU PHYSICS PAST EXAMS')

    wrapper.unmount()
  })

  it('uses readable placeholders when statistics fetching fails', async () => {
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    statisticsServiceMock.getSystemStatistics.mockRejectedValueOnce(new Error('stats'))

    const wrapper = mount(HomeView)
    await flushPromises()

    expect(wrapper.vm.animatedValues.totalUsers).toBe('--')
    expect(wrapper.vm.animatedValues.totalDownloads).toBe('--')
    expect(wrapper.vm.statsLoaded).toBe(true)
    expect(consoleErrorSpy).toHaveBeenLastCalledWith(
      'Error fetching statistics:',
      expect.any(Error)
    )

    consoleErrorSpy.mockRestore()
    wrapper.unmount()
  })
})
