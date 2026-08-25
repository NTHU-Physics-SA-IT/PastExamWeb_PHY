import { api } from './client'

const BASE_PATH = '/homepage-slogans'

export const homepageSloganService = {
  getSelected() {
    return api.get(`${BASE_PATH}/selected`)
  },
  submit(content) {
    return api.post(BASE_PATH, { content })
  },
  listAdmin(params = {}) {
    return api.get(`${BASE_PATH}/admin`, { params })
  },
  getAdmin(id) {
    return api.get(`${BASE_PATH}/admin/${id}`)
  },
  updateAdmin(id, payload) {
    return api.patch(`${BASE_PATH}/admin/${id}`, payload)
  },
  removeAdmin(id) {
    return api.delete(`${BASE_PATH}/admin/${id}`)
  },
}
