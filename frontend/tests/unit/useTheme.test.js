import { describe, it, expect, beforeEach, vi } from 'vitest'
import { nextTick } from 'vue'

const THEME_KEY = 'theme-preference'
const getActiveMock = vi.hoisted(() => vi.fn())

vi.mock('@/api/services/themeManagement', () => ({
  themeManagementService: { getActive: getActiveMock },
}))

async function loadUseTheme() {
  const module = await import('@/utils/useTheme.js')
  return module.useTheme()
}

describe('useTheme composable', () => {
  beforeEach(() => {
    vi.resetModules()
    getActiveMock.mockReset().mockResolvedValue({ data: { active_theme: 'general' } })
    localStorage.clear()
    document.documentElement.classList.remove('dark')
    document.documentElement.removeAttribute('data-effective-theme')
  })

  it('reads initial preference from localStorage', async () => {
    localStorage.setItem(THEME_KEY, 'light')

    const { isDarkTheme } = await loadUseTheme()

    await nextTick()

    expect(isDarkTheme.value).toBe(false)
    expect(document.documentElement.classList.contains('dark')).toBe(false)
  })

  it('toggles theme and persists preference', async () => {
    localStorage.setItem(THEME_KEY, 'light')

    const { isDarkTheme, toggleTheme } = await loadUseTheme()

    toggleTheme()
    await nextTick()

    expect(isDarkTheme.value).toBe(true)
    expect(localStorage.getItem(THEME_KEY)).toBe('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })

  it.each([
    ['light', false],
    ['dark', true],
  ])(
    'preserves stored %s while Christmas overrides and restores the effective theme',
    async (storedTheme, storedIsDark) => {
      localStorage.setItem(THEME_KEY, storedTheme)
      const { isDarkTheme, effectiveTheme, applyActiveSiteTheme, toggleTheme } =
        await loadUseTheme()

      expect(isDarkTheme.value).toBe(storedIsDark)
      expect(effectiveTheme.value).toBe(storedTheme)

      applyActiveSiteTheme('christmas')
      await nextTick()
      expect(effectiveTheme.value).toBe('christmas')
      expect(document.documentElement.dataset.effectiveTheme).toBe('christmas')
      expect(document.documentElement.classList.contains('dark')).toBe(false)
      expect(localStorage.getItem(THEME_KEY)).toBe(storedTheme)

      toggleTheme()
      await nextTick()
      const futurePreference = storedIsDark ? 'light' : 'dark'
      expect(effectiveTheme.value).toBe('christmas')
      expect(localStorage.getItem(THEME_KEY)).toBe(futurePreference)

      applyActiveSiteTheme('general')
      await nextTick()
      expect(effectiveTheme.value).toBe(futurePreference)
      expect(document.documentElement.classList.contains('dark')).toBe(futurePreference === 'dark')
    }
  )

  it('loads the public active theme contract without requiring authentication', async () => {
    getActiveMock.mockResolvedValueOnce({ data: { active_theme: 'christmas' } })
    const { effectiveTheme, refreshActiveSiteTheme } = await loadUseTheme()

    await refreshActiveSiteTheme()
    await nextTick()

    expect(getActiveMock).toHaveBeenCalledOnce()
    expect(effectiveTheme.value).toBe('christmas')
  })
})
