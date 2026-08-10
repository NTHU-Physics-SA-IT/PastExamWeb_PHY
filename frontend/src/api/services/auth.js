import { api } from './client'

export const buildNthuLoginUrl = () => {
  const baseUrl = (api.defaults.baseURL || '/api').replace(/\/$/, '')
  return `${baseUrl}/auth/nthu/login`
}

export const authService = {
  login() {
    window.__pastexam?.openLoginModal?.()
  },

  async localLogin(username, password) {
    const formData = new FormData()
    formData.append('username', username)
    formData.append('password', password)

    const response = await api.post('/auth/login', formData)
    return response.data
  },

  nthuLogin() {
    window.location.assign(buildNthuLoginUrl())
  },

  async exchangeNthuCode(code) {
    const response = await api.post('/auth/nthu/exchange', { code })
    return response.data
  },

  async heartbeat() {
    return api.post('/auth/heartbeat')
  },

  logout() {
    return api.post('/auth/logout')
  },
}
