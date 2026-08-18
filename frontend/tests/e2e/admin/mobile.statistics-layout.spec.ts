import { expect, test } from '@playwright/test'
import { buildJwt } from '../support/jwt'
import { JSON_HEADERS } from '../support/constants'
import {
  defaultUsers,
  mockAdminCourseEndpoints,
  mockAdminUserEndpoints,
} from '../support/adminFixtures'

const json = (value: unknown) => ({
  status: 200,
  headers: JSON_HEADERS,
  body: JSON.stringify(value),
})

const buildOnlinePoints = () => {
  const start = Date.UTC(2026, 6, 15, 0, 0, 0)
  return Array.from({ length: 144 }, (_, index) => ({
    start: new Date(start + index * 600_000).toISOString(),
    end: new Date(start + (index + 1) * 600_000).toISOString(),
    at: new Date(start + index * 600_000).toISOString(),
    count: index === 20 ? 1 : 0,
    has_data: true,
  }))
}

const buildDurationPoints = () => {
  const start = Date.UTC(2026, 6, 14, 16, 0, 0)
  return Array.from({ length: 24 }, (_, index) => ({
    start: new Date(start + index * 3_600_000).toISOString(),
    end: new Date(start + (index + 1) * 3_600_000).toISOString(),
    duration_seconds: index === 4 ? 1140 : 0,
    has_data: index <= 4,
  }))
}

const expectNoHorizontalOverflow = async (page: import('@playwright/test').Page) => {
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= document.documentElement.clientWidth
      )
    )
    .toBe(true)
}

const responsiveWidths = [390, 438, 544, 545, 550, 558, 559, 640, 641, 650, 651, 768]
const mobileSummaryWidths = [
  390, 430, 495, 544, 545, 550, 560, 567, 568, 600, 640, 641, 645, 650, 651,
]

const expectSameRow = async (locator: import('@playwright/test').Locator) => {
  const tops = await locator.evaluateAll((elements) =>
    elements.map((element) => Math.round(element.getBoundingClientRect().top))
  )
  expect(new Set(tops).size).toBe(1)
}

test.use({
  viewport: { width: 393, height: 852 },
  deviceScaleFactor: 3,
  hasTouch: true,
})

test('keeps mobile statistics tabs and duration summaries aligned', async ({ page }) => {
  test.setTimeout(90_000)

  const token = buildJwt({
    uid: 1,
    email: 'admin@example.com',
    name: 'Admin',
    is_admin: true,
    exp: Math.floor(Date.now() / 1000) + 3600,
  })
  await page.addInitScript((value: string) => {
    window.sessionStorage.setItem('auth-token', value)
    window.localStorage.setItem('auth-token', value)
    window.localStorage.setItem('admin-current-tab', '1')
  }, token)

  await page.route('**/api/notifications/active', (route) => route.fulfill(json([])))
  await page.route('**/api/courses/admin/categories**', (route) => route.fulfill(json([])))
  await page.route('**/api/settings/contributor-levels', (route) =>
    route.fulfill(
      json(
        Array.from({ length: 10 }, (_, index) => ({
          level: index + 1,
          name: `等級 ${index + 1}`,
          min_exp: index === 0 ? 0 : index * (index + 1),
        }))
      )
    )
  )
  await page.route('**/api/settings/nthu-access-policy', (route) =>
    route.fulfill(
      json({
        mode: 'all_nthu',
        allowed_department_codes: [],
        staff_access: 'none',
        allowed_staff_userids: [],
        departments: [],
      })
    )
  )
  await mockAdminCourseEndpoints(page)
  await mockAdminUserEndpoints(
    page,
    defaultUsers.map((user, index) => ({
      ...user,
      contributor_experience: index === 0 ? 5 : 0,
      is_online: index === 0,
      online_status_label: index === 0 ? '在線' : '離線',
    }))
  )
  const localStatsUserId = defaultUsers.find((user) => user.account_source === 'local')!.id

  const onlinePoints = buildOnlinePoints()
  await page.route('**/api/users/admin/online-statistics**', (route) =>
    route.fulfill(
      json({
        range: '24h',
        bucket_minutes: 10,
        timezone: 'Asia/Taipei',
        online_timeout_seconds: 300,
        current_online: 0,
        peak_online: 1,
        average_online: 1 / 144,
        history_started_at: onlinePoints[0].start,
        points: onlinePoints,
      })
    )
  )
  await page.route(`**/api/users/admin/users/${localStatsUserId}/submission-stats**`, (route) =>
    route.fulfill(
      json({
        user_id: localStatsUserId,
        name: '一般使用者',
        contributor_experience: 5,
        total_count: 0,
        status_counts: { pending: 0, approved: 0, rejected: 0, takedown: 0, deleted: 0 },
        records_total: 0,
        submission_records: [],
      })
    )
  )
  const durationPoints = buildDurationPoints()
  await page.route(`**/api/users/admin/users/${localStatsUserId}/online-duration**`, (route) =>
    route.fulfill(
      json({
        user_id: localStatsUserId,
        mode: 'hourly',
        timezone: 'Asia/Taipei',
        online_timeout_seconds: 300,
        range_start: durationPoints[0].start,
        range_end: durationPoints.at(-1)?.end,
        history_started_at: durationPoints[0].start,
        points: durationPoints,
      })
    )
  )
  await page.route('**/api/archives/admin/submissions', (route) => route.fulfill(json([])))
  await page.route('**/api/archives/admin/submission-statistics**', (route) => {
    const url = new URL(route.request().url())
    const range = url.searchParams.get('range') ?? '24h'
    const mode = url.searchParams.get('mode') ?? 'time'
    const bucketCount = range === '7d' ? 42 : range === '30d' ? 60 : range === '90d' ? 90 : 144
    const bucketMinutes =
      range === '24h'
        ? 10
        : range === '48h'
          ? 20
          : range === '72h'
            ? 30
            : range === '7d'
              ? 240
              : range === '30d'
                ? 720
                : 1440
    const start = Date.UTC(2026, 6, 15) - bucketCount * bucketMinutes * 60_000
    const points = Array.from({ length: bucketCount }, (_, index) => ({
      start: new Date(start + index * bucketMinutes * 60_000).toISOString(),
      end: new Date(start + (index + 1) * bucketMinutes * 60_000).toISOString(),
      count: index === 2 ? 1 : 0,
    }))
    return route.fulfill(
      json({
        mode,
        range,
        timezone: 'Asia/Taipei',
        bucket_minutes: bucketMinutes,
        range_start: points[0].start,
        range_end: points.at(-1)?.end,
        summary: { total: 1, peak: 1, average: Number((1 / bucketCount).toFixed(1)) },
        points,
      })
    )
  })

  await page.goto('/admin', { waitUntil: 'networkidle' })
  const viewportMetrics = await page.evaluate(() => ({
    innerWidth: window.innerWidth,
    clientWidth: document.documentElement.clientWidth,
    visualViewportWidth: window.visualViewport?.width ?? null,
    devicePixelRatio: window.devicePixelRatio,
  }))
  expect(viewportMetrics.innerWidth).toBe(393)
  expect(viewportMetrics.clientWidth).toBe(393)
  expect(viewportMetrics.visualViewportWidth).toBe(393)
  expect(viewportMetrics.devicePixelRatio).toBe(3)

  await expect(page.getByRole('heading', { name: '使用者統計圖表' })).toBeVisible()
  await page.getByRole('button', { name: '展開使用者統計圖表' }).click()

  const userInsightsCard = page
    .locator('.admin-insights-card')
    .filter({ hasText: '使用者統計圖表' })
  const userSummaryCards = userInsightsCard.locator('.chart-summary-item')
  const userRangeButtons = userInsightsCard.locator('.user-insights__range button')
  await expect(userSummaryCards).toHaveCount(3)
  await expect(userRangeButtons).toHaveCount(3)
  for (const width of responsiveWidths) {
    await page.setViewportSize({ width, height: 900 })
    const metrics = await page.evaluate(() => ({
      innerWidth: window.innerWidth,
      clientWidth: document.documentElement.clientWidth,
      visualViewportWidth: window.visualViewport?.width ?? null,
    }))
    expect(metrics).toEqual({ innerWidth: width, clientWidth: width, visualViewportWidth: width })
    await expectSameRow(userSummaryCards)
    await expectSameRow(userRangeButtons)
    await expectNoHorizontalOverflow(page)
  }

  await page.setViewportSize({ width: 393, height: 852 })

  const modeSwitch = page.locator('.user-insights__switch--three')
  const modeButtons = modeSwitch.locator(':scope > .user-insights__switch-option')
  await expect(modeButtons).toHaveCount(3)
  const switchStyle = await modeSwitch.evaluate((element) => {
    const style = getComputedStyle(element)
    return { display: style.display, columns: style.gridTemplateColumns }
  })
  expect(switchStyle.display).toBe('grid')
  expect(switchStyle.columns.split(' ').length).toBe(2)

  const firstBox = await modeButtons.nth(0).boundingBox()
  const secondBox = await modeButtons.nth(1).boundingBox()
  const fullRowBox = await modeButtons.nth(2).boundingBox()
  expect(firstBox).not.toBeNull()
  expect(secondBox).not.toBeNull()
  expect(fullRowBox).not.toBeNull()
  expect(Math.abs((fullRowBox?.x ?? 0) - (firstBox?.x ?? 0))).toBeLessThanOrEqual(1)
  expect(
    Math.abs(
      (fullRowBox?.width ?? 0) -
        ((secondBox?.x ?? 0) + (secondBox?.width ?? 0) - (firstBox?.x ?? 0))
    )
  ).toBeLessThanOrEqual(2)
  expect(fullRowBox?.y ?? 0).toBeGreaterThan(firstBox?.y ?? 0)
  const fullRowStyle = await modeButtons.nth(2).evaluate((element) => {
    const style = getComputedStyle(element)
    return {
      gridColumnStart: style.gridColumnStart,
      gridColumnEnd: style.gridColumnEnd,
      minWidth: style.minWidth,
    }
  })
  expect(fullRowStyle).toEqual({ gridColumnStart: '1', gridColumnEnd: '-1', minWidth: '0px' })

  await modeButtons.nth(2).click()
  const activeBackground = await modeButtons
    .nth(2)
    .evaluate((element) => getComputedStyle(element).backgroundColor)
  expect(activeBackground).not.toBe('rgba(0, 0, 0, 0)')
  await modeButtons.nth(0).click()
  await expectNoHorizontalOverflow(page)

  await page.getByRole('button', { name: '查看使用者資料統計' }).first().click()
  const dialog = page.getByRole('dialog', { name: '使用者資料統計' })
  await expect(dialog).toBeVisible()
  const summaryCards = dialog.locator('.user-duration-card .chart-summary-item')
  const summaryGroup = dialog.locator('.user-duration-card .chart-summary-group')
  const durationModeButtons = dialog.locator('.user-duration-switch button')
  await expect(summaryCards).toHaveCount(3)
  await expect(durationModeButtons).toHaveCount(2)

  for (const width of mobileSummaryWidths) {
    await page.setViewportSize({ width, height: 900 })
    await expect
      .poll(() => summaryGroup.evaluate((element) => getComputedStyle(element).display))
      .toBe('grid')
    const summaryTops = await summaryCards.evaluateAll((elements) =>
      elements.map((element) => Math.round(element.getBoundingClientRect().top))
    )
    expect(new Set(summaryTops).size).toBe(1)
    await expect
      .poll(() =>
        summaryCards.evaluateAll((elements) =>
          elements.every(
            (element) => element.scrollWidth <= Math.ceil(element.getBoundingClientRect().width)
          )
        )
      )
      .toBe(true)
    await expectSameRow(durationModeButtons)
    await expectNoHorizontalOverflow(page)
  }

  for (const dark of [false, true]) {
    await page.evaluate(
      (enabled) => document.documentElement.classList.toggle('dark', enabled),
      dark
    )
    const boxes = await summaryCards.evaluateAll((elements) =>
      elements.map((element) => {
        const rect = element.getBoundingClientRect()
        return { top: rect.top, width: rect.width, scrollWidth: element.scrollWidth }
      })
    )
    expect(new Set(boxes.map(({ top }) => Math.round(top))).size).toBe(1)
    expect(boxes.every(({ width, scrollWidth }) => scrollWidth <= Math.ceil(width))).toBe(true)
    await expectNoHorizontalOverflow(page)
  }

  await page.evaluate(() => {
    document.documentElement.style.fontSize = '150%'
    document.documentElement.style.setProperty('--app-effective-font-scale', '1.5')
  })
  const scaledTops = await summaryCards.evaluateAll((elements) =>
    elements.map((element) => Math.round(element.getBoundingClientRect().top))
  )
  expect(new Set(scaledTops).size).toBe(1)
  await expectNoHorizontalOverflow(page)

  for (const desktopWidth of [1280, 1440]) {
    await page.setViewportSize({ width: desktopWidth, height: 900 })
    await expect
      .poll(() => summaryGroup.evaluate((element) => getComputedStyle(element).display))
      .toBe('flex')
    const desktopSummaryTops = await summaryCards.evaluateAll((elements) =>
      elements.map((element) => Math.round(element.getBoundingClientRect().top))
    )
    expect(new Set(desktopSummaryTops).size).toBe(1)
    await expectNoHorizontalOverflow(page)
  }

  await dialog.getByRole('button', { name: '關閉' }).click()
  for (const desktopWidth of [1280, 1440]) {
    await page.setViewportSize({ width: desktopWidth, height: 900 })
    await expect
      .poll(() => modeSwitch.evaluate((element) => getComputedStyle(element).display))
      .toBe('flex')
    const desktopBoxes = await modeButtons.evaluateAll((elements) =>
      elements.map((element) => Math.round(element.getBoundingClientRect().y))
    )
    expect(new Set(desktopBoxes).size).toBe(1)
    await expectNoHorizontalOverflow(page)
  }

  await page.setViewportSize({ width: 393, height: 852 })
  await page.getByRole('tab', { name: '審核中心' }).click()
  const reviewModeSwitch = page.locator('.user-insights__switch--two')
  const reviewModeButtons = reviewModeSwitch.locator(':scope > .user-insights__switch-option')
  await expect(reviewModeButtons).toHaveCount(2)
  const reviewBoxes = await reviewModeButtons.evaluateAll((elements) =>
    elements.map((element) => element.getBoundingClientRect())
  )
  expect(Math.abs(reviewBoxes[0].top - reviewBoxes[1].top)).toBeLessThanOrEqual(1)
  expect(Math.abs(reviewBoxes[0].width - reviewBoxes[1].width)).toBeLessThanOrEqual(1)
  const reviewInsightsCard = page
    .locator('.admin-insights-card')
    .filter({ hasText: '投稿統計圖表' })
  const reviewSummaryCards = reviewInsightsCard.locator('.chart-summary-item')
  const reviewRangeButtons = reviewInsightsCard.locator('.user-insights__range button')
  await expect(reviewSummaryCards).toHaveCount(3)
  await expect(reviewRangeButtons).toHaveCount(3)
  for (const width of responsiveWidths) {
    await page.setViewportSize({ width, height: 900 })
    await expectSameRow(reviewSummaryCards)
    await expectSameRow(reviewRangeButtons)
    await expectNoHorizontalOverflow(page)
  }
  await expectNoHorizontalOverflow(page)
})
