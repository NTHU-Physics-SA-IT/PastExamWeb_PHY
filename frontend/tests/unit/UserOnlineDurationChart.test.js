import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import process from 'node:process'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import UserOnlineDurationChart from '@/components/UserOnlineDurationChart.vue'
import { applyFontSizePreference } from '@/utils/fontSizePreference'

const getUserOnlineDurationMock = vi.hoisted(() => vi.fn())

vi.mock('@/api', () => ({
  getUserOnlineDuration: getUserOnlineDurationMock,
}))

const componentSource = readFileSync(
  resolve(process.cwd(), 'src/components/UserOnlineDurationChart.vue'),
  'utf8'
)

const makeResponse = ({
  mode = 'hourly',
  days = 7,
  history = true,
  durationSeconds = mode === 'hourly' ? 1140 : 9300,
  valueIndex = mode === 'hourly' ? 4 : 3,
} = {}) => {
  const count = mode === 'hourly' ? 24 : days
  const bucketMs = mode === 'hourly' ? 3_600_000 : 86_400_000
  const rangeStart = Date.UTC(2026, 6, 14, 16) - (mode === 'daily' ? (days - 1) * bucketMs : 0)
  const points = Array.from({ length: count }, (_, index) => ({
    start: new Date(rangeStart + index * bucketMs).toISOString(),
    end: new Date(rangeStart + (index + 1) * bucketMs).toISOString(),
    duration_seconds: index === valueIndex ? durationSeconds : 0,
    has_data: history && index <= valueIndex,
  }))
  return {
    user_id: 7,
    mode,
    timezone: 'Asia/Taipei',
    online_timeout_seconds: 300,
    range_start: points[0].start,
    range_end: points.at(-1).end,
    history_started_at: history ? points[0].start : null,
    points,
  }
}

const stubs = {
  Select: {
    props: ['modelValue', 'options'],
    template: '<select aria-label="選擇最近七日日期"><option>{{ modelValue }}</option></select>',
  },
  ProgressSpinner: { template: '<span class="spinner" />' },
  Message: { template: '<div class="message"><slot /></div>' },
  Button: { props: ['label'], template: '<button>{{ label }}</button>' },
}

const mountChart = () =>
  mount(UserOnlineDurationChart, {
    props: { userId: 7, active: true },
    global: { stubs },
  })

describe('UserOnlineDurationChart', () => {
  it('keeps all three duration summary cards in one mobile grid row', () => {
    expect(componentSource).toMatch(
      /\.user-duration-card\s*\{[^}]*container: user-duration \/ inline-size;/
    )
    expect(componentSource).toMatch(
      /@container user-duration \(max-width: 40rem\)[\s\S]*?\.user-duration-card \.chart-summary-group\s*\{[^}]*display: grid;[^}]*grid-template-columns: repeat\(3, minmax\(0, 1fr\)\);[^}]*width: 100%;/
    )
    expect(componentSource).toMatch(
      /@container user-duration \(max-width: 40rem\)[\s\S]*?\.user-duration-card \.user-duration-switch\s*\{[^}]*display: grid;[^}]*grid-template-columns: repeat\(2, minmax\(0, 1fr\)\);[^}]*width: 100%;/
    )
    expect(componentSource).toMatch(
      /\.user-duration-card \.chart-summary-item\s*\{[^}]*box-sizing: border-box;[^}]*min-width: 0;[^}]*width: 100%;[^}]*justify-items: center;[^}]*text-align: center;/
    )
  })

  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-07-15T15:30:00Z'))
    getUserOnlineDurationMock.mockReset()
    getUserOnlineDurationMock.mockImplementation((_userId, options) =>
      Promise.resolve({ data: makeResponse({ mode: options.mode, days: options.days }) })
    )
  })

  afterEach(() => {
    applyFontSizePreference(100)
    vi.useRealTimers()
  })

  it('defaults to today hourly mode and renders exactly 24 accessible bars before submission data', async () => {
    const wrapper = mountChart()
    await flushPromises()

    expect(getUserOnlineDurationMock).toHaveBeenCalledWith(
      7,
      expect.objectContaining({ mode: 'hourly', date: '2026-07-15' })
    )
    expect(wrapper.text()).toContain('當日在線時長紀錄')
    expect(wrapper.text()).toContain('每日在線時長紀錄')
    expect(wrapper.findAll('.user-duration-chart__item')).toHaveLength(24)
    expect(wrapper.find('[aria-label="選擇最近七日日期"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('在線時長：19 分鐘')
    expect(wrapper.text()).toContain('統計 2026/07/15 每小時的在線使用時長。')
    expect(wrapper.text()).toContain('統計時區：UTC+8')
    expect(wrapper.text()).toContain('當日總時長19 分鐘')
    expect(wrapper.text()).toContain('每小時平均')
    expect(wrapper.text()).toContain('單小時峰值19 分鐘')
    const controlRow = wrapper.find('.chart-summary-control-row')
    expect(controlRow.findAll(':scope > div')[0].classes()).toContain('chart-summary-group')
    expect(controlRow.findAll(':scope > div')[1].classes()).toContain('chart-control-stack')
    const midnightLabel = wrapper.find('.user-duration-chart__x-axis > span')
    expect(midnightLabel.findAll('span').map((line) => line.text())).toEqual(['00 時', '07/15'])
    expect(wrapper.find('canvas').exists()).toBe(false)
    expect(componentSource).not.toContain('收合')
  })

  it('maps seconds to numeric chart units and renders a visible proportional bar', async () => {
    const wrapper = mountChart()
    await flushPromises()

    const bars = wrapper.findAll('.user-duration-chart__bar')
    expect(bars).toHaveLength(24)
    expect(bars[4].classes()).toContain('has-value')
    expect(bars[4].attributes('style')).toContain('height: 31.666')
    expect(bars[5].classes()).not.toContain('has-value')
    expect(bars[5].attributes('style')).toContain('height: 0%')
    expect(componentSource).toContain('chartValue: point.duration_seconds / divisor')
    expect(componentSource).toContain('background: var(--p-primary-color)')
    expect(componentSource).not.toContain('background: var(--primary-color)')
    expect(componentSource).not.toContain('minBarLength')
  })

  it('preserves sub-minute precision and future zero-value tooltips', async () => {
    getUserOnlineDurationMock.mockResolvedValueOnce({
      data: makeResponse({ durationSeconds: 30 }),
    })
    const wrapper = mountChart()
    await flushPromises()

    expect(wrapper.findAll('.user-duration-chart__bar')[4].attributes('style')).toContain(
      'height: 0.833'
    )
    expect(wrapper.text()).toContain('在線時長：30 秒')
    expect(wrapper.findAll('.user-duration-chart__item')[18].attributes('aria-label')).toContain(
      '在線時長 0 秒'
    )
  })

  it('uses the product calendar date when UTC is still on the previous day', async () => {
    vi.setSystemTime(new Date('2026-07-14T16:05:00Z'))
    const wrapper = mountChart()
    await flushPromises()

    expect(getUserOnlineDurationMock).toHaveBeenCalledWith(
      7,
      expect.objectContaining({ mode: 'hourly', date: '2026-07-15' })
    )
    expect(wrapper.findAll('.user-duration-chart__item')[0].attributes('aria-label')).toContain(
      '2026/07/15 00:00–01:00'
    )
  })

  it('resets mode and product date when the dialog is reopened', async () => {
    const wrapper = mountChart()
    await flushPromises()
    await wrapper.findAll('.user-duration-switch button')[1].trigger('click')
    await flushPromises()

    await wrapper.setProps({ active: false })
    vi.setSystemTime(new Date('2026-07-15T16:05:00Z'))
    await wrapper.setProps({ active: true })
    await flushPromises()

    expect(getUserOnlineDurationMock).toHaveBeenLastCalledWith(
      7,
      expect.objectContaining({ mode: 'hourly', date: '2026-07-16', days: 7 })
    )
  })

  it.each([7, 30, 90])(
    'loads and renders %s daily points without horizontal data padding',
    async (days) => {
      const wrapper = mountChart()
      await flushPromises()
      await wrapper.findAll('.user-duration-switch button')[1].trigger('click')
      await flushPromises()
      const rangeButton = wrapper
        .findAll('.user-duration-range button')
        .find((button) => button.text() === `${days} 日`)
      if (days !== 7) {
        await rangeButton.trigger('click')
        await flushPromises()
      }

      expect(getUserOnlineDurationMock).toHaveBeenLastCalledWith(
        7,
        expect.objectContaining({ mode: 'daily', days })
      )
      expect(wrapper.findAll('.user-duration-chart__item')).toHaveLength(days)
      expect(wrapper.findAll('.user-duration-chart__bar')[3].classes()).toContain('has-value')
      expect(wrapper.findAll('.user-duration-chart__bar')[3].attributes('style')).not.toContain(
        'height: 0%'
      )
      const yAxisLabels = wrapper
        .findAll('.user-duration-chart__y-axis span')
        .map((label) => label.text())
      expect(yAxisLabels).toContain('0.5 小時')
      expect(yAxisLabels).not.toContain('30 分鐘')
      expect(yAxisLabels.every((label) => !label.includes('小時 30 分鐘'))).toBe(true)
      expect(wrapper.text()).toContain(`統計最近 ${days} 個日曆日的每日在線使用時長。`)
      expect(wrapper.text()).toContain('區間總時長2 小時 35 分鐘')
      expect(wrapper.text()).toContain('每日平均')
      expect(wrapper.text()).toContain('單日峰值2 小時 35 分鐘')
      expect(
        wrapper
          .findAll('.user-duration-chart__x-axis > span')
          .filter((label) => label.text())
          .every((label) => label.findAll('span').length === 1)
      ).toBe(true)
    }
  )

  it('keeps loading, empty, malformed and request failure states distinct', async () => {
    let resolveRequest
    getUserOnlineDurationMock.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveRequest = resolve
      })
    )
    const wrapper = mountChart()
    expect(wrapper.text()).toContain('載入在線時長紀錄')
    resolveRequest({ data: makeResponse({ history: false }) })
    await flushPromises()
    expect(wrapper.text()).toContain('目前尚無紀錄')

    getUserOnlineDurationMock.mockResolvedValueOnce({ data: { points: [] } })
    await wrapper.findAll('.user-duration-switch button')[1].trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('在線時長載入失敗')
    expect(wrapper.findAll('.user-duration-chart__item')).toHaveLength(0)
    expect(wrapper.find('.chart-summary-group').exists()).toBe(false)

    getUserOnlineDurationMock.mockResolvedValueOnce({
      data: makeResponse({ durationSeconds: Number.NaN }),
    })
    await wrapper.findAll('.user-duration-switch button')[0].trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('在線時長載入失敗')
  })

  it('uses the authoritative font tokens at 50, 100 and 150 percent without a chart instance', async () => {
    const wrapper = mountChart()
    await flushPromises()

    for (const [percent, scale] of [
      [50, '0.45'],
      [100, '0.9'],
      [150, '1.35'],
    ]) {
      applyFontSizePreference(percent)
      expect(document.documentElement.style.getPropertyValue('--app-effective-font-scale')).toBe(
        scale
      )
      expect(wrapper.findAll('.user-duration-chart')).toHaveLength(1)
      expect(wrapper.findAll('.user-duration-chart__bar')[4].classes()).toContain('has-value')
    }

    expect(componentSource).toMatch(/user-duration-chart__y-axis[\s\S]*var\(--app-font-size-xs\)/)
    expect(componentSource).toMatch(/user-duration-chart__y-axis span[\s\S]*white-space: nowrap/)
    expect(componentSource).toMatch(/user-duration-chart__tooltip[\s\S]*var\(--app-font-size-xs\)/)
    expect(componentSource).toMatch(/user-duration-switch button[\s\S]*var\(--app-font-size-xs\)/)
    expect(componentSource).not.toMatch(/font-size:\s*(11|12)px/)
    expect(componentSource).not.toContain('overflow-x: auto')
    expect(componentSource).not.toContain('var(--app-effective-font-scale)')
  })
})
