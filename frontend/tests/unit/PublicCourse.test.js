import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

import PublicCourse from '@/views/PublicCourse.vue'

const routeMock = vi.hoisted(() => ({
  params: { courseId: '42' },
  path: '/courses/42',
}))

const courseServiceMock = vi.hoisted(() => ({
  listPublicCategories: vi.fn(),
  listPublicCourses: vi.fn(),
  getPublicCourseArchives: vi.fn(),
}))

const setSeoMock = vi.hoisted(() => vi.fn())

vi.mock('vue-router', () => ({ useRoute: () => routeMock }))
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
  return mount(PublicCourse, {
    global: { stubs: { RouterLink: RouterLinkStub } },
  })
}

describe('PublicCourse', () => {
  beforeEach(() => {
    routeMock.params.courseId = '42'
    routeMock.path = '/courses/42'
    courseServiceMock.listPublicCategories.mockReset()
    courseServiceMock.listPublicCourses.mockReset()
    courseServiceMock.getPublicCourseArchives.mockReset()
    setSeoMock.mockReset()
  })

  it('renders safe archive metadata without exposing file actions', async () => {
    courseServiceMock.listPublicCategories.mockResolvedValue({
      data: [{ key: 'fundamental', name: '基礎課程', label: '基礎' }],
    })
    courseServiceMock.listPublicCourses.mockResolvedValue({
      data: {
        fundamental: [{ id: 42, name: '普通物理(一)', order_index: 0 }],
      },
    })
    courseServiceMock.getPublicCourseArchives.mockResolvedValue({
      data: [
        {
          id: 7,
          name: '期末考',
          academic_year: 2026,
          archive_type: 'final',
          professor: '王教授',
          has_answers: true,
        },
      ],
    })

    const wrapper = mountView()
    expect(wrapper.text()).toContain('正在載入課程資料')

    await flushPromises()

    expect(wrapper.text()).toContain('普通物理(一)考古題')
    expect(wrapper.text()).toContain('2026')
    expect(wrapper.text()).toContain('王教授')
    expect(wrapper.text()).toContain('附解答')
    expect(wrapper.find('button').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('下載檔案')
    expect(setSeoMock).toHaveBeenCalledWith(
      expect.objectContaining({
        title: expect.not.stringContaining('PhysArchive'),
        canonicalPath: '/courses/42',
        robots: 'index, follow',
      })
    )
    wrapper.unmount()
  })

  it('renders an active course with no public archives and keeps it out of the index', async () => {
    courseServiceMock.listPublicCategories.mockResolvedValue({
      data: [{ key: 'fundamental', name: '基礎課程', label: '基礎' }],
    })
    courseServiceMock.listPublicCourses.mockResolvedValue({
      data: {
        fundamental: [{ id: 42, name: '普通物理(一)', order_index: 0 }],
      },
    })
    courseServiceMock.getPublicCourseArchives.mockResolvedValue({ data: [] })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('普通物理(一)考古題')
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.get('.empty-state').text()).toContain('目前尚未有可公開瀏覽的考古題')
    expect(wrapper.find('.archive-card').exists()).toBe(false)
    expect(setSeoMock).toHaveBeenCalledWith(
      expect.objectContaining({
        canonicalPath: '/courses/42',
        robots: 'noindex, follow',
      })
    )
    const zeroArchiveSeo = setSeoMock.mock.calls.at(-1)[0]
    expect(zeroArchiveSeo.jsonLd.map((item) => item['@type'])).toEqual([
      'CollectionPage',
      'BreadcrumbList',
    ])
    wrapper.unmount()
  })

  it('rejects an invalid course id without issuing API requests', async () => {
    routeMock.params.courseId = 'invalid'
    routeMock.path = '/courses/invalid'

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.get('[role="alert"]').text()).toContain('課程編號格式不正確')
    expect(courseServiceMock.listPublicCategories).not.toHaveBeenCalled()
    expect(courseServiceMock.listPublicCourses).not.toHaveBeenCalled()
    expect(courseServiceMock.getPublicCourseArchives).not.toHaveBeenCalled()
    expect(setSeoMock).toHaveBeenCalledWith(
      expect.objectContaining({ robots: 'noindex, nofollow' })
    )
    wrapper.unmount()
  })

  it('renders a not-found state when public metadata is unavailable', async () => {
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    courseServiceMock.listPublicCategories.mockResolvedValue({ data: [] })
    courseServiceMock.listPublicCourses.mockResolvedValue({ data: {} })
    courseServiceMock.getPublicCourseArchives.mockRejectedValue(new Error('missing'))

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.get('[role="alert"]').text()).toContain('不存在或目前無法載入')
    expect(setSeoMock).toHaveBeenCalledWith(
      expect.objectContaining({ robots: 'noindex, nofollow' })
    )
    consoleErrorSpy.mockRestore()
    wrapper.unmount()
  })
})
