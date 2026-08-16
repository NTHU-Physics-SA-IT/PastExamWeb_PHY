import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const listMock = vi.hoisted(() => vi.fn())
const createMock = vi.hoisted(() => vi.fn())
const updateMock = vi.hoisted(() => vi.fn())
const getCurrentUserMock = vi.hoisted(() => vi.fn())

vi.mock('@/api', () => ({
  aboutUsService: { list: listMock, create: createMock, update: updateMock },
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
    await wrapper.vm.saveEntry()
    expect(createMock).toHaveBeenCalledWith({ title: 'Second', body: '- item' })
  })
})
