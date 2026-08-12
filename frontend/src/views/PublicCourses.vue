<template>
  <main class="public-catalog">
    <nav class="breadcrumbs" aria-label="麵包屑導覽">
      <RouterLink to="/">首頁</RouterLink>
      <span aria-hidden="true">/</span>
      <span>公開課程目錄</span>
    </nav>

    <header class="catalog-header">
      <p class="eyebrow">PHY ARCHIVE</p>
      <h1>清大物理考古題課程目錄</h1>
      <p>
        瀏覽清大物理相關課程；有公開考古題時，頁面會提供學年度、授課教師、
        考試類型與解答收錄狀況。完整 PDF 的預覽與下載仍需登入。
      </p>
    </header>

    <p v-if="loading" class="status-message" aria-live="polite">正在載入課程資料……</p>

    <section v-else-if="errorMessage" class="status-message error-message" role="alert">
      <h2>課程目錄暫時無法使用</h2>
      <p>{{ errorMessage }}</p>
      <button type="button" class="retry-button" @click="loadCatalog">重新載入</button>
    </section>

    <section v-else-if="sections.length === 0" class="empty-state">
      <h2>目前尚未有可公開瀏覽的課程</h2>
      <p>網站運作正常；有通過公開條件的考古題後，課程會顯示在這裡。</p>
    </section>

    <div v-else class="category-list">
      <section v-for="section in sections" :key="section.key" class="category-section">
        <header class="category-header">
          <div>
            <p v-if="section.label" class="category-label">{{ section.label }}</p>
            <h2>{{ section.name }}</h2>
          </div>
          <span>{{ section.courses.length }} 門課程</span>
        </header>

        <div class="course-grid">
          <article v-for="course in section.courses" :key="course.id" class="course-card">
            <h3>
              <RouterLink :to="{ name: 'PublicCourse', params: { courseId: course.id } }">
                {{ course.name }}考古題
              </RouterLink>
            </h3>
            <p>查看課程資訊，以及已公開收錄的學年度、授課教師、考試類型與解答資訊。</p>
          </article>
        </div>
      </section>
    </div>

    <aside class="access-note" aria-label="檔案存取說明">
      <h2>公開頁面不提供檔案下載</h2>
      <p>課程與考古題中繼資料可匿名瀏覽；完整文件仍受網站登入與權限保護。</p>
    </aside>
  </main>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'

import { courseService } from '../api'
import { SITE_URL, setSeo } from '../utils/seo'

const categories = ref([])
const coursesByCategory = ref({})
const loading = ref(true)
const errorMessage = ref('')

const sections = computed(() =>
  categories.value
    .map((category) => ({
      key: category.key,
      name: category.name,
      label: category.label,
      courses: coursesByCategory.value[category.key] || [],
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
        name: course.name,
        url: `${SITE_URL}/courses/${course.id}`,
        provider: { '@id': `${SITE_URL}/#organization` },
      },
    }))

  setSeo({
    title: '清大物理考古題課程目錄',
    description: '瀏覽清大物理相關課程已公開收錄的歷屆考題資訊。',
    canonicalPath: '/courses',
    robots: 'index, follow',
    jsonLd: [
      {
        '@type': 'CollectionPage',
        '@id': `${SITE_URL}/courses#page`,
        name: '清大物理考古題課程目錄',
        url: `${SITE_URL}/courses`,
        isPartOf: { '@id': `${SITE_URL}/#website` },
      },
      {
        '@type': 'BreadcrumbList',
        itemListElement: [
          { '@type': 'ListItem', position: 1, name: '首頁', item: `${SITE_URL}/` },
          {
            '@type': 'ListItem',
            position: 2,
            name: '公開課程目錄',
            item: `${SITE_URL}/courses`,
          },
        ],
      },
      {
        '@type': 'ItemList',
        name: '公開考古題課程',
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
    errorMessage.value = '目前無法讀取課程目錄，請稍後再試。'
    setSeo({
      title: '課程目錄暫時無法使用',
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

.catalog-header {
  max-width: 760px;
  margin-bottom: 2.5rem;
}

.catalog-header h1 {
  margin: 0.35rem 0 1rem;
  font-size: clamp(2rem, 5vw, 3.4rem);
}

.catalog-header > p,
.course-card p,
.access-note p,
.empty-state p,
.error-message p {
  color: var(--text-secondary);
  line-height: 1.75;
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

.course-card,
.access-note,
.empty-state,
.error-message {
  padding: 1.25rem;
  border: 1px solid var(--surface-border);
  border-radius: 1rem;
  background: var(--surface-card);
}

.course-card h3,
.access-note h2,
.empty-state h2,
.error-message h2 {
  margin-top: 0;
}

.course-card p,
.access-note p,
.empty-state p,
.error-message p {
  margin-bottom: 0;
}

.access-note {
  margin-top: 3rem;
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

@media (max-width: 560px) {
  .public-catalog {
    width: min(100% - 1.25rem, 1080px);
    padding-top: 1.25rem;
  }

  .category-header {
    align-items: start;
    flex-direction: column;
  }
}
</style>
