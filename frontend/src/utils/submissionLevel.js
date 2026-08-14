import { reactive } from 'vue'
import { api } from '../api/services/client'
import { i18n } from '../i18n'

// Safe fallback only. A successful API load replaces these runtime values.
export const DEFAULT_SUBMISSION_LEVELS = [
  { level: 1, name: '新手投稿者', name_en: 'Novice Contributor', minExp: 0 },
  { level: 2, name: '初階整理者', name_en: 'Junior Curator', minExp: 2 },
  { level: 3, name: '穩定投稿者', name_en: 'Regular Contributor', minExp: 5 },
  { level: 4, name: '認真貢獻者', name_en: 'Dedicated Contributor', minExp: 9 },
  { level: 5, name: '經典整理師', name_en: 'Archive Curator', minExp: 14 },
  { level: 6, name: '題庫建設者', name_en: 'Archive Builder', minExp: 20 },
  { level: 7, name: '資源探索者', name_en: 'Resource Explorer', minExp: 27 },
  { level: 8, name: '校園收藏家', name_en: 'Campus Collector', minExp: 35 },
  { level: 9, name: '傳奇貢獻者', name_en: 'Legendary Contributor', minExp: 44 },
  { level: 10, name: '題庫宗師', name_en: 'Archive Grandmaster', minExp: 54 },
]

export const SUBMISSION_LEVELS = reactive(DEFAULT_SUBMISSION_LEVELS.map((level) => ({ ...level })))

export const CONTRIBUTOR_LEVEL_PALETTE = [
  { bg: '#7a513a', fg: '#ffffff', border: '#493023', accent: '#ddb99f' },
  { bg: '#66747b', fg: '#ffffff', border: '#3d474c', accent: '#d8e0e3' },
  { bg: '#285c68', fg: '#ffffff', border: '#173a42', accent: '#b8dce2' },
  { bg: '#23745d', fg: '#ffffff', border: '#12493a', accent: '#afe0cf' },
  { bg: '#f2f0e8', fg: '#253238', border: '#666d70', accent: '#ffffff' },
  { bg: '#202427', fg: '#f7faf9', border: '#c6d0d2', accent: '#edf3f2' },
  { bg: '#174b8f', fg: '#ffffff', border: '#0b2d59', accent: '#b8d6ff' },
  { bg: '#8d2741', fg: '#ffffff', border: '#541425', accent: '#f4bdca' },
  { bg: '#9a7420', fg: '#ffffff', border: '#58400d', accent: '#f8e3a3' },
  { bg: '#674096', fg: '#ffffff', border: '#392257', accent: '#dec7f5' },
]

let settingsLoaded = false
let settingsRequest = null

function normalizeSettings(settings) {
  if (!Array.isArray(settings) || settings.length !== 10) {
    throw new Error(i18n.global.t('投稿等級設定必須正好包含 10 個等級'))
  }

  const names = new Set()
  let previousMinExp = null
  return settings.map((item, index) => {
    const level = item?.level
    const name = typeof item?.name === 'string' ? item.name.trim() : ''
    const nameEn = typeof item?.name_en === 'string' ? item.name_en.trim() : ''
    const minExp = item?.minExp ?? item?.min_exp
    if (!Number.isInteger(level) || level !== index + 1) {
      throw new Error(i18n.global.t('投稿等級必須依序為 Lv.1 至 Lv.10'))
    }
    if (!name || name.length > 30 || !/[^\s\p{Cf}]/u.test(name)) {
      throw new Error(i18n.global.t('Lv.{level} 名稱不可為空白，且不得超過 30 個字元', { level }))
    }
    if (names.has(name)) throw new Error(i18n.global.t('投稿等級名稱不可重複'))
    if (!Number.isInteger(minExp) || minExp < 0) {
      throw new Error(i18n.global.t('Lv.{level} 累積 EXP 必須是非負整數', { level }))
    }
    if (level === 1 && minExp !== 0) throw new Error(i18n.global.t('Lv.1 累積 EXP 必須為 0'))
    if (previousMinExp !== null && minExp <= previousMinExp) {
      throw new Error(i18n.global.t('Lv.2 至 Lv.10 累積 EXP 門檻必須嚴格遞增'))
    }
    names.add(name)
    previousMinExp = minExp
    return { level, name, name_en: nameEn || null, minExp }
  })
}

function replaceRuntimeSettings(settings) {
  const normalized = normalizeSettings(settings)
  SUBMISSION_LEVELS.splice(0, SUBMISSION_LEVELS.length, ...normalized)
  return getContributorLevelSettingsSnapshot()
}

export function validateContributorLevelSettings(settings) {
  return normalizeSettings(settings)
}

export function getContributorLevelSettingsSnapshot() {
  return SUBMISSION_LEVELS.map((level) => ({ ...level }))
}

export async function loadContributorLevelSettings({ force = false } = {}) {
  if (settingsLoaded && !force) return getContributorLevelSettingsSnapshot()
  if (settingsRequest) return settingsRequest

  settingsRequest = api
    .get('/settings/contributor-levels')
    .then(({ data }) => {
      const settings = replaceRuntimeSettings(data)
      settingsLoaded = true
      return settings
    })
    .catch(() => {
      settingsLoaded = true
      return getContributorLevelSettingsSnapshot()
    })
    .finally(() => {
      settingsRequest = null
    })
  return settingsRequest
}

export async function saveContributorLevelSettings(settings) {
  const normalized = normalizeSettings(settings)
  const payload = normalized.map(({ level, name, name_en: nameEn, minExp }) => ({
    level,
    name,
    name_en: nameEn || null,
    min_exp: minExp,
  }))
  const { data } = await api.put('/settings/contributor-levels', payload)
  settingsLoaded = true
  return replaceRuntimeSettings(data)
}

export function getContributorLevelPalette(level) {
  const index = Math.min(Math.max(Number(level) || 1, 1), CONTRIBUTOR_LEVEL_PALETTE.length) - 1
  return CONTRIBUTOR_LEVEL_PALETTE[index]
}

export function resolveSubmissionLevel(experience) {
  const currentExp = Math.max(0, Number(experience) || 0)
  const currentLevel = SUBMISSION_LEVELS.reduce(
    (matchedLevel, level) => (currentExp >= level.minExp ? level : matchedLevel),
    SUBMISSION_LEVELS[0]
  )
  const nextLevel = SUBMISSION_LEVELS[currentLevel.level]
  if (!nextLevel) {
    return {
      ...currentLevel,
      currentExp,
      isMaxLevel: true,
      progressInLevel: 1,
      progressRange: 1,
      progressPercent: 100,
      expToNextLevel: 0,
    }
  }
  const progressRange = nextLevel.minExp - currentLevel.minExp
  const progressInLevel = Math.max(0, currentExp - currentLevel.minExp)
  return {
    ...currentLevel,
    currentExp,
    isMaxLevel: false,
    progressInLevel,
    progressRange,
    progressPercent: Math.min(100, (progressInLevel / progressRange) * 100),
    expToNextLevel: Math.max(0, nextLevel.minExp - currentExp),
  }
}

export function localizedSubmissionLevelName(level) {
  if (!level) return ''
  if (i18n.global.locale.value === 'en') {
    return typeof level.name_en === 'string' && level.name_en.trim()
      ? level.name_en.trim()
      : level.name || ''
  }
  return level.name || ''
}

export function formatSubmissionLevelTitle(experience) {
  const level = resolveSubmissionLevel(experience)
  return `Lv.${level.level} ${localizedSubmissionLevelName(level)}`
}
