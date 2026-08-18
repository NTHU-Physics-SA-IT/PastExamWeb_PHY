import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const listMock = vi.hoisted(() => vi.fn())
const createMock = vi.hoisted(() => vi.fn())
const updateMock = vi.hoisted(() => vi.fn())
const deleteMock = vi.hoisted(() => vi.fn())
const getCurrentUserMock = vi.hoisted(() => vi.fn())

vi.mock('@/api', () => ({
  aboutUsService: { list: listMock, create: createMock, update: updateMock, remove: deleteMock },
}))
vi.mock('@/utils/auth.js', () => ({ getCurrentUser: getCurrentUserMock }))

const stubs = {
  Button: { template: '<button><slot /></button>' },
  Card: { template: '<article><slot name="title" /><slot name="content" /></article>' },
  Dialog: { template: '<div><slot /></div>' },
  InputText: { template: '<input />' },
  Message: { template: '<div><slot /></div>' },
  ProgressSpinner: { template: '<div />' },
  Textarea: { template: '<textarea />' },
}

describe('About Us view', () => {
  beforeEach(() => {
    getCurrentUserMock.mockReturnValue({ id: 1, is_admin: true })
    listMock.mockResolvedValue({
      data: [
        {
          id: 1,
          title: 'Team',
          body: '# Hello\n\n## Section\n\nA **safe** paragraph.\n\n> Quoted\n\n- Item\n\n---\n\n[Site](https://example.com)',
        },
      ],
    })
    createMock.mockResolvedValue({ data: {} })
    updateMock.mockResolvedValue({ data: {} })
    deleteMock.mockResolvedValue({ data: {} })
  })

  it('renders stored Markdown and allows an administrator to create another entry', async () => {
    const AboutUs = (await import('@/views/AboutUs.vue')).default
    const wrapper = mount(AboutUs, {
      global: { stubs, mocks: { $t: (key) => key } },
    })
    await flushPromises()

    expect(wrapper.html()).toContain('<h1>Hello</h1>')
    expect(wrapper.find('.markdown-content h2').text()).toBe('Section')
    expect(wrapper.find('.markdown-content strong').text()).toBe('safe')
    expect(wrapper.find('.markdown-content blockquote').text()).toBe('Quoted')
    expect(wrapper.find('.markdown-content ul li').text()).toBe('Item')
    expect(wrapper.find('.markdown-content hr').exists()).toBe(true)
    expect(wrapper.find('.markdown-content a').attributes()).toMatchObject({
      href: 'https://example.com',
      target: '_blank',
      rel: 'noopener noreferrer',
    })

    wrapper.vm.openCreate()
    wrapper.vm.form.title = 'Second'
    wrapper.vm.form.body = '- item'
    wrapper.vm.form.title_en = 'Second entry'
    wrapper.vm.form.body_en = '- item'
    await wrapper.vm.saveEntry()
    expect(createMock).toHaveBeenCalledWith({
      title: 'Second',
      body: '- item',
      title_en: 'Second entry',
      body_en: '- item',
    })
    expect(wrapper.text()).toContain('英文標題')
    expect(wrapper.text()).toContain('英文 Markdown 內容')
    expect(wrapper.text()).not.toContain('英文標題（選填）')
    expect(wrapper.text()).not.toContain('英文 Markdown 內容（選填）')
  })

  it('uses English content when available, falls back to Chinese, and permanently deletes', async () => {
    const { i18n, setLocale } = await import('@/i18n')
    setLocale('en')
    listMock.mockResolvedValueOnce({
      data: [
        {
          id: 1,
          title: '中文標題',
          body: '# 中文內容',
          title_en: 'English title',
          body_en: '# English body',
        },
        { id: 2, title: '舊資料標題', body: '# 舊資料內容', title_en: null, body_en: null },
      ],
    })
    const AboutUs = (await import('@/views/AboutUs.vue')).default
    const wrapper = mount(AboutUs, {
      global: { stubs, plugins: [i18n] },
    })
    await flushPromises()

    const titles = wrapper.findAll('.about-us-entry-title h2').map((node) => node.text())
    expect(titles).toEqual(['English title', '舊資料標題'])
    expect(wrapper.html()).toContain('<h1>English body</h1>')
    expect(wrapper.html()).toContain('<h1>舊資料內容</h1>')

    await wrapper.vm.deleteEntry({ id: 1, title: '中文標題', title_en: 'English title' })
    expect(deleteMock).toHaveBeenCalledWith(1)
    setLocale('zh-TW')
  })
})
