import { beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import { flushPromises, shallowMount } from '@vue/test-utils'
import FestivalThemeManagementPanel from '@/components/admin/FestivalThemeManagementPanel.vue'
import source from '@/components/admin/FestivalThemeManagementPanel.vue?raw'
import { messages } from '@/i18n/messages'
import { useTheme } from '@/utils/useTheme'
import {
  FESTIVAL_THEME_PREVIEW_QUERY_KEY,
  createFestivalThemePreviewRows,
  isFestivalThemePreviewEnabled,
} from '@/utils/festivalThemePreview'

const mocks = vi.hoisted(() => ({
  getAdmin: vi.fn(),
  activateAdmin: vi.fn(),
  updateAdmin: vi.fn(),
}))

const themeState = useTheme()

vi.mock('@/api', () => ({
  themeManagementService: {
    getAdmin: mocks.getAdmin,
    activateAdmin: mocks.activateAdmin,
    updateAdmin: mocks.updateAdmin,
  },
}))

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

function themeCards(wrapper, kind) {
  return wrapper
    .findAll('[data-testid="theme-overview-card"]')
    .filter((card) => card.attributes('data-theme-kind') === kind)
}

describe('FestivalThemeManagementPanel', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/admin')
    themeState.isDarkTheme.value = false
    themeState.applyActiveSiteTheme('general')
    mocks.getAdmin.mockReset().mockResolvedValue({ data: phaseOneCapabilities })
    mocks.activateAdmin.mockReset()
    mocks.updateAdmin.mockReset()
  })

  it('keeps only activation and edit as festival card actions', () => {
    expect(source.match(/theme-download-action/g)).toHaveLength(2)
    expect(source).not.toContain('theme-admin-delete-action')
    expect(source).not.toContain('festival-theme-delete')
    expect(source).not.toContain('pi pi-trash')
    expect(source).not.toContain('confirmDelete')
    expect(source).not.toContain('removeTheme')
  })

  it('keeps gallery interactions explicit and motion preferences safe', () => {
    const articleStartTag = source.match(/<article[\s\S]*?>/)?.[0]

    expect(source).toContain(':aria-current="row.isActive ? \'true\' : undefined"')
    expect(source).toContain(':aria-describedby="`theme-card-details-${row.id}`"')
    expect(source).toContain('tabindex="0"')
    expect(source).toMatch(/<article[\s\S]*?class="theme-gallery-card"[\s\S]*?<\/article>/)
    expect(articleStartTag).not.toContain('@click')
    expect(source).toContain('.theme-gallery-card:focus-within')
    expect(source).toContain('@media (min-width: 768px) and (hover: hover) and (pointer: fine)')
    expect(source).toContain('@media (prefers-reduced-motion: reduce)')
    expect(source).not.toContain('.theme-gallery-card__swatch')
    expect(source).not.toContain('.theme-gallery-card__hex')
  })

  it('groups desktop cards into one expanding suite and keeps the governed phone fallback', () => {
    expect(source).toContain('width: min(100%, 58rem);')
    expect(source).toContain('height: clamp(18rem, 32vw, 21rem);')
    expect(source).toMatch(
      /@media \(min-width: 768px\) and \(hover: hover\) and \(pointer: fine\)[\s\S]*?\.theme-gallery \{[\s\S]*?display: flex;/
    )
    expect(source).toMatch(
      /\.theme-gallery-card:hover,[\s\S]*?\.theme-gallery-card:focus-within \{[\s\S]*?flex-grow: 1\.85;/
    )
    expect(source).toMatch(
      /\.theme-gallery-card:hover \.theme-gallery-card__details,[\s\S]*?max-height: 12rem;[\s\S]*?opacity: 1;/
    )
    expect(source).toMatch(
      /@media \(min-width: 768px\)[\s\S]*?grid-template-rows: minmax\(0, 1fr\) 4\.25rem;/
    )
    expect(source).toMatch(
      /\.theme-gallery-card__details \{[\s\S]*?position: absolute;[\s\S]*?bottom: 4\.8rem;/
    )
    expect(source).toMatch(/\.theme-gallery-card__footer \{[\s\S]*?min-height: 4\.25rem;/)
    expect(source).toContain('aspect-ratio: 1.7 / 1;')
    expect(source).toContain('@media (max-width: 767.98px)')
    expect(source).not.toContain('@media (max-width: 640px)')
    expect(source).toMatch(
      /\.theme-row-actions :deep\(\.p-button\)[\s\S]*?flex: 1 1 100%;[\s\S]*?width: 100%;/
    )
  })

  it('renders classic and festival as distinct single-color mode cards without palette strips', async () => {
    const wrapper = createWrapper()
    await flushPromises()

    const [classicCard, festivalCard] = wrapper.findAll('[data-testid="theme-overview-card"]')

    expect(classicCard.findAll('[data-testid="theme-mode-visual"]')).toHaveLength(1)
    expect(festivalCard.findAll('[data-testid="theme-mode-visual"]')).toHaveLength(1)
    expect(classicCard.findAll('[data-testid="theme-card-details"]')).toHaveLength(1)
    expect(festivalCard.findAll('[data-testid="theme-card-details"]')).toHaveLength(1)
    expect(classicCard.attributes('aria-describedby')).toBe('theme-card-details-general')
    expect(festivalCard.attributes('aria-describedby')).toBe('theme-card-details-christmas')
    expect(wrapper.find('[data-testid="theme-palette"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="theme-palette-swatch"]').exists()).toBe(false)
    expect(source).toMatch(
      /\.theme-gallery-card\[data-theme-kind='classic'\][\s\S]{0,220}?--theme-card-surface: #eef6f2;/
    )
    expect(source).toMatch(
      /:global\([\s\S]{0,180}?html\[data-effective-theme='dark'\][\s\S]{0,180}?\.festival-theme-management[\s\S]{0,180}?\.theme-gallery-card\[data-theme-kind='classic'\][\s\S]{0,80}?\) \{[\s\S]{0,420}?--theme-card-surface: var\(--bg-secondary\);[\s\S]*?--theme-card-layer: var\(--bg-primary\);[\s\S]*?--theme-card-text: var\(--text-primary\);[\s\S]*?--theme-card-muted-text: var\(--text-secondary\);[\s\S]*?--theme-card-border: var\(--border-color\);/
    )
    expect(source).toMatch(
      /\.theme-gallery-card\[data-theme-kind='festival'\][\s\S]{0,220}?--theme-card-surface: #426878;/
    )
    expect(source).not.toContain('THEME_PALETTE')
    expect(source).not.toContain('themePalette')
    expect(source).not.toContain('linear-gradient')
  })

  it('uses the Navbar PrimeIcons as decorative mode identity without parallel theme state', async () => {
    const wrapper = createWrapper()
    await flushPromises()

    const classicIcon = themeCards(wrapper, 'classic')[0].get('[data-testid="theme-mode-icon"]')
    const festivalIcon = themeCards(wrapper, 'festival')[0].get('[data-testid="theme-mode-icon"]')

    expect(classicIcon.classes()).toEqual(expect.arrayContaining(['pi', 'pi-sun']))
    expect(festivalIcon.classes()).toEqual(expect.arrayContaining(['pi', 'pi-bell']))
    for (const icon of [classicIcon, festivalIcon]) {
      expect(icon.element.tagName).toBe('I')
      expect(icon.attributes('aria-hidden')).toBe('true')
      expect(icon.attributes('tabindex')).toBeUndefined()
      expect(icon.attributes('role')).toBeUndefined()
    }

    themeState.isDarkTheme.value = true
    await nextTick()
    expect(classicIcon.classes()).toEqual(expect.arrayContaining(['pi', 'pi-moon']))
    expect(classicIcon.classes()).not.toContain('pi-sun')

    expect(source).toContain('const { isDarkTheme, applyActiveSiteTheme } = useTheme()')
    expect(source).not.toContain('isDarkForCard')
    expect(source).not.toContain('@click="handleToggleTheme"')
    expect(source).not.toContain('notificationStore')
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

  it('renders one semantic card gallery with the built-in classic theme', async () => {
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
    expect(wrapper.find('.theme-table').exists()).toBe(false)
    expect(wrapper.find('[data-testid="theme-overview-mobile-card"]').exists()).toBe(false)
    const gallery = wrapper.get('[data-testid="theme-overview-gallery"]')
    expect(gallery.element.tagName).toBe('DIV')
    expect(gallery.findAll(':scope > article')).toHaveLength(2)

    const classicCard = themeCards(wrapper, 'classic')[0]
    expect(classicCard.element.tagName).toBe('ARTICLE')
    expect(classicCard.attributes('aria-label')).toBe('經典模式')
    expect(classicCard.attributes('aria-current')).toBe('true')
    expect(classicCard.classes()).toContain('theme-gallery-card--active')
    expect(classicCard.text()).toContain('經典模式')
    expect(classicCard.text()).not.toContain('一般主題')
    expect(classicCard.text()).toContain('最初設計的模式，有深淺色可供使用者切換。')
    expect(classicCard.text()).toContain('有')
    expect(classicCard.text()).toContain('已啟用')
    expect(classicCard.text()).toContain('系統內建')
    expect(classicCard.find('[data-testid="festival-theme-edit"]').exists()).toBe(false)
    expect(classicCard.find('[data-testid="festival-theme-delete"]').exists()).toBe(false)
  })

  it('renders the production Christmas row inactive beneath the active classic row', async () => {
    const wrapper = createWrapper()
    await flushPromises()

    const cards = wrapper.findAll('[data-testid="theme-overview-card"]')
    expect(cards).toHaveLength(2)
    expect(cards[0].text()).toContain('經典模式')
    expect(cards[0].text()).toContain('已啟用')
    expect(cards[1].text()).toContain('聖誕模式')
    expect(cards[1].text()).toContain('這是專門為聖誕節準備的主題，只會在聖誕節使用。')
    expect(cards[1].text()).toContain('無')
    expect(cards[1].attributes('aria-current')).toBeUndefined()
    expect(cards[1].classes()).toContain('theme-gallery-card--inactive')
    expect(cards[1].get('[data-testid="festival-theme-activation"]').text()).toBe('啟用')
    expect(cards[1].get('[data-testid="festival-theme-edit"]').text()).toBe('編輯')
    expect(cards[1].find('[data-testid="festival-theme-delete"]').exists()).toBe(false)
    expect(cards[1].text()).not.toContain('刪除')
    expect(wrapper.find('[data-testid="festival-theme-empty-note"]').exists()).toBe(false)
  })

  it('keeps the classic row and explicit empty note when the backend catalog is empty', async () => {
    mocks.getAdmin.mockResolvedValueOnce({ data: emptyCapabilities })
    const wrapper = createWrapper()
    await flushPromises()

    expect(wrapper.findAll('[data-testid="theme-overview-card"]')).toHaveLength(1)
    expect(wrapper.get('[data-testid="festival-theme-empty-note"]').text()).toBe(
      '目前尚未建立節日主題'
    )
  })

  it('sorts an active festival first, classic second, and keeps inactive backend order', async () => {
    mocks.getAdmin.mockResolvedValueOnce({ data: sortedCapabilities })
    const wrapper = createWrapper()
    await flushPromises()

    expect(
      wrapper
        .findAll('[data-testid="theme-overview-card"]')
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
      wrapper
        .findAll('[data-testid="theme-overview-card"]')
        .map((card) => card.find('strong').text())
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
      wrapper
        .findAll('[data-testid="theme-overview-card"]')
        .map((card) => card.find('strong').text())
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
    const cards = themeCards(wrapper, 'festival')
    expect(cards).toHaveLength(2)
    expect(cards[0].text()).toContain('聖誕節主題')
    expect(cards[0].text()).toContain('冬季節慶視覺主題')
    expect(cards[0].text()).toContain('有')
    expect(cards[0].text()).toContain('已啟用')
    expect(cards[1].text()).toContain('春節主題')
    expect(cards[1].text()).toContain('農曆新年節慶視覺主題')
    expect(cards[1].text()).toContain('無')
    expect(cards[1].get('[data-testid="festival-theme-activation"]').text()).toBe('啟用')
    for (const card of cards) {
      expect(card.get('[data-testid="festival-theme-edit"]').text()).toBe('編輯')
      expect(card.find('[data-testid="festival-theme-delete"]').exists()).toBe(false)
      expect(card.text()).not.toContain('刪除')
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

  it('switches preview activation in memory without calling the real activation endpoint', async () => {
    window.history.replaceState({}, '', '/admin?festivalThemePreview=1')
    const wrapper = createWrapper()
    await flushPromises()

    const springCard = themeCards(wrapper, 'festival')[1]
    await springCard.get('[data-testid="festival-theme-activation"]').trigger('click')
    await flushPromises()
    const cards = wrapper.findAll('[data-testid="theme-overview-card"]')
    expect(cards[0].text()).toContain('春節主題')
    expect(cards[0].text()).toContain('已啟用')
    expect(cards[1].text()).toContain('經典模式')
    expect(cards[2].text()).toContain('聖誕節主題')
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
    expect(themeCards(wrapper, 'classic')[0].text()).toContain('系統內建')
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

    await themeCards(wrapper, 'festival')[0]
      .get('[data-testid="festival-theme-activation"]')
      .trigger('click')
    await flushPromises()

    expect(mocks.activateAdmin).toHaveBeenCalledOnce()
    expect(mocks.activateAdmin).toHaveBeenCalledWith('christmas')
    expect(wrapper.findAll('[data-testid="theme-overview-card"]')[0].text()).toContain('聖誕模式')
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

    const cards = themeCards(wrapper, 'festival')
    expect(cards).toHaveLength(2)
    expect(cards[0].text()).toContain('春日主題')
    expect(cards[0].text()).toContain('有')
    expect(cards[0].text()).toContain('已啟用')
    expect(cards[1].text()).toContain('無')
    await cards[1].get('[data-testid="festival-theme-activation"]').trigger('click')
    await flushPromises()
    expect(mocks.activateAdmin).toHaveBeenCalledWith('mid_autumn')
    expect(themeCards(wrapper, 'festival')[0].text()).toContain('中秋主題')
    expect(themeCards(wrapper, 'festival')[0].text()).toContain('已啟用')
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
