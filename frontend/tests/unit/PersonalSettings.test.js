import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import PersonalSettings from '@/views/PersonalSettings.vue'

const userServiceMock = vi.hoisted(() => ({
  getMe: vi.fn(),
  updateMyNickname: vi.fn(),
}))

const toastAddMock = vi.hoisted(() => vi.fn())

vi.mock('@/api', () => ({
  userService: userServiceMock,
}))

vi.mock('@/utils/auth', () => ({
  getCurrentUser: () => ({ name: 'Cached name', email: 'cached@example.com' }),
}))

vi.mock('primevue/usetoast', () => ({
  useToast: () => ({ add: toastAddMock }),
}))

const CardStub = {
  template: '<article><slot name="title" /><slot name="content" /></article>',
}

const formControlStub = {
  inheritAttrs: false,
  template: '<input v-bind="$attrs" />',
}

function mountSettings() {
  return mount(PersonalSettings, {
    attachTo: document.body,
    global: {
      stubs: {
        Button: { template: '<button><slot />{{ $attrs.label }}</button>' },
        Card: CardStub,
        InputText: formControlStub,
        Password: formControlStub,
        Select: formControlStub,
        Slider: formControlStub,
        Tag: { template: '<span><slot /></span>' },
      },
    },
  })
}

function deferred() {
  let resolve
  let reject
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

class IntersectionObserverMock {
  static instances = []

  constructor() {
    this.observe = vi.fn()
    this.disconnect = vi.fn()
    IntersectionObserverMock.instances.push(this)
  }
}

describe('PersonalSettings account visibility', () => {
  beforeEach(() => {
    userServiceMock.getMe.mockReset()
    userServiceMock.updateMyNickname.mockReset()
    toastAddMock.mockReset()
    IntersectionObserverMock.instances = []
    globalThis.IntersectionObserver = IntersectionObserverMock
  })

  afterEach(() => {
    vi.restoreAllMocks()
    delete globalThis.IntersectionObserver
  })

  it('renders only display settings for an external account', async () => {
    userServiceMock.getMe.mockResolvedValue({
      data: {
        is_local: false,
        name: 'NTHU User',
        nickname: 'External nickname',
        email: 'external@example.com',
      },
    })

    const wrapper = mountSettings()
    await flushPromises()

    expect(wrapper.text()).toContain('顯示設定')
    expect(wrapper.text()).not.toContain('帳號設定')
    expect(wrapper.text()).not.toContain('基本資料')
    expect(wrapper.text()).not.toContain('密碼設定')
    expect(wrapper.find('#account-settings').exists()).toBe(false)
    expect(wrapper.find('#profile-setting').exists()).toBe(false)
    expect(wrapper.find('#password-setting').exists()).toBe(false)
    expect(wrapper.findAll('.settings-nav-item').map((item) => item.text())).toEqual([
      '顯示設定',
      '字體大小',
      '語言',
    ])
    expect(wrapper.vm.profileForm).toEqual({ name: '', email: '' })
    expect(
      IntersectionObserverMock.instances[0].observe.mock.calls.map(([element]) => element.id)
    ).toEqual(['display-settings', 'font-size-setting', 'language-setting'])

    wrapper.unmount()
  })

  it('keeps the complete account settings flow for a local account', async () => {
    userServiceMock.getMe.mockResolvedValue({
      data: {
        is_local: true,
        name: 'Local Admin',
        nickname: '管理員',
        email: 'admin@example.com',
      },
    })

    const wrapper = mountSettings()
    await flushPromises()

    expect(wrapper.text()).toContain('帳號設定')
    expect(wrapper.text()).toContain('基本資料')
    expect(wrapper.text()).toContain('密碼設定')
    expect(wrapper.find('#account-settings').exists()).toBe(true)
    expect(wrapper.find('#profile-setting').exists()).toBe(true)
    expect(wrapper.find('#password-setting').exists()).toBe(true)
    expect(wrapper.findAll('.settings-nav-item').map((item) => item.text())).toEqual([
      '顯示設定',
      '字體大小',
      '語言',
      '帳號設定',
      '基本資料',
      '密碼設定',
    ])
    expect(wrapper.vm.profileForm).toEqual({ name: '管理員', email: 'admin@example.com' })
    expect(
      IntersectionObserverMock.instances[0].observe.mock.calls.map(([element]) => element.id)
    ).toEqual([
      'display-settings',
      'font-size-setting',
      'language-setting',
      'account-settings',
      'profile-setting',
      'password-setting',
    ])

    wrapper.unmount()
  })

  it('does not flash account settings while the account type is loading', async () => {
    const request = deferred()
    userServiceMock.getMe.mockReturnValue(request.promise)

    const wrapper = mountSettings()
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('顯示設定')
    expect(wrapper.text()).not.toContain('帳號設定')
    expect(wrapper.find('#account-settings').exists()).toBe(false)

    request.resolve({ data: { is_local: false } })
    await flushPromises()
    wrapper.unmount()
  })

  it('fails safe when the current-user request fails', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    userServiceMock.getMe.mockRejectedValue(new Error('request failed'))

    const wrapper = mountSettings()
    await flushPromises()

    expect(wrapper.text()).toContain('顯示設定')
    expect(wrapper.text()).not.toContain('帳號設定')
    expect(wrapper.find('#account-settings').exists()).toBe(false)
    expect(wrapper.findAll('.settings-nav-item').map((item) => item.text())).toEqual([
      '顯示設定',
      '字體大小',
      '語言',
    ])
    expect(consoleError).toHaveBeenCalledWith('Load profile failed:', expect.any(Error))

    wrapper.unmount()
  })
})
