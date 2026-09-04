export const FESTIVAL_THEME_PREVIEW_QUERY_KEY = 'festivalThemePreview'
export const FESTIVAL_THEME_PREVIEW_QUERY_VALUE = '1'

export function isFestivalThemePreviewEnabled({
  isDev = import.meta.env.DEV,
  search = typeof window === 'undefined' ? '' : window.location.search,
} = {}) {
  if (!isDev) return false
  return (
    new URLSearchParams(search).get(FESTIVAL_THEME_PREVIEW_QUERY_KEY) ===
    FESTIVAL_THEME_PREVIEW_QUERY_VALUE
  )
}

export function createFestivalThemePreviewRows() {
  return [
    {
      id: 'preview-christmas',
      name: '聖誕節主題',
      name_en: 'Christmas Theme',
      description: '冬季節慶視覺主題',
      description_en: 'A winter holiday visual theme.',
      supports_color_modes: true,
      starts_at: '2026-12-20T00:00:00Z',
      ends_at: '2026-12-27T00:00:00Z',
      preview_only: true,
    },
    {
      id: 'preview-spring-festival',
      name: '春節主題',
      name_en: 'Spring Festival Theme',
      description: '農曆新年節慶視覺主題',
      description_en: 'A Lunar New Year visual theme.',
      supports_color_modes: false,
      starts_at: '2027-02-05T00:00:00Z',
      ends_at: '2027-02-12T00:00:00Z',
      preview_only: true,
    },
  ]
}
