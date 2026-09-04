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

const contrastRatio = (foreground, background) => {
  const luminance = (hex) => {
    const channels = hex
      .slice(1)
      .match(/.{2}/g)
      .map((channel) => Number.parseInt(channel, 16) / 255)
      .map((channel) => (channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4))

    return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722
  }

  const lighter = Math.max(luminance(foreground), luminance(background))
  const darker = Math.min(luminance(foreground), luminance(background))
  return (lighter + 0.05) / (darker + 0.05)
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

  it('keeps Classic surfaces and adds an owner-scoped Christmas continuity contract', () => {
    expect(notFoundSource).toContain('.not-found-card')
    expect(notFoundSource).toContain("html[data-effective-theme='christmas'] .not-found")
    expect(notFoundSource).toContain('background: transparent')
    expect(notFoundSource).toContain('background: #293f52')
    expect(notFoundSource).toContain('background: #3e5f72')
    expect(notFoundSource).toContain('border-left: 0.25rem solid #793941')
    expect(notFoundSource).toContain('color: #f8f2e8')
    expect(notFoundSource).toContain('color: #f5eedc')
    expect(notFoundSource).not.toContain('@keyframes')
    expect(notFoundSource).not.toContain('@media')
  })

  it('uses readable existing Christmas palette pairings', () => {
    expect(contrastRatio('#F8F2E8', '#293F52')).toBeGreaterThanOrEqual(4.5)
    expect(contrastRatio('#F5EEDC', '#3E5F72')).toBeGreaterThanOrEqual(4.5)
  })
})
