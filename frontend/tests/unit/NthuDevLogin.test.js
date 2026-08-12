import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

import NthuDevLogin from '@/views/NthuDevLogin.vue'

const authServiceMock = vi.hoisted(() => ({
  getNthuDevProfiles: vi.fn(),
  nthuDevLogin: vi.fn(),
}))

vi.mock('@/api', () => ({ authService: authServiceMock }))

const profiles = [
  ['physics', '112022123'],
  ['other_department', '112025123'],
  ['special_userid', 'X1106099'],
  ['missing_userid', null],
  ['staff_allowed', 'W90001'],
  ['staff_unlisted', 'W90002'],
  ['not_inschool', '112022124'],
].map(([key, userid], index) => ({
  key,
  label: `Profile ${index + 1}`,
  userid,
  name: `[DEV] Profile ${index + 1}`,
  inschool: key !== 'not_inschool',
  department_code: key === 'physics' ? '022' : null,
  nthu_affiliation_kind:
    key === 'physics' || key === 'other_department' || key === 'not_inschool'
      ? 'standard_student'
      : key === 'special_userid'
        ? 'special_student'
        : key.startsWith('staff_')
          ? 'staff'
          : 'unknown',
  nthu_affiliation_label:
    key === 'physics' || key === 'other_department' || key === 'not_inschool'
      ? '一般學生'
      : key === 'special_userid'
        ? '交換生／特殊學生'
        : key.startsWith('staff_')
          ? '教職員'
          : '未分類',
  department_name: key === 'physics' ? '物理學系' : null,
}))

describe('NTHU development login harness', () => {
  beforeEach(() => {
    authServiceMock.getNthuDevProfiles.mockReset()
    authServiceMock.nthuDevLogin.mockReset()
  })

  it('renders the seven backend-owned profiles and navigates by key only', async () => {
    authServiceMock.getNthuDevProfiles.mockResolvedValue({ profiles })
    const wrapper = mount(NthuDevLogin)
    await flushPromises()

    expect(wrapper.findAll('.nthu-dev-login__card')).toHaveLength(7)
    expect(wrapper.text()).toContain('W90001')
    expect(wrapper.text()).toContain('交換生／特殊學生')
    expect(wrapper.text()).toContain('教職員')
    expect(wrapper.find('input').exists()).toBe(false)

    await wrapper.findAll('button')[4].trigger('click')
    expect(authServiceMock.nthuDevLogin).toHaveBeenCalledWith('staff_allowed')
    wrapper.unmount()
  })

  it('fails safely when the development endpoint is unavailable', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    authServiceMock.getNthuDevProfiles.mockRejectedValue(new Error('disabled'))
    const wrapper = mount(NthuDevLogin)
    await flushPromises()

    expect(wrapper.text()).toContain('無法載入 NTHU OAuth 測試身分')
    expect(wrapper.findAll('.nthu-dev-login__card')).toHaveLength(0)
    consoleError.mockRestore()
    wrapper.unmount()
  })
})
