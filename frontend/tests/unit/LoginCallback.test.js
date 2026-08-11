import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import LoginCallback from '@/views/LoginCallback.vue'

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
    expect(wrapper.text()).toContain('目前網站僅開放指定系所學生登入，無法確認您的系所資格。')
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
})
