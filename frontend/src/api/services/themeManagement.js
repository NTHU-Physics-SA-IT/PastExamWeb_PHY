import { api } from './client'

export const themeManagementService = {
  getActive() {
    return api.get('/theme-management/active-theme')
  },
  getAdmin() {
    return api.get('/admin/theme-management')
  },
  activateAdmin(themeId) {
    return api.patch('/admin/theme-management/active-theme', { theme_id: themeId })
  },
  updateAdmin(themeId, payload) {
    return api.patch(`/admin/theme-management/themes/${themeId}`, payload)
  },
  removeAdmin(themeId) {
    return api.delete(`/admin/theme-management/themes/${themeId}`)
  },
}
