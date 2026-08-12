import { getLocalItem, setLocalItem } from './storage'

export const FONT_SIZE_STORAGE_KEY = 'personal-settings-font-size'

export const APP_FONT_BASELINE = 0.9
export const FONT_SIZE_MIN = 50
export const FONT_SIZE_MAX = 150
export const FONT_SIZE_STEP = 1
export const USER_SCALE_DEFAULT_PERCENT = 100

const DISPLAY_PERCENT_PREFIX = 'display-percent:'

const LEGACY_FONT_SIZE_SCALE = {
  small: 0.9,
  default: 1,
  large: 1.1,
  'x-large': 1.2,
}

function normalizeFontSizePercent(value) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) {
    return USER_SCALE_DEFAULT_PERCENT
  }

  const clamped = Math.min(FONT_SIZE_MAX, Math.max(FONT_SIZE_MIN, numeric))
  return Math.round(clamped)
}

function displayPercentFromEffectiveScale(value) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) {
    return USER_SCALE_DEFAULT_PERCENT
  }

  return normalizeFontSizePercent((numeric / APP_FONT_BASELINE) * 100)
}

export function userScaleFromDisplayPercent(value) {
  const percent = normalizeFontSizePercent(value)
  return Number((percent / 100).toFixed(4))
}

export function effectiveFontScaleFromDisplayPercent(value) {
  return Number((APP_FONT_BASELINE * userScaleFromDisplayPercent(value)).toFixed(4))
}

function parseStoredFontSizePercent(stored) {
  if (!stored) {
    return USER_SCALE_DEFAULT_PERCENT
  }

  if (Object.hasOwn(LEGACY_FONT_SIZE_SCALE, stored)) {
    return displayPercentFromEffectiveScale(LEGACY_FONT_SIZE_SCALE[stored])
  }

  if (stored.startsWith(DISPLAY_PERCENT_PREFIX)) {
    return normalizeFontSizePercent(stored.slice(DISPLAY_PERCENT_PREFIX.length))
  }

  const numeric = Number(stored)
  if (!Number.isFinite(numeric)) {
    return USER_SCALE_DEFAULT_PERCENT
  }

  if (numeric > 2) {
    return normalizeFontSizePercent(numeric)
  }

  return displayPercentFromEffectiveScale(numeric)
}

export function getFontSizePreference() {
  const stored = getLocalItem(FONT_SIZE_STORAGE_KEY)
  return parseStoredFontSizePercent(stored)
}

export function applyFontSizePreference(value = getFontSizePreference()) {
  const percent = normalizeFontSizePercent(value)
  const userScale = userScaleFromDisplayPercent(percent)
  const effectiveScale = effectiveFontScaleFromDisplayPercent(percent)

  if (typeof document !== 'undefined') {
    document.documentElement.style.fontSize = `${effectiveScale * 100}%`
    document.documentElement.style.setProperty('--app-font-baseline', String(APP_FONT_BASELINE))
    document.documentElement.style.setProperty('--app-user-font-scale', String(userScale))
    document.documentElement.style.setProperty(
      '--app-effective-font-scale',
      String(effectiveScale)
    )
    document.documentElement.dataset.appFontBaseline = String(APP_FONT_BASELINE)
    document.documentElement.dataset.appFontUserScale = String(userScale)
    document.documentElement.dataset.appFontEffectiveScale = String(effectiveScale)
    document.documentElement.dataset.appFontSizeDisplayPercent = String(percent)
  }

  return percent
}

export function setFontSizePreference(value) {
  const percent = normalizeFontSizePercent(value)
  setLocalItem(FONT_SIZE_STORAGE_KEY, `${DISPLAY_PERCENT_PREFIX}${percent}`)
  applyFontSizePreference(percent)
  return percent
}
