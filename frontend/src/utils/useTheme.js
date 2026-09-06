import { computed, ref, watch } from 'vue'
import { STORAGE_KEYS, getLocalItem, setLocalItem } from './storage'

const GENERAL_THEME_ID = 'general'

const initialThemeIsDark = (() => {
  const raw = getLocalItem(STORAGE_KEYS.local.THEME_PREFERENCE)
  return raw ? raw === 'dark' : true
})()
const isDarkTheme = ref(initialThemeIsDark)
const activeSiteTheme = ref(GENERAL_THEME_ID)
const effectiveTheme = computed(() =>
  activeSiteTheme.value !== GENERAL_THEME_ID
    ? activeSiteTheme.value
    : isDarkTheme.value
      ? 'dark'
      : 'light'
)

function applyActiveSiteTheme(themeId) {
  activeSiteTheme.value =
    typeof themeId === 'string' && themeId !== GENERAL_THEME_ID ? themeId : GENERAL_THEME_ID
}

async function refreshActiveSiteTheme() {
  try {
    const { themeManagementService } = await import('@/api/services/themeManagement')
    const response = await themeManagementService.getActive()
    applyActiveSiteTheme(response?.data?.active_theme)
  } catch {
    applyActiveSiteTheme(GENERAL_THEME_ID)
  }
  return activeSiteTheme.value
}

watch(
  effectiveTheme,
  (theme) => {
    document.documentElement.classList.toggle('dark', theme === 'dark')
    document.documentElement.dataset.effectiveTheme = theme
  },
  { immediate: true }
)

export function useTheme() {
  const toggleTheme = () => {
    isDarkTheme.value = !isDarkTheme.value
    setLocalItem(STORAGE_KEYS.local.THEME_PREFERENCE, isDarkTheme.value ? 'dark' : 'light')
  }

  return {
    isDarkTheme,
    activeSiteTheme,
    effectiveTheme,
    toggleTheme,
    applyActiveSiteTheme,
    refreshActiveSiteTheme,
  }
}
