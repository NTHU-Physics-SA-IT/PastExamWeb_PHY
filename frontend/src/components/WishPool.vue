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
    <div v-else class="wish-cloud-stage">
      <div
        ref="cloudRef"
        class="wish-cloud"
        role="list"
        :aria-label="$t('考古許願池')"
        :style="cloudStyle"
      >
        <button
          v-for="wish in wishes"
          :key="wish.id"
          :ref="(element) => setWordRef(wish.id, element)"
          type="button"
          role="listitem"
          class="wish-word"
          :class="{ fulfilled: wish.fulfilled }"
          :style="wordStyle(wish)"
          @click="selected = wish"
        >
          <span class="wish-word__title">{{ wish.title }}</span>
          <small>♥ {{ wish.heart_count }}</small>
          <span v-if="wish.fulfilled" class="fulfilled-label">{{ $t('已實現') }}</span>
        </button>
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
              @click="toggleHeart"
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
const poolRef = ref(null)
const cloudRef = ref(null)
const wordElements = new Map()
const positions = ref({})
const fittedFontSizes = ref({})
const cloudDimensions = ref({ width: 0, height: 0 })
let resizeObserver
let layoutFrame
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
const densityFontBoost = computed(() => Math.max(0, (16 - wishes.value.length) / 16) * 0.22)
const baseFontSize = (count) =>
  Math.min(2.5, 1.05 + densityFontBoost.value + Math.log2(Number(count || 0) + 1) * 0.27)
function stableHash(value) {
  let hash = 2166136261
  for (const character of String(value)) {
    hash ^= character.charCodeAt(0)
    hash = Math.imul(hash, 16777619)
  }
  return hash >>> 0
}
function setWordRef(id, element) {
  if (element) wordElements.set(id, element)
  else wordElements.delete(id)
}
function overlaps(candidate, placed) {
  const gap = 12
  return placed.some(
    (box) =>
      candidate.x < box.x + box.width + gap &&
      candidate.x + candidate.width + gap > box.x &&
      candidate.y < box.y + box.height + gap &&
      candidate.y + candidate.height + gap > box.y
  )
}
async function layoutCloud() {
  if (!cloudRef.value || !poolRef.value || !wishes.value.length) {
    positions.value = {}
    fittedFontSizes.value = {}
    cloudDimensions.value = { width: 0, height: 0 }
    return
  }
  const maxWidth = Math.max(140, Math.min(1100, poolRef.value.clientWidth - 32))
  cloudDimensions.value = { width: maxWidth, height: 1 }
  positions.value = {}
  await nextTick()
  const placed = []
  const nextPositions = {}
  const goldenAngle = Math.PI * (3 - Math.sqrt(5))
  const horizontalLayout = maxWidth >= 560
  const horizontalScale = horizontalLayout ? 1.32 : 0.96
  const verticalScale = horizontalLayout ? 0.62 : 0.82
  const ordered = [...wishes.value].sort((left, right) => Number(left.id) - Number(right.id))
  fittedFontSizes.value = Object.fromEntries(
    ordered.map((wish) => [wish.id, baseFontSize(wish.heart_count)])
  )
  await nextTick()
  const maxTokenWidth = maxWidth - 12
  const nextFontSizes = { ...fittedFontSizes.value }
  for (const wish of ordered) {
    const element = wordElements.get(wish.id)
    if (!element || element.offsetWidth <= maxTokenWidth) continue
    nextFontSizes[wish.id] *= (maxTokenWidth / element.offsetWidth) * 0.98
  }
  fittedFontSizes.value = nextFontSizes
  await nextTick()
  for (const wish of ordered) {
    const element = wordElements.get(wish.id)
    if (!element) continue
    const width = Math.min(element.offsetWidth, maxWidth - 12)
    const height = element.offsetHeight
    const hash = stableHash(wish.id)
    const startAngle = ((hash % 360) * Math.PI) / 180
    let candidate
    for (let attempt = 0; attempt < 3000; attempt += 1) {
      const radius = 8 * Math.sqrt(attempt)
      const angle = startAngle + attempt * goldenAngle
      const trial = {
        x: Math.cos(angle) * radius * horizontalScale - width / 2,
        y: Math.sin(angle) * radius * verticalScale - height / 2,
        width,
        height,
      }
      if (trial.x < -maxWidth / 2 || trial.x + width > maxWidth / 2) continue
      if (!overlaps(trial, placed)) {
        candidate = trial
        break
      }
    }
    candidate ||= {
      x: -width / 2,
      y: placed.reduce((bottom, box) => Math.max(bottom, box.y + box.height), 0) + 10,
      width,
      height,
    }
    placed.push(candidate)
    nextPositions[wish.id] = { ...candidate, rotation: (hash % 3) - 1 }
  }
  const padding = 24
  const minX = Math.min(...placed.map((box) => box.x))
  const maxX = Math.max(...placed.map((box) => box.x + box.width))
  const minY = Math.min(...placed.map((box) => box.y))
  const maxY = Math.max(...placed.map((box) => box.y + box.height))
  for (const position of Object.values(nextPositions)) {
    position.left = position.x - minX + padding
    position.top = position.y - minY + padding
  }
  positions.value = nextPositions
  cloudDimensions.value = {
    width: Math.min(maxWidth, Math.max(140, maxX - minX + padding * 2)),
    height: Math.max(120, maxY - minY + padding * 2),
  }
}
function scheduleLayout() {
  if (typeof requestAnimationFrame === 'undefined') {
    nextTick(layoutCloud)
    return
  }
  if (layoutFrame) cancelAnimationFrame(layoutFrame)
  layoutFrame = requestAnimationFrame(() => layoutCloud())
}
const cloudStyle = computed(() => ({
  width: cloudDimensions.value.width ? `${cloudDimensions.value.width}px` : '100%',
  height: cloudDimensions.value.height ? `${cloudDimensions.value.height}px` : 'auto',
}))
function wordStyle(wish) {
  const position = positions.value[wish.id]
  return {
    fontSize: `${fittedFontSizes.value[wish.id] || baseFontSize(wish.heart_count)}rem`,
    left: position ? `${position.left}px` : '50%',
    top: position ? `${position.top}px` : '50%',
    transform: position ? `rotate(${position.rotation}deg)` : 'translate(-50%, -50%)',
    visibility: position ? 'visible' : 'hidden',
  }
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
async function toggleHeart() {
  if (!selected.value || heartLoading.value) return
  heartLoading.value = true
  try {
    const { data } = await wishService.toggleHeart(selected.value.id)
    Object.assign(selected.value, { hearted_by_me: data.hearted, heart_count: data.heart_count })
    const item = wishes.value.find((wish) => wish.id === selected.value.id)
    if (item) Object.assign(item, selected.value)
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
watch(
  () => wishes.value.map((wish) => `${wish.id}:${wish.title}:${wish.heart_count}`).join('|'),
  scheduleLayout
)
onMounted(() => {
  if (typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(scheduleLayout)
    if (poolRef.value) resizeObserver.observe(poolRef.value)
  }
  load()
  const fontLoad = document.fonts?.load?.('1rem Huninn')
  if (fontLoad) void fontLoad.then(scheduleLayout).catch(scheduleLayout)
})
onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  if (layoutFrame && typeof cancelAnimationFrame !== 'undefined') cancelAnimationFrame(layoutFrame)
})
</script>

<style scoped>
.wish-pool {
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
.wish-cloud {
  position: relative;
  max-width: 1100px;
  margin: 0 auto;
  overflow: visible;
}
.wish-cloud-stage {
  display: flex;
  width: 100%;
  min-height: clamp(26rem, 58vh, 42rem);
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  padding: clamp(5rem, 11vh, 8rem) 0 clamp(2.5rem, 6vh, 4.5rem);
  overflow: visible;
}
.wish-word {
  position: absolute;
  display: inline-flex;
  width: max-content;
  max-width: none;
  align-items: baseline;
  flex: 0 0 auto;
  gap: 0.3em;
  border: 0;
  background: transparent;
  color: var(--text-color);
  cursor: pointer;
  padding: 0.35em;
  border-radius: 0.5em;
  line-height: 1.25;
  overflow-wrap: normal;
  white-space: nowrap;
  transform-origin: center;
  font-family: 'Huninn', 'Noto Sans TC', system-ui, sans-serif;
}
.wish-word__title,
.wish-word small,
.fulfilled-label {
  white-space: nowrap;
}
.wish-word small,
.fulfilled-label {
  flex: 0 0 auto;
}
.wish-word:hover,
.wish-word:focus-visible {
  background: var(--surface-hover);
  outline: 2px solid var(--primary-color);
}
.wish-word small,
.fulfilled-label {
  font-size: 0.7em;
  margin-left: 0;
}
.fulfilled-label {
  font-weight: 700;
}
.wish-word.fulfilled {
  color: var(--green-600);
  font-weight: 600;
}
.wish-word.fulfilled:hover,
.wish-word.fulfilled:focus-visible {
  color: var(--green-500);
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
  .wish-cloud-stage {
    min-height: clamp(20rem, 50vh, 30rem);
    padding: clamp(3.5rem, 9vh, 5.5rem) 0 clamp(2rem, 5vh, 3rem);
  }
}
</style>
