<template>
  <section class="wish-pool" aria-labelledby="wish-pool-title">
    <header class="wish-header">
      <div>
        <h2 id="wish-pool-title">{{ $t('考古許願池') }}</h2>
        <p>{{ $t('點選許願可按愛心、回報問題或協助上傳。') }}</p>
      </div>
      <div class="wish-header__actions">
        <Button
          :label="$t('新增許願')"
          icon="pi pi-plus"
          severity="success"
          size="small"
          @click="emit('add-wish')"
        />
        <Button
          :label="$t('投稿首頁 slogan')"
          icon="pi pi-send"
          severity="secondary"
          outlined
          size="small"
          class="wish-slogan-submit-button"
          @click="openSloganDialog"
        />
      </div>
    </header>
    <Message v-if="error" severity="error" :closable="false">{{ error }}</Message>
    <ProgressSpinner v-if="loading" class="wish-spinner" />
    <div v-else class="wish-pool-stage-shell">
      <div
        ref="viewportRef"
        class="wish-pool-stage"
        :class="{
          'is-panning': isPanning,
          'is-native-scroll': navigationMode !== 'desktop',
          'is-tablet-scroll': navigationMode === 'tablet',
          'is-mobile-scroll': navigationMode === 'mobile',
        }"
        @scroll.passive="handleNativeScroll"
        @wheel.passive="markNavigationInteraction"
        @pointerdown="startPan"
        @pointermove="movePan"
        @pointerup="finishPan"
        @pointercancel="finishPan"
        @dragstart.prevent
      >
        <div
          class="wish-pool-world"
          :class="{ 'is-returning': isReturningToOrigin }"
          role="list"
          :aria-label="$t('考古許願池')"
          :style="worldStyle"
        >
          <div
            v-for="wish in wishes"
            :key="wish.id"
            role="listitem"
            class="wish-node"
            :data-wish-id="wish.id"
            :data-wish-q="positions[wish.id]?.q"
            :data-wish-r="positions[wish.id]?.r"
            :style="wishPositionStyle(wish)"
          >
            <div class="wish-item" :class="{ fulfilled: wish.fulfilled }">
              <button
                type="button"
                class="wish-word"
                :style="wishTextStyle(wish)"
                @click="openWishDetail(wish, $event)"
              >
                <span class="wish-word__title">{{ wish.title }}</span>
                <span v-if="wish.fulfilled" class="fulfilled-label">{{ $t('已實現') }}</span>
              </button>
              <Button
                :label="String(wish.heart_count)"
                :icon="wish.hearted_by_me ? 'pi pi-heart-fill' : 'pi pi-heart'"
                :severity="wish.hearted_by_me ? 'danger' : 'secondary'"
                text
                rounded
                size="small"
                :loading="heartLoading"
                :disabled="heartLoading"
                :aria-label="$t('愛心 {count}', { count: wish.heart_count })"
                :title="$t('愛心 {count}', { count: wish.heart_count })"
                :aria-pressed="wish.hearted_by_me"
                class="wish-inline-heart discussion-action-button discussion-action-like-button"
                :class="{ 'is-active': wish.hearted_by_me }"
                @pointerdown.stop
                @click.stop="toggleHeart(wish)"
              />
            </div>
          </div>
        </div>
      </div>
      <div class="wish-overlay-controls">
        <div v-if="showMoreHint" class="wish-navigation-hint" aria-hidden="true">
          <i class="pi pi-arrows-alt" />
          <span>{{ $t(navigationHintText) }}</span>
        </div>
        <Button
          v-show="returnControlVisible"
          class="wish-return-button"
          :class="{ 'is-at-origin': returnControlAtOrigin }"
          icon="pi pi-arrows-alt"
          severity="secondary"
          text
          rounded
          :aria-label="$t(returnControlText)"
          :title="$t(returnControlText)"
          @pointerdown.stop
          @click.stop="returnToExplorationOrigin"
        />
      </div>
    </div>
    <Button
      v-if="wishes.length < total"
      class="load-more"
      :label="$t('載入更多')"
      text
      @click="loadMore"
    />

    <Dialog
      :visible="Boolean(selected)"
      @update:visible="!$event && closeWishDetail()"
      modal
      :draggable="false"
      :style="{ width: '520px', maxWidth: '94vw' }"
    >
      <template #header>
        <div class="wish-dialog-header">
          <strong>{{ selected?.title }}</strong>
          <div v-if="selected" class="wish-dialog-header__actions">
            <Button
              :label="String(selected.heart_count)"
              :icon="selected.hearted_by_me ? 'pi pi-heart-fill' : 'pi pi-heart'"
              :severity="selected.hearted_by_me ? 'danger' : 'secondary'"
              text
              rounded
              size="small"
              :loading="heartLoading"
              :disabled="heartLoading"
              :aria-label="$t('愛心 {count}', { count: selected.heart_count })"
              :title="$t('愛心 {count}', { count: selected.heart_count })"
              :aria-pressed="selected.hearted_by_me"
              class="discussion-action-button discussion-action-like-button"
              :class="{ 'is-active': selected.hearted_by_me }"
              @click="toggleHeart()"
            />
            <Button
              icon="pi pi-flag"
              severity="secondary"
              text
              rounded
              size="small"
              :aria-label="$t('回報')"
              :title="$t('回報')"
              class="discussion-action-button"
              @click="toggleReport"
            />
          </div>
        </div>
      </template>
      <div v-if="selected" class="wish-detail">
        <p>
          {{ selected.subject }} · {{ selected.professor }} · {{ semesterLabel(selected) }} ·
          {{ selected.name }}
        </p>
        <p v-if="isAdmin" class="wish-creator">
          {{ $t('許願者：{name}', { name: selected.creator_name }) }}
        </p>
        <Tag v-if="selected.fulfilled" severity="success">{{ $t('已實現') }}</Tag>
        <div class="dialog-actions wrap">
          <Button
            :label="$t('協助上傳')"
            icon="pi pi-cloud-upload"
            severity="success"
            @click="$emit('help-upload', selected)"
          />
          <Button
            v-if="isAdmin"
            :label="$t('永久刪除')"
            icon="pi pi-trash"
            severity="danger"
            outlined
            :loading="deleting"
            :disabled="deleting"
            @click="requestRemoveWish"
          />
        </div>
        <InlineCommentReport
          v-if="reportVisible"
          :message="reportTarget"
          targetType="wish"
          :reason="report.reason"
          :customMessage="report.customMessage"
          :loading="reportSubmitting"
          @update:reason="report.reason = $event"
          @update:customMessage="report.customMessage = $event"
          @cancel="closeReport"
          @submit="submitReport"
        />
      </div>
    </Dialog>

    <Dialog
      v-model:visible="sloganDialogVisible"
      modal
      :draggable="false"
      :header="$t('投稿首頁 slogan')"
      :style="{ width: '440px', maxWidth: '94vw' }"
      @hide="resetSloganDialog"
    >
      <form class="slogan-submission-form" @submit.prevent="submitSlogan">
        <label for="homepage-slogan-content">{{ $t('slogan 內容') }}</label>
        <InputText
          id="homepage-slogan-content"
          v-model="sloganContent"
          maxlength="80"
          :placeholder="$t('例如：書卷沒有，考古這有')"
          autocomplete="off"
          class="w-full"
        />
        <small>{{ $t('限單行純文字，最多 80 個字元。') }}</small>
        <div class="dialog-actions">
          <Button
            type="button"
            :label="$t('取消')"
            severity="secondary"
            text
            @click="sloganDialogVisible = false"
          />
          <Button
            type="submit"
            :label="$t('投稿')"
            icon="pi pi-send"
            :loading="sloganSubmitting"
            :disabled="!sloganContent.trim() || sloganSubmitting"
          />
        </div>
      </form>
    </Dialog>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useConfirm } from 'primevue/useconfirm'
import { useToast } from 'primevue/usetoast'
import { homepageSloganService, wishService } from '@/api'
import { getCurrentUser } from '@/utils/auth'
import {
  appendResponsiveWishPositions,
  assignWishCentralityScores,
  createSeededWishRng,
  createResponsiveWishLayout,
  createWishLayoutSeed,
  createWishWorldGeometry,
  reprojectWishHoneycombPositions,
  wishFontSizeRem,
  wishHoneycombGeometry,
  wishInteractionMode,
} from '@/utils/wishHoneycombLayout'
import InlineCommentReport from '@/components/InlineCommentReport.vue'

const emit = defineEmits(['add-wish', 'help-upload'])
const { t } = useI18n()
const confirm = useConfirm()
const toast = useToast()
const isAdmin = Boolean(getCurrentUser()?.is_admin)
const wishes = ref([]),
  total = ref(0),
  loading = ref(true),
  error = ref('')
const selected = ref(null)
const reportVisible = ref(false)
const reportSubmitting = ref(false),
  deleting = ref(false),
  heartLoading = ref(false)
const report = reactive({ reason: null, customMessage: '' })
const sloganDialogVisible = ref(false)
const sloganContent = ref('')
const sloganSubmitting = ref(false)
const viewportRef = ref(null)
const viewportSize = ref({ width: 0, height: 0 })
const positions = ref({})
const sessionScores = ref({})
const layoutMode = ref('honeycomb')
const navigationMode = ref('desktop')
const worldGeometry = ref({ width: 0, height: 0, offsetX: 0, offsetY: 0 })
const camera = reactive({ x: 0, y: 0 })
const explorationOrigin = reactive({ x: 0, y: 0 })
const isPanning = ref(false)
const isReturningToOrigin = ref(false)
const navigationInteracted = ref(false)
const showMoreHint = ref(false)
const showReturnControl = ref(false)
const sessionLayoutSeed = createWishLayoutSeed(Math.random)
const sessionScoreRng = createSeededWishRng(sessionLayoutSeed, 'centrality')
const PAN_THRESHOLD = 7
let resizeObserver
let panStart = null
let suppressNextClick = false
let suppressClickTimer
let nativeScrollSyncToken = 0
let returnTransitionTimer
let nativeNavigationIntent = false
let nativeNavigationIntentTimer
const semesterLabel = (wish) =>
  wish?.academic_year == null ? t('不限學期') : formatSemester(wish.academic_year)
function formatSemester(value) {
  const numericValue = Number(value)
  if (numericValue >= 1000 && numericValue < 2000) {
    const year = Math.floor(numericValue / 10)
    const semester = numericValue % 10
    return t(semester === 1 ? '{year}上學期' : '{year}下學期', { year })
  }
  return `${value}`
}
const reportTarget = computed(() => ({
  id: selected.value?.id,
  user_name: selected.value?.creator_name || t('許願者'),
  created_at: selected.value?.created_at,
  content: selected.value
    ? `${selected.value.title} · ${selected.value.subject} · ${selected.value.professor} · ${semesterLabel(selected.value)} · ${selected.value.name}`
    : '',
  is_deleted: false,
}))
const worldStyle = computed(() => {
  const geometry = wishHoneycombGeometry(viewportSize.value, rootFontSize())
  const sharedStyle = { '--wish-item-max-width': `${geometry.itemWidth}px` }
  if (navigationMode.value === 'desktop') {
    return { ...sharedStyle, transform: `translate3d(${camera.x}px, ${camera.y}px, 0)` }
  }
  return {
    ...sharedStyle,
    width: `${worldGeometry.value.width}px`,
    height: `${worldGeometry.value.height}px`,
    transform: 'none',
  }
})
const navigationHintText = computed(() => '拖曳以查看更多')
const returnControlText = computed(() => '回到中央')
const returnControlVisible = computed(() => Boolean(wishes.value.length))
const returnControlAtOrigin = computed(() => !showReturnControl.value)

function openSloganDialog() {
  sloganContent.value = ''
  sloganDialogVisible.value = true
}

function resetSloganDialog() {
  if (!sloganSubmitting.value) sloganContent.value = ''
}

async function submitSlogan() {
  const content = sloganContent.value.trim()
  if (!content || sloganSubmitting.value) return
  sloganSubmitting.value = true
  try {
    await homepageSloganService.submit(content)
    sloganDialogVisible.value = false
    sloganContent.value = ''
    toast.add({
      severity: 'success',
      summary: t('投稿成功'),
      detail: t('期待有一天可以在首頁看到你的 slogan！'),
      life: 4000,
    })
  } catch (submissionError) {
    toast.add({
      severity: 'error',
      summary: t('投稿失敗'),
      detail: submissionError?.response?.data?.detail || t('請確認內容後再試一次。'),
      life: 4000,
    })
  } finally {
    sloganSubmitting.value = false
  }
}
function wishPositionStyle(wish) {
  const position = positions.value[wish.id]
  if (!position) return { visibility: 'hidden' }
  const offsetX = navigationMode.value === 'desktop' ? 0 : worldGeometry.value.offsetX
  const offsetY = navigationMode.value === 'desktop' ? 0 : worldGeometry.value.offsetY
  return {
    '--wish-x': `${position.x + offsetX}px`,
    '--wish-y': `${position.y + offsetY}px`,
  }
}
function wishTextStyle(wish) {
  return { fontSize: `${wishFontSizeRem(wish.heart_count)}rem` }
}
function openWishDetail(wish, event) {
  if (suppressNextClick) {
    event.preventDefault()
    return
  }
  selected.value = wish
}
function startPan(event) {
  if (navigationMode.value !== 'desktop') {
    markNavigationInteraction()
    return
  }
  if (event.isPrimary === false || (event.pointerType === 'mouse' && event.button !== 0)) return
  panStart = {
    pointerId: event.pointerId,
    clientX: event.clientX,
    clientY: event.clientY,
    cameraX: camera.x,
    cameraY: camera.y,
    moved: false,
  }
}
function movePan(event) {
  if (!panStart || panStart.pointerId !== event.pointerId) return
  const deltaX = event.clientX - panStart.clientX
  const deltaY = event.clientY - panStart.clientY
  if (!panStart.moved && Math.hypot(deltaX, deltaY) < PAN_THRESHOLD) return
  if (!panStart.moved) {
    panStart.moved = true
    event.currentTarget.setPointerCapture?.(event.pointerId)
  }
  isPanning.value = true
  navigationInteracted.value = true
  camera.x = panStart.cameraX + deltaX
  camera.y = panStart.cameraY + deltaY
  updateNavigationAffordances()
  event.preventDefault()
}
function finishPan(event) {
  if (navigationMode.value !== 'desktop') return
  if (!panStart || panStart.pointerId !== event.pointerId) return
  if (panStart.moved) {
    suppressNextClick = true
    clearTimeout(suppressClickTimer)
    suppressClickTimer = setTimeout(() => {
      suppressNextClick = false
    }, 0)
  }
  if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
    event.currentTarget.releasePointerCapture(event.pointerId)
  }
  panStart = null
  isPanning.value = false
}
function rootFontSize() {
  if (typeof getComputedStyle !== 'function') return 16
  return Number.parseFloat(getComputedStyle(document.documentElement).fontSize) || 16
}
function navigationDistanceThreshold() {
  const shortestSide = Math.min(viewportSize.value.width, viewportSize.value.height)
  return Math.max(32, Math.min(64, shortestSide * 0.08))
}
function hasWishesOutsideInitialViewport() {
  return Object.values(positions.value).some(({ inInitialViewport }) => !inInitialViewport)
}
function updateNavigationAffordances() {
  if (!wishes.value.length || !viewportRef.value) {
    showMoreHint.value = false
    showReturnControl.value = false
    return
  }
  const threshold = navigationDistanceThreshold()
  showMoreHint.value = !navigationInteracted.value && hasWishesOutsideInitialViewport()
  const currentPosition =
    navigationMode.value !== 'desktop'
      ? { x: viewportRef.value.scrollLeft, y: viewportRef.value.scrollTop }
      : camera
  showReturnControl.value =
    navigationInteracted.value &&
    Math.hypot(currentPosition.x - explorationOrigin.x, currentPosition.y - explorationOrigin.y) >
      threshold
}
function markNavigationInteraction() {
  nativeNavigationIntent = true
  clearTimeout(nativeNavigationIntentTimer)
  nativeNavigationIntentTimer = setTimeout(() => {
    nativeNavigationIntent = false
  }, 160)
}
function handleNativeScroll() {
  if (navigationMode.value === 'desktop') return
  if (nativeNavigationIntent) navigationInteracted.value = true
  updateNavigationAffordances()
}
function prefersReducedMotion() {
  return Boolean(window.matchMedia?.('(prefers-reduced-motion: reduce)').matches)
}
function returnToExplorationOrigin() {
  nativeNavigationIntent = false
  navigationInteracted.value = false
  showReturnControl.value = false
  if (navigationMode.value !== 'desktop') {
    const target = { left: explorationOrigin.x, top: explorationOrigin.y }
    const options = {
      ...target,
      behavior: prefersReducedMotion() ? 'auto' : 'smooth',
    }
    if (typeof viewportRef.value?.scrollTo === 'function') {
      viewportRef.value.scrollTo(options)
    } else if (viewportRef.value) {
      viewportRef.value.scrollLeft = target.left
      viewportRef.value.scrollTop = target.top
    }
    updateNavigationAffordances()
    return
  }
  clearTimeout(returnTransitionTimer)
  isReturningToOrigin.value = !prefersReducedMotion()
  camera.x = explorationOrigin.x
  camera.y = explorationOrigin.y
  updateNavigationAffordances()
  if (isReturningToOrigin.value) {
    returnTransitionTimer = setTimeout(() => {
      isReturningToOrigin.value = false
    }, 320)
  }
}
function captureNativeScroll() {
  if (navigationMode.value === 'desktop' || !viewportRef.value) return null
  const { horizontalRange, verticalRange } = nativeScrollRanges()
  return {
    left: viewportRef.value.scrollLeft,
    top: viewportRef.value.scrollTop,
    leftRatio: horizontalRange ? viewportRef.value.scrollLeft / horizontalRange : 0,
    topRatio: verticalRange ? viewportRef.value.scrollTop / verticalRange : 0,
  }
}
function nativeScrollRanges() {
  return {
    horizontalRange: Math.max(0, worldGeometry.value.width - viewportSize.value.width),
    verticalRange: Math.max(0, worldGeometry.value.height - viewportSize.value.height),
  }
}
function initialNativeScroll() {
  const { horizontalRange, verticalRange } = nativeScrollRanges()
  return { left: horizontalRange / 2, top: verticalRange / 2 }
}
function scheduleNativeScroll(snapshot = null, preserveAbsolute = false) {
  const token = ++nativeScrollSyncToken
  nextTick(() => {
    if (
      token !== nativeScrollSyncToken ||
      navigationMode.value === 'desktop' ||
      !viewportRef.value
    ) {
      return
    }
    const { horizontalRange, verticalRange } = nativeScrollRanges()
    const target = snapshot
      ? {
          left: preserveAbsolute ? snapshot.left : snapshot.leftRatio * horizontalRange,
          top: preserveAbsolute ? snapshot.top : snapshot.topRatio * verticalRange,
        }
      : initialNativeScroll()
    viewportRef.value.scrollLeft = Math.min(horizontalRange, Math.max(0, target.left))
    viewportRef.value.scrollTop = Math.min(verticalRange, Math.max(0, target.top))
    updateNavigationAffordances()
  })
}
function updateWorldGeometry() {
  if (navigationMode.value === 'desktop') {
    worldGeometry.value = { width: 0, height: 0, offsetX: 0, offsetY: 0 }
    return
  }
  worldGeometry.value = createWishWorldGeometry(
    positions.value,
    viewportSize.value,
    rootFontSize(),
    { native2DOverflow: true }
  )
}
function applyResponsiveLayout(scrollSnapshot = captureNativeScroll()) {
  if (!wishes.value.length || !viewportSize.value.width || !viewportSize.value.height) return
  const previousNavigationMode = navigationMode.value
  const layout = createResponsiveWishLayout(
    wishes.value,
    sessionScores.value,
    viewportSize.value,
    rootFontSize(),
    sessionLayoutSeed
  )
  positions.value = layout.positions
  layoutMode.value = layout.mode
  navigationMode.value = layout.interactionMode
  camera.x = layout.camera.x
  camera.y = layout.camera.y
  updateWorldGeometry()
  const initialOrigin = navigationMode.value !== 'desktop' ? initialNativeScroll() : layout.camera
  explorationOrigin.x = initialOrigin.x ?? initialOrigin.left
  explorationOrigin.y = initialOrigin.y ?? initialOrigin.top
  if (previousNavigationMode !== navigationMode.value) navigationInteracted.value = false
  if (previousNavigationMode !== navigationMode.value) nativeNavigationIntent = false
  if (navigationMode.value === 'desktop') {
    nativeScrollSyncToken += 1
    updateNavigationAffordances()
  } else {
    scheduleNativeScroll(previousNavigationMode === navigationMode.value ? scrollSnapshot : null)
  }
}
function measureViewport(entry) {
  const target = entry?.target || viewportRef.value
  if (!target) return
  const width = Math.round(target.clientWidth || entry?.contentRect?.width || 0)
  const height = Math.round(target.clientHeight || entry?.contentRect?.height || 0)
  if (!width || !height) return
  if (viewportSize.value.width === width && viewportSize.value.height === height) return
  const scrollSnapshot = captureNativeScroll()
  const widthChanged = viewportSize.value.width !== width
  viewportSize.value = { width, height }
  if (Object.keys(positions.value).length) {
    const previousNavigationMode = navigationMode.value
    positions.value = reprojectWishHoneycombPositions(
      positions.value,
      viewportSize.value,
      rootFontSize()
    )
    navigationMode.value = wishInteractionMode(viewportSize.value)
    camera.x = 0
    camera.y = 0
    updateWorldGeometry()
    const refreshedOrigin = navigationMode.value === 'desktop' ? camera : initialNativeScroll()
    const navigationModeChanged = previousNavigationMode !== navigationMode.value
    if (navigationModeChanged) {
      navigationInteracted.value = false
      nativeNavigationIntent = false
    }
    if (navigationModeChanged || !navigationInteracted.value) {
      explorationOrigin.x = refreshedOrigin.x ?? refreshedOrigin.left
      explorationOrigin.y = refreshedOrigin.y ?? refreshedOrigin.top
    }
    if (navigationMode.value === 'desktop') {
      updateNavigationAffordances()
    } else {
      scheduleNativeScroll(navigationModeChanged ? null : scrollSnapshot, !widthChanged)
    }
    return
  }
  applyResponsiveLayout(scrollSnapshot)
}
function observeViewport() {
  if (!viewportRef.value) return
  measureViewport({ target: viewportRef.value })
  if (typeof ResizeObserver === 'undefined') return
  resizeObserver = new ResizeObserver((entries) => {
    const viewportEntry = entries.find((entry) => entry.target === viewportRef.value)
    if (viewportEntry) measureViewport(viewportEntry)
  })
  resizeObserver.observe(viewportRef.value)
}
async function load(reset = true) {
  loading.value = reset
  error.value = ''
  try {
    const { data } = await wishService.list({ limit: 60, offset: reset ? 0 : wishes.value.length })
    const incomingWishes = data.items || []
    if (reset) {
      wishes.value = incomingWishes
      sessionScores.value = assignWishCentralityScores(incomingWishes, sessionScoreRng)
      applyResponsiveLayout()
    } else {
      const scrollSnapshot = captureNativeScroll()
      sessionScores.value = assignWishCentralityScores(
        incomingWishes,
        sessionScoreRng,
        sessionScores.value
      )
      wishes.value = [...wishes.value, ...incomingWishes]
      positions.value = appendResponsiveWishPositions(
        positions.value,
        incomingWishes,
        sessionScores.value,
        viewportSize.value,
        rootFontSize(),
        sessionLayoutSeed
      )
      updateWorldGeometry()
      if (navigationMode.value !== 'desktop') {
        scheduleNativeScroll(scrollSnapshot, true)
      } else {
        updateNavigationAffordances()
      }
    }
    total.value = data.total
  } catch {
    error.value = t('許願池載入失敗，請稍後再試。')
  } finally {
    loading.value = false
  }
}
const loadMore = () => load(false)
async function toggleHeart(wish = selected.value) {
  if (!wish || heartLoading.value) return
  heartLoading.value = true
  try {
    const { data } = await wishService.toggleHeart(wish.id)
    const nextHeartState = { hearted_by_me: data.hearted, heart_count: data.heart_count }
    Object.assign(wish, nextHeartState)
    const item = wishes.value.find((itemWish) => itemWish.id === wish.id)
    if (item && item !== wish) Object.assign(item, nextHeartState)
    if (selected.value?.id === wish.id && selected.value !== wish) {
      Object.assign(selected.value, nextHeartState)
    }
  } finally {
    heartLoading.value = false
  }
}
function toggleReport() {
  if (reportVisible.value) return closeReport()
  report.reason = null
  report.customMessage = ''
  reportVisible.value = true
}
function closeReport() {
  reportVisible.value = false
  report.reason = null
  report.customMessage = ''
}
function closeWishDetail() {
  closeReport()
  selected.value = null
}
async function submitReport(payload) {
  if (!selected.value || reportSubmitting.value) return
  reportSubmitting.value = true
  try {
    await wishService.report(selected.value.id, {
      report_reason: payload.report_reason,
      custom_message: payload.custom_message,
    })
    toast.add({
      severity: 'success',
      summary: t('回報已送出'),
      detail: t('許願回報已送出，請等待管理員審核'),
      life: 3500,
    })
    closeReport()
  } catch (requestError) {
    const isDuplicate = requestError?.response?.status === 409
    toast.add({
      severity: isDuplicate ? 'warn' : 'error',
      summary: isDuplicate ? t('已有待審核回報') : t('回報送出失敗'),
      detail: isDuplicate ? t('這筆許願已有你的回報') : t('請稍後再試'),
      life: 3500,
    })
  } finally {
    reportSubmitting.value = false
  }
}
function requestRemoveWish() {
  if (!selected.value || deleting.value) return
  confirm.require({
    header: t('永久刪除這筆許願？'),
    message: t('這筆許願將永久刪除，無法復原，也不會進入垃圾桶。'),
    icon: 'pi pi-exclamation-triangle',
    rejectLabel: t('取消'),
    acceptLabel: t('永久刪除'),
    acceptClass: 'p-button-danger',
    defaultFocus: 'reject',
    accept: removeWish,
  })
}
async function removeWish() {
  if (!selected.value || deleting.value) return
  const wishId = selected.value.id
  deleting.value = true
  try {
    await wishService.remove(wishId)
    const scrollSnapshot = captureNativeScroll()
    wishes.value = wishes.value.filter((wish) => wish.id !== wishId)
    const nextPositions = { ...positions.value }
    delete nextPositions[wishId]
    positions.value = nextPositions
    updateWorldGeometry()
    if (navigationMode.value !== 'desktop') {
      scheduleNativeScroll(scrollSnapshot, true)
    } else {
      updateNavigationAffordances()
    }
    total.value = Math.max(0, total.value - 1)
    selected.value = null
    closeReport()
    toast.add({
      severity: 'success',
      summary: t('許願已永久刪除'),
      detail: t('這筆許願已永久移除，未進入垃圾桶。'),
      life: 3000,
    })
  } catch {
    toast.add({
      severity: 'error',
      summary: t('永久刪除失敗'),
      detail: t('許願未變更，請稍後再試。'),
      life: 3500,
    })
  } finally {
    deleting.value = false
  }
}
onMounted(async () => {
  await load()
  await nextTick()
  observeViewport()
})
onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  nativeScrollSyncToken += 1
  clearTimeout(suppressClickTimer)
  clearTimeout(returnTransitionTimer)
  clearTimeout(nativeNavigationIntentTimer)
})
</script>

<style scoped>
.wish-pool {
  display: flex;
  height: 100%;
  min-height: 0;
  box-sizing: border-box;
  flex-direction: column;
  width: 100%;
  padding: 1.5rem;
  margin: 0;
  container-type: inline-size;
  overflow-x: clip;
}
.wish-header,
.dialog-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}
.wish-header {
  width: 100%;
  text-align: left;
}
.wish-header > div {
  min-width: 0;
}
.wish-header__actions {
  display: flex;
  flex: 0 0 auto;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 0.75rem;
}
.wish-header__actions :deep(.wish-slogan-submit-button.p-button) {
  border-color: var(--border-color);
  background: var(--p-surface-0);
  color: var(--p-surface-700);
}
.wish-header__actions :deep(.wish-slogan-submit-button.p-button:not(:disabled):hover) {
  border-color: var(--border-color);
  background: var(--p-surface-100);
  color: var(--p-surface-800);
}
.wish-header h2,
.wish-header p {
  margin: 0.2rem 0;
  text-align: left;
}
.wish-header :deep(.p-button) {
  flex: 0 0 auto;
  min-height: 2.75rem;
  white-space: nowrap;
}
.wish-pool-stage-shell {
  position: relative;
  isolation: isolate;
  min-height: 0;
  flex: 1 1 auto;
  margin-top: 1.25rem;
}
.wish-pool-stage {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 0;
  box-sizing: border-box;
  border-block: 1px solid var(--surface-border);
  background: var(--surface-ground);
  cursor: grab;
  overflow: hidden;
  touch-action: none;
  user-select: none;
}
.wish-pool-stage.is-panning {
  cursor: grabbing;
}
.wish-pool-stage.is-native-scroll {
  scrollbar-width: none;
  -ms-overflow-style: none;
  -webkit-overflow-scrolling: touch;
}
.wish-pool-stage.is-native-scroll::-webkit-scrollbar {
  display: none;
  width: 0;
  height: 0;
}
.wish-pool-stage.is-tablet-scroll,
.wish-pool-stage.is-mobile-scroll {
  cursor: default;
  overflow: auto;
  touch-action: auto;
}
.wish-pool-world {
  position: absolute;
  left: 50%;
  top: 50%;
  width: 0;
  height: 0;
  will-change: transform;
}
.wish-pool-stage.is-native-scroll .wish-pool-world {
  position: relative;
  left: 0;
  top: 0;
  will-change: auto;
}
.wish-pool-world.is-returning {
  transition: transform 300ms ease-out;
}
.wish-overlay-controls {
  position: absolute;
  z-index: 2;
  inset: 0;
  pointer-events: none;
}
.wish-navigation-hint {
  position: absolute;
  bottom: calc(0.75rem + env(safe-area-inset-bottom, 0px));
  left: 50%;
  display: inline-flex;
  max-width: calc(100% - 7rem);
  align-items: center;
  gap: 0.4rem;
  transform: translateX(-50%);
  color: var(--text-color-secondary);
  font-size: var(--app-font-size-xs);
  line-height: 1.3;
  pointer-events: none;
  text-align: center;
  white-space: nowrap;
}
:deep(.wish-return-button.p-button) {
  position: absolute;
  z-index: 1;
  right: 1rem;
  bottom: calc(3.25rem + env(safe-area-inset-bottom, 0px));
  width: 2.75rem;
  height: 2.75rem;
  border: 1px solid color-mix(in srgb, var(--p-primary-color) 38%, var(--border-color)) !important;
  border-radius: 50%;
  background: color-mix(in srgb, var(--bg-primary) 88%, transparent);
  color: var(--text-secondary);
  padding: 0;
  pointer-events: auto;
}
:deep(.wish-return-button.p-button:hover),
:deep(.wish-return-button.p-button:focus-visible),
:deep(.wish-return-button.p-button:active) {
  border-color: color-mix(in srgb, var(--p-primary-color) 68%, var(--border-color)) !important;
  background: color-mix(in srgb, var(--p-primary-color) 10%, var(--bg-primary));
  color: var(--p-primary-color);
}
:deep(.wish-return-button.is-at-origin.p-button:not(:hover):not(:focus-visible):not(:active)) {
  opacity: 0.58;
}
@media (prefers-reduced-motion: reduce) {
  .wish-pool-world.is-returning {
    transition: none;
  }
}
.wish-node {
  position: absolute;
  left: var(--wish-x);
  top: var(--wish-y);
  transform: translate(-50%, -50%);
}
.wish-item {
  display: flex;
  width: max-content;
  max-width: min(var(--wish-item-max-width, 15rem), calc(100cqw - 2rem));
  box-sizing: border-box;
  align-items: center;
  flex-direction: column;
  gap: 0.15rem;
  border: 1px solid var(--surface-border);
  background: var(--surface-card);
  color: var(--text-color);
  padding: 0.55rem 0.75rem;
  border-radius: 0.5rem;
  font-family: 'Huninn', 'Noto Sans TC', system-ui, sans-serif;
  text-align: center;
}
.wish-word {
  display: flex;
  width: 100%;
  min-width: 0;
  align-items: center;
  flex-direction: column;
  gap: 0.2rem;
  border: 0;
  background: transparent;
  color: inherit;
  cursor: pointer;
  padding: 0;
  line-height: 1.35;
  font-family: inherit;
  text-align: center;
}
.wish-word__title {
  display: -webkit-box;
  overflow: hidden;
  overflow-wrap: anywhere;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  white-space: normal;
}
.fulfilled-label {
  flex: 0 0 auto;
  font-size: 0.7em;
  font-weight: 700;
  margin-left: 0;
}
.wish-word:hover,
.wish-word:focus-visible {
  color: var(--primary-color);
  outline: 2px solid var(--primary-color);
  outline-offset: 2px;
}
.wish-item.fulfilled {
  color: var(--green-600);
  font-weight: 600;
}
.wish-item.fulfilled .wish-word:hover,
.wish-item.fulfilled .wish-word:focus-visible {
  color: var(--green-500);
}
:deep(.wish-inline-heart.p-button) {
  min-width: 2.25rem;
  min-height: 2rem;
  padding: 0.25rem 0.45rem;
  font-size: var(--app-font-size-xs);
}
.wish-spinner,
.load-more {
  display: block;
  margin: 2rem auto;
}
.wish-detail {
  display: grid;
  gap: 0.8rem;
}
.wish-creator {
  margin: 0;
  color: var(--text-color-secondary);
  font-size: var(--app-font-size-sm);
}
.slogan-submission-form {
  display: grid;
  gap: 0.75rem;
}
.slogan-submission-form > label {
  font-weight: 600;
}
.slogan-submission-form > small {
  color: var(--text-color-secondary);
}
.wish-dialog-header {
  display: flex;
  min-width: 0;
  flex: 1;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}
.wish-dialog-header > strong {
  min-width: 0;
  overflow-wrap: anywhere;
}
.wish-dialog-header__actions {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 0.35rem;
}
.dialog-actions {
  justify-content: flex-end;
  margin-top: 0.8rem;
}
.wrap {
  flex-wrap: wrap;
  justify-content: flex-start;
}
@container (max-width:720px) {
  .wish-header {
    align-items: stretch;
    flex-direction: column;
  }
  .wish-header :deep(.p-button) {
    width: 100%;
    justify-content: center;
  }
  .wish-header__actions {
    width: 100%;
  }
}
</style>
