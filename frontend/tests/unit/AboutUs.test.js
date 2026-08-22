import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const listMock = vi.hoisted(() => vi.fn())
const createMock = vi.hoisted(() => vi.fn())
const updateMock = vi.hoisted(() => vi.fn())
const deleteMock = vi.hoisted(() => vi.fn())
const reorderMock = vi.hoisted(() => vi.fn())
const getCurrentUserMock = vi.hoisted(() => vi.fn())

vi.mock('@/api', () => ({
  aboutUsService: {
    list: listMock,
    create: createMock,
    update: updateMock,
    reorder: reorderMock,
    remove: deleteMock,
  },
}))
vi.mock('@/utils/auth.js', () => ({ getCurrentUser: getCurrentUserMock }))

const stubs = {
  Button: {
    props: ['label', 'disabled'],
    template: '<button v-bind="$attrs" :disabled="disabled">{{ label }}<slot /></button>',
  },
  Card: { template: '<article><slot name="title" /><slot name="content" /></article>' },
  Dialog: { template: '<div><slot /></div>' },
  InputText: { template: '<input />' },
  Message: { template: '<div><slot /></div>' },
  ProgressSpinner: { template: '<div />' },
  Textarea: { template: '<textarea />' },
}

describe('About Us view', () => {
  beforeEach(() => {
    vi.clearAllMocks()
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
    reorderMock.mockResolvedValue({ data: {} })
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
    wrapper.vm.form.body = '- item'
    wrapper.vm.form.body_en = '- item'
    await wrapper.vm.saveEntry()
    expect(createMock).toHaveBeenCalledWith({
      body: '- item',
      body_en: '- item',
    })
    expect(wrapper.text()).not.toContain('標題')
    expect(wrapper.text()).toContain('英文 Markdown 內容')
    expect(wrapper.text()).toContain('aboutUsImageHelp')
    expect(wrapper.find('.about-us-pagination').exists()).toBe(false)
    expect(wrapper.find('.about-us-order-actions').text()).toContain('排序')
  })

  it('keeps browsing distinct from administrator reordering', async () => {
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

    expect(wrapper.find('.about-us-entry-title').exists()).toBe(false)
    expect(wrapper.html()).toContain('<h1>English body</h1>')
    expect(wrapper.findAll('.about-us-pagination-page')).toHaveLength(2)
    expect(wrapper.findAll('.about-us-pagination-page')[0].attributes('aria-current')).toBe('page')
    expect(wrapper.find('.about-us-order-actions').text()).toContain('Reorder')

    wrapper.vm.selectEntry(1)
    await wrapper.vm.$nextTick()
    expect(wrapper.html()).toContain('<h1>舊資料內容</h1>')
    expect(wrapper.findAll('.about-us-pagination-page')[1].attributes('aria-current')).toBe('page')
    expect(reorderMock).not.toHaveBeenCalled()

    await wrapper.vm.moveEntry(wrapper.vm.entries[1], -1)
    expect(reorderMock).toHaveBeenCalledWith([2, 1])

    await wrapper.vm.deleteEntry({ id: 1, title: '中文標題', title_en: 'English title' })
    expect(deleteMock).toHaveBeenCalledWith(1)
    setLocale('zh-TW')
  })

  it('renders the localized image help with literal bounded attributes', async () => {
    const { i18n, setLocale } = await import('@/i18n')
    setLocale('en')
    expect(i18n.global.t('aboutUsImageHelp')).toContain(
      '![alt text](image URL){width=33% align=right wrap=true}'
    )
    setLocale('zh-TW')
    expect(i18n.global.t('aboutUsImageHelp')).toContain(
      '![替代文字](圖片網址){width=50% align=center}'
    )
  })

  it('shows the shared image help once below the English Markdown field', async () => {
    const AboutUs = (await import('@/views/AboutUs.vue')).default
    const wrapper = mount(AboutUs, {
      global: { stubs, mocks: { $t: (key) => key } },
    })
    await flushPromises()

    const fields = wrapper.findAll('.about-us-form > .field')
    expect(fields).toHaveLength(2)
    expect(fields[0].find('.about-us-editor-hint').exists()).toBe(false)
    expect(fields[1].get('textarea').attributes('id')).toBe('about-us-body-en')
    expect(fields[1].findAll('.about-us-editor-hint')).toHaveLength(1)
    expect(wrapper.findAll('.about-us-editor-hint')).toHaveLength(1)
  })

  it('keeps the existing empty state without browse pagination', async () => {
    listMock.mockResolvedValueOnce({ data: [] })
    const AboutUs = (await import('@/views/AboutUs.vue')).default
    const wrapper = mount(AboutUs, {
      global: { stubs, mocks: { $t: (key) => key } },
    })
    await flushPromises()

    expect(wrapper.find('.about-us-empty').exists()).toBe(true)
    expect(wrapper.find('.about-us-pagination').exists()).toBe(false)
  })

  it('lets a non-admin browse entries without rendering reorder controls', async () => {
    getCurrentUserMock.mockReturnValue({ id: 2, is_admin: false })
    listMock.mockResolvedValueOnce({
      data: [
        { id: 1, body: '# 第一則', body_en: '# First' },
        { id: 2, body: '# 第二則', body_en: '# Second' },
      ],
    })
    const AboutUs = (await import('@/views/AboutUs.vue')).default
    const wrapper = mount(AboutUs, {
      global: {
        stubs,
        mocks: {
          $t: (key, values) => (values ? `第 ${values.current} / ${values.total} 則` : key),
        },
      },
    })
    await flushPromises()

    expect(wrapper.find('.about-us-pagination').exists()).toBe(true)
    expect(wrapper.find('.about-us-order-actions').exists()).toBe(false)
    wrapper.vm.selectEntry(1)
    await wrapper.vm.$nextTick()
    expect(wrapper.html()).toContain('<h1>第二則</h1>')
    expect(reorderMock).not.toHaveBeenCalled()
  })
})
