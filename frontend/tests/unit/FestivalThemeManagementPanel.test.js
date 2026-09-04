import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, shallowMount } from '@vue/test-utils'
import FestivalThemeManagementPanel from '@/components/admin/FestivalThemeManagementPanel.vue'
import source from '@/components/admin/FestivalThemeManagementPanel.vue?raw'
import { messages } from '@/i18n/messages'
import {
  FESTIVAL_THEME_PREVIEW_QUERY_KEY,
  createFestivalThemePreviewRows,
  isFestivalThemePreviewEnabled,
} from '@/utils/festivalThemePreview'

const mocks = vi.hoisted(() => ({
  getAdmin: vi.fn(),
  activateAdmin: vi.fn(),
  updateAdmin: vi.fn(),
  removeAdmin: vi.fn(),
  confirm: vi.fn(),
}))

vi.mock('@/api', () => ({
  themeManagementService: {
    getAdmin: mocks.getAdmin,
    activateAdmin: mocks.activateAdmin,
    updateAdmin: mocks.updateAdmin,
    removeAdmin: mocks.removeAdmin,
  },
}))
vi.mock('primevue/useconfirm', () => ({ useConfirm: () => ({ require: mocks.confirm }) }))

const phaseOneCapabilities = {
  general_theme: { active: true, user_selectable: true, supported_modes: ['light', 'dark'] },
  festival_theme: {
    active: null,
    themes: [
      {
        id: 'christmas',
        name: '聖誕模式',
        name_en: 'Christmas Theme',
        description: '這是專門為聖誕節準備的主題，只會在聖誕節使用。',
        description_en: 'A theme prepared especially for Christmas and used only during Christmas.',
        supports_color_modes: false,
        starts_at: null,
        ends_at: null,
      },
    ],
  },
}
const emptyCapabilities = {
  general_theme: { ...phaseOneCapabilities.general_theme },
  festival_theme: { active: null, themes: [] },
}
const futureCapabilities = {
  general_theme: { ...phaseOneCapabilities.general_theme, active: false },
  festival_theme: {
    active: 'spring',
    themes: [
      {
        id: 'spring',
        name: '春日主題',
        name_en: 'Spring Theme',
        description: '春季限定外觀。',
        description_en: 'A seasonal spring appearance.',
        supports_color_modes: true,
        starts_at: '2026-03-01T00:00:00Z',
        ends_at: '2026-04-01T00:00:00Z',
      },
      {
        id: 'mid_autumn',
        name: '中秋主題',
        name_en: 'Mid-Autumn Theme',
        description: '中秋限定外觀。',
        description_en: 'A Mid-Autumn appearance.',
        supports_color_modes: false,
      },
    ],
  },
}

const sortedCapabilities = {
  general_theme: { ...phaseOneCapabilities.general_theme, active: false },
  festival_theme: {
    active: 'christmas',
    themes: [
      {
        id: 'spring',
        name: '春節主題',
        name_en: 'Spring Festival Theme',
        description: '農曆新年節慶視覺主題',
        description_en: 'A Lunar New Year visual theme.',
        supports_color_modes: false,
      },
      {
        id: 'christmas',
        name: '聖誕節主題',
        name_en: 'Christmas Theme',
        description: '冬季節慶視覺主題',
        description_en: 'A winter holiday visual theme.',
        supports_color_modes: true,
      },
      {
        id: 'halloween',
        name: '萬聖節主題',
        name_en: 'Halloween Theme',
        description: '萬聖節視覺主題',
        description_en: 'A Halloween visual theme.',
        supports_color_modes: true,
      },
    ],
  },
}

function createWrapper() {
  return shallowMount(FestivalThemeManagementPanel, {
    global: {
      stubs: {
        Message: { template: '<div><slot /></div>' },
        ProgressSpinner: { template: '<span />' },
        Button: {
          props: ['label', 'disabled', 'loading'],
          emits: ['click'],
          template:
            '<button type="button" :disabled="disabled || loading" @click="$emit(\'click\')">{{ label }}</button>',
        },
        Tag: { props: ['severity'], template: '<span><slot /></span>' },
        Dialog: { props: ['visible'], template: '<div v-if="visible"><slot /></div>' },
        InputText: { template: '<input />' },
        Textarea: { template: '<textarea />' },
        Checkbox: { template: '<input type="checkbox" />' },
        DatePicker: { template: '<input type="text" />' },
      },
    },
  })
}

function themeRows(wrapper, kind) {
  return wrapper
    .findAll('[data-testid="theme-overview-row"]')
    .filter((row) => row.attributes('data-theme-kind') === kind)
}

describe('FestivalThemeManagementPanel', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/admin')
    mocks.getAdmin.mockReset().mockResolvedValue({ data: phaseOneCapabilities })
    mocks.activateAdmin.mockReset()
    mocks.updateAdmin.mockReset()
    mocks.removeAdmin.mockReset()
    mocks.confirm.mockReset()
  })

  it('maps editable theme actions to the approved Christmas button roles', () => {
    expect(source.match(/theme-download-action/g)).toHaveLength(4)
    expect(source.match(/theme-admin-delete-action/g)).toHaveLength(2)
  })

  it('maps the edit dialog footer to the preview and download button treatments', () => {
    expect(source).toMatch(
      /class="theme-dialog-cancel-action review-action-preview"[\s\S]{0,220}?severity="secondary"[\s\S]{0,160}?outlined[\s\S]{0,160}?size="small"/
    )
    expect(source).toMatch(
      /class="theme-dialog-save-action review-action-republish"[\s\S]{0,220}?severity="success"[\s\S]{0,160}?size="small"/
    )
  })

  it('keeps loading distinct from the festival empty table', async () => {
    let resolveRequest
    mocks.getAdmin.mockReturnValue(
      new Promise((resolve) => {
        resolveRequest = resolve
      })
    )
    const wrapper = createWrapper()

    expect(wrapper.get('[data-testid="theme-management-loading"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="festival-theme-empty"]').exists()).toBe(false)
    resolveRequest({ data: phaseOneCapabilities })
    await flushPromises()
    expect(wrapper.find('[data-testid="theme-management-loading"]').exists()).toBe(false)
  })

  it('renders one unified five-column overview with the built-in classic row', async () => {
    const wrapper = createWrapper()
    await flushPromises()

    expect(wrapper.get('section.festival-theme-management').attributes('aria-label')).toBe(
      '節日主題管理'
    )
    expect(wrapper.find('h2').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('管理網站支援的主題，並查看節日主題功能狀態。')
    expect(wrapper.get('[data-testid="theme-overview-panel"] h3').text()).toBe('主題一覽')
    expect(wrapper.find('[data-testid="general-theme-panel"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="festival-theme-panel"]').exists()).toBe(false)
    expect(wrapper.findAll('.theme-table')).toHaveLength(1)
    expect(
      wrapper
        .get('[data-testid="theme-overview-table"]')
        .findAll('th')
        .map((node) => node.text())
    ).toEqual(['主題名稱', '主題簡介', '深淺模式', '狀態', '操作'])

    const classicRow = themeRows(wrapper, 'classic')[0]
    expect(classicRow.text()).toContain('經典模式')
    expect(classicRow.text()).not.toContain('一般主題')
    expect(classicRow.text()).toContain('最初設計的模式，有深淺色可供使用者切換。')
    expect(classicRow.text()).toContain('有')
    expect(classicRow.text()).toContain('已啟用')
    expect(classicRow.text()).toContain('系統內建')
    expect(classicRow.find('[data-testid="festival-theme-edit"]').exists()).toBe(false)
    expect(classicRow.find('[data-testid="festival-theme-delete"]').exists()).toBe(false)
  })

  it('renders the production Christmas row inactive beneath the active classic row', async () => {
    const wrapper = createWrapper()
    await flushPromises()

    const rows = wrapper.findAll('[data-testid="theme-overview-row"]')
    expect(rows).toHaveLength(2)
    expect(rows[0].text()).toContain('經典模式')
    expect(rows[0].text()).toContain('已啟用')
    expect(rows[1].text()).toContain('聖誕模式')
    expect(rows[1].text()).toContain('這是專門為聖誕節準備的主題，只會在聖誕節使用。')
    expect(rows[1].text()).toContain('無')
    expect(rows[1].get('[data-testid="festival-theme-activation"]').text()).toBe('啟用')
    expect(rows[1].get('[data-testid="festival-theme-edit"]').text()).toBe('編輯')
    expect(rows[1].get('[data-testid="festival-theme-delete"]').text()).toBe('刪除')
    expect(wrapper.find('[data-testid="festival-theme-empty-note"]').exists()).toBe(false)
  })

  it('keeps the classic row and explicit empty note when the backend catalog is empty', async () => {
    mocks.getAdmin.mockResolvedValueOnce({ data: emptyCapabilities })
    const wrapper = createWrapper()
    await flushPromises()

    expect(wrapper.findAll('[data-testid="theme-overview-row"]')).toHaveLength(1)
    expect(wrapper.get('[data-testid="festival-theme-empty-note"]').text()).toBe(
      '目前尚未建立節日主題'
    )
  })

  it('sorts an active festival first, classic second, and keeps inactive backend order', async () => {
    mocks.getAdmin.mockResolvedValueOnce({ data: sortedCapabilities })
    const wrapper = createWrapper()
    await flushPromises()

    expect(
      wrapper.findAll('[data-testid="theme-overview-row"]').map((row) => row.find('strong').text())
    ).toEqual(['聖誕節主題', '經典模式', '春節主題', '萬聖節主題'])
    expect(
      wrapper
        .findAll('[data-testid="theme-overview-mobile-card"]')
        .map((card) => card.find('strong').text())
    ).toEqual(['聖誕節主題', '經典模式', '春節主題', '萬聖節主題'])
  })

  it('keeps classic first and inactive festivals in backend order', async () => {
    mocks.getAdmin.mockResolvedValueOnce({
      data: {
        general_theme: { ...phaseOneCapabilities.general_theme, active: true },
        festival_theme: { ...sortedCapabilities.festival_theme, active: null },
      },
    })
    const wrapper = createWrapper()
    await flushPromises()

    expect(
      wrapper.findAll('[data-testid="theme-overview-row"]').map((row) => row.find('strong').text())
    ).toEqual(['經典模式', '春節主題', '聖誕節主題', '萬聖節主題'])
  })

  it('handles multiple active festival ids deterministically and reports a contract violation', async () => {
    mocks.getAdmin.mockResolvedValueOnce({
      data: {
        general_theme: { ...phaseOneCapabilities.general_theme, active: false },
        festival_theme: { ...sortedCapabilities.festival_theme, active: ['spring', 'christmas'] },
      },
    })
    const wrapper = createWrapper()
    await flushPromises()

    expect(
      wrapper.findAll('[data-testid="theme-overview-row"]').map((row) => row.find('strong').text())
    ).toEqual(['春節主題', '聖誕節主題', '經典模式', '萬聖節主題'])
    expect(wrapper.get('[data-testid="multiple-active-theme-violation"]').text()).toContain(
      '同時標記多個已啟用主題'
    )
  })

  it('requires both DEV and the explicit preview query before fixtures can appear', () => {
    expect(FESTIVAL_THEME_PREVIEW_QUERY_KEY).toBe('festivalThemePreview')
    expect(isFestivalThemePreviewEnabled({ isDev: true, search: '' })).toBe(false)
    expect(isFestivalThemePreviewEnabled({ isDev: true, search: '?festivalThemePreview=1' })).toBe(
      true
    )
    expect(isFestivalThemePreviewEnabled({ isDev: false, search: '?festivalThemePreview=1' })).toBe(
      false
    )
    expect(createFestivalThemePreviewRows()).toHaveLength(2)
  })

  it('shows both opt-in preview rows, metadata, status, actions, and a preview indicator', async () => {
    window.history.replaceState({}, '', '/admin?festivalThemePreview=1')
    const wrapper = createWrapper()
    await flushPromises()

    expect(mocks.getAdmin).toHaveBeenCalledTimes(1)
    expect(wrapper.get('[data-testid="festival-theme-preview-indicator"]').text()).toBe(
      'UI 預覽模式'
    )
    const rows = themeRows(wrapper, 'festival')
    expect(rows).toHaveLength(2)
    expect(rows[0].text()).toContain('聖誕節主題')
    expect(rows[0].text()).toContain('冬季節慶視覺主題')
    expect(rows[0].text()).toContain('有')
    expect(rows[0].text()).toContain('已啟用')
    expect(rows[1].text()).toContain('春節主題')
    expect(rows[1].text()).toContain('農曆新年節慶視覺主題')
    expect(rows[1].text()).toContain('無')
    expect(rows[1].get('[data-testid="festival-theme-activation"]').text()).toBe('啟用')
    for (const row of rows) {
      expect(row.get('[data-testid="festival-theme-edit"]').text()).toBe('編輯')
      expect(row.get('[data-testid="festival-theme-delete"]').text()).toBe('刪除')
    }
  })

  it('opens preview edit details and disables save without a backend update', async () => {
    window.history.replaceState({}, '', '/admin?festivalThemePreview=1')
    const wrapper = createWrapper()
    await flushPromises()

    await wrapper.findAll('[data-testid="festival-theme-edit"]')[0].trigger('click')
    const dialog = wrapper.get('[data-testid="festival-theme-edit-dialog"]')
    expect(dialog.text()).toContain('預覽模式不會儲存變更')
    expect(dialog.text()).toContain('主題名稱')
    expect(dialog.text()).toContain('主題簡介')
    expect(dialog.text()).toContain('支援淺色與深色模式')
    expect(dialog.text()).toContain('啟用時間')
    expect(dialog.text()).toContain('停用時間')
    expect(wrapper.vm.editForm.name).toBe('聖誕節主題')
    expect(wrapper.vm.editForm.starts_at.toISOString()).toBe('2026-12-20T00:00:00.000Z')
    expect(wrapper.vm.editForm.ends_at.toISOString()).toBe('2026-12-27T00:00:00.000Z')
    expect(wrapper.get('[data-testid="festival-theme-save"]').attributes('disabled')).toBeDefined()
    expect(mocks.updateAdmin).not.toHaveBeenCalled()
  })

  it('confirms preview deletion, supports cancel, and removes only in memory until reload', async () => {
    window.history.replaceState({}, '', '/admin?festivalThemePreview=1')
    const wrapper = createWrapper()
    await flushPromises()

    await wrapper.findAll('[data-testid="festival-theme-delete"]')[1].trigger('click')
    const firstConfirmation = mocks.confirm.mock.calls[0][0]
    expect(firstConfirmation.message).toContain('春節主題')
    expect(firstConfirmation.rejectLabel).toBe('取消')
    expect(firstConfirmation.acceptLabel).toBe('確認刪除')
    expect(themeRows(wrapper, 'festival')).toHaveLength(2)

    await firstConfirmation.accept()
    await flushPromises()
    expect(themeRows(wrapper, 'festival')).toHaveLength(1)
    expect(mocks.removeAdmin).not.toHaveBeenCalled()

    wrapper.unmount()
    const reloadedWrapper = createWrapper()
    await flushPromises()
    expect(themeRows(reloadedWrapper, 'festival')).toHaveLength(2)
  })

  it('switches preview activation in memory without calling the real activation endpoint', async () => {
    window.history.replaceState({}, '', '/admin?festivalThemePreview=1')
    const wrapper = createWrapper()
    await flushPromises()

    const springRow = themeRows(wrapper, 'festival')[1]
    await springRow.get('[data-testid="festival-theme-activation"]').trigger('click')
    await flushPromises()
    const rows = wrapper.findAll('[data-testid="theme-overview-row"]')
    expect(rows[0].text()).toContain('春節主題')
    expect(rows[0].text()).toContain('已啟用')
    expect(rows[1].text()).toContain('經典模式')
    expect(rows[2].text()).toContain('聖誕節主題')
    expect(mocks.activateAdmin).not.toHaveBeenCalled()
  })

  it('activates general and festival themes only through the existing API', async () => {
    mocks.getAdmin.mockResolvedValueOnce({ data: futureCapabilities })
    mocks.activateAdmin.mockResolvedValueOnce({ data: phaseOneCapabilities })
    const wrapper = createWrapper()
    await flushPromises()

    await wrapper.get('[data-testid="classic-theme-activation"]').trigger('click')
    await flushPromises()
    expect(mocks.activateAdmin).toHaveBeenCalledWith('general')
    expect(wrapper.get('[data-testid="classic-theme-active-status"]').text()).toBe('已啟用')
    expect(themeRows(wrapper, 'classic')[0].text()).toContain('系統內建')
  })

  it('activates production Christmas once, applies the shared effective theme, and sorts it first', async () => {
    mocks.activateAdmin.mockResolvedValueOnce({
      data: {
        general_theme: { ...phaseOneCapabilities.general_theme, active: false },
        festival_theme: { ...phaseOneCapabilities.festival_theme, active: 'christmas' },
      },
    })
    const wrapper = createWrapper()
    await flushPromises()

    await themeRows(wrapper, 'festival')[0]
      .get('[data-testid="festival-theme-activation"]')
      .trigger('click')
    await flushPromises()

    expect(mocks.activateAdmin).toHaveBeenCalledOnce()
    expect(mocks.activateAdmin).toHaveBeenCalledWith('christmas')
    expect(wrapper.findAll('[data-testid="theme-overview-row"]')[0].text()).toContain('聖誕模式')
    expect(wrapper.get('[data-testid="festival-theme-active-status"]').text()).toBe('已啟用')
  })

  it('renders future festival metadata and switches to another registered theme', async () => {
    mocks.getAdmin.mockResolvedValueOnce({ data: futureCapabilities })
    mocks.activateAdmin.mockResolvedValueOnce({
      data: {
        ...futureCapabilities,
        festival_theme: { ...futureCapabilities.festival_theme, active: 'mid_autumn' },
      },
    })
    const wrapper = createWrapper()
    await flushPromises()

    const rows = themeRows(wrapper, 'festival')
    expect(rows).toHaveLength(2)
    expect(rows[0].text()).toContain('春日主題')
    expect(rows[0].text()).toContain('有')
    expect(rows[0].text()).toContain('已啟用')
    expect(rows[1].text()).toContain('無')
    await rows[1].get('[data-testid="festival-theme-activation"]').trigger('click')
    await flushPromises()
    expect(mocks.activateAdmin).toHaveBeenCalledWith('mid_autumn')
    expect(themeRows(wrapper, 'festival')[0].text()).toContain('中秋主題')
    expect(themeRows(wrapper, 'festival')[0].text()).toContain('已啟用')
  })

  it('opens the edit form, validates its time range, and reports persistence failure', async () => {
    mocks.getAdmin.mockResolvedValueOnce({ data: futureCapabilities })
    mocks.updateAdmin.mockRejectedValueOnce(new Error('unavailable'))
    const wrapper = createWrapper()
    await flushPromises()

    await wrapper.findAll('[data-testid="festival-theme-edit"]')[0].trigger('click')
    expect(wrapper.get('[data-testid="festival-theme-edit-dialog"]').exists()).toBe(true)
    wrapper.vm.editForm.starts_at = new Date('2026-04-02T00:00:00Z')
    wrapper.vm.editForm.ends_at = new Date('2026-04-01T00:00:00Z')
    await wrapper.get('[data-testid="festival-theme-save"]').trigger('click')
    expect(wrapper.get('[data-testid="festival-theme-end-error"]').text()).toContain('必須晚於')

    wrapper.vm.editForm.ends_at = new Date('2026-04-03T00:00:00Z')
    await wrapper.get('[data-testid="festival-theme-save"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-testid="festival-theme-edit-dialog"]').text()).toContain(
      '儲存節日主題失敗'
    )
  })

  it('uses the shared confirmation contract and retains rows when deletion fails', async () => {
    mocks.getAdmin.mockResolvedValueOnce({ data: futureCapabilities })
    mocks.removeAdmin.mockRejectedValueOnce(new Error('unavailable'))
    const wrapper = createWrapper()
    await flushPromises()

    await wrapper.findAll('[data-testid="festival-theme-delete"]')[1].trigger('click')
    expect(mocks.confirm).toHaveBeenCalledTimes(1)
    const request = mocks.confirm.mock.calls[0][0]
    expect(request.rejectLabel).toBe('取消')
    expect(request.acceptLabel).toBe('確認刪除')
    await request.accept()
    await flushPromises()
    expect(themeRows(wrapper, 'festival')).toHaveLength(2)
    expect(wrapper.get('[data-testid="theme-management-action-error"]').text()).toContain(
      '刪除節日主題失敗'
    )
  })

  it('persists Christmas edits through the backend without changing deep/light support', async () => {
    mocks.updateAdmin.mockResolvedValueOnce({ data: phaseOneCapabilities })
    const wrapper = createWrapper()
    await flushPromises()

    await wrapper.get('[data-testid="festival-theme-edit"]').trigger('click')
    expect(wrapper.vm.editForm.supports_color_modes).toBe(false)
    wrapper.vm.editForm.description = '更新後的聖誕說明'
    await wrapper.get('[data-testid="festival-theme-save"]').trigger('click')
    await flushPromises()

    expect(mocks.updateAdmin).toHaveBeenCalledOnce()
    expect(mocks.updateAdmin).toHaveBeenCalledWith(
      'christmas',
      expect.objectContaining({
        description: '更新後的聖誕說明',
      })
    )
    expect(mocks.updateAdmin.mock.calls[0][1]).not.toHaveProperty('supports_color_modes')
  })

  it('deletes inactive Christmas through confirmation and disables deletion while active', async () => {
    mocks.removeAdmin.mockResolvedValueOnce({ data: emptyCapabilities })
    const wrapper = createWrapper()
    await flushPromises()

    await wrapper.get('[data-testid="festival-theme-delete"]').trigger('click')
    const request = mocks.confirm.mock.calls[0][0]
    await request.accept()
    await flushPromises()
    expect(mocks.removeAdmin).toHaveBeenCalledWith('christmas')
    expect(themeRows(wrapper, 'festival')).toHaveLength(0)

    mocks.getAdmin.mockResolvedValueOnce({
      data: {
        general_theme: { ...phaseOneCapabilities.general_theme, active: false },
        festival_theme: { ...phaseOneCapabilities.festival_theme, active: 'christmas' },
      },
    })
    const activeWrapper = createWrapper()
    await flushPromises()
    expect(
      activeWrapper.get('[data-testid="festival-theme-delete"]').attributes('disabled')
    ).toBeDefined()
    expect(activeWrapper.text()).toContain('請先停用此主題後再刪除')
  })

  it('renders a recoverable load error and catalogs new copy in both locales', async () => {
    mocks.getAdmin.mockRejectedValueOnce(new Error('network unavailable'))
    const wrapper = createWrapper()
    await flushPromises()
    expect(wrapper.get('[data-testid="theme-management-error"]').text()).toContain(
      '載入節日主題管理資料失敗'
    )
    await wrapper.get('[data-testid="theme-management-retry"]').trigger('click')
    await flushPromises()
    expect(mocks.getAdmin).toHaveBeenCalledTimes(2)

    for (const key of [
      '主題名稱',
      '主題簡介',
      '主題一覽',
      '經典模式',
      '深淺模式',
      '系統內建',
      '編輯節日主題',
      '停用時間必須晚於啟用時間。',
    ]) {
      expect(messages['zh-TW']).toHaveProperty(key)
      expect(messages.en).toHaveProperty(key)
      expect(messages.en[key]).not.toBe(key)
    }
  })
})
