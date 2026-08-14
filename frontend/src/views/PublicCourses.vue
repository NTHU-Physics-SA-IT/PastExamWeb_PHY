<template>
  <main class="public-catalog">
    <nav class="breadcrumbs" :aria-label="$t('麵包屑導覽')">
      <RouterLink to="/">{{ $t('首頁') }}</RouterLink>
      <span aria-hidden="true">/</span>
      <span>{{ $t('公開課程目錄') }}</span>
    </nav>

    <header class="catalog-header">
      <p class="eyebrow">PHY ARCHIVE</p>
      <h1>{{ $t('清大物理考古題課程目錄') }}</h1>
      <p>
        {{
          $t(
            '瀏覽清大物理相關課程；有公開考古題時，頁面會提供學年度、授課教師、考試類型與解答收錄狀況。完整 PDF 的預覽與下載仍需登入。'
          )
        }}
      </p>
    </header>

    <label class="catalog-search">
      <span>{{ $t('搜尋課程') }}</span>
      <input v-model="searchQuery" type="search" :placeholder="$t('輸入中文或英文課程名稱')" />
    </label>

    <p v-if="loading" class="status-message" aria-live="polite">{{ $t('正在載入課程資料……') }}</p>

    <section v-else-if="errorMessage" class="status-message error-message" role="alert">
      <h2>{{ $t('課程目錄暫時無法使用') }}</h2>
      <p>{{ errorMessage }}</p>
      <button type="button" class="retry-button" @click="loadCatalog">{{ $t('重新載入') }}</button>
    </section>

    <section v-else-if="sections.length === 0" class="empty-state">
      <h2>{{ searchQuery ? $t('找不到符合的課程') : $t('目前尚未有可公開瀏覽的課程') }}</h2>
      <p>
        {{
          searchQuery
            ? $t('請嘗試其他中文或英文關鍵字。')
            : $t('網站運作正常；有通過公開條件的考古題後，課程會顯示在這裡。')
        }}
      </p>
    </section>

    <div v-else class="category-list">
      <section v-for="section in sections" :key="section.key" class="category-section">
        <header class="category-header">
          <div>
            <p v-if="section.label" class="category-label">{{ section.label }}</p>
            <h2>{{ section.name }}</h2>
          </div>
          <span>{{ $t('{count} 門課程', { count: section.courses.length }) }}</span>
        </header>

        <div class="course-grid">
          <article v-for="course in section.courses" :key="course.id" class="course-card">
            <RouterLink
              class="course-card-link"
              :to="{ name: 'PublicCourse', params: { courseId: course.id } }"
            >
              <h3>{{ localizedCourseName(course) }}</h3>
              <i class="pi pi-arrow-right" aria-hidden="true"></i>
            </RouterLink>
          </article>
        </div>
      </section>
    </div>
  </main>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { courseService } from '../api'
import { SITE_URL, setSeo } from '../utils/seo'
import {
  courseMatchesSearch,
  localizedCategoryLabel,
  localizedCategoryName,
  localizedCourseName,
} from '../utils/localizedCatalog'

const { t } = useI18n()

const categories = ref([])
const coursesByCategory = ref({})
const loading = ref(true)
const errorMessage = ref('')
const searchQuery = ref('')

const sections = computed(() =>
  categories.value
    .map((category) => ({
      key: category.key,
      name: localizedCategoryName(category),
      label: localizedCategoryLabel(category),
      courses: (coursesByCategory.value[category.key] || []).filter((course) =>
        courseMatchesSearch(course, searchQuery.value)
      ),
    }))
    .filter((section) => section.courses.length > 0)
)

function applyCatalogSeo() {
  const courseItems = sections.value
    .flatMap((section) => section.courses)
    .map((course, index) => ({
      '@type': 'ListItem',
      position: index + 1,
      item: {
        '@type': 'Course',
        name: localizedCourseName(course),
        url: `${SITE_URL}/courses/${course.id}`,
        provider: { '@id': `${SITE_URL}/#organization` },
      },
    }))

  setSeo({
    title: t('清大物理考古題課程目錄'),
    description: t('瀏覽清大物理相關課程已公開收錄的歷屆考題資訊。'),
    canonicalPath: '/courses',
    robots: 'index, follow',
    jsonLd: [
      {
        '@type': 'CollectionPage',
        '@id': `${SITE_URL}/courses#page`,
        name: t('清大物理考古題課程目錄'),
        url: `${SITE_URL}/courses`,
        isPartOf: { '@id': `${SITE_URL}/#website` },
      },
      {
        '@type': 'BreadcrumbList',
        itemListElement: [
          { '@type': 'ListItem', position: 1, name: t('首頁'), item: `${SITE_URL}/` },
          {
            '@type': 'ListItem',
            position: 2,
            name: t('公開課程目錄'),
            item: `${SITE_URL}/courses`,
          },
        ],
      },
      {
        '@type': 'ItemList',
        name: t('公開考古題課程'),
        numberOfItems: courseItems.length,
        itemListElement: courseItems,
      },
    ],
  })
}

async function loadCatalog() {
  loading.value = true
  errorMessage.value = ''
  try {
    const [categoriesResponse, coursesResponse] = await Promise.all([
      courseService.listPublicCategories(),
      courseService.listPublicCourses(),
    ])
    categories.value = Array.isArray(categoriesResponse.data) ? categoriesResponse.data : []
    coursesByCategory.value =
      coursesResponse.data && typeof coursesResponse.data === 'object' ? coursesResponse.data : {}
    applyCatalogSeo()
  } catch (error) {
    console.error('Failed to load public course catalog:', error)
    categories.value = []
    coursesByCategory.value = {}
    errorMessage.value = t('目前無法讀取課程目錄，請稍後再試。')
    setSeo({
      title: t('課程目錄暫時無法使用'),
      canonicalPath: '/courses',
      robots: 'noindex, follow',
    })
  } finally {
    loading.value = false
  }
}

onMounted(loadCatalog)
</script>

<style scoped>
.public-catalog {
  width: min(1080px, calc(100% - 2rem));
  margin: 0 auto;
  padding: 2rem 0 4rem;
  color: var(--text-primary);
}

.breadcrumbs {
  display: flex;
  gap: 0.5rem;
  align-items: center;
  margin-bottom: 2rem;
  color: var(--text-secondary);
  font-size: 0.9rem;
}

.breadcrumbs a,
.course-card a {
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

.catalog-header {
  max-width: 720px;
  margin-bottom: 2rem;
}

.catalog-search {
  display: grid;
  gap: 0.45rem;
  max-width: 32rem;
  margin: 0 0 2rem;
  font-weight: 650;
}

.catalog-search input {
  min-width: 0;
  padding: 0.75rem 0.9rem;
  border: 1px solid var(--border-color);
  border-radius: 0.7rem;
  color: var(--text-primary);
  background: var(--bg-secondary);
  font: inherit;
}

.catalog-header h1 {
  margin: 0.35rem 0 0.85rem;
  font-size: clamp(1.6rem, 2.6vw, 2rem);
}

.catalog-header > p,
.empty-state p,
.error-message p {
  color: var(--text-secondary);
  line-height: 1.75;
}

.catalog-header > p {
  max-width: 68ch;
  margin: 0;
  text-wrap: pretty;
}

.eyebrow,
.category-label {
  margin: 0;
  color: var(--primary-color);
  font-size: 0.82rem;
  font-weight: 700;
  letter-spacing: 0.12em;
}

.category-list {
  display: grid;
  gap: 2.5rem;
}

.category-header {
  display: flex;
  gap: 1rem;
  align-items: end;
  justify-content: space-between;
  margin-bottom: 1rem;
}

.category-header h2 {
  margin: 0.25rem 0 0;
  font-size: 1.2rem;
}

.category-header > span {
  color: var(--text-secondary);
  font-size: 0.9rem;
}

.course-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 1rem;
}

.empty-state,
.error-message {
  padding: 1.25rem;
  border: 1px solid var(--border-color);
  border-radius: 1rem;
  background: var(--bg-secondary);
}

.course-card {
  border: 1px solid var(--border-color);
  border-radius: 0.8rem;
  background: var(--bg-secondary);
  overflow: hidden;
  transition:
    border-color 160ms ease,
    transform 160ms ease;
}

.course-card:hover {
  border-color: var(--primary-color);
  transform: translateY(-2px);
}

.course-card-link {
  display: flex;
  min-height: 4.75rem;
  padding: 1rem 1.15rem;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  text-decoration: none;
}

.course-card-link h3 {
  margin: 0;
  font-size: 1rem;
}

.course-card-link i {
  color: var(--primary-color);
  transition: transform 160ms ease;
}

.course-card-link:hover i {
  transform: translateX(0.2rem);
}

@media (prefers-reduced-motion: reduce) {
  .course-card,
  .course-card-link i {
    transition: none;
  }
}

.course-card h3,
.empty-state h2,
.error-message h2 {
  margin-top: 0;
}

.course-card p,
.empty-state p,
.error-message p {
  margin-bottom: 0;
}

.status-message {
  padding: 3rem 1rem;
  text-align: center;
}

.retry-button {
  margin-top: 1rem;
  padding: 0.65rem 1rem;
  border: 1px solid var(--surface-border);
  border-radius: 0.6rem;
  color: var(--text-primary);
  background: transparent;
  cursor: pointer;
}

.retry-button:focus-visible,
.course-card a:focus-visible,
.breadcrumbs a:focus-visible {
  outline: 2px solid var(--primary-color);
  outline-offset: 3px;
}

@media (max-width: 820px) {
  .public-catalog {
    width: min(100% - 56px, 1080px);
  }
}

@media (max-width: 560px) {
  .public-catalog {
    width: min(100% - 40px, 1080px);
    padding-top: 1.25rem;
  }

  .category-header {
    align-items: start;
    flex-direction: column;
  }
}
</style>
