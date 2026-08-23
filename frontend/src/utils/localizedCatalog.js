import { i18n } from '../i18n'
import { normalizeCourseSearchText } from './courseText'

const englishValue = (value) => (value == null ? '' : String(value).trim())

export const localizedCourseName = (course) => {
  if (!course) return ''
  return i18n.global.locale.value === 'en'
    ? englishValue(course.name_en) || course.name || ''
    : course.name || ''
}

export const localizedCategoryName = (category) => {
  if (!category) return ''
  return i18n.global.locale.value === 'en'
    ? englishValue(category.name_en) || category.name || ''
    : category.name || ''
}

export const localizedCategoryLabel = (category) => {
  if (!category) return ''
  if (i18n.global.locale.value === 'en') {
    return englishValue(category.label_en) || category.label || ''
  }
  return category.label || ''
}

export const localizedSubmissionCourseName = (submission) => {
  if (!submission) return ''
  const chinese =
    submission.requested_course_name || submission.course_name || submission.subject || ''
  if (i18n.global.locale.value !== 'en') return chinese
  return englishValue(submission.requested_course_name_en || submission.course_name_en) || chinese
}

export const localizedSubmissionCurrentCourseName = (submission) => {
  const current = submission?.current_archive
  if (!current) return ''
  if (i18n.global.locale.value !== 'en') return current.course_name || ''
  return englishValue(current.course_name_en) || current.course_name || ''
}

export const localizedCourseSnapshotName = (record) => {
  if (!record) return ''
  const chinese = record.course_name || ''
  if (i18n.global.locale.value !== 'en') return chinese
  return englishValue(record.course_name_en) || chinese
}

export const localizedSubmissionCategoryName = (submission) => {
  if (!submission) return ''
  const chinese = submission.requested_category_name || ''
  if (i18n.global.locale.value !== 'en') return chinese
  return englishValue(submission.requested_category_name_en) || chinese
}

export const localizedTrashDisplayName = (item) => {
  if (!item) return ''
  return i18n.global.locale.value === 'en'
    ? englishValue(item.display_name_en) || item.display_name || ''
    : item.display_name || ''
}

export const localizedTrashCourseName = (item) => {
  if (!item) return ''
  const chinese = item.requested_course_name || item.course_name || ''
  if (i18n.global.locale.value !== 'en') return chinese
  return englishValue(item.requested_course_name_en || item.course_name_en) || chinese
}

export const localizedTrashParentName = (item) => {
  if (!item) return ''
  if (i18n.global.locale.value !== 'en') return item.parent_name || ''
  return englishValue(item.parent_name_en) || item.parent_name || ''
}

export const courseMatchesSearch = (course, query) => {
  const normalizedQuery = normalizeCourseSearchText(query)
  if (!normalizedQuery) return true
  return [course?.name, course?.name_en].some((value) =>
    normalizeCourseSearchText(value).includes(normalizedQuery)
  )
}
