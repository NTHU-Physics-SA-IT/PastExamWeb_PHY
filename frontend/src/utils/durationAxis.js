import { i18n } from '../i18n'

export function buildDurationAxis({ mode, maxValue }) {
  if (mode === 'hourly') {
    return { yMax: 60, yTicks: [60, 45, 30, 15, 0] }
  }

  const yMax = Math.min(24, Math.max(1, Math.ceil(Number(maxValue) || 0)))
  const step = yMax <= 3 ? 0.5 : yMax <= 6 ? 1 : yMax <= 12 ? 2 : 4
  const yTicks = []
  for (let value = yMax; value > 0; value -= step) {
    yTicks.push(Number(value.toFixed(4)))
  }
  yTicks.push(0)
  return { yMax, yTicks }
}

export function formatDurationAxisTick(value, unit) {
  const numericValue = Number(value)
  if (!Number.isFinite(numericValue) || numericValue < 0) return ''
  if (unit === 'minutes') {
    return i18n.global.locale.value === 'en' ? `${numericValue} min` : `${numericValue} 分`
  }
  if (unit !== 'hours') return ''
  const compactValue = Number.parseFloat(numericValue.toFixed(2))
  return i18n.global.locale.value === 'en' ? `${compactValue} hr` : `${compactValue} 小時`
}
