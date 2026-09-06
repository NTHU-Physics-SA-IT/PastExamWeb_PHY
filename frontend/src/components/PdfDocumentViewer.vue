<template>
  <div
    ref="scrollContainer"
    class="pdf-document-viewer"
    data-testid="pdf-document-viewer"
    :aria-busy="isLoading ? 'true' : 'false'"
  >
    <div v-if="pageEntries.length && !hasError" class="pdf-document-pages">
      <div
        v-for="entry in pageEntries"
        :key="`${entry.generation}-${entry.page}`"
        class="pdf-page-shell"
        :data-pdf-page="entry.page"
        :data-pdf-generation="entry.generation"
        :data-rendered="isPageActive(entry.page) ? 'true' : 'false'"
        :data-page-loaded="isPageLoaded(entry.page) ? 'true' : 'false'"
      >
        <VuePDF
          v-if="pdfTask && renderWidth > 0 && isPageActive(entry.page)"
          :pdf="pdfTask"
          :page="entry.page"
          :width="renderWidth"
          @loaded="handlePageLoaded(entry)"
        >
          <div class="pdf-page-loading" aria-hidden="true">
            <span class="pdf-page-loading-indicator" />
          </div>
        </VuePDF>
        <div v-else class="pdf-page-placeholder" aria-hidden="true" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { effectScope, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { GlobalWorkerOptions } from 'pdfjs-dist'
import LegacyPdfWorker from 'pdfjs-dist/legacy/build/pdf.worker.min.mjs?url'
import { usePDF, VuePDF } from '@tato30/vue-pdf/minimal'

GlobalWorkerOptions.workerSrc = LegacyPdfWorker

const PAGE_HORIZONTAL_INSET = 32
const PAGE_PRELOAD_MARGIN = '800px 0px'

const props = defineProps({
  source: {
    type: String,
    default: '',
  },
})

const emit = defineEmits(['load', 'error'])

const scrollContainer = ref(null)
const pdfTask = shallowRef()
const pageEntries = ref([])
const activePages = ref(new Set())
const loadedPages = ref(new Set())
const renderWidth = ref(0)
const isLoading = ref(false)
const hasError = ref(false)

let loadGeneration = 0
let sourceScope = null
let sourcePdfRef = null
let intersectionObserver = null
let resizeObserver = null
let didEmitLoad = false

function replaceActivePages(pages) {
  activePages.value = new Set(pages)
}

function activatePage(page) {
  if (activePages.value.has(page)) return
  replaceActivePages([...activePages.value, page])
}

function isPageActive(page) {
  return activePages.value.has(page)
}

function isPageLoaded(page) {
  return loadedPages.value.has(page)
}

function disconnectIntersectionObserver() {
  intersectionObserver?.disconnect()
  intersectionObserver = null
}

function observePendingPages(generation) {
  disconnectIntersectionObserver()
  const root = scrollContainer.value
  if (!root || pageEntries.value.length < 2) return

  if (typeof IntersectionObserver === 'undefined') {
    replaceActivePages(pageEntries.value.map((entry) => entry.page))
    return
  }

  intersectionObserver = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return
        const page = Number(entry.target.dataset.pdfPage)
        const targetGeneration = Number(entry.target.dataset.pdfGeneration)
        if (targetGeneration !== loadGeneration || targetGeneration !== generation) return
        activatePage(page)
        intersectionObserver?.unobserve(entry.target)
      })
    },
    {
      root,
      rootMargin: PAGE_PRELOAD_MARGIN,
      threshold: 0.01,
    }
  )

  root.querySelectorAll('.pdf-page-shell[data-pdf-page]').forEach((element) => {
    if (Number(element.dataset.pdfPage) > 1) intersectionObserver.observe(element)
  })
}

function updateRenderWidth() {
  const width = scrollContainer.value?.clientWidth || 0
  renderWidth.value = width > PAGE_HORIZONTAL_INSET ? width - PAGE_HORIZONTAL_INSET : 0
}

function destroySourceTask() {
  const task = sourcePdfRef?.value || pdfTask.value
  sourceScope?.stop()
  sourceScope = null
  sourcePdfRef = null
  pdfTask.value = undefined
  if (task) {
    Promise.resolve(task.destroy()).catch(() => {})
  }
}

function resetDocumentState() {
  disconnectIntersectionObserver()
  pageEntries.value = []
  replaceActivePages([])
  loadedPages.value = new Set()
  isLoading.value = false
  hasError.value = false
  didEmitLoad = false
}

function handleDocumentError(error, generation) {
  if (generation !== loadGeneration) return
  pdfTask.value = undefined
  pageEntries.value = []
  replaceActivePages([])
  loadedPages.value = new Set()
  isLoading.value = false
  hasError.value = true
  emit('error', error)
}

function loadSource(source) {
  const generation = ++loadGeneration
  destroySourceTask()
  resetDocumentState()
  if (!source) return

  isLoading.value = true
  const scope = effectScope()
  sourceScope = scope

  scope.run(() => {
    const state = usePDF(source, {
      onError: (error) => handleDocumentError(error, generation),
    })
    sourcePdfRef = state.pdf

    watch(
      state.pdf,
      async (task) => {
        if (!task || generation !== loadGeneration) return
        const totalPages = state.pages.value
        pdfTask.value = task
        pageEntries.value = Array.from({ length: totalPages }, (_, index) => ({
          page: index + 1,
          generation,
        }))
        replaceActivePages(totalPages ? [1] : [])
        await nextTick()
        if (generation === loadGeneration) observePendingPages(generation)
      },
      { flush: 'post' }
    )
  })
}

function handlePageLoaded(entry) {
  if (entry.generation !== loadGeneration) return
  loadedPages.value = new Set([...loadedPages.value, entry.page])
  if (entry.page !== 1 || didEmitLoad) return
  didEmitLoad = true
  isLoading.value = false
  emit('load')
}

watch(
  () => props.source,
  (source) => loadSource(source),
  { immediate: true }
)

onMounted(() => {
  updateRenderWidth()
  if (typeof ResizeObserver !== 'undefined' && scrollContainer.value) {
    resizeObserver = new ResizeObserver(updateRenderWidth)
    resizeObserver.observe(scrollContainer.value)
  }
})

onBeforeUnmount(() => {
  loadGeneration += 1
  disconnectIntersectionObserver()
  resizeObserver?.disconnect()
  resizeObserver = null
  destroySourceTask()
})
</script>

<style scoped>
.pdf-document-viewer {
  flex: 1 1 auto;
  width: 100%;
  height: 100%;
  min-height: 0;
  overflow: auto;
  overscroll-behavior: contain;
  -webkit-overflow-scrolling: touch;
}

.pdf-document-pages {
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1rem;
  min-width: 100%;
  padding: 1rem;
}

.pdf-page-shell {
  width: 100%;
  min-width: 0;
  overflow: hidden;
  background: white;
  border-radius: 2px;
  box-shadow: 0 2px 8px rgb(0 0 0 / 24%);
}

.pdf-page-placeholder,
.pdf-page-loading {
  width: 100%;
  aspect-ratio: 1 / 1.4142;
  background: white;
}

.pdf-page-loading {
  display: grid;
  place-items: center;
}

.pdf-page-loading-indicator {
  width: 2rem;
  height: 2rem;
  border: 3px solid color-mix(in srgb, var(--p-primary-color) 22%, transparent);
  border-top-color: var(--p-primary-color);
  border-radius: 50%;
  animation: pdf-page-spin 0.8s linear infinite;
}

@keyframes pdf-page-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .pdf-page-loading-indicator {
    animation: none;
  }
}
</style>
