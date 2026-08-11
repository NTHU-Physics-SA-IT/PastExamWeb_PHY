import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import HomeView from '@/views/Home.vue'

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

const matchMediaMock = vi.fn((query) => ({
  matches: false,
  media: query,
  addEventListener: vi.fn(),
  removeEventListener: vi.fn(),
}))

class ResizeObserverMock {
  observe() {}
  disconnect() {}
}

const originalMatchMedia = window.matchMedia
const originalResizeObserver = globalThis.ResizeObserver
const originalScrollIntoView = HTMLElement.prototype.scrollIntoView

describe('HomeView', () => {
  beforeEach(() => {
    window.matchMedia = matchMediaMock
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
    window.matchMedia = originalMatchMedia
    globalThis.ResizeObserver = originalResizeObserver
    HTMLElement.prototype.scrollIntoView = originalScrollIntoView
  })

  it('renders the physics landing page and fetched statistics', async () => {
    const wrapper = mount(HomeView)
    await flushPromises()

    expect(wrapper.text()).toContain('清大物理')
    expect(wrapper.findAll('.theory-card')).toHaveLength(22)

    const statCards = wrapper.findAll('.stat-card')
    expect(statCards).toHaveLength(6)
    expect(statCards[0].text()).toContain('考古題')
    expect(statCards[0].text()).toContain(String(statisticsPayload.totalArchives))
    expect(statCards[3].text()).toContain('使用者')
    expect(statCards[3].text()).toContain(String(statisticsPayload.totalUsers))

    wrapper.unmount()
  })

  it('opens the shared login modal from the primary action', async () => {
    const openLoginModal = vi.fn()
    window.__pastexam = { openLoginModal }
    const wrapper = mount(HomeView)
    await flushPromises()

    await wrapper.get('button[aria-label="登入開始使用"]').trigger('click')
    expect(openLoginModal).toHaveBeenCalledOnce()

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
