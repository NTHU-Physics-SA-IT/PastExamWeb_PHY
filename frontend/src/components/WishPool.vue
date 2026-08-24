<template>
  <section class="wish-pool" aria-labelledby="wish-pool-title">
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
      class="wish-pool-stage"
      :class="{ 'is-panning': isPanning, 'is-mobile-layout': layoutMode === 'mobile' }"
      @pointerdown="startPan"
      @pointermove="movePan"
      @pointerup="finishPan"
      @pointercancel="finishPan"
      @dragstart.prevent
    >
      <div class="wish-pool-world" role="list" :aria-label="$t('考古許願池')" :style="worldStyle">
        <div
          v-for="wish in wishes"
          :key="wish.id"
          role="listitem"
          class="wish-node"
          :data-wish-id="wish.id"
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
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useConfirm } from 'primevue/useconfirm'
import { useToast } from 'primevue/usetoast'
import { wishService } from '@/api'
import { getCurrentUser } from '@/utils/auth'
import {
  appendResponsiveWishPositions,
  assignWishCentralityScores,
  createSeededWishRng,
  createResponsiveWishLayout,
  createWishLayoutSeed,
  selectMobileAnchorWishId,
  wishFontSizeRem,
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
const viewportRef = ref(null)
const viewportSize = ref({ width: 0, height: 0 })
const positions = ref({})
const sessionScores = ref({})
const mobileAnchorWishId = ref(null)
const layoutMode = ref('honeycomb')
const camera = reactive({ x: 0, y: 0 })
const isPanning = ref(false)
const sessionLayoutSeed = createWishLayoutSeed(Math.random)
const sessionScoreRng = createSeededWishRng(sessionLayoutSeed, 'centrality')
const sessionAnchorRng = createSeededWishRng(sessionLayoutSeed, 'mobile-anchor')
const PAN_THRESHOLD = 7
let resizeObserver
let panStart = null
let suppressNextClick = false
let suppressClickTimer
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
const worldStyle = computed(() => ({
  transform: `translate3d(${layoutMode.value === 'mobile' ? 0 : camera.x}px, ${camera.y}px, 0)`,
}))
function wishPositionStyle(wish) {
  const position = positions.value[wish.id]
  if (!position) return { visibility: 'hidden' }
  return {
    '--wish-x': `${position.x}px`,
    '--wish-y': `${position.y}px`,
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
  camera.x = layoutMode.value === 'mobile' ? 0 : panStart.cameraX + deltaX
  camera.y = panStart.cameraY + deltaY
  event.preventDefault()
}
function finishPan(event) {
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
function applyResponsiveLayout() {
  if (!wishes.value.length || !viewportSize.value.width || !viewportSize.value.height) return
  const layout = createResponsiveWishLayout(
    wishes.value,
    sessionScores.value,
    viewportSize.value,
    mobileAnchorWishId.value,
    rootFontSize(),
    sessionLayoutSeed
  )
  positions.value = layout.positions
  layoutMode.value = layout.mode
  camera.x = layout.camera.x
  camera.y = layout.camera.y
}
function measureViewport(entry) {
  const target = entry?.target || viewportRef.value
  if (!target) return
  const width = Math.round(target.clientWidth || entry?.contentRect?.width || 0)
  const height = Math.round(target.clientHeight || entry?.contentRect?.height || 0)
  if (!width || !height) return
  if (viewportSize.value.width === width && viewportSize.value.height === height) return
  viewportSize.value = { width, height }
  applyResponsiveLayout()
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
      mobileAnchorWishId.value = selectMobileAnchorWishId(incomingWishes, sessionAnchorRng)
      applyResponsiveLayout()
    } else {
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
        mobileAnchorWishId.value,
        rootFontSize(),
        sessionLayoutSeed
      )
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
    wishes.value = wishes.value.filter((wish) => wish.id !== wishId)
    const nextPositions = { ...positions.value }
    delete nextPositions[wishId]
    positions.value = nextPositions
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
  clearTimeout(suppressClickTimer)
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
.wish-pool-stage {
  position: relative;
  width: 100%;
  min-height: 0;
  box-sizing: border-box;
  flex: 1 1 auto;
  border-block: 1px solid var(--surface-border);
  margin-top: 1.25rem;
  background: var(--surface-ground);
  cursor: grab;
  overflow: hidden;
  touch-action: none;
  user-select: none;
}
.wish-pool-stage.is-panning {
  cursor: grabbing;
}
.wish-pool-world {
  position: absolute;
  left: 50%;
  top: 50%;
  width: 0;
  height: 0;
  will-change: transform;
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
  max-width: min(15rem, calc(100cqw - 2rem));
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
}
</style>
