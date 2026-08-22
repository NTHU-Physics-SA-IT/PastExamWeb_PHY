import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import publicCoursesSource from '@/views/PublicCourses.vue?raw'

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

  it('uses the catalog header selector for the bold page title', () => {
    expect(publicCoursesSource).toMatch(/\.catalog-header h1\s*\{[^}]*font-weight:\s*700;/s)
  })

  it('uses plain breadcrumbs and stable responsive gutters', () => {
    expect(publicCoursesSource).toMatch(
      /\.breadcrumbs a\s*\{[^}]*padding:\s*0;[^}]*text-decoration:\s*none/s
    )
    expect(publicCoursesSource).not.toMatch(/\.breadcrumbs a\s*\{[^}]*border:/s)
    expect(publicCoursesSource).toMatch(
      /@media \(max-width: 820px\)[\s\S]*?\.public-catalog\s*\{[^}]*width:\s*min\(100% - 56px, 1080px\)/
    )
    expect(publicCoursesSource).toMatch(
      /@media \(max-width: 560px\)[\s\S]*?\.public-catalog\s*\{[^}]*width:\s*min\(100% - 40px, 1080px\)/
    )
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
    expect(setSeoMock).toHaveBeenCalledWith(
      expect.objectContaining({
        title: '清大物理考古題課程目錄',
        canonicalPath: '/courses',
      })
    )
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

    expect(wrapper.find('.course-card h3').text()).toBe('普通物理(一)')
    expect(wrapper.find('.course-card').text()).not.toContain('考古題')
    expect(wrapper.find('.course-card').text()).not.toContain('查看課程資訊')
    expect(wrapper.find('.course-card-link .pi-arrow-right').exists()).toBe(true)
    expect(wrapper.find('.access-note').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('公開頁面不提供檔案下載')
    expect(wrapper.text()).toContain('1 門課程')
    expect(wrapper.text()).toContain('瀏覽清大物理相關課程')
    expect(wrapper.text()).not.toContain('瀏覽目前已有公開考古題中繼資料的課程')
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
