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

const routerPushMock = vi.hoisted(() => vi.fn())

vi.mock('@/api', () => ({
  statisticsService: statisticsServiceMock,
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: routerPushMock }),
}))

vi.mock('@/composables/useFormulaPhysics', () => ({
  useFormulaPhysics: vi.fn(),
}))

let prefersReducedMotion = false
const matchMediaMock = vi.fn((query) => ({
  matches: query === '(prefers-reduced-motion: reduce)' && prefersReducedMotion,
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

describe('HomeView', () => {
  beforeEach(() => {
    prefersReducedMotion = false
    nextAnimationFrameId = 1
    animationFrameCallbacks = new Map()
    window.matchMedia = matchMediaMock
    window.requestAnimationFrame = requestAnimationFrameMock
    window.cancelAnimationFrame = cancelAnimationFrameMock
    globalThis.ResizeObserver = ResizeObserverMock
    statisticsServiceMock.getSystemStatistics.mockReset()
    routerPushMock.mockReset()
    statisticsServiceMock.getSystemStatistics.mockResolvedValue({
      data: { data: statisticsPayload },
    })
  })

  afterEach(() => {
    vi.clearAllMocks()
    delete window.__pastexam
    window.matchMedia = originalMatchMedia || matchMediaMock
    window.requestAnimationFrame = originalRequestAnimationFrame
    window.cancelAnimationFrame = originalCancelAnimationFrame
    globalThis.ResizeObserver = originalResizeObserver
    HTMLElement.prototype.scrollIntoView = originalScrollIntoView
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

  it('renders the physics landing page and fetched statistics', async () => {
    const wrapper = mount(HomeView)
    await flushPromises()

    expect(wrapper.text()).toContain('清大物理')
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
