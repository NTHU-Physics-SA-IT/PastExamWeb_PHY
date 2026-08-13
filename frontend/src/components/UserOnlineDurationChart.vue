<template>
  <section class="user-duration-card" aria-labelledby="user-duration-title">
    <div class="user-duration-heading">
      <div>
        <h3 id="user-duration-title">{{ $t('在線時長統計') }}</h3>
        <p>{{ description }}</p>
      </div>
      <div class="user-duration-switch" role="group" :aria-label="$t('切換在線時長統計模式')">
        <button
          type="button"
          :class="{ 'is-active': mode === 'hourly' }"
          :aria-pressed="mode === 'hourly'"
          @click="setMode('hourly')"
        >
          {{ $t('當日在線時長紀錄') }}
        </button>
        <button
          type="button"
          :class="{ 'is-active': mode === 'daily' }"
          :aria-pressed="mode === 'daily'"
          @click="setMode('daily')"
        >
          {{ $t('每日在線時長紀錄') }}
        </button>
      </div>
    </div>

    <div class="chart-summary-control-row">
      <div
        v-if="durationSummary && !loading"
        class="chart-summary-group"
        :aria-label="mode === 'hourly' ? $t('當日在線時長摘要') : $t('每日在線時長摘要')"
      >
        <span v-for="item in durationSummary" :key="item.label" class="chart-summary-item">
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
        </span>
      </div>
      <div class="chart-control-stack user-duration-control-stack">
        <Select
          v-if="mode === 'hourly'"
          v-model="selectedDate"
          :options="recentDateOptions"
          optionLabel="label"
          optionValue="value"
          :aria-label="$t('選擇最近七日日期')"
          class="user-duration-date-select"
          @change="loadDuration"
        />
        <div v-else class="user-duration-range" role="group" :aria-label="$t('每日在線時長範圍')">
          <button
            v-for="option in DAILY_OPTIONS"
            :key="option"
            type="button"
            :class="{ 'is-active': days === option }"
            :aria-pressed="days === option"
            @click="setDays(option)"
          >
            {{ $t('{count} 日', { count: option }) }}
          </button>
        </div>
        <span class="chart-timezone-label">{{
          $t('統計時區：{zone}', { zone: PRODUCT_TIME_ZONE_LABEL })
        }}</span>
      </div>
    </div>

    <div v-if="loading" class="user-duration-state" role="status">
      <ProgressSpinner strokeWidth="4" />
      <span>{{ $t('載入在線時長紀錄…') }}</span>
    </div>
    <Message v-else-if="error" severity="error" :closable="false">
      <div class="user-duration-error">
        <span>{{ error }}</span>
        <Button
          :label="$t('重新載入')"
          icon="pi pi-refresh"
          size="small"
          outlined
          @click="loadDuration"
        />
      </div>
    </Message>
    <div v-else-if="!durationData?.history_started_at" class="user-duration-state" role="status">
      {{ $t('在線歷史資料自功能啟用後開始累積，目前尚無紀錄。') }}
    </div>
    <div v-else-if="!hasAvailableHistory" class="user-duration-state" role="status">
      {{ $t('此日期範圍尚無在線時長紀錄。') }}
    </div>
    <div v-else class="user-duration-chart" role="img" :aria-label="chartAriaLabel">
      <div class="user-duration-chart__y-axis" aria-hidden="true">
        <span v-for="tick in chartData.yTicks" :key="`duration-y-${tick}`">
          {{ formatAxisTick(tick) }}
        </span>
      </div>
      <div class="user-duration-chart__plot">
        <div class="user-duration-chart__grid" aria-hidden="true">
          <span
            v-for="tick in chartData.yTicks"
            :key="`duration-grid-${tick}`"
            :style="{ bottom: `${(tick / chartData.yMax) * 100}%` }"
          ></span>
        </div>
        <div
          class="user-duration-chart__bars"
          :style="{ '--duration-chart-columns': chartData.buckets.length }"
        >
          <div
            v-for="bucket in chartData.buckets"
            :key="bucket.start"
            class="user-duration-chart__item"
            tabindex="0"
            :aria-label="
              $t('{label}，在線時長 {duration}', {
                label: bucket.fullLabel,
                duration: formatDuration(bucket.duration_seconds),
              })
            "
          >
            <span
              class="user-duration-chart__bar"
              :class="{ 'has-value': bucket.duration_seconds > 0 }"
              :style="{ height: `${(bucket.chartValue / chartData.yMax) * 100}%` }"
            ></span>
            <span class="user-duration-chart__tooltip" role="tooltip">
              <strong>{{ bucket.fullLabel }}</strong>
              <span>{{
                $t('在線時長：{duration}', { duration: formatDuration(bucket.duration_seconds) })
              }}</span>
            </span>
          </div>
        </div>
        <div
          class="user-duration-chart__x-axis"
          :style="{ '--duration-chart-columns': chartData.buckets.length }"
          aria-hidden="true"
        >
          <span
            v-for="bucket in chartData.buckets"
            :key="`duration-label-${bucket.start}`"
            :class="{ 'is-multiline': bucket.isMultiline }"
          >
            <template v-if="bucket.showLabel">
              <span v-for="line in bucket.labelLines" :key="line">{{ line }}</span>
            </template>
          </span>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { getUserOnlineDuration } from '../api'
import {
  PRODUCT_TIME_ZONE,
  PRODUCT_TIME_ZONE_LABEL,
  addCalendarDays,
  formatProductDate,
  getProductDateString,
  getProductTimeParts,
} from '../utils/productTimezone'
import { buildTemporalTicks } from '../utils/temporalChart'
import { buildOnlineDurationSummary, formatDuration } from '../utils/onlineDurationSummary'
import { buildDurationAxis, formatDurationAxisTick } from '../utils/durationAxis'

const props = defineProps({
  userId: { type: Number, default: null },
  active: { type: Boolean, default: false },
})
const { t, locale } = useI18n()

const DAILY_OPTIONS = [7, 30, 90]
const mode = ref('hourly')
const days = ref(7)
const todayDate = ref(getProductDateString())
const selectedDate = ref(todayDate.value)
const durationData = ref(null)
const loading = ref(false)
const error = ref('')
let requestController = null

const recentDateOptions = computed(() => {
  return Array.from({ length: 7 }, (_, index) => {
    const value = addCalendarDays(todayDate.value, -index)
    return {
      value,
      label: new Intl.DateTimeFormat(locale.value, {
        timeZone: 'UTC',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
      }).format(new Date(`${value}T00:00:00Z`)),
    }
  })
})

const description = computed(() =>
  mode.value === 'hourly'
    ? t('統計 {date} 每小時的在線使用時長。', {
        date:
          recentDateOptions.value.find(({ value }) => value === selectedDate.value)?.label ||
          selectedDate.value,
      })
    : t('統計最近 {count} 個日曆日的每日在線使用時長。', { count: days.value })
)

const chartData = computed(() => {
  const points = Array.isArray(durationData.value?.points) ? durationData.value.points : []
  const divisor = mode.value === 'hourly' ? 60 : 3600
  const maxValue = Math.max(0, ...points.map(({ duration_seconds }) => duration_seconds / divisor))
  const { yMax, yTicks } = buildDurationAxis({ mode: mode.value, maxValue })
  const labelEvery = mode.value === 'hourly' ? 3 : days.value === 7 ? 1 : days.value === 30 ? 5 : 15
  const ticks = buildTemporalTicks(points, {
    mode: mode.value === 'hourly' ? 'hour' : 'date',
    labelEvery,
    minGap: mode.value === 'hourly' ? 2 : 1,
  })
  const buckets = points.map((point, index) => {
    const start = new Date(point.start)
    const { hour } = getProductTimeParts(start)
    const { hour: endHour } = getProductTimeParts(point.end)
    return {
      ...point,
      ...ticks[index],
      chartValue: point.duration_seconds / divisor,
      fullLabel:
        mode.value === 'hourly'
          ? `${formatProductDate(start, { includeYear: true })} ${hour}:00–${endHour}:00`
          : formatProductDate(start, { includeYear: true }),
    }
  })
  return { buckets, yMax, yTicks }
})

const hasAvailableHistory = computed(() => chartData.value.buckets.some(({ has_data }) => has_data))
const durationSummary = computed(() => {
  if (!durationData.value?.history_started_at || !hasAvailableHistory.value || error.value)
    return null
  const points = chartData.value.buckets
  const { totalSeconds, averageSeconds, peakSeconds } = buildOnlineDurationSummary({
    points,
    mode: mode.value,
    days: days.value,
    isToday: selectedDate.value === todayDate.value,
  })
  if (mode.value === 'daily') {
    return [
      { label: t('區間總時長'), value: formatDuration(totalSeconds) },
      { label: t('每日平均'), value: formatDuration(averageSeconds) },
      { label: t('單日峰值'), value: formatDuration(peakSeconds) },
    ]
  }
  return [
    { label: t('當日總時長'), value: formatDuration(totalSeconds) },
    { label: t('每小時平均'), value: formatDuration(averageSeconds) },
    { label: t('單小時峰值'), value: formatDuration(peakSeconds) },
  ]
})
const chartAriaLabel = computed(() =>
  mode.value === 'hourly'
    ? t('統計 {date} 的二十四小時在線時長分布', { date: selectedDate.value })
    : t('統計最近 {count} 個日曆日的每日在線時長分布', { count: days.value })
)
const formatAxisTick = (value) =>
  formatDurationAxisTick(value, mode.value === 'hourly' ? 'minutes' : 'hours')

const validateResponse = (data) => {
  const expectedCount = mode.value === 'hourly' ? 24 : days.value
  return (
    data?.user_id === props.userId &&
    data?.mode === mode.value &&
    data?.timezone === PRODUCT_TIME_ZONE &&
    Number.isInteger(data?.online_timeout_seconds) &&
    Array.isArray(data?.points) &&
    data.points.length === expectedCount &&
    data.points.every(
      (point) =>
        point?.start &&
        point?.end &&
        Number.isInteger(point?.duration_seconds) &&
        point.duration_seconds >= 0 &&
        typeof point.has_data === 'boolean'
    )
  )
}

const loadDuration = async () => {
  if (!props.active || !props.userId) return
  requestController?.abort()
  const controller = new AbortController()
  requestController = controller
  loading.value = true
  error.value = ''
  try {
    const { data } = await getUserOnlineDuration(props.userId, {
      mode: mode.value,
      date: selectedDate.value,
      days: days.value,
      signal: controller.signal,
    })
    if (requestController !== controller) return
    if (!validateResponse(data)) throw new TypeError('Invalid user online duration response')
    durationData.value = data
  } catch (requestError) {
    if (requestError?.code === 'ERR_CANCELED' || requestController !== controller) return
    durationData.value = null
    error.value = t('在線時長載入失敗，請稍後再試。')
  } finally {
    if (requestController === controller) {
      loading.value = false
      requestController = null
    }
  }
}

const setMode = (value) => {
  if (mode.value === value) return
  mode.value = value
  void loadDuration()
}
const setDays = (value) => {
  if (days.value === value) return
  days.value = value
  void loadDuration()
}

watch(
  () => [props.userId, props.active],
  ([userId, active], previous = []) => {
    const wasActive = previous[1]
    if (userId && active) {
      if (!wasActive) {
        mode.value = 'hourly'
        days.value = 7
        todayDate.value = getProductDateString()
        selectedDate.value = todayDate.value
      }
      void loadDuration()
    }
    if (!active) requestController?.abort()
  },
  { immediate: true }
)

onBeforeUnmount(() => requestController?.abort())
</script>

<style scoped>
.user-duration-card {
  container: user-duration / inline-size;
  display: grid;
  gap: 0.75rem;
  min-width: 0;
  padding: 0.85rem;
  border: 1px solid var(--border-color);
  border-radius: 9px;
  background: var(--bg-secondary);
  color: var(--text-color);
}

.user-duration-card .chart-summary-item {
  flex: 1 1 0;
  min-width: 0;
}

@container user-duration (max-width: 640px) {
  .user-duration-card .user-duration-heading {
    align-items: stretch;
    flex-direction: column;
  }

  .user-duration-card .user-duration-switch {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    width: 100%;
  }

  .user-duration-card .user-duration-switch > button {
    box-sizing: border-box;
    min-width: 0;
    width: 100%;
    white-space: normal;
  }

  .user-duration-card .user-duration-date-select,
  .user-duration-card .user-duration-control-stack {
    width: 100%;
  }

  .user-duration-card .chart-summary-group {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0.3rem;
    width: 100%;
  }

  .user-duration-card .chart-summary-item {
    box-sizing: border-box;
    min-width: 0;
    width: 100%;
    padding: 0.35rem 0.2rem;
    justify-items: center;
    text-align: center;
  }

  .user-duration-card .chart-summary-item > span,
  .user-duration-card .chart-summary-item > strong {
    max-width: 100%;
    text-align: center;
    white-space: normal;
  }

  .user-duration-card .chart-summary-item > span {
    word-break: keep-all;
  }

  .user-duration-card .chart-summary-item > strong {
    overflow-wrap: anywhere;
  }
}

.user-duration-heading,
.user-duration-switch,
.user-duration-range,
.user-duration-error {
  display: flex;
  align-items: center;
}

.user-duration-heading {
  justify-content: space-between;
  gap: 0.65rem 1rem;
}

.user-duration-heading h3,
.user-duration-heading p {
  margin: 0;
}

.user-duration-heading h3 {
  font-size: var(--app-font-size-base);
}

.user-duration-heading p {
  margin-top: 0.15rem;
  color: var(--text-secondary);
  font-size: var(--app-font-size-xs);
  line-height: 1.4;
}

.user-duration-switch,
.user-duration-range {
  flex-wrap: wrap;
  gap: 0.25rem;
  padding: 0.2rem;
  border: 1px solid var(--border-color);
  border-radius: 7px;
  background: var(--bg-primary);
}

.user-duration-switch button,
.user-duration-range button {
  min-height: 2.35rem;
  padding: 0.38rem 0.62rem;
  border: 1px solid transparent;
  border-radius: 5px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  font: inherit;
  font-size: var(--app-font-size-xs);
  font-weight: 700;
}

.user-duration-switch button.is-active,
.user-duration-range button.is-active {
  border-color: color-mix(in srgb, var(--p-primary-color) 42%, var(--border-color));
  background: color-mix(in srgb, var(--p-primary-color) 12%, var(--bg-primary));
  color: var(--text-color);
}

.user-duration-switch button:focus-visible,
.user-duration-range button:focus-visible {
  outline: 2px solid var(--p-primary-color);
  outline-offset: 2px;
}

.user-duration-date-select {
  width: min(100%, 14rem);
}

.user-duration-control-stack {
  min-width: min(100%, 14rem);
}

.user-duration-state {
  display: flex;
  min-height: 8rem;
  align-items: center;
  justify-content: center;
  gap: 0.65rem;
  padding: 1rem;
  border: 1px dashed var(--border-color);
  border-radius: 7px;
  color: var(--text-secondary);
  font-size: var(--app-font-size-sm);
  text-align: center;
}

.user-duration-state :deep(.p-progressspinner) {
  width: 2rem;
  height: 2rem;
}

.user-duration-error {
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 0.5rem 1rem;
}

.user-duration-chart {
  --temporal-edge-padding: 1.35rem;
  display: grid;
  grid-template-columns: 3.5rem minmax(0, 1fr);
  gap: 0.5rem;
  min-width: 0;
  height: clamp(13rem, 34vw, 18rem);
  padding-top: 0.35rem;
  font-size: var(--app-font-size-xs);
}

.user-duration-chart__y-axis {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  height: calc(100% - 2.55rem);
  color: var(--text-secondary);
  text-align: right;
}

.user-duration-chart__y-axis span {
  white-space: nowrap;
}

.user-duration-chart__plot {
  position: relative;
  min-width: 0;
  height: 100%;
  border-left: 1px solid var(--border-color);
  border-bottom: 1px solid var(--border-color);
}

.user-duration-chart__grid,
.user-duration-chart__bars {
  position: absolute;
  inset: 0 0 2.55rem;
}

.user-duration-chart__grid span {
  position: absolute;
  right: 0;
  left: 0;
  border-top: 1px solid color-mix(in srgb, var(--border-color) 70%, transparent);
}

.user-duration-chart__bars,
.user-duration-chart__x-axis {
  display: grid;
  grid-template-columns: repeat(var(--duration-chart-columns), minmax(0, 1fr));
}

.user-duration-chart__bars {
  box-sizing: border-box;
  z-index: 1;
  align-items: end;
  gap: clamp(1px, 0.25vw, 3px);
  padding-inline: var(--temporal-edge-padding);
}

.user-duration-chart__item {
  position: relative;
  display: flex;
  min-width: 0;
  height: 100%;
  align-items: flex-end;
  justify-content: center;
  outline: none;
}

.user-duration-chart__bar {
  display: block;
  width: 100%;
  min-height: 0;
  border-radius: 4px 4px 1px 1px;
}

.user-duration-chart__bar.has-value {
  background: var(--p-primary-color);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--p-primary-color) 60%, transparent);
}

.user-duration-chart__tooltip {
  position: absolute;
  z-index: 4;
  bottom: calc(100% + 0.35rem);
  left: 50%;
  display: none;
  width: max-content;
  max-width: min(20rem, calc(100vw - 3rem));
  padding: 0.4rem 0.55rem;
  border: 1px solid var(--border-color);
  border-radius: 5px;
  background: var(--bg-primary);
  color: var(--text-color);
  font-size: var(--app-font-size-xs);
  line-height: 1.4;
  overflow-wrap: anywhere;
  transform: translateX(-50%);
}

.user-duration-chart__tooltip strong,
.user-duration-chart__tooltip span {
  display: block;
}

.user-duration-chart__item:hover,
.user-duration-chart__item:focus-visible {
  z-index: 3;
}

.user-duration-chart__item:hover .user-duration-chart__tooltip,
.user-duration-chart__item:focus-visible .user-duration-chart__tooltip {
  display: block;
}

.user-duration-chart__item:first-child .user-duration-chart__tooltip {
  left: 0;
  transform: none;
}

.user-duration-chart__item:last-child .user-duration-chart__tooltip {
  right: 0;
  left: auto;
  transform: none;
}

.user-duration-chart__item:focus-visible {
  box-shadow: inset 0 0 0 2px var(--p-primary-color);
}

.user-duration-chart__x-axis {
  position: absolute;
  right: 0;
  bottom: 0;
  left: 0;
  box-sizing: border-box;
  height: 2.5rem;
  align-items: start;
  gap: 1px;
  padding: 0.35rem var(--temporal-edge-padding) 0;
  color: var(--text-secondary);
  text-align: center;
}

.user-duration-chart__x-axis > span {
  min-width: 0;
  font-size: var(--app-font-size-xs);
  line-height: 1.1;
  white-space: nowrap;
}

.user-duration-chart__x-axis > span > span {
  display: block;
}

@media (max-width: 640px) {
  .user-duration-chart {
    grid-template-columns: 2.75rem minmax(0, 1fr);
    height: 14rem;
  }
}
</style>
