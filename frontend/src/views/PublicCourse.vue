<template>
  <main
    class="public-course"
    :class="{ 'public-course-christmas': effectiveTheme === 'christmas' }"
  >
    <nav class="breadcrumbs" :aria-label="$t('麵包屑導覽')">
      <RouterLink to="/">{{ $t('首頁') }}</RouterLink>
      <span aria-hidden="true">/</span>
      <RouterLink to="/courses">{{ $t('公開課程目錄') }}</RouterLink>
      <template v-if="course">
        <span aria-hidden="true">/</span>
        <span>{{ courseName }}</span>
      </template>
    </nav>

    <p v-if="loading" class="status-message" aria-live="polite">{{ $t('正在載入課程資料……') }}</p>

    <section v-else-if="errorMessage" class="status-message error-message" role="alert">
      <h1>{{ $t('找不到公開課程') }}</h1>
      <p>{{ errorMessage }}</p>
      <RouterLink to="/courses">{{ $t('返回公開課程目錄') }}</RouterLink>
    </section>

    <template v-else-if="course">
      <header class="course-header">
        <p v-if="category" class="eyebrow">{{ categoryName }}</p>
        <h1>{{ $t('{course}考古題', { course: courseName }) }}</h1>
        <p>
          {{
            $t(
              '本頁公開顯示這門課程已收錄考古題的學年度、授課教師、考試類型與是否附解答。完整 PDF 仍需登入後依網站權限使用。'
            )
          }}
        </p>
        <div class="course-summary" :aria-label="$t('課程收錄摘要')">
          <span>{{ $t('共 {count} 份', { count: archives.length }) }}</span>
          <span v-if="latestAcademicYear">{{
            $t('最新：{year}', { year: latestAcademicYear })
          }}</span>
          <span v-if="professorCount">{{
            $t('{count} 位授課教師', { count: professorCount })
          }}</span>
        </div>
      </header>

      <section v-if="archives.length === 0" class="empty-state">
        <h2>{{ $t('目前尚未有可公開瀏覽的考古題') }}</h2>
        <p>{{ $t('這門課程目前尚未收錄可公開顯示的考古題中繼資料。') }}</p>
      </section>

      <section v-else class="archive-groups" :aria-label="$t('公開考古題中繼資料')">
        <section v-for="group in groupedArchives" :key="group.year" class="archive-group">
          <header class="group-header">
            <h2>{{ formatAcademicYear(group.year) }}</h2>
            <span>{{ $t('共 {count} 份', { count: group.items.length }) }}</span>
          </header>

          <div class="archive-grid">
            <article v-for="archive in group.items" :key="archive.id" class="archive-card">
              <div class="archive-title-row">
                <span class="archive-type">
                  {{ archiveTypeLabels[archive.archive_type] || archive.archive_type }}
                </span>
                <h3>{{ archive.name }}</h3>
              </div>
              <dl>
                <div>
                  <dt>{{ $t('授課教師') }}</dt>
                  <dd>{{ archive.professor || $t('未提供') }}</dd>
                </div>
                <div>
                  <dt>{{ $t('解答') }}</dt>
                  <dd>{{ archive.has_answers ? $t('附解答') : $t('未附解答') }}</dd>
                </div>
              </dl>
            </article>
          </div>
        </section>
      </section>
    </template>
  </main>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'

import { courseService } from '../api'
import { SITE_URL, setSeo } from '../utils/seo'
import { localizedCategoryName, localizedCourseName } from '../utils/localizedCatalog'
import { formatAcademicTerm } from '../utils/academicTerm'
import { useTheme } from '../utils/useTheme'

const route = useRoute()
const { t, locale } = useI18n()
const { effectiveTheme } = useTheme()
const course = ref(null)
const category = ref(null)
const archives = ref([])
const loading = ref(true)
const errorMessage = ref('')

const archiveTypeLabels = computed(() => ({
  quiz: t('小考'),
  midterm: t('期中考'),
  final: t('期末考'),
  other: t('其他'),
}))

const courseName = computed(() => localizedCourseName(course.value))
const categoryName = computed(() => localizedCategoryName(category.value))

const groupedArchives = computed(() => {
  const groups = new Map()
  for (const archive of archives.value) {
    const year = archive.academic_year
    if (!groups.has(year)) groups.set(year, [])
    groups.get(year).push(archive)
  }
  return Array.from(groups.entries())
    .sort(([yearA], [yearB]) => Number(yearB) - Number(yearA))
    .map(([year, items]) => ({ year, items }))
})

const latestAcademicYear = computed(() =>
  groupedArchives.value.length ? formatAcademicYear(groupedArchives.value[0].year) : ''
)

const professorCount = computed(
  () => new Set(archives.value.map((archive) => archive.professor?.trim()).filter(Boolean)).size
)

function formatAcademicYear(value) {
  return formatAcademicTerm(value, t) || t('{year} 學年度', { year: value })
}

function findCourse(courseId, categories, coursesByCategory) {
  for (const categoryItem of categories) {
    const matchedCourse = (coursesByCategory[categoryItem.key] || []).find(
      (item) => Number(item.id) === courseId
    )
    if (matchedCourse) return { course: matchedCourse, category: categoryItem }
  }
  return { course: null, category: null }
}

function applyMissingSeo() {
  setSeo({
    title: t('找不到公開課程'),
    canonicalPath: route.path,
    robots: 'noindex, nofollow',
  })
}

function applyCourseSeo() {
  const courseUrl = `${SITE_URL}/courses/${course.value.id}`
  const hasPublicArchives = archives.value.length > 0
  const description = hasPublicArchives
    ? t('公開課程 SEO 有資料', { course: courseName.value, count: archives.value.length })
    : t('公開課程 SEO 無資料', { course: courseName.value })
  const archiveItems = archives.value.map((archive, index) => ({
    '@type': 'ListItem',
    position: index + 1,
    name: [
      formatAcademicYear(archive.academic_year),
      archiveTypeLabels.value[archive.archive_type] || archive.archive_type,
      archive.name,
    ]
      .filter(Boolean)
      .join(' '),
  }))

  const collectionPage = {
    '@type': 'CollectionPage',
    '@id': `${courseUrl}#page`,
    name: t('{course}考古題', { course: courseName.value }),
    url: courseUrl,
    description,
    isPartOf: { '@id': `${SITE_URL}/#website` },
  }
  const breadcrumbList = {
    '@type': 'BreadcrumbList',
    itemListElement: [
      { '@type': 'ListItem', position: 1, name: t('首頁'), item: `${SITE_URL}/` },
      {
        '@type': 'ListItem',
        position: 2,
        name: t('公開課程目錄'),
        item: `${SITE_URL}/courses`,
      },
      { '@type': 'ListItem', position: 3, name: courseName.value, item: courseUrl },
    ],
  }
  const jsonLd = [collectionPage, breadcrumbList]

  if (hasPublicArchives) {
    collectionPage.mainEntity = { '@id': `${courseUrl}#course` }
    jsonLd.splice(
      1,
      0,
      {
        '@type': 'Course',
        '@id': `${courseUrl}#course`,
        name: courseName.value,
        url: courseUrl,
        provider: { '@id': `${SITE_URL}/#organization` },
      },
      {
        '@type': 'ItemList',
        name: t('課程公開考古題中繼資料', { course: courseName.value }),
        numberOfItems: archiveItems.length,
        itemListElement: archiveItems,
      }
    )
  }

  setSeo({
    title: t('公開課程 SEO 標題', { course: courseName.value }),
    description,
    canonicalPath: `/courses/${course.value.id}`,
    robots: hasPublicArchives ? 'index, follow' : 'noindex, follow',
    jsonLd,
  })
}

async function loadCourse() {
  loading.value = true
  errorMessage.value = ''
  course.value = null
  category.value = null
  archives.value = []

  const courseId = Number(route.params.courseId)
  if (!Number.isInteger(courseId) || courseId <= 0) {
    errorMessage.value = t('課程編號格式不正確。')
    loading.value = false
    applyMissingSeo()
    return
  }

  try {
    const [categoriesResponse, coursesResponse, archivesResponse] = await Promise.all([
      courseService.listPublicCategories(),
      courseService.listPublicCourses(),
      courseService.getPublicCourseArchives(courseId),
    ])
    const categories = Array.isArray(categoriesResponse.data) ? categoriesResponse.data : []
    const coursesByCategory =
      coursesResponse.data && typeof coursesResponse.data === 'object' ? coursesResponse.data : {}
    const matched = findCourse(courseId, categories, coursesByCategory)
    const publicArchives = Array.isArray(archivesResponse.data) ? archivesResponse.data : []
    if (!matched.course) throw new Error('Course not public')

    course.value = matched.course
    category.value = matched.category
    archives.value = publicArchives
    applyCourseSeo()
  } catch (error) {
    console.error('Failed to load public course:', error)
    errorMessage.value = t('這門課程不存在或目前無法載入。')
    applyMissingSeo()
  } finally {
    loading.value = false
  }
}

onMounted(loadCourse)
watch(() => route.params.courseId, loadCourse)
watch(locale, () => {
  if (course.value) applyCourseSeo()
  else if (errorMessage.value) applyMissingSeo()
})
</script>

<style scoped>
.public-course {
  width: min(980px, calc(100% - 2rem));
  margin: 0 auto;
  padding: 2rem 0 4rem;
  color: var(--text-primary);
}

.breadcrumbs {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 2rem;
  color: var(--text-secondary);
  font-size: 0.9rem;
}

.breadcrumbs a,
.error-message a {
  color: inherit;
}

.breadcrumbs a {
  display: inline-flex;
  min-height: 2rem;
  align-items: center;
  padding: 0;
  text-decoration: none;
  transition: color 160ms ease;
}

.breadcrumbs > span {
  display: inline-flex;
  min-height: 2rem;
  align-items: center;
  line-height: 1.25;
}

.breadcrumbs a:hover {
  color: var(--primary-color);
}

.course-header {
  max-width: 780px;
  margin-bottom: 2.5rem;
}

.course-header h1 {
  margin: 0.35rem 0 1rem;
  font-size: clamp(1.7rem, 3vw, 2.25rem);
  font-weight: 700;
}

.course-header > p,
.error-message p {
  color: var(--text-secondary);
  line-height: 1.75;
}

.course-header > p {
  max-width: 68ch;
  margin: 0;
  text-wrap: pretty;
}

.eyebrow {
  color: var(--primary-color);
  font-weight: 700;
  letter-spacing: 0.08em;
}

.course-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem 1.5rem;
  margin-top: 1.5rem;
  font-weight: 600;
}

.archive-groups {
  display: grid;
  gap: 2.5rem;
}

.group-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 1rem;
}

.group-header h2 {
  margin: 0;
}

.group-header span,
.archive-card dt {
  color: var(--text-secondary);
}

.archive-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: 1rem;
}

.archive-card,
.empty-state,
.error-message {
  padding: 1.25rem;
  border: 1px solid var(--border-color);
  border-radius: 1rem;
  background: var(--bg-secondary);
}

.archive-title-row {
  display: flex;
  gap: 0.75rem;
  align-items: center;
}

.archive-title-row h3 {
  margin: 0;
}

.archive-type {
  flex: 0 0 auto;
  padding: 0.25rem 0.55rem;
  border-radius: 999px;
  color: var(--text-secondary);
  background: var(--surface-100);
  font-size: 0.8rem;
}

.archive-card dl {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem 2rem;
  margin: 1rem 0 0;
}

.archive-card dl div {
  display: grid;
  gap: 0.2rem;
}

.archive-card dt {
  font-size: 0.8rem;
}

.archive-card dd {
  margin: 0;
}

.empty-state h2,
.error-message h1 {
  margin-top: 0;
}

.status-message {
  padding: 3rem 1rem;
  text-align: center;
}

.empty-state p {
  margin-bottom: 0;
  color: var(--text-secondary);
  line-height: 1.75;
}

.breadcrumbs a:focus-visible,
.error-message a:focus-visible {
  outline: 2px solid var(--primary-color);
  outline-offset: 3px;
}

@media (max-width: 820px) {
  .public-course {
    width: min(100% - 56px, 980px);
  }
}

@media (max-width: 560px) {
  .public-course {
    width: min(100% - 40px, 980px);
    padding-top: 1.25rem;
  }

  .archive-title-row {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
