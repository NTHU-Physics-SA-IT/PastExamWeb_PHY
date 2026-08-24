<template>
  <section ref="poolRef" class="wish-pool" aria-labelledby="wish-pool-title">
    <header class="wish-header">
      <div>
        <h2 id="wish-pool-title">{{ $t('考古許願池') }}</h2>
        <p>{{ $t('點選許願可按愛心、回報問題或協助上傳。') }}</p>
      </div>
      <Button
        :label="$t('新增許願')"
        icon="pi pi-plus"
        severity="success"
        size="small"
        @click="emit('add-wish')"
      />
    </header>
    <Message v-if="error" severity="error" :closable="false">{{ error }}</Message>
    <ProgressSpinner v-if="loading" class="wish-spinner" />
    <div
      v-else
      ref="viewportRef"
      class="wish-bubble-viewport"
      :class="{ 'is-panning': panning }"
      :aria-label="$t('考古許願池')"
      @pointerdown="handlePointerDown"
      @pointermove="handlePointerMove"
      @pointerup="handlePointerEnd"
      @pointercancel="handlePointerCancel"
      @click.capture="handleViewportClick"
      @dragstart.prevent
    >
      <div ref="worldRef" class="wish-bubble-world" role="list">
        <article
          v-for="wish in wishes"
          :key="wish.id"
          :ref="(element) => setBubbleRef(wish.id, element)"
          class="wish-bubble"
          :class="{ fulfilled: wish.fulfilled }"
          :style="bubbleStyle(wish)"
          role="listitem"
          :data-wish-id="wish.id"
        >
          <button
            type="button"
            class="wish-bubble__open"
            :aria-label="wish.title"
            @click="openWishFromBubble(wish, $event)"
          >
            <span class="wish-bubble__message">{{ wish.title }}</span>
          </button>
          <button
            type="button"
            class="wish-bubble__heart"
            :class="{ 'is-active': wish.hearted_by_me }"
            :aria-label="$t('愛心 {count}', { count: wish.heart_count })"
            :title="$t('愛心 {count}', { count: wish.heart_count })"
            :aria-pressed="wish.hearted_by_me"
            :disabled="heartLoadingId === wish.id"
            @pointerdown.stop
            @click.stop="toggleHeart(wish)"
          >
            <i
              :class="wish.hearted_by_me ? 'pi pi-heart-fill' : 'pi pi-heart'"
              aria-hidden="true"
            />
            <span>{{ wish.heart_count }}</span>
          </button>
        </article>
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
              @click="toggleHeart(selected)"
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
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useConfirm } from 'primevue/useconfirm'
import { useToast } from 'primevue/usetoast'
import { wishService } from '@/api'
import { getCurrentUser } from '@/utils/auth'
import {
  beginRadiusTransition,
  createInitialBubbleLayout,
  getWishBubbleDiameter,
  stepBubblePhysics,
  updateBubbleRadius,
} from '@/utils/wishBubblePhysics'
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
  deleting = ref(false)
const heartLoadingId = ref(null)
const panning = ref(false)
const report = reactive({ reason: null, customMessage: '' })
const poolRef = ref(null)
const viewportRef = ref(null)
const worldRef = ref(null)
const bubbleElements = new Map()
const camera = { x: 0, y: 0 }
const pointerGesture = {
  pointerId: null,
  startX: 0,
  startY: 0,
  cameraX: 0,
  cameraY: 0,
  moved: false,
}
const PAN_THRESHOLD = 7
let suppressNextBubbleClick = false
let resizeObserver
let intersectionObserver
let reducedMotionQuery
let physicsFrame = null
let previousTimestamp = null
let physicsStates = []
let physicsById = new Map()
let layoutGeneration = 0
let mounted = false
let poolVisible = true
let reducedMotion = false

const heartLoading = computed(
  () => Boolean(selected.value) && heartLoadingId.value === selected.value.id
)
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

function now() {
  return typeof performance !== 'undefined' ? performance.now() : Date.now()
}

function setBubbleRef(id, element) {
  if (element) bubbleElements.set(id, element)
  else bubbleElements.delete(id)
}

function bubbleStyle(wish) {
  return { '--bubble-diameter': `${getWishBubbleDiameter(wish.heart_count)}px` }
}

function applyCameraTransform() {
  if (!worldRef.value) return
  worldRef.value.style.transform = `translate3d(${camera.x}px, ${camera.y}px, 0)`
}

function applyBubbleTransforms() {
  for (const bubble of physicsStates) {
    const element = bubbleElements.get(bubble.id)
    if (!element) continue
    element.style.transform = `translate3d(${bubble.x - bubble.radius}px, ${bubble.y - bubble.radius}px, 0)`
  }
}

function canRunPhysics() {
  return (
    mounted &&
    !reducedMotion &&
    poolVisible &&
    !document.hidden &&
    physicsStates.length > 0 &&
    typeof window.requestAnimationFrame === 'function'
  )
}

function stopPhysics() {
  if (physicsFrame !== null && typeof window.cancelAnimationFrame === 'function') {
    window.cancelAnimationFrame(physicsFrame)
  }
  physicsFrame = null
  previousTimestamp = null
}

function animatePhysics(timestamp) {
  if (!canRunPhysics()) {
    stopPhysics()
    return
  }
  const deltaSeconds = previousTimestamp === null ? 0 : (timestamp - previousTimestamp) / 1000
  previousTimestamp = timestamp
  for (const bubble of physicsStates) updateBubbleRadius(bubble, timestamp)
  stepBubblePhysics(physicsStates, deltaSeconds)
  applyBubbleTransforms()
  physicsFrame = window.requestAnimationFrame(animatePhysics)
}

function startPhysics() {
  if (physicsFrame !== null || !canRunPhysics()) return
  physicsFrame = window.requestAnimationFrame(animatePhysics)
}

async function rebuildBubbleLayout() {
  const generation = ++layoutGeneration
  await nextTick()
  if (generation !== layoutGeneration || !viewportRef.value) return
  const width = viewportRef.value.clientWidth || 960
  const height = viewportRef.value.clientHeight || 620
  physicsStates = createInitialBubbleLayout(wishes.value, { width, height })
  physicsById = new Map(physicsStates.map((bubble) => [bubble.id, bubble]))
  camera.x = 0
  camera.y = 0
  applyCameraTransform()
  applyBubbleTransforms()
  startPhysics()
}

function handlePoolResize() {
  if (!physicsStates.length) {
    void rebuildBubbleLayout()
    return
  }
  applyCameraTransform()
  applyBubbleTransforms()
}

function syncBubbleRadii() {
  const timestamp = now()
  let transitionStarted = false
  for (const wish of wishes.value) {
    const bubble = physicsById.get(wish.id)
    if (!bubble) continue
    const nextRadius = getWishBubbleDiameter(wish.heart_count) / 2
    if (reducedMotion) {
      bubble.radius = nextRadius
      bubble.targetRadius = nextRadius
      bubble.mass = nextRadius * nextRadius
      bubble.radiusTransition = null
      continue
    }
    transitionStarted = beginRadiusTransition(bubble, nextRadius, timestamp) || transitionStarted
  }
  applyBubbleTransforms()
  if (transitionStarted) startPhysics()
}

function handlePointerDown(event) {
  if (!event.isPrimary || event.button > 0 || event.target.closest('.wish-bubble__heart')) return
  suppressNextBubbleClick = false
  pointerGesture.pointerId = event.pointerId
  pointerGesture.startX = event.clientX
  pointerGesture.startY = event.clientY
  pointerGesture.cameraX = camera.x
  pointerGesture.cameraY = camera.y
  pointerGesture.moved = false
}

function handlePointerMove(event) {
  if (event.pointerId !== pointerGesture.pointerId) return
  const deltaX = event.clientX - pointerGesture.startX
  const deltaY = event.clientY - pointerGesture.startY
  if (!pointerGesture.moved && Math.hypot(deltaX, deltaY) < PAN_THRESHOLD) return
  if (!pointerGesture.moved) {
    pointerGesture.moved = true
    viewportRef.value?.setPointerCapture?.(event.pointerId)
  }
  panning.value = true
  camera.x = pointerGesture.cameraX + deltaX
  camera.y = pointerGesture.cameraY + deltaY
  applyCameraTransform()
  event.preventDefault()
}

function releasePointerCapture(pointerId = pointerGesture.pointerId) {
  if (pointerId === null || !viewportRef.value?.hasPointerCapture?.(pointerId)) return
  viewportRef.value.releasePointerCapture(pointerId)
}

function endPointerGesture(event, cancelled = false) {
  if (event.pointerId !== pointerGesture.pointerId) return
  if (pointerGesture.moved && !cancelled) suppressNextBubbleClick = true
  releasePointerCapture(event.pointerId)
  pointerGesture.pointerId = null
  pointerGesture.moved = false
  panning.value = false
}

function handlePointerEnd(event) {
  endPointerGesture(event)
}

function handlePointerCancel(event) {
  endPointerGesture(event, true)
}

function handleViewportClick(event) {
  if (!suppressNextBubbleClick) return
  suppressNextBubbleClick = false
  event.preventDefault()
  event.stopPropagation()
}

function openWishFromBubble(wish, event) {
  if (suppressNextBubbleClick) {
    suppressNextBubbleClick = false
    event.preventDefault()
    return
  }
  selected.value = wish
}

async function load(reset = true) {
  loading.value = reset
  error.value = ''
  try {
    const { data } = await wishService.list({ limit: 60, offset: reset ? 0 : wishes.value.length })
    wishes.value = reset ? data.items : [...wishes.value, ...data.items]
    total.value = data.total
  } catch {
    error.value = t('許願池載入失敗，請稍後再試。')
  } finally {
    loading.value = false
  }
}

const loadMore = () => load(false)

async function toggleHeart(wish = selected.value) {
  if (!wish || heartLoadingId.value !== null) return
  heartLoadingId.value = wish.id
  try {
    const { data } = await wishService.toggleHeart(wish.id)
    Object.assign(wish, { hearted_by_me: data.hearted, heart_count: data.heart_count })
    const item = wishes.value.find((candidate) => candidate.id === wish.id)
    if (item && item !== wish) Object.assign(item, wish)
    if (selected.value?.id === wish.id && selected.value !== wish)
      Object.assign(selected.value, wish)
  } finally {
    heartLoadingId.value = null
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
    wishes.value = wishes.value.filter((wish) => wish.id !== wishId)
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

function handleReducedMotionChange(event) {
  reducedMotion = event.matches
  if (reducedMotion) {
    stopPhysics()
    for (const bubble of physicsStates) {
      bubble.radius = bubble.targetRadius
      bubble.mass = bubble.radius * bubble.radius
      bubble.radiusTransition = null
    }
    applyBubbleTransforms()
  } else {
    startPhysics()
  }
}

function handleVisibilityChange() {
  if (document.hidden) stopPhysics()
  else startPhysics()
}

watch(() => wishes.value.map((wish) => `${wish.id}:${wish.title}`).join('|'), rebuildBubbleLayout)
watch(() => wishes.value.map((wish) => `${wish.id}:${wish.heart_count}`).join('|'), syncBubbleRadii)

onMounted(() => {
  mounted = true
  if (typeof window.matchMedia === 'function') {
    reducedMotionQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
    reducedMotion = reducedMotionQuery.matches
    reducedMotionQuery.addEventListener?.('change', handleReducedMotionChange)
  }
  if (typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(handlePoolResize)
    if (poolRef.value) resizeObserver.observe(poolRef.value)
  }
  if (typeof IntersectionObserver !== 'undefined') {
    intersectionObserver = new IntersectionObserver(([entry]) => {
      poolVisible = entry?.isIntersecting ?? true
      if (poolVisible) startPhysics()
      else stopPhysics()
    })
    if (poolRef.value) intersectionObserver.observe(poolRef.value)
  }
  document.addEventListener('visibilitychange', handleVisibilityChange)
  load()
})

onBeforeUnmount(() => {
  mounted = false
  releasePointerCapture()
  pointerGesture.pointerId = null
  pointerGesture.moved = false
  stopPhysics()
  resizeObserver?.disconnect()
  intersectionObserver?.disconnect()
  reducedMotionQuery?.removeEventListener?.('change', handleReducedMotionChange)
  document.removeEventListener('visibilitychange', handleVisibilityChange)
})
</script>

<style scoped>
.wish-pool {
  display: flex;
  height: 100%;
  min-height: 0;
  flex-direction: column;
  box-sizing: border-box;
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
  flex: 0 0 auto;
  width: 100%;
  text-align: left;
}
.wish-header > div {
  min-width: 0;
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
.wish-bubble-viewport {
  position: relative;
  isolation: isolate;
  flex: 1 1 auto;
  width: 100%;
  height: auto;
  min-height: 16rem;
  box-sizing: border-box;
  margin-top: 1.25rem;
  border: 1px solid color-mix(in srgb, var(--p-primary-color) 24%, var(--border-color));
  border-radius: 0.5rem;
  background:
    radial-gradient(
      ellipse at 48% 42%,
      color-mix(in srgb, var(--bg-primary) 68%, transparent) 0,
      transparent 58%
    ),
    radial-gradient(
      circle at 18% 22%,
      color-mix(in srgb, var(--p-primary-color) 11%, transparent) 0,
      transparent 32%
    ),
    radial-gradient(
      circle at 82% 76%,
      color-mix(in srgb, var(--p-cyan-500) 10%, transparent) 0,
      transparent 34%
    ),
    linear-gradient(
      145deg,
      color-mix(in srgb, var(--bg-primary) 94%, var(--p-primary-color) 6%),
      color-mix(in srgb, var(--bg-secondary) 92%, var(--p-cyan-500) 8%)
    );
  box-shadow:
    inset 0 0 0 1px color-mix(in srgb, var(--p-surface-0) 34%, transparent),
    inset 0 0 5rem color-mix(in srgb, var(--p-primary-color) 8%, transparent);
  cursor: grab;
  overflow: hidden;
  touch-action: none;
  user-select: none;
}
.wish-bubble-viewport::before,
.wish-bubble-viewport::after {
  position: absolute;
  z-index: 0;
  width: min(42rem, 84%);
  aspect-ratio: 1;
  border-radius: 50%;
  background: repeating-radial-gradient(
    circle,
    transparent 0 3.7rem,
    color-mix(in srgb, var(--p-primary-color) 9%, transparent) 3.76rem 3.82rem,
    transparent 3.88rem 7.5rem
  );
  content: '';
  opacity: 0.76;
  pointer-events: none;
}
.wish-bubble-viewport::before {
  top: -34%;
  left: -18%;
}
.wish-bubble-viewport::after {
  right: -18%;
  bottom: -38%;
  width: min(36rem, 72%);
  background: repeating-radial-gradient(
    circle,
    transparent 0 3.2rem,
    color-mix(in srgb, var(--p-cyan-500) 8%, transparent) 3.26rem 3.32rem,
    transparent 3.38rem 6.6rem
  );
}
.wish-bubble-viewport.is-panning {
  cursor: grabbing;
}
.wish-bubble-world {
  position: absolute;
  z-index: 1;
  top: 50%;
  left: 50%;
  width: 0;
  height: 0;
  transform: translate3d(0, 0, 0);
  transform-origin: center;
  will-change: transform;
}
.wish-bubble {
  --bubble-diameter: 116px;
  position: absolute;
  top: 0;
  left: 0;
  width: var(--bubble-diameter);
  height: var(--bubble-diameter);
  aspect-ratio: 1;
  isolation: isolate;
  border: 1px solid color-mix(in srgb, var(--p-primary-color) 42%, var(--border-color));
  border-radius: 50%;
  background:
    radial-gradient(
      ellipse at 30% 23%,
      color-mix(in srgb, var(--p-surface-0) 72%, transparent) 0 7%,
      transparent 29%
    ),
    radial-gradient(
      circle at 70% 76%,
      color-mix(in srgb, var(--p-cyan-500) 14%, transparent) 0,
      transparent 60%
    ),
    linear-gradient(
      145deg,
      color-mix(in srgb, var(--bg-primary) 82%, var(--p-surface-0) 18%),
      color-mix(in srgb, var(--bg-secondary) 82%, var(--p-primary-color) 18%)
    );
  box-shadow:
    0 0.55rem 1.35rem color-mix(in srgb, var(--text-primary) 10%, transparent),
    inset 0 0 0 1px color-mix(in srgb, var(--p-surface-0) 28%, transparent),
    inset -0.55rem -0.7rem 1.3rem color-mix(in srgb, var(--p-primary-color) 10%, transparent);
  color: var(--text-primary);
  overflow: hidden;
  transform: translate3d(-50%, -50%, 0);
  transition:
    width 320ms ease,
    height 320ms ease,
    border-color 180ms ease,
    box-shadow 180ms ease;
  will-change: transform;
}
.wish-bubble::before {
  position: absolute;
  z-index: 1;
  top: 10%;
  left: 17%;
  width: 38%;
  height: 22%;
  border-radius: 50%;
  background: radial-gradient(
    ellipse,
    color-mix(in srgb, var(--p-surface-0) 82%, transparent) 0,
    color-mix(in srgb, var(--p-surface-0) 28%, transparent) 48%,
    transparent 74%
  );
  content: '';
  pointer-events: none;
  transform: rotate(-24deg);
}
.wish-bubble.fulfilled {
  border-color: color-mix(in srgb, var(--p-green-500) 42%, var(--border-color));
  background:
    radial-gradient(
      ellipse at 30% 23%,
      color-mix(in srgb, var(--p-surface-0) 72%, transparent) 0 7%,
      transparent 29%
    ),
    radial-gradient(
      circle at 70% 76%,
      color-mix(in srgb, var(--p-green-500) 14%, transparent) 0,
      transparent 60%
    ),
    linear-gradient(
      145deg,
      color-mix(in srgb, var(--bg-primary) 82%, var(--p-surface-0) 18%),
      color-mix(in srgb, var(--bg-secondary) 82%, var(--p-green-500) 18%)
    );
}
.wish-bubble__open {
  position: absolute;
  z-index: 2;
  inset: 0;
  display: grid;
  width: 100%;
  height: 100%;
  place-items: center;
  border: 0;
  border-radius: 50%;
  padding: 1.1rem 0.9rem 2.7rem;
  background: transparent;
  color: inherit;
  cursor: pointer;
  font: inherit;
  text-align: center;
}
.wish-bubble__message {
  display: -webkit-box;
  max-width: 100%;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  overflow-wrap: anywhere;
  font-family: 'Huninn', 'Noto Sans TC', system-ui, sans-serif;
  font-size: clamp(0.88rem, 1.5cqi, 1.05rem);
  font-weight: 600;
  line-height: 1.35;
  text-overflow: ellipsis;
}
.wish-bubble__heart {
  position: absolute;
  z-index: 3;
  bottom: 0.8rem;
  left: 50%;
  display: inline-flex;
  min-width: 2.8rem;
  min-height: 2rem;
  align-items: center;
  justify-content: center;
  gap: 0.35rem;
  border: 0;
  border-radius: 1rem;
  padding: 0.2rem 0.55rem;
  background: color-mix(in srgb, var(--bg-primary) 78%, transparent);
  color: var(--text-secondary);
  cursor: pointer;
  font: inherit;
  font-size: 0.84rem;
  font-variant-numeric: tabular-nums;
  transform: translateX(-50%);
  transition:
    color 160ms ease,
    background-color 160ms ease;
}
.wish-bubble__heart:hover,
.wish-bubble__heart.is-active {
  background: color-mix(in srgb, var(--p-red-500) 11%, var(--bg-primary));
  color: var(--p-red-500);
}
.wish-bubble__heart:disabled {
  cursor: wait;
  opacity: 0.62;
}
.wish-bubble:hover,
.wish-bubble:focus-within {
  border-color: color-mix(in srgb, var(--p-primary-color) 58%, var(--border-color));
  box-shadow:
    0 0.65rem 1.5rem color-mix(in srgb, var(--text-primary) 12%, transparent),
    inset 0 0 0 1px color-mix(in srgb, var(--p-surface-0) 34%, transparent),
    inset -0.55rem -0.7rem 1.3rem color-mix(in srgb, var(--p-primary-color) 12%, transparent);
}
.wish-bubble__open:focus-visible,
.wish-bubble__heart:focus-visible {
  outline: 2px solid var(--p-primary-color);
  outline-offset: -3px;
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
@container (max-width: 720px) {
  .wish-header {
    align-items: stretch;
    flex-direction: column;
  }
  .wish-header :deep(.p-button) {
    width: 100%;
    justify-content: center;
  }
  .wish-bubble-viewport {
    height: clamp(28rem, 58vh, 38rem);
  }
  .wish-bubble__message {
    font-size: clamp(0.8rem, 3.4cqi, 0.98rem);
  }
}
@media (prefers-reduced-motion: reduce) {
  .wish-bubble,
  .wish-bubble__heart {
    transition: none;
  }
}
</style>
