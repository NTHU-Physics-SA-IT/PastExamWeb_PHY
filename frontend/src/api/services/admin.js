import { api } from './client'

export const getCourses = () => {
  return api.get('/courses/admin/courses')
}

export const getAdminAttentionSummary = () => {
  return api.get('/admin/attention-summary')
}

export const createCourse = (courseData) => {
  return api.post('/courses/admin/courses', courseData)
}

export const updateCourse = (courseId, courseData) => {
  return api.put(`/courses/admin/courses/${courseId}`, courseData)
}

export const reorderCourses = (category, courseIds) => {
  return api.post('/courses/admin/courses/reorder', {
    category,
    course_ids: courseIds,
  })
}

export const deleteCourse = (courseId) => {
  return api.delete(`/courses/admin/courses/${courseId}`)
}
export const getUsers = () => {
  return api.get('/users/admin/users')
}

export const getNthuAccessPolicy = () => {
  return api.get('/settings/nthu-access-policy')
}

export const updateNthuAccessPolicy = (policy) => {
  return api.put('/settings/nthu-access-policy', policy)
}

export const getOnlineStatistics = (range) => {
  return api.get('/users/admin/online-statistics', { params: { range } })
}

export const getUserSubmissionStats = (userId, { includeRecords = false, signal } = {}) => {
  return api.get(`/users/admin/users/${userId}/submission-stats`, {
    signal,
    params: { include_records: includeRecords },
  })
}

export const getUserOnlineDuration = (userId, { mode = 'hourly', date, days = 7, signal } = {}) => {
  return api.get(`/users/admin/users/${userId}/online-duration`, {
    signal,
    params: {
      mode,
      ...(mode === 'hourly' ? { date } : { days }),
    },
  })
}

export const createUser = (userData) => {
  return api.post('/users/admin/users', userData)
}

export const updateUser = (userId, userData) => {
  return api.put(`/users/admin/users/${userId}`, userData)
}

export const deleteUser = (userId) => {
  return api.delete(`/users/admin/users/${userId}`)
}

export const resetUserPassword = (userId, payload) => {
  return api.post(`/users/admin/users/${userId}/reset-password`, payload)
}
