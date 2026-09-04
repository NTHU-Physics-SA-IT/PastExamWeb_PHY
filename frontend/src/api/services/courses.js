import { api } from './client'

export const courseService = {
  listPublicCourses(search = '') {
    return api.get('/courses/public', { params: search.trim() ? { search: search.trim() } : {} })
  },

  listPublicCategories() {
    return api.get('/courses/public/categories')
  },

  getPublicCourseArchives(courseId) {
    return api.get(`/courses/public/${courseId}/archives`)
  },

  listCourses(search = '') {
    return api.get('/courses', { params: search.trim() ? { search: search.trim() } : {} })
  },

  listCategories() {
    return api.get('/courses/categories')
  },

  getCourseArchives(courseId, { includeOwnerPending = false } = {}) {
    if (!includeOwnerPending) return api.get(`/courses/${courseId}/archives`)
    return api.get(`/courses/${courseId}/archives`, {
      params: { include_owner_pending: true },
    })
  },

  getAllCourses() {
    return api.get('/courses/admin/courses')
  },

  createCourse(courseData) {
    return api.post('/courses/admin/courses', courseData)
  },

  updateCourse(courseId, courseData) {
    return api.put(`/courses/admin/courses/${courseId}`, courseData)
  },

  reorderCourses(category, courseIds) {
    return api.post('/courses/admin/courses/reorder', {
      category,
      course_ids: courseIds,
    })
  },

  deleteCourse(courseId) {
    return api.delete(`/courses/admin/courses/${courseId}`)
  },

  listAdminCategories() {
    return api.get('/courses/admin/categories')
  },

  createCategory(categoryData) {
    return api.post('/courses/admin/categories', categoryData)
  },

  updateCategory(categoryId, categoryData) {
    return api.put(`/courses/admin/categories/${categoryId}`, categoryData)
  },

  setCategoryActive(categoryId, isActive) {
    return api.put(`/courses/admin/categories/${categoryId}`, { is_active: isActive })
  },

  reorderCategories(categoryIds) {
    return api.post('/courses/admin/categories/reorder', {
      category_ids: categoryIds,
    })
  },

  deleteCategory(categoryId) {
    return api.delete(`/courses/admin/categories/${categoryId}`)
  },

  requestCourse(courseData) {
    return api.post('/courses/requests', courseData)
  },

  listMyRequests() {
    return api.get('/courses/requests/me')
  },

  listAdminRequests() {
    return api.get('/courses/admin/requests')
  },

  approveRequest(requestId, note = '') {
    return api.post(`/courses/admin/requests/${requestId}/approve`, { note })
  },

  rejectRequest(requestId, note = '') {
    return api.post(`/courses/admin/requests/${requestId}/reject`, { note })
  },

  updateRequest(requestId, requestData) {
    return api.put(`/courses/admin/requests/${requestId}`, requestData)
  },
}
