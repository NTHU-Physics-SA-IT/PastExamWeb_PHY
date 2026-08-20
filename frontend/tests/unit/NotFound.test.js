import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import NotFound from '@/views/NotFound.vue'
import notFoundSource from '@/views/NotFound.vue?raw'

const routerMock = {
  push: vi.fn(),
}

const componentStubs = {
  Card: { template: '<div><slot name="title"></slot><slot name="content"></slot></div>' },
  Button: {
    template: '<button type="button" @click="$emit(\'click\', $event)"><slot /></button>',
  },
}

function mountView() {
  return mount(NotFound, {
    attachTo: document.body,
    global: {
      mocks: { $router: routerMock },
      stubs: componentStubs,
    },
  })
}

describe('NotFound view', () => {
  beforeEach(() => {
    routerMock.push.mockReset()
    document.body.innerHTML = ''
  })

  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('renders 404 heading and helpful message', () => {
    const wrapper = mountView()
    expect(wrapper.text()).toContain('404')
    expect(wrapper.text()).toContain('頁面不存在')
    expect(wrapper.text()).toContain('抱歉，我們找不到您要找的頁面。')
    wrapper.unmount()
  })

  it('routes back home when the button is clicked', async () => {
    const wrapper = mountView()
    await wrapper.find('button').trigger('click')
    expect(routerMock.push).toHaveBeenCalledWith('/')
    wrapper.unmount()
  })

  it('uses the theme surface without the decorative physics pattern', () => {
    expect(notFoundSource).toContain('background: var(--bg-primary)')
    expect(notFoundSource).not.toContain('physics-background')
    expect(notFoundSource).not.toContain('getFieldBgSvg')
  })
})
