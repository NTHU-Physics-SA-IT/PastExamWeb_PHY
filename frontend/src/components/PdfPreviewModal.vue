<template>
  <Dialog
    :visible="localVisible"
    @update:visible="localVisible = $event"
    :style="{ width: 'min(1200px, 95vw)', height: 'min(90vh, 90dvh)' }"
    :contentStyle="{ flex: '1 1 auto', overflow: 'clip' }"
    :modal="true"
    :draggable="false"
    :closeOnEscape="false"
    :dismissableMask="true"
    :maximizable="true"
    :autoFocus="false"
    :pt="{ root: { 'aria-label': displayTitle, 'aria-labelledby': null } }"
    @maximize="handleMaximize"
    @unmaximize="handleUnmaximize"
    @hide="onHide"
  >
    <template #maximizebutton="{ maximized, maximizeCallback }">
      <Button
        v-if="discussionEnabled"
        icon="pi pi-flag"
        severity="secondary"
        text
        rounded
        :aria-label="$t('回報考古題')"
        :title="$t('回報考古題')"
        style="width: 2.5rem; height: 2.5rem; padding: 0"
        @click="handleArchiveReportClick"
      />
      <Button
        v-if="discussionEnabled"
        :icon="discussionOpen ? 'pi pi-comments' : 'pi pi-comment'"
        severity="secondary"
        text
        rounded
        :aria-label="
          isMobile ? $t('開啟討論區') : discussionOpen ? $t('關閉討論區') : $t('開啟討論區')
        "
        style="width: 2.5rem; height: 2.5rem; padding: 0"
        @click="handleDiscussionClick"
      />
      <Button
        :icon="maximized ? 'pi pi-window-minimize' : 'pi pi-window-maximize'"
        severity="secondary"
        text
        rounded
        :aria-label="maximized ? $t('還原視窗') : $t('最大化')"
        style="width: 2.5rem; height: 2.5rem; padding: 0"
        @click="maximizeCallback"
      />
    </template>
    <template #header>
      <div class="flex align-items-center gap-2.5">
        <i class="pi pi-file-pdf text-2xl" />
        <div class="flex flex-column">
          <div class="text-xl leading-tight">
            {{ displayTitle }}
          </div>
          <div
            v-if="metaTextItems.length && !isMobile"
            class="text-sm mt-1 flex flex-wrap gap-3"
            style="color: var(--text-secondary)"
          >
            <span v-for="item in metaTextItems" :key="item.key" class="flex align-items-center">
              <i :class="`pi ${item.icon} mr-1`"></i>
              {{ item.value }}
            </span>
          </div>
        </div>
      </div>
    </template>

    <div class="w-full h-full flex flex-column">
      <div class="flex-1 flex min-h-0">
        <div class="flex-1 flex flex-column min-w-0">
          <div
            v-if="error || pdfError"
            class="flex-1 flex flex-column align-items-center justify-content-center gap-4"
          >
            <i class="pi pi-exclamation-circle text-6xl text-red-500" />
            <div class="text-xl">{{ errorMessage }}</div>
            <div v-if="isGenericPreviewError" class="text-sm text-gray-600">
              {{ $t('請嘗試下載檔案查看') }}
            </div>
          </div>

          <div v-else-if="currentPdf && renderPdf" class="flex-1 pdf-container">
            <iframe
              :key="currentPdf"
              :src="currentPdf"
              class="pdf-frame"
              :title="$t('PDF 預覽')"
              @load="handlePdfLoaded"
              @error="handlePdfError"
            ></iframe>
            <div
              v-if="loading || pdfLoading"
              class="pdf-loading-overlay flex align-items-center justify-content-center"
            >
              <ProgressSpinner strokeWidth="4" />
            </div>
          </div>

          <div v-else class="flex-1 flex align-items-center justify-content-center">
            <ProgressSpinner strokeWidth="4" />
          </div>
        </div>

        <div
          v-if="discussionEnabled && !isMobile"
          class="discussion-wrapper"
          :class="{ 'is-open': discussionOpen, 'is-closed': !discussionOpen }"
        >
          <ArchiveDiscussionPanel
            v-show="sidePanelMode === 'discussion'"
            :courseId="courseId"
            :archiveId="archiveId"
            width="100%"
            @desktop-default-open-change="handleDesktopDefaultOpenChange"
          />
          <ArchiveReportPanel
            v-if="archiveReportActivated"
            v-show="sidePanelMode === 'exam-report'"
            :courseId="courseId"
            :archiveId="archiveId"
            :courseName="courseName"
            :archiveName="title"
            @back="returnToDiscussion"
          />
        </div>
      </div>
    </div>

    <template #footer>
      <Button
        v-if="showDownload"
        :label="$t('下載')"
        icon="pi pi-download"
        @click="handleDownload"
        severity="success"
        :loading="downloading"
      />
    </template>
  </Dialog>

  <Dialog
    v-if="discussionEnabled"
    :visible="discussionModalVisible"
    @update:visible="discussionModalVisible = $event"
    :modal="true"
    :draggable="false"
    :dismissableMask="true"
    :closeOnEscape="true"
    :style="{ width: 'min(520px, 95vw)', height: 'min(90vh, 90dvh)' }"
    :contentStyle="{ flex: '1 1 auto' }"
    :autoFocus="false"
  >
    <template #header>
      <div class="flex align-items-center gap-2.5">
        <i :class="`pi ${sidePanelMode === 'exam-report' ? 'pi-flag' : 'pi-comments'} text-2xl`" />
        <div class="text-xl leading-tight">
          {{ sidePanelMode === 'exam-report' ? $t('回報考古題') : $t('討論區') }}
        </div>
      </div>
    </template>
    <template #closebutton="{ closeCallback }">
      <Button
        :icon="sidePanelMode === 'exam-report' ? 'pi pi-comments' : 'pi pi-flag'"
        severity="secondary"
        text
        rounded
        :aria-label="sidePanelMode === 'exam-report' ? $t('返回留言區') : $t('回報考古題')"
        style="width: 2.5rem; height: 2.5rem; padding: 0"
        @click="toggleSidePanelMode"
      />
      <Button
        v-if="sidePanelMode === 'discussion'"
        icon="pi pi-cog"
        severity="secondary"
        text
        rounded
        :aria-label="$t('暱稱設定')"
        style="width: 2.5rem; height: 2.5rem; padding: 0"
        @click="openDiscussionSettings"
      />
      <Button
        icon="pi pi-times"
        severity="secondary"
        text
        rounded
        :aria-label="$t('關閉')"
        style="width: 2.5rem; height: 2.5rem; padding: 0"
        @click="closeCallback"
      />
    </template>
    <div class="h-full min-h-0">
      <ArchiveDiscussionPanel
        v-show="sidePanelMode === 'discussion'"
        ref="discussionPanelRef"
        :courseId="courseId"
        :archiveId="archiveId"
        width="100%"
        class="discussion-modal-panel"
        :showHeader="false"
        :showSettings="false"
        @desktop-default-open-change="handleDesktopDefaultOpenChange"
      />
      <ArchiveReportPanel
        v-if="archiveReportActivated"
        v-show="sidePanelMode === 'exam-report'"
        :courseId="courseId"
        :archiveId="archiveId"
        :courseName="courseName"
        :archiveName="title"
        @back="returnToDiscussion"
      />
    </div>
  </Dialog>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useUnauthorizedEvent } from '../utils/useUnauthorizedEvent'
import ArchiveDiscussionPanel from './ArchiveDiscussionPanel.vue'
import ArchiveReportPanel from './ArchiveReportPanel.vue'
import { getBooleanPreference } from '../utils/usePreferences'
import { STORAGE_KEYS } from '../utils/storage'

const DESKTOP_DEFAULT_OPEN_KEY = STORAGE_KEYS.local.DISCUSSION_DESKTOP_DEFAULT_OPEN
const { t } = useI18n()

const props = defineProps({
  visible: {
    type: Boolean,
    required: true,
  },
  courseId: {
    type: [Number, String],
    default: null,
  },
  archiveId: {
    type: [Number, String],
    default: null,
  },
  previewUrl: {
    type: String,
    default: '',
  },
  title: {
    type: String,
    default: '',
  },
  academicYear: {
    type: [Number, String, Date],
    default: null,
  },
  archiveType: {
    type: String,
    default: '',
  },
  courseName: {
    type: String,
    default: '',
  },
  professorName: {
    type: String,
    default: '',
  },
  loading: {
    type: Boolean,
    default: false,
  },
  error: {
    type: Boolean,
    default: false,
  },
  errorMessage: {
    type: String,
    default: '',
  },
  showDownload: {
    type: Boolean,
    default: true,
  },
  showDiscussion: {
    type: Boolean,
    default: true,
  },
})

const emit = defineEmits(['update:visible', 'hide', 'load', 'error', 'download'])

useUnauthorizedEvent(() => {
  emit('update:visible', false)
})

const localVisible = computed({
  get: () => props.visible,
  set: (value) => emit('update:visible', value),
})

const isMaximized = ref(false)
const isMobile = ref(false)
const discussionOpen = ref(false)
const discussionModalVisible = ref(false)
const sidePanelMode = ref('discussion')
const archiveReportActivated = ref(false)
const discussionPanelRef = ref(null)
const discussionEnabled = computed(
  () => props.showDiscussion && Boolean(props.courseId) && Boolean(props.archiveId)
)
const displayTitle = computed(() => props.title || t('預覽文件'))
const isGenericPreviewError = computed(
  () =>
    !props.errorMessage ||
    props.errorMessage === '無法載入預覽' ||
    props.errorMessage === t('無法載入預覽')
)

const archiveTypeLabel = computed(() => {
  const archiveTypeKey = (props.archiveType || '').trim().toLowerCase()
  const map = {
    midterm: t('期中考'),
    final: t('期末考'),
    quiz: t('小考'),
    other: t('其他'),
  }
  return map[archiveTypeKey] || (props.archiveType || '').trim()
})

const metaTextItems = computed(() => {
  let year = ''
  if (props.academicYear instanceof Date) {
    year = String(props.academicYear.getFullYear())
  } else if (props.academicYear !== null && props.academicYear !== undefined) {
    year = String(props.academicYear).trim()
  }

  const courseName = (props.courseName || '').trim()
  const professorName = (props.professorName || '').trim()
  const typeLabel = (archiveTypeLabel.value || '').trim()

  return [
    year ? { key: 'year', icon: 'pi-calendar', value: year } : null,
    courseName ? { key: 'course', icon: 'pi-book', value: courseName } : null,
    professorName ? { key: 'professor', icon: 'pi-user', value: professorName } : null,
    typeLabel ? { key: 'type', icon: 'pi-bookmark', value: typeLabel } : null,
  ].filter(Boolean)
})

const downloading = ref(false)
const pdfLoading = ref(false)
const pdfError = ref(false)
const renderPdf = ref(false)

const currentPdf = computed(() => props.previewUrl || '')

watch(
  currentPdf,
  (val) => {
    pdfError.value = false
    pdfLoading.value = !!val
  },
  { immediate: true }
)

watch(
  () => props.visible,
  async (visible) => {
    renderPdf.value = false
    if (!visible) return

    // PrimeVue Dialog teleports + transitions; defer mounting until the
    // content is attached to the DOM so native PDF viewers get stable sizing.
    await nextTick()
    requestAnimationFrame(() => {
      if (props.visible) renderPdf.value = true
    })
  },
  { immediate: true }
)

function onHide() {
  pdfLoading.value = false
  pdfError.value = false
  isMaximized.value = false
  discussionOpen.value = isMobile.value
    ? false
    : getBooleanPreference(DESKTOP_DEFAULT_OPEN_KEY, true)
  discussionModalVisible.value = false
  sidePanelMode.value = 'discussion'
  archiveReportActivated.value = false
  emit('hide')
}

function handleMaximize() {
  isMaximized.value = true
}

function handleUnmaximize() {
  isMaximized.value = false
}

function toggleDiscussion() {
  discussionOpen.value = !discussionOpen.value
}

function handleDiscussionClick() {
  if (isMobile.value) {
    discussionModalVisible.value = true
    return
  }
  toggleDiscussion()
}

function handleArchiveReportClick() {
  archiveReportActivated.value = true
  sidePanelMode.value = 'exam-report'
  if (isMobile.value) {
    discussionModalVisible.value = true
    return
  }
  discussionOpen.value = true
}

function returnToDiscussion() {
  sidePanelMode.value = 'discussion'
}

function toggleSidePanelMode() {
  if (sidePanelMode.value === 'exam-report') {
    sidePanelMode.value = 'discussion'
    return
  }
  archiveReportActivated.value = true
  sidePanelMode.value = 'exam-report'
}

function openDiscussionSettings() {
  discussionPanelRef.value?.openNicknameDialog?.()
}

function handleDesktopDefaultOpenChange(isOpen) {
  if (isMobile.value) return
  discussionOpen.value = Boolean(isOpen)
}

function updateIsMobile() {
  const prev = isMobile.value
  const next =
    typeof window !== 'undefined' && window.matchMedia
      ? window.matchMedia('(width < 768px)').matches
      : false

  isMobile.value = next
  if (next) {
    discussionOpen.value = false
  } else if (prev && !next) {
    discussionOpen.value = getBooleanPreference(DESKTOP_DEFAULT_OPEN_KEY, true)
  }
  if (prev && !next) {
    discussionModalVisible.value = false
  }
}

onMounted(() => {
  updateIsMobile()
  discussionOpen.value = isMobile.value
    ? false
    : getBooleanPreference(DESKTOP_DEFAULT_OPEN_KEY, true)
  if (typeof window !== 'undefined') {
    window.addEventListener('resize', updateIsMobile, { passive: true })
  }
})

onBeforeUnmount(() => {
  if (typeof window !== 'undefined') {
    window.removeEventListener('resize', updateIsMobile)
  }
})

function handlePdfError(err) {
  console.error('PDF loading failed:', err)
  pdfError.value = true
  pdfLoading.value = false
  emit('error')
}

function handlePdfLoaded() {
  pdfLoading.value = false
  pdfError.value = false
  emit('load')
}

function handleDownload() {
  downloading.value = true
  emit('download', () => {
    downloading.value = false
  })
}
</script>

<style scoped>
.pdf-container {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 300px;
  overflow: hidden;
  scrollbar-gutter: stable;
  display: flex;
  flex-direction: column;
  background-color: #525659;
  border-radius: 6px;
}

.pdf-frame {
  width: 100%;
  height: 100%;
  min-height: 65vh;
  flex: 1 1 auto;
  border: 0;
  background: white;
  border-radius: 6px;
}

.pdf-loading-overlay {
  position: absolute;
  inset: 0;
  z-index: 1;
  background: color-mix(in srgb, var(--p-content-background) 72%, transparent);
}

.discussion-wrapper {
  min-width: 0;
  flex: 0 0 auto;
  overflow: hidden;
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  transition:
    width 220ms ease,
    margin-left 220ms ease,
    opacity 220ms ease;
}

.discussion-wrapper :deep(.discussion-panel) {
  height: 100%;
  min-height: 0;
}

.discussion-wrapper.is-open {
  width: min(380px, 40%);
  margin-left: 1rem;
  opacity: 1;
  pointer-events: auto;
}

.discussion-wrapper.is-closed {
  width: 0;
  margin-left: 0;
  opacity: 0;
  pointer-events: none;
}

@media (prefers-reduced-motion: reduce) {
  .discussion-wrapper {
    transition: none;
  }
}

.discussion-modal-panel {
  height: 100%;
}

.discussion-modal-panel :deep(.discussion-panel) {
  height: 100%;
  max-width: none;
  border-radius: 0;
}

/* Mobile responsive adjustments */
@media (width < 768px) {
  :deep(.p-dialog .p-dialog-header) {
    font-size: 1rem;
  }

  :deep(.p-dialog .p-dialog-footer .p-button) {
    font-size: 0.875rem;
    padding: 0.5rem 0.75rem;
  }
}
</style>
