import { api } from './client'

const BASE_PATH = '/wishes'

export const wishService = {
  list(params = {}) {
    return api.get(BASE_PATH, { params })
  },
  create(payload) {
    return api.post(BASE_PATH, payload)
  },
  toggleHeart(id) {
    return api.post(`${BASE_PATH}/${id}/heart`)
  },
  remove(id) {
    return api.delete(`${BASE_PATH}/${id}`)
  },
  report(id, payload) {
    return api.post(`${BASE_PATH}/${id}/reports`, payload)
  },
  listReports(params = {}) {
    return api.get(`${BASE_PATH}/admin/reports`, { params })
  },
  getReport(id) {
    return api.get(`${BASE_PATH}/admin/reports/${id}`)
  },
  reviewReport(id, payload) {
    return api.patch(`${BASE_PATH}/admin/reports/${id}`, payload)
  },
  removeReport(id) {
    return api.delete(`${BASE_PATH}/admin/reports/${id}`)
  },
}
