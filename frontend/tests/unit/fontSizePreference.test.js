import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  APP_FONT_BASELINE,
  FONT_SIZE_STORAGE_KEY,
  USER_SCALE_DEFAULT_PERCENT,
  applyFontSizePreference,
  effectiveFontScaleFromDisplayPercent,
  getFontSizePreference,
  setFontSizePreference,
  userScaleFromDisplayPercent,
} from '@/utils/fontSizePreference'

describe('font size preference architecture', () => {
  beforeEach(() => {
    if (!globalThis.localStorage) {
      const store = new Map()
      globalThis.localStorage = {
        getItem: vi.fn((key) => store.get(key) ?? null),
        setItem: vi.fn((key, value) => store.set(key, String(value))),
        removeItem: vi.fn((key) => store.delete(key)),
        clear: vi.fn(() => store.clear()),
      }
    }
    globalThis.localStorage.removeItem(FONT_SIZE_STORAGE_KEY)
    document.documentElement.removeAttribute('style')
  })

  afterEach(() => {
    globalThis.localStorage.removeItem(FONT_SIZE_STORAGE_KEY)
    document.documentElement.removeAttribute('style')
  })

  it('uses the 90% application baseline with a 100% user multiplier by default', () => {
    expect(APP_FONT_BASELINE).toBe(0.9)
    expect(getFontSizePreference()).toBe(USER_SCALE_DEFAULT_PERCENT)

    applyFontSizePreference()

    expect(document.documentElement.style.fontSize).toBe('90%')
    expect(document.documentElement.style.getPropertyValue('--app-font-baseline')).toBe('0.9')
    expect(document.documentElement.style.getPropertyValue('--app-user-font-scale')).toBe('1')
    expect(document.documentElement.style.getPropertyValue('--app-effective-font-scale')).toBe(
      '0.9'
    )
  })

  it.each([
    [50, 0.5, 0.45, '45%'],
    [100, 1, 0.9, '90%'],
    [150, 1.5, 1.35, '135%'],
  ])(
    'maps display %s%% to user scale %s and one effective root scale %s',
    (displayPercent, userScale, effectiveScale, rootFontSize) => {
      expect(userScaleFromDisplayPercent(displayPercent)).toBe(userScale)
      expect(effectiveFontScaleFromDisplayPercent(displayPercent)).toBe(effectiveScale)

      applyFontSizePreference(displayPercent)

      expect(document.documentElement.style.fontSize).toBe(rootFontSize)
      expect(document.documentElement.style.getPropertyValue('--app-user-font-scale')).toBe(
        String(userScale)
      )
      expect(document.documentElement.style.getPropertyValue('--app-effective-font-scale')).toBe(
        String(effectiveScale)
      )
    }
  )

  it('reloads the stored display percent and reapplies its effective root scale', () => {
    setFontSizePreference(150)
    document.documentElement.removeAttribute('style')

    const reloadedDisplayPercent = getFontSizePreference()
    applyFontSizePreference(reloadedDisplayPercent)

    expect(reloadedDisplayPercent).toBe(150)
    expect(document.documentElement.style.fontSize).toBe('135%')
    expect(document.documentElement.dataset.appFontSizeDisplayPercent).toBe('150')
  })
})
