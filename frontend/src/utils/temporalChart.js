import { i18n } from '../i18n'
import { formatProductDate, getProductTimeParts } from './productTimezone'

function formatHourLabel(hour) {
  return i18n.global.locale.value === 'en' ? `${hour}:00` : `${hour} 時`
}

export function resolveTemporalTickLayout({
  baseLabelEvery,
  chartWidth,
  pointCount,
  mode,
  fontScale = 1,
}) {
  const base = Math.max(1, Math.floor(Number(baseLabelEvery) || 1))
  const width = Number(chartWidth)
  const count = Math.max(0, Math.floor(Number(pointCount) || 0))
  if (!Number.isFinite(width) || width <= 0 || count <= 2) {
    return {
      labelEvery: base,
      minGap: mode === 'hour' ? Math.max(6, Math.floor(base / 2)) : 1,
    }
  }

  const scale = Math.min(1.5, Math.max(0.75, Number(fontScale) || 1))
  const minimumLabelWidth = (mode === 'hour' ? 64 : 58) * scale
  const visibleLabelCapacity = Math.max(2, Math.floor(width / minimumLabelWidth))
  const responsiveEvery = Math.ceil((count - 1) / Math.max(1, visibleLabelCapacity - 1))
  const pointSpacing = width / Math.max(1, count - 1)
  const labelEvery = Math.max(base, responsiveEvery)

  return {
    labelEvery,
    minGap:
      responsiveEvery > base
        ? Math.max(1, Math.ceil(minimumLabelWidth / pointSpacing))
        : mode === 'hour'
          ? Math.max(6, Math.floor(base / 2))
          : 1,
  }
}

export function resolveTemporalLabelEvery(options) {
  return resolveTemporalTickLayout(options).labelEvery
}

function selectVisibleTicks(points, { labelEvery, includeMidnights, minGap }) {
  if (points.length === 0) return new Set()
  const lastIndex = points.length - 1
  const visibleIndexes = new Set([0, lastIndex])
  const canAdd = (index) =>
    [...visibleIndexes].every((visibleIndex) => Math.abs(visibleIndex - index) >= minGap)

  if (includeMidnights) {
    points.forEach((point, index) => {
      const { hour, minute } = getProductTimeParts(point.start)
      if (hour === '00' && minute === '00' && canAdd(index)) visibleIndexes.add(index)
    })
  }

  points.forEach((_point, index) => {
    if (index % labelEvery !== 0 || visibleIndexes.has(index)) return
    if (canAdd(index)) visibleIndexes.add(index)
  })
  return visibleIndexes
}

export function buildTemporalTicks(points, { mode, labelEvery, minGap = mode === 'hour' ? 8 : 1 }) {
  const includeMidnights = mode === 'hour'
  const visibleIndexes = selectVisibleTicks(points, {
    labelEvery,
    includeMidnights,
    minGap,
  })

  return points.map((point, index) => {
    const parts = getProductTimeParts(point.start)
    const isMidnight = parts.hour === '00' && parts.minute === '00'
    const labelLines =
      mode === 'date'
        ? [formatProductDate(point.start)]
        : isMidnight
          ? [formatHourLabel(parts.hour), formatProductDate(point.start)]
          : [formatHourLabel(parts.hour)]
    return {
      labelLines,
      showLabel: visibleIndexes.has(index),
      isMultiline: labelLines.length > 1,
    }
  })
}
