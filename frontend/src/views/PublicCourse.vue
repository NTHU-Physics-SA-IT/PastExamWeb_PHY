<template>
  <main class="public-course">
    <nav class="breadcrumbs" aria-label="麵包屑導覽">
      <RouterLink to="/">首頁</RouterLink>
      <span aria-hidden="true">/</span>
      <RouterLink to="/courses">課程目錄</RouterLink>
      <span v-if="course" aria-hidden="true">/</span>
      <span v-if="course">{{ course.name }}</span>
    </nav>

    <p v-if="loading" class="status-message">
      正在載入課程資料……
    </p>

    <section
      v-else-if="errorMessage"
      class="status-message error-message"
      role="alert"
    >
      <h1>找不到課程</h1>
      <p>{{ errorMessage }}</p>
      <RouterLink to="/courses">
        返回課程目錄
      </RouterLink>
    </section>

    <template v-else-if="course">
      <header class="course-header">
        <p v-if="category" class="eyebrow">
          {{ category.name }}
        </p>

        <h1>{{ course.name }}考古題</h1>

        <p>
          清大物理系 {{ course.name }} 歷屆考題整理。
          本頁公開顯示收錄學期、授課教師、考試類型與
          是否附解答；完整文件需登入後依網站權限使用。
        </p>

        <div class="course-summary">
          <span>共 {{ archives.length }} 份考古題</span>
          <span v-if="latestAcademicTerm">
            最新：{{ latestAcademicTerm }}
          </span>
          <span v-if="professorCount">
            {{ professorCount }} 位授課教師
          </span>
        </div>
      </header>

      <section
        v-if="groupedArchives.length"
        class="archive-groups"
      >
        <section
          v-for="group in groupedArchives"
          :key="group.year"
          class="archive-group"
        >
          <header class="group-header">
            <h2>{{ formatAcademicTerm(group.year) }}</h2>
            <span>{{ group.items.length }} 份</span>
          </header>

          <div class="archive-grid">
            <article
              v-for="archive in group.items"
              :key="archive.id"
              class="archive-card"
            >
              <div class="archive-title-row">
                <span class="archive-type">
                  {{
                    archiveTypeLabels[
                      archive.archive_type
                    ] || archive.archive_type
                  }}
                </span>
                <h3>{{ archive.name }}</h3>
              </div>

              <dl>
                <div>
                  <dt>授課教師</dt>
                  <dd>
                    {{ archive.professor || '未提供' }}
                  </dd>
                </div>
                <div>
                  <dt>解答</dt>
                  <dd>
                    {{
                      archive.has_answers
                        ? '附解答'
                        : '未附解答'
                    }}
                  </dd>
                </div>
              </dl>
            </article>
          </div>
        </section>
      </section>

      <section v-else class="empty-state">
        <h2>目前尚未收錄公開考古題</h2>
        <p>
          此課程尚未有可公開列出的考古題資料。
        </p>
      </section>

      <section class="login-notice">
        <h2>預覽或下載完整文件</h2>
        <p>
          為維持使用與權限管理，完整 PDF 預覽及下載
          仍需登入清大物理考古系統。
        </p>
        <RouterLink to="/" class="login-link">
          前往登入
        </RouterLink>
      </section>
    </template>
  </main>
</template>

<script setup>
import {
  computed,
  onMounted,
  ref,
  watch,
} from 'vue'
import { useRoute } from 'vue-router'

import { courseService } from '../api'
import { SITE_URL, setSeo } from '../utils/seo'

const route = useRoute()

const course = ref(null)
const category = ref(null)
const archives = ref([])
const loading = ref(true)
const errorMessage = ref('')

const archiveTypeLabels = {
  quiz: '小考',
  midterm: '期中考',
  final: '期末考',
  other: '其他',
}

const groupedArchives = computed(() => {
  const groups = new Map()

  for (const archive of archives.value) {
    const year = archive.academic_year

    if (!groups.has(year)) {
      groups.set(year, [])
    }

    groups.get(year).push(archive)
  }

  return Array.from(groups.entries())
    .sort(([yearA], [yearB]) => yearB - yearA)
    .map(([year, items]) => ({
      year,
      items,
    }))
})

const latestAcademicTerm = computed(() => {
  const latestYear = archives.value
    .map((archive) => archive.academic_year)
    .filter(Boolean)
    .sort((a, b) => b - a)[0]

  return latestYear
    ? formatAcademicTerm(latestYear)
    : ''
})

const professorCount = computed(() => {
  return new Set(
    archives.value
      .map((archive) => archive.professor?.trim())
      .filter(Boolean)
  ).size
})

function formatAcademicTerm(value) {
  const numericValue = Number(value)

  if (!numericValue) return ''

  if (numericValue >= 1000 && numericValue < 2000) {
    const year = Math.floor(numericValue / 10)
    const semester = numericValue % 10

    return `${year}${semester === 1 ? '上' : '下'}學期`
  }

  return `${numericValue} 年`
}

function findCourse(
  courseId,
  categories,
  coursesByCategory
) {
  for (const categoryItem of categories) {
    const categoryCourses =
      coursesByCategory[categoryItem.key] || []

    const matchedCourse = categoryCourses.find(
      (item) => Number(item.id) === courseId
    )

    if (matchedCourse) {
      return {
        course: matchedCourse,
        category: categoryItem,
      }
    }
  }

  return {
    course: null,
    category: null,
  }
}

function applyCourseSeo() {
  if (!course.value) {
    setSeo({
      title: '找不到課程｜PhysArchive',
      canonicalPath: route.path,
      robots: 'noindex, nofollow',
    })
    return
  }

  const courseUrl = `${SITE_URL}/courses/${course.value.id}`
  const count = archives.value.length

  const description = count
    ? `清大物理系${course.value.name}考古題整理，共收錄 ${count} 份歷屆考題，可查看學期、授課教師、考試類型與是否附解答。`
    : `清大物理系${course.value.name}考古題資訊，目前尚未收錄可公開列出的歷屆考題。`

  const itemList = archives.value.map(
    (archive, index) => ({
      '@type': 'ListItem',
      position: index + 1,
      item: {
        '@type': 'CreativeWork',
        name: [
          course.value.name,
          formatAcademicTerm(
            archive.academic_year
          ),
          archiveTypeLabels[
            archive.archive_type
          ] || archive.archive_type,
          archive.name,
        ]
          .filter(Boolean)
          .join(' '),
        inLanguage: 'zh-TW',
      },
    })
  )

  setSeo({
    title:
      `清大${course.value.name}考古題｜` +
      '歷屆考題與解答｜PhysArchive',
    description,
    canonicalPath: `/courses/${course.value.id}`,
    robots:
      count > 0
        ? 'index, follow'
        : 'noindex, follow',
    jsonLd: [
      {
        '@type': 'CollectionPage',
        '@id': `${courseUrl}#page`,
        name: `${course.value.name}考古題`,
        url: courseUrl,
        description,
        isPartOf: {
          '@id': `${SITE_URL}/#website`,
        },
      },
      {
        '@type': 'BreadcrumbList',
        itemListElement: [
          {
            '@type': 'ListItem',
            position: 1,
            name: '首頁',
            item: `${SITE_URL}/`,
          },
          {
            '@type': 'ListItem',
            position: 2,
            name: '課程目錄',
            item: `${SITE_URL}/courses`,
          },
          {
            '@type': 'ListItem',
            position: 3,
            name: course.value.name,
            item: courseUrl,
          },
        ],
      },
      {
        '@type': 'ItemList',
        name: `${course.value.name}歷屆考題`,
        numberOfItems: itemList.length,
        itemListElement: itemList,
      },
    ],
  })
}

async function fetchCourse() {
  loading.value = true
  errorMessage.value = ''

  const courseId = Number(route.params.courseId)

  if (!Number.isInteger(courseId) || courseId <= 0) {
    course.value = null
    errorMessage.value = '課程編號格式不正確。'
    loading.value = false
    applyCourseSeo()
    return
  }

  try {
    const [
      categoriesResponse,
      coursesResponse,
      archivesResponse,
    ] = await Promise.all([
      courseService.listPublicCategories(),
      courseService.listPublicCourses(),
      courseService.getPublicCourseArchives(
        courseId
      ),
    ])

    const categories = Array.isArray(
      categoriesResponse.data
    )
      ? categoriesResponse.data
      : []

    const coursesByCategory =
      coursesResponse.data &&
      typeof coursesResponse.data === 'object'
        ? coursesResponse.data
        : {}

    const matched = findCourse(
      courseId,
      categories,
      coursesByCategory
    )

    if (!matched.course) {
      throw new Error('Course not found')
    }

    course.value = matched.course
    category.value = matched.category
    archives.value = Array.isArray(
      archivesResponse.data
    )
      ? archivesResponse.data
      : []

    applyCourseSeo()
  } catch (error) {
    console.error(
      'Failed to load public course:',
      error
    )

    course.value = null
    category.value = null
    archives.value = []
    errorMessage.value =
      '這門課程不存在，或目前無法讀取課程資料。'

    applyCourseSeo()
  } finally {
    loading.value = false
  }
}

onMounted(fetchCourse)

watch(
  () => route.params.courseId,
  () => {
    fetchCourse()
  }
)
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
  gap: 0.5rem;
  margin-bottom: 2rem;
  color: var(--text-secondary);
  font-size: 0.9rem;
}

.breadcrumbs a {
  color: inherit;
}

.course-header {
  max-width: 780px;
  margin-bottom: 2.5rem;
}

.course-header h1 {
  margin: 0.35rem 0 1rem;
  font-size: clamp(2rem, 5vw, 3.5rem);
}

.course-header > p {
  color: var(--text-secondary);
  line-height: 1.8;
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
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 1rem;
}

.group-header h2 {
  margin: 0;
}

.group-header span {
  color: var(--text-secondary);
}

.archive-grid {
  display: grid;
  gap: 1rem;
}

.archive-card {
  padding: 1.25rem;
  border: 1px solid var(--surface-border);
  border-radius: 1rem;
  background: var(--surface-card);
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
  background: var(--surface-100);
  color: var(--text-secondary);
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
  color: var(--text-secondary);
  font-size: 0.8rem;
}

.archive-card dd {
  margin: 0;
}

.login-notice,
.empty-state {
  margin-top: 3rem;
  padding: 1.5rem;
  border: 1px solid var(--surface-border);
  border-radius: 1rem;
  background: var(--surface-card);
}

.login-notice p,
.empty-state p {
  color: var(--text-secondary);
  line-height: 1.7;
}

.login-link {
  display: inline-flex;
  margin-top: 0.5rem;
  font-weight: 700;
}

.status-message {
  padding: 3rem 1rem;
  text-align: center;
}

.error-message {
  color: var(--text-secondary);
}
</style>