import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import LoginCallback from '@/views/LoginCallback.vue'
import loginCallbackSource from '@/views/LoginCallback.vue?raw'

const routerMock = {
  push: vi.fn(),
  replace: vi.fn(),
}

let consoleErrorSpy

const exchangeNthuCodeMock = vi.hoisted(() => vi.fn())

vi.mock('@/utils/svgBg', () => ({
  getFieldBgSvg: vi.fn(() => 'mocked-bg'),
}))

vi.mock('@/api', () => ({
  authService: {
    exchangeNthuCode: exchangeNthuCodeMock,
  },
}))

const originalURLSearchParams = window.URLSearchParams

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

function mockURLSearchParams(values = {}) {
  window.URLSearchParams = class {
    constructor() {}
    get(key) {
      return values[key] ?? null
    }
  }
}

describe('LoginCallback view', () => {
  beforeEach(() => {
    routerMock.push.mockReset()
    routerMock.replace.mockReset()
    sessionStorage.clear()
    localStorage.clear()
    document.body.innerHTML = '<div class="code-background"></div>'
    consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    exchangeNthuCodeMock.mockReset()
    exchangeNthuCodeMock.mockResolvedValue({ access_token: 'test-token' })
    vi.spyOn(window.history, 'replaceState').mockImplementation(() => {})
  })

  afterEach(() => {
    document.body.innerHTML = ''
    window.URLSearchParams = originalURLSearchParams
    vi.restoreAllMocks()
    consoleErrorSpy.mockRestore()
  })

  it('exchanges a one-time code, removes it from the URL, and stores the returned token', async () => {
    mockURLSearchParams({ code: 'one-time-code' })

    mount(LoginCallback, {
      global: {
        mocks: {
          $router: routerMock,
        },
        stubs: {
          Card: { template: '<div><slot name="title"></slot><slot name="content"></slot></div>' },
          Button: { template: '<button><slot /></button>' },
          ProgressSpinner: { template: '<div class="spinner"></div>' },
        },
      },
    })

    await flushPromises()

    expect(exchangeNthuCodeMock).toHaveBeenCalledWith('one-time-code')
    expect(window.history.replaceState).toHaveBeenCalledWith(
      {},
      document.title,
      window.location.pathname
    )
    expect(sessionStorage.getItem('auth-token')).toBe('test-token')
    expect(routerMock.replace).toHaveBeenCalledWith('/archive')
  })

  it('shows a safe error when the provider redirects with a failure code', async () => {
    mockURLSearchParams({ error: 'oauth_not_in_school' })

    const wrapper = mount(LoginCallback, {
      global: {
        mocks: {
          $router: routerMock,
        },
        stubs: {
          Card: { template: '<div><slot name="title"></slot><slot name="content"></slot></div>' },
          Button: { template: '<button><slot /></button>' },
          ProgressSpinner: { template: '<div class="spinner"></div>' },
        },
      },
    })

    await flushPromises()

    expect(exchangeNthuCodeMock).not.toHaveBeenCalled()
    expect(routerMock.push).not.toHaveBeenCalledWith('/archive')
    expect(sessionStorage.getItem('auth-token')).toBeNull()
    expect(wrapper.text()).toContain('登入失敗')
    expect(wrapper.text()).toContain('目前僅限在校生登入')
  })

  it('shows a friendly affiliation message without exposing the internal error code', async () => {
    mockURLSearchParams({ error: 'oauth_department_not_allowed' })

    const wrapper = mount(LoginCallback, {
      global: {
        mocks: {
          $router: routerMock,
        },
        stubs: {
          Card: { template: '<div><slot name="title"></slot><slot name="content"></slot></div>' },
          Button: { template: '<button><slot /></button>' },
          ProgressSpinner: { template: '<div class="spinner"></div>' },
        },
      },
    })

    await flushPromises()

    expect(exchangeNthuCodeMock).not.toHaveBeenCalled()
    expect(sessionStorage.getItem('auth-token')).toBeNull()
    expect(wrapper.text()).toContain('目前網站僅開放指定的清大成員登入，您的身分不在開放範圍內。')
    expect(wrapper.text()).not.toContain('oauth_department_not_allowed')
  })

  it('shows a safe error when code exchange fails', async () => {
    mockURLSearchParams({ code: 'expired-code' })
    exchangeNthuCodeMock.mockRejectedValueOnce(new Error('expired'))

    const wrapper = mount(LoginCallback, {
      global: {
        mocks: {
          $router: routerMock,
        },
        stubs: {
          Card: { template: '<div><slot name="title"></slot><slot name="content"></slot></div>' },
          Button: { template: '<button><slot /></button>' },
          ProgressSpinner: { template: '<div class="spinner"></div>' },
        },
      },
    })

    await flushPromises()

    expect(sessionStorage.getItem('auth-token')).toBeNull()
    expect(wrapper.text()).toContain('驗證失敗')
  })

  it('rejects an exchange response without an application token', async () => {
    mockURLSearchParams({ code: 'one-time-code' })
    exchangeNthuCodeMock.mockResolvedValueOnce({})

    const wrapper = mount(LoginCallback, {
      global: {
        mocks: { $router: routerMock },
        stubs: {
          Card: { template: '<div><slot name="title"></slot><slot name="content"></slot></div>' },
          Button: { template: '<button><slot /></button>' },
          ProgressSpinner: { template: '<div class="spinner"></div>' },
        },
      },
    })

    await flushPromises()

    expect(sessionStorage.getItem('auth-token')).toBeNull()
    expect(routerMock.replace).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('驗證失敗')
  })

  it('uses the theme surface without changing callback behavior', () => {
    expect(loginCallbackSource).toContain('background: var(--bg-primary)')
    expect(loginCallbackSource).not.toContain('physics-background')
    expect(loginCallbackSource).not.toContain('getFieldBgSvg')
    expect(loginCallbackSource).toContain('authService.exchangeNthuCode(code)')
  })

  it('keeps Classic surfaces and covers every callback view state with owner-scoped Christmas styles', () => {
    expect(loginCallbackSource).toContain('.login-callback-card')
    expect(loginCallbackSource).toContain("html[data-effective-theme='christmas'] .login-callback")
    expect(loginCallbackSource).toContain('background: transparent')
    expect(loginCallbackSource).toContain('background: #293f52')
    expect(loginCallbackSource).toContain('background: #3e5f72')
    expect(loginCallbackSource).toContain('border-left: 0.25rem solid #793941')
    expect(loginCallbackSource).toContain('.loading-container')
    expect(loginCallbackSource).toContain('.p-progressspinner-circle')
    expect(loginCallbackSource).toContain('stroke: #dec78e')
    expect(loginCallbackSource).not.toContain('@keyframes')
    expect(loginCallbackSource).not.toContain('@media')
  })

  it('uses readable existing Christmas palette pairings for error and body text', () => {
    expect(contrastRatio('#F8F2E8', '#293F52')).toBeGreaterThanOrEqual(4.5)
    expect(contrastRatio('#F5EEDC', '#3E5F72')).toBeGreaterThanOrEqual(4.5)
  })
})
