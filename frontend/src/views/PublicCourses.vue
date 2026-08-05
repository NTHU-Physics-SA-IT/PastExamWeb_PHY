<template>
  <main class="public-catalog">
    <nav class="breadcrumbs" aria-label="麵包屑導覽">
      <RouterLink to="/">首頁</RouterLink>
      <span aria-hidden="true">/</span>
      <span>課程目錄</span>
    </nav>

    <header class="catalog-header">
      <p class="eyebrow">PHY ARCHIVE</p>
      <h1>清大物理考古題課程目錄</h1>
      <p>
        瀏覽清華大學物理系相關課程的歷屆考題資訊。
        可查看收錄學期、授課教師、考試類型與是否附解答；
        完整文件的預覽與下載仍需登入。
      </p>
    </header>

    <p v-if="loading" class="status-message">
      正在載入課程資料……
    </p>

    <section
      v-else-if="errorMessage"
      class="status-message error-message"
      role="alert"
    >
      {{ errorMessage }}
    </section>

    <div v-else class="category-list">
      <section
        v-for="section in sections"
        :key="section.key"
        class="category-section"
      >
        <header class="category-header">
          <h2>{{ section.name }}</h2>
          <span>{{ section.courses.length }} 門課程</span>
        </header>

        <div class="course-grid">
          <article
            v-for="course in section.courses"
            :key="course.id"
            class="course-card"
          >
            <h3>
              <RouterLink
                :to="{
                  name: 'PublicCourse',
                  params: { courseId: course.id },
                }"
              >
                {{ course.name }}考古題
              </RouterLink>
            </h3>

            <p>
              查看 {{ course.name }} 的歷屆考試、
              授課教師與解答收錄狀況。
            </p>
          </article>
        </div>
      </section>
    </div>

    <section class="catalog-faq">
      <h2>關於清大物理考古系統</h2>

      <article>
        <h3>這個網站收錄什麼資料？</h3>
        <p>
          網站整理清大物理系及相關課程的歷屆考題、
          解答、授課教師、學期與考試類型資訊。
        </p>
      </article>

      <article>
        <h3>是否可以直接下載考古題？</h3>
        <p>
          公開頁面只顯示課程及考古題中繼資料。
          登入後才可依網站權限預覽或下載文件。
        </p>
      </article>

      <article>
        <h3>資料由誰維護？</h3>
        <p>
          系統由清大物理系系學會資訊組維護，
          並透過投稿及審核流程整理課程資料。
        </p>
      </article>
    </section>
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
      courses:
        coursesByCategory.value[category.key] || [],
    }))
    .filter((section) => section.courses.length > 0)
)

function applyCatalogSeo() {
  const courseItems = sections.value
    .flatMap((section) => section.courses)
    .map((course, index) => ({
      '@type': 'ListItem',
      position: index + 1,
      name: `${course.name}考古題`,
      url: `${SITE_URL}/courses/${course.id}`,
    }))

  setSeo({
    title: '清大物理考古題課程目錄｜PhysArchive',
    description:
      '瀏覽清大物理系各課程的歷屆考古題、考試類型、授課教師與是否附解答。',
    canonicalPath: '/courses',
    robots: 'index, follow',
    jsonLd: [
      {
        '@type': 'CollectionPage',
        '@id': `${SITE_URL}/courses#page`,
        name: '清大物理考古題課程目錄',
        url: `${SITE_URL}/courses`,
        description:
          '清大物理系各課程歷屆考古題與解答收錄目錄。',
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
        ],
      },
      {
        '@type': 'ItemList',
        name: '清大物理考古題課程',
        numberOfItems: courseItems.length,
        itemListElement: courseItems,
      },
    ],
  })
}

onMounted(async () => {
  try {
    const [categoriesResponse, coursesResponse] =
      await Promise.all([
        courseService.listPublicCategories(),
        courseService.listPublicCourses(),
      ])

    categories.value = Array.isArray(
      categoriesResponse.data
    )
      ? categoriesResponse.data
      : []

    coursesByCategory.value =
      coursesResponse.data &&
      typeof coursesResponse.data === 'object'
        ? coursesResponse.data
        : {}

    applyCatalogSeo()
  } catch (error) {
    console.error(
      'Failed to load public course catalog:',
      error
    )
    errorMessage.value =
      '目前無法讀取課程目錄，請稍後重新整理。'

    setSeo({
      title: '課程目錄暫時無法使用｜PhysArchive',
      canonicalPath: '/courses',
      robots: 'noindex, follow',
    })
  } finally {
    loading.value = false
  }
})
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
  font-size: clamp(2rem, 5vw, 3.5rem);
}

.catalog-header p {
  line-height: 1.8;
  color: var(--text-secondary);
}

.eyebrow {
  letter-spacing: 0.16em;
  font-weight: 700;
  color: var(--primary-color);
}

.category-list {
  display: grid;
  gap: 2.5rem;
}

.category-header {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  align-items: baseline;
  margin-bottom: 1rem;
}

.category-header h2 {
  margin: 0;
}

.category-header span {
  color: var(--text-secondary);
  font-size: 0.9rem;
}

.course-grid {
  display: grid;
  grid-template-columns:
    repeat(auto-fit, minmax(240px, 1fr));
  gap: 1rem;
}

.course-card {
  padding: 1.25rem;
  border: 1px solid var(--surface-border);
  border-radius: 1rem;
  background: var(--surface-card);
}

.course-card h3 {
  margin: 0 0 0.75rem;
}

.course-card p {
  margin: 0;
  color: var(--text-secondary);
  line-height: 1.65;
}

.catalog-faq {
  margin-top: 4rem;
  padding-top: 2rem;
  border-top: 1px solid var(--surface-border);
}

.catalog-faq article {
  margin-top: 1.5rem;
}

.catalog-faq p {
  color: var(--text-secondary);
  line-height: 1.75;
}

.status-message {
  padding: 2rem;
  text-align: center;
  color: var(--text-secondary);
}

.error-message {
  color: var(--red-500);
}
</style>