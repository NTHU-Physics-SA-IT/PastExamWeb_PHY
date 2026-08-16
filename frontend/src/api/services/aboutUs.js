import { api } from './client'

const BASE_PATH = '/about-us'

export const aboutUsService = {
  list() {
    return api.get(BASE_PATH)
  },
  create(payload) {
    return api.post(`${BASE_PATH}/admin/entries`, payload)
  },
  update(id, payload) {
    return api.put(`${BASE_PATH}/admin/entries/${id}`, payload)
  },
}
