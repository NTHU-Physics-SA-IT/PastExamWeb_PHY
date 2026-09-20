import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount, shallowMount } from '@vue/test-utils'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import PrimeVue from 'primevue/config'
import ConfirmDialog from 'primevue/confirmdialog'
import ConfirmationEventBus from 'primevue/confirmationeventbus'
import App from '@/App.vue'
import appSource from '@/App.vue?raw'
import homeSource from '@/views/Home.vue?raw'
import archiveSource from '@/views/Archive.vue?raw'
import { useTheme } from '@/utils/useTheme'

const globalStyles = readFileSync(resolve('src/style.css'), 'utf8')
enableAutoUnmount(afterEach)

// jsdom does not negotiate viewport / reduced-motion media queries. Exercise
// the real selectors and declarations from the selected CSSOM branch; actual
// browser media negotiation and visual density remain preview acceptance.
function mountSnowStyles(activeMedia = []) {
  const source = document.createElement('style')
  source.textContent = globalStyles.slice(
    globalStyles.indexOf('.app-christmas-frosted-window > .christmas-snowfall {'),
    globalStyles.indexOf('.p-error {')
  )
  document.head.append(source)
  const styles = document.createElement('style')
  styles.dataset.snowTest = ''
  styles.textContent = [...source.sheet.cssRules]
    .flatMap((rule) =>
      rule.media
        ? activeMedia.includes(rule.media.mediaText)
          ? [...rule.cssRules].map((child) => child.cssText)
          : []
        : [rule.cssText]
    )
    .join('\n')
  source.remove()
  document.head.append(styles)
}

const getActiveMock = vi.hoisted(() => vi.fn())
const snowEngineStartMock = vi.hoisted(() => vi.fn())
const snowEngineStopMock = vi.hoisted(() => vi.fn())

vi.mock('@/api/services/themeManagement', () => ({
  themeManagementService: { getActive: getActiveMock },
}))

vi.mock('@/utils/christmasButtonSnow', () => ({
  createChristmasButtonSnowEngine: () => ({
    start: snowEngineStartMock,
    stop: snowEngineStopMock,
  }),
}))

vi.mock('primevue/usetoast', () => ({ useToast: () => ({ add: vi.fn() }) }))
vi.mock('primevue/useconfirm', () => ({ useConfirm: () => ({ require: vi.fn() }) }))

const mountApp = () =>
  shallowMount(App, {
    global: {
      stubs: {
        ConfirmDialog: true,
        Navbar: true,
        RouterView: true,
        Toast: true,
      },
    },
  })

describe('App shared Christmas background', () => {
  beforeEach(() => {
    getActiveMock.mockReset()
    snowEngineStartMock.mockReset()
    snowEngineStopMock.mockReset()
    useTheme().applyActiveSiteTheme('general')
  })

  afterEach(() => {
    ConfirmationEventBus.emit('close')
    document.documentElement.classList.remove('admin-page-active')
    document.documentElement.removeAttribute('data-effective-theme')
    document.querySelectorAll('style[data-snow-test]').forEach((style) => style.remove())
  })

  it('hosts the frosted-window state and existing varied snowfall once for Christmas', async () => {
    getActiveMock.mockResolvedValueOnce({ data: { active_theme: 'christmas' } })

    const wrapper = mountApp()
    await flushPromises()

    expect(wrapper.get('#app').classes()).toContain('app-christmas-frosted-window')
    expect(wrapper.findAll('.christmas-background-snowflake')).toHaveLength(72)
    expect(wrapper.findAll('.christmas-decorative-snowflake')).toHaveLength(18)
    expect(wrapper.findAll('.christmas-snowfall')).toHaveLength(1)
    expect(snowEngineStartMock).toHaveBeenCalled()

    wrapper.unmount()
  })

  it('keeps the shared frosted-window system and snowfall absent outside Christmas', async () => {
    getActiveMock.mockResolvedValueOnce({ data: { active_theme: 'general' } })

    const wrapper = mountApp()
    await flushPromises()

    expect(wrapper.get('#app').classes()).not.toContain('app-christmas-frosted-window')
    expect(wrapper.find('.christmas-snowfall').exists()).toBe(false)

    wrapper.unmount()
  })

  it.each([false, true])(
    'removes snow on return to Classic (dark=%s) and disposes its watcher',
    async (dark) => {
      getActiveMock.mockResolvedValueOnce({ data: { active_theme: 'christmas' } })
      const wrapper = mountApp()
      await flushPromises()
      const theme = useTheme()
      theme.isDarkTheme.value = dark
      theme.applyActiveSiteTheme('general')
      await flushPromises()
      expect(theme.effectiveTheme.value).toBe(dark ? 'dark' : 'light')
      expect(wrapper.find('.christmas-snowfall').exists()).toBe(false)
      expect(snowEngineStopMock).toHaveBeenCalled()

      theme.applyActiveSiteTheme('christmas')
      await flushPromises()
      expect(wrapper.findAll('.christmas-snowfall')).toHaveLength(1)
      expect(wrapper.findAll('.christmas-background-snowflake')).toHaveLength(72)
      expect(wrapper.findAll('.christmas-decorative-snowflake')).toHaveLength(18)
      wrapper.unmount()
      const startCount = snowEngineStartMock.mock.calls.length
      const stopCount = snowEngineStopMock.mock.calls.length
      theme.applyActiveSiteTheme('general')
      await flushPromises()
      theme.applyActiveSiteTheme('christmas')
      await flushPromises()
      expect(snowEngineStartMock).toHaveBeenCalledTimes(startCount)
      expect(snowEngineStopMock).toHaveBeenCalledTimes(stopCount)
    }
  )

  it('retains the full moving snow field without per-flake filter surfaces', async () => {
    getActiveMock.mockResolvedValueOnce({ data: { active_theme: 'christmas' } })
    mountSnowStyles()
    const wrapper = mountApp()
    document.body.append(wrapper.element)
    await flushPromises()
    expect(wrapper.get('.christmas-snowfall').attributes('aria-hidden')).toBe('true')
    const dots = wrapper.findAll('.christmas-background-snowflake')
    const glyphs = wrapper.findAll('.christmas-decorative-snowflake')
    expect(dots).toHaveLength(72)
    expect(glyphs).toHaveLength(18)
    for (const flake of [...dots, ...glyphs]) {
      const style = getComputedStyle(flake.element)
      expect(['', 'none']).toContain(style.filter)
      expect(style.display).not.toBe('none')
      expect(style.pointerEvents).toBe('none')
      expect(style.animation).toContain('infinite')
    }
    expect(
      new Set(dots.map((flake) => flake.element.style.getPropertyValue('--snow-duration'))).size
    ).toBeGreaterThan(10)
    expect(
      new Set(dots.map((flake) => flake.element.style.getPropertyValue('--snow-left'))).size
    ).toBeGreaterThan(40)
    expect(new Set(glyphs.map((flake) => flake.text()))).toEqual(new Set(['❄︎', '❅', '❆']))
    expect(getComputedStyle(glyphs[0].element).animation).toContain('christmasSnowflakeFlicker')
    wrapper.unmount()
  })

  it.each([
    [[], 72, 18],
    [['(max-width: 767px)'], 48, 12],
    [['(prefers-reduced-motion: reduce)'], 0, 0],
    [['(max-width: 767px)', '(prefers-reduced-motion: reduce)'], 0, 0],
  ])('preserves snow visibility for selected media %j', async (media, dots, glyphs) => {
    getActiveMock.mockResolvedValueOnce({ data: { active_theme: 'christmas' } })
    mountSnowStyles(media)
    const wrapper = mountApp()
    document.body.append(wrapper.element)
    await flushPromises()
    const visible = (selector) =>
      wrapper
        .findAll(selector)
        .filter((flake) => getComputedStyle(flake.element).display !== 'none').length
    expect(visible('.christmas-background-snowflake')).toBe(dots)
    expect(visible('.christmas-decorative-snowflake')).toBe(glyphs)
    // Accessibility mode only suppresses the environmental particles, not the theme.
    expect(wrapper.get('#app').classes()).toContain('app-christmas-frosted-window')
    wrapper.unmount()
  })

  it('assigns the global ConfirmDialog an App-owned root identifier', async () => {
    getActiveMock.mockResolvedValueOnce({ data: { active_theme: 'christmas' } })

    const wrapper = mountApp()
    await flushPromises()

    expect(wrapper.get('confirm-dialog-stub').classes()).toContain('app-global-confirm-dialog')

    wrapper.unmount()
  })

  it('keeps the teleported App-owned ConfirmDialog palette independent of the Admin route', async () => {
    document.documentElement.dataset.effectiveTheme = 'christmas'
    document.documentElement.classList.add('admin-page-active')
    const appStyleElement = document.createElement('style')
    appStyleElement.textContent = appSource.match(/<style>([\s\S]*?)<\/style>\s*$/)?.[1] ?? ''
    document.head.append(appStyleElement)

    const wrapper = mount(ConfirmDialog, {
      attrs: { class: 'app-global-confirm-dialog' },
      global: { plugins: [PrimeVue] },
    })
    ConfirmationEventBus.emit('confirm', {
      header: '確認操作',
      message: '這是全域確認視窗。',
      rejectLabel: '取消',
      acceptLabel: '確認',
    })
    await flushPromises()

    const root = document.body.querySelector('.p-confirmdialog.app-global-confirm-dialog')
    const header = root?.querySelector('.p-dialog-header')
    const content = root?.querySelector('.p-dialog-content')
    const footer = root?.querySelector('.p-dialog-footer')
    const title = root?.querySelector('.p-dialog-title')
    const closeButton = root?.querySelector('.p-dialog-close-button')
    const buttons = [...(root?.querySelectorAll('.p-dialog-footer .p-button') ?? [])]
    const captureVisualContract = () => ({
      root: {
        background: getComputedStyle(root).backgroundColor,
        border: getComputedStyle(root).border,
        borderRadius: getComputedStyle(root).borderRadius,
        boxShadow: getComputedStyle(root).boxShadow,
        color: getComputedStyle(root).color,
        width: getComputedStyle(root).width,
      },
      header: {
        background: getComputedStyle(header).backgroundColor,
        color: getComputedStyle(header).color,
        padding: getComputedStyle(header).padding,
      },
      content: {
        background: getComputedStyle(content).backgroundColor,
        color: getComputedStyle(content).color,
        padding: getComputedStyle(content).padding,
      },
      footer: {
        background: getComputedStyle(footer).backgroundColor,
        color: getComputedStyle(footer).color,
        padding: getComputedStyle(footer).padding,
      },
      titleColor: getComputedStyle(title).color,
      closeButton: {
        color: getComputedStyle(closeButton).color,
        padding: getComputedStyle(closeButton).padding,
      },
      buttons: buttons.map((button) => ({
        background: getComputedStyle(button).backgroundColor,
        border: getComputedStyle(button).border,
        color: getComputedStyle(button).color,
        padding: getComputedStyle(button).padding,
      })),
    })
    expect(root).not.toBeNull()
    expect(getComputedStyle(root).backgroundColor).toBe('rgb(62, 95, 114)')
    expect(getComputedStyle(header).backgroundColor).toBe('rgb(41, 63, 82)')
    expect(getComputedStyle(content).backgroundColor).toBe('rgb(62, 95, 114)')
    expect(getComputedStyle(footer).backgroundColor).toBe('rgb(62, 95, 114)')
    const adminRouteVisualContract = captureVisualContract()

    document.documentElement.classList.remove('admin-page-active')

    expect(captureVisualContract()).toEqual(adminRouteVisualContract)

    wrapper.unmount()
    appStyleElement.remove()
  })

  it('keeps the ConfirmDialog Christmas authority App-scoped and geometry-neutral', () => {
    const appConfirmStyles = appSource.slice(
      appSource.indexOf(
        "html[data-effective-theme='christmas'] body .p-dialog.app-global-confirm-dialog"
      )
    )

    expect(appConfirmStyles).toContain('background: #293f52 !important;')
    expect(appConfirmStyles).toContain('background: #3e5f72 !important;')
    expect(appConfirmStyles).not.toContain('.admin-page-active')
    expect(appConfirmStyles).not.toMatch(
      /@media|\b(?:width|max-width|min-width|padding|border-radius)\s*:/
    )
  })

  it('keeps one CSS-only shared authority with four static layers and no page-owned snowfall', () => {
    expect(appSource).toContain("'app-christmas-frosted-window': effectiveTheme === 'christmas'")
    expect(globalStyles).toMatch(
      /html\[data-effective-theme='christmas'\]\s*\{[\s\S]*--christmas-page-background-color:\s*#426878;[\s\S]*--christmas-page-background-gradient:\s*linear-gradient\(\s*135deg,\s*#426878 0%,\s*#3d6272 52%,\s*#365968 100%\s*\);/i
    )
    expect(globalStyles).toMatch(
      /#app\.app-christmas-frosted-window\s*\{[\s\S]*background-color:\s*var\(--christmas-page-background-color\);[\s\S]*background-image:\s*var\(--christmas-page-background-gradient\);/i
    )
    expect(globalStyles).toContain('rgba(214, 181, 104, 0.14)')
    expect(globalStyles).toContain('rgba(255, 241, 214, 0.07)')
    expect(globalStyles).toContain('rgba(255, 255, 255, 0.025)')
    expect(globalStyles).toContain('--christmas-background-snow-strength: 0.75')
    expect(homeSource).not.toContain('const CHRISTMAS_BACKGROUND_SNOWFLAKES')
    expect(homeSource).not.toContain('class="christmas-snowfall"')
    expect(archiveSource).not.toMatch(/\.archive-christmas \.card::before\s*\{/)
  })
})
