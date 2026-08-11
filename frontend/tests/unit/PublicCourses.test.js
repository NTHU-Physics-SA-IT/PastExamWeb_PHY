import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

import PublicCourses from '@/views/PublicCourses.vue'

const courseServiceMock = vi.hoisted(() => ({
  listPublicCategories: vi.fn(),
  listPublicCourses: vi.fn(),
}))

const setSeoMock = vi.hoisted(() => vi.fn())

vi.mock('@/api', () => ({ courseService: courseServiceMock }))
vi.mock('@/utils/seo', () => ({
  SITE_URL: 'http://localhost:8080',
  setSeo: setSeoMock,
}))

const RouterLinkStub = {
  props: ['to'],
  template: '<a><slot /></a>',
}

function mountView() {
  return mount(PublicCourses, {
    global: { stubs: { RouterLink: RouterLinkStub } },
  })
}

describe('PublicCourses', () => {
  beforeEach(() => {
    courseServiceMock.listPublicCategories.mockReset()
    courseServiceMock.listPublicCourses.mockReset()
    setSeoMock.mockReset()
  })

  it('renders loading and a useful empty state for a fresh database', async () => {
    courseServiceMock.listPublicCategories.mockResolvedValue({
      data: [{ key: 'fundamental', name: '基礎課程', label: '基礎' }],
    })
    courseServiceMock.listPublicCourses.mockResolvedValue({
      data: { fundamental: [] },
    })

    const wrapper = mountView()
    expect(wrapper.text()).toContain('正在載入課程資料')

    await flushPromises()

    expect(wrapper.text()).toContain('目前尚未有可公開瀏覽的課程')
    expect(wrapper.findAll('.course-card')).toHaveLength(0)
    expect(setSeoMock).toHaveBeenCalledWith(expect.objectContaining({ canonicalPath: '/courses' }))
    wrapper.unmount()
  })

  it('renders categorized public courses without download actions', async () => {
    courseServiceMock.listPublicCategories.mockResolvedValue({
      data: [{ key: 'fundamental', name: '基礎課程', label: '基礎' }],
    })
    courseServiceMock.listPublicCourses.mockResolvedValue({
      data: {
        fundamental: [{ id: 42, name: '普通物理(一)', order_index: 0 }],
      },
    })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('普通物理(一)考古題')
    expect(wrapper.text()).toContain('1 門課程')
    expect(wrapper.text()).not.toContain('目前尚未有可公開瀏覽的課程')
    const actionableLabels = wrapper.findAll('a, button').map((item) => item.text())
    expect(actionableLabels.some((label) => label.includes('下載'))).toBe(false)
    wrapper.unmount()
  })

  it('renders a recoverable error state and prevents indexing it', async () => {
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    courseServiceMock.listPublicCategories.mockRejectedValue(new Error('catalog'))
    courseServiceMock.listPublicCourses.mockResolvedValue({ data: {} })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.get('[role="alert"]').text()).toContain('目前無法讀取課程目錄')
    expect(setSeoMock).toHaveBeenCalledWith(expect.objectContaining({ robots: 'noindex, follow' }))
    consoleErrorSpy.mockRestore()
    wrapper.unmount()
  })
})
