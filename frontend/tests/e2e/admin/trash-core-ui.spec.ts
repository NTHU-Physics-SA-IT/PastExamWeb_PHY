import type { Locator, Page, TestInfo } from '@playwright/test'
import { adminTest as test, expect } from '../support/adminTest'
import { mockAdminCourseEndpoints } from '../support/adminFixtures'
import { JSON_HEADERS } from '../support/constants'
import { clickWhenVisible } from '../support/ui'

const reviewItems = [
  {
    id: 801,
    subject: 'Pending Core UI',
    requested_course_name: 'Pending Core UI',
    name: '期中考',
    academic_year: 2024,
    professor: '測試教授',
    status: 'pending',
    available_actions: ['approve', 'takedown', 'reject', 'delete'],
    created_at: '2026-08-05T01:00:00Z',
  },
  {
    id: 802,
    subject: 'Takedown Core UI',
    requested_course_name: 'Takedown Core UI',
    name: '期末考',
    academic_year: 2024,
    professor: '測試教授',
    status: 'takedown',
    available_actions: ['republish', 'delete'],
    created_at: '2026-08-05T02:00:00Z',
  },
]

const trashItems = [
  {
    item_type: 'archive_submission',
    id: 901,
    display_name: 'Blocked Trash Item',
    parent_type: 'course',
    parent_name: '普通物理',
    deleted_at: '2026-08-05T03:00:00Z',
    dependencies: [{ key: 'blocked', label: '阻擋還原：測試依賴', severity: 'danger' }],
    canRestore: false,
    canPermanentDelete: false,
  },
  {
    item_type: 'archive_submission',
    id: 902,
    display_name: 'Allowed Trash Item',
    parent_type: 'archive',
    parent_name: '期中考',
    deleted_at: '2026-08-05T04:00:00Z',
    dependencies: [{ key: 'display-only', label: '阻擋還原：顯示文字', severity: 'danger' }],
    canRestore: true,
    canPermanentDelete: true,
  },
]

const buildSubmissionStatistics = (requestUrl: string) => {
  const url = new URL(requestUrl)
  const mode = url.searchParams.get('mode') ?? 'time'
  const range = url.searchParams.get('range') ?? '24h'
  const bucketMinutes = mode === 'time' ? 10 : 1440
  const bucketCount = mode === 'time' ? 144 : Number(range.replace('d', '')) || 30
  const start = Date.parse('2026-08-01T00:00:00Z')
  const points = Array.from({ length: bucketCount }, (_, index) => {
    const pointStart = new Date(start + index * bucketMinutes * 60_000)
    return {
      start: pointStart.toISOString(),
      end: new Date(pointStart.getTime() + bucketMinutes * 60_000).toISOString(),
      count: 0,
    }
  })
  return {
    mode,
    range,
    timezone: 'Asia/Taipei',
    bucket_minutes: bucketMinutes,
    range_start: points[0].start,
    range_end: points.at(-1)?.end,
    summary: { total: 0, peak: 0, average: 0 },
    points,
  }
}

const mockShellEndpoints = async (page: Page) => {
  await page.route('**/api/auth/heartbeat', (route) =>
    route.fulfill({ status: 200, headers: JSON_HEADERS, body: '{}' })
  )
  await page.route('**/api/notifications/active', (route) =>
    route.fulfill({ status: 200, headers: JSON_HEADERS, body: '[]' })
  )
  await page.route('**/api/notifications/unread-summary**', (route) =>
    route.fulfill({
      status: 200,
      headers: JSON_HEADERS,
      body: JSON.stringify({
        announcements: [],
        personal_notifications: [],
        counts: { announcements: 0, personal_notifications: 0, total: 0 },
      }),
    })
  )
}

const mockTrashCoreEndpoints = async (page: Page) => {
  await mockShellEndpoints(page)
  await mockAdminCourseEndpoints(page)

  await page.route('**/api/archives/admin/submission-statistics**', (route) =>
    route.fulfill({
      status: 200,
      headers: JSON_HEADERS,
      body: JSON.stringify(buildSubmissionStatistics(route.request().url())),
    })
  )
  await page.route('**/api/archives/admin/submissions', (route) =>
    route.fulfill({
      status: 200,
      headers: JSON_HEADERS,
      body: JSON.stringify(reviewItems),
    })
  )
  await page.route('**/api/archives/admin/submissions/*', async (route) => {
    if (route.request().method() === 'DELETE') {
      await route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify({ changed: false }),
      })
      return
    }
    await route.fulfill({
      status: 200,
      headers: JSON_HEADERS,
      body: JSON.stringify({ changed: false }),
    })
  })
  await page.route('**/api/trash**', (route) =>
    route.fulfill({
      status: 200,
      headers: JSON_HEADERS,
      body: JSON.stringify(trashItems),
    })
  )
}

const assertActionRowFits = async (
  row: Locator,
  expectedNames: string[],
  { singleRow = false } = {}
) => {
  const actionArea = row.locator('.review-card-actions')
  await expect(actionArea).toBeVisible()
  const buttons = actionArea.getByRole('button')
  await expect(buttons).toHaveCount(expectedNames.length)
  const names = await buttons.evaluateAll((elements) =>
    elements.map((element) => element.getAttribute('aria-label'))
  )
  expect(names).toEqual(expectedNames)

  const geometry = await actionArea.evaluate((element) => {
    const rect = element.getBoundingClientRect()
    const children = Array.from(element.querySelectorAll('button')).map((button) => {
      const childRect = button.getBoundingClientRect()
      return {
        left: childRect.left,
        right: childRect.right,
        top: childRect.top,
      }
    })
    return {
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
      rect: { left: rect.left, right: rect.right },
      children,
    }
  })
  expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.clientWidth + 1)
  if (singleRow) {
    for (let index = 1; index < geometry.children.length; index += 1) {
      expect(Math.abs(geometry.children[index].top - geometry.children[0].top)).toBeLessThanOrEqual(
        1
      )
      expect(geometry.children[index].left).toBeGreaterThanOrEqual(
        geometry.children[index - 1].right - 1
      )
    }
  }
  expect(geometry.children[0].left).toBeGreaterThanOrEqual(geometry.rect.left - 1)
  expect(geometry.children.at(-1)?.right ?? 0).toBeLessThanOrEqual(geometry.rect.right + 1)
}

const captureEvidence = async (page: Page, testInfo: TestInfo, name: string) => {
  await page.screenshot({ path: testInfo.outputPath(`${name}.png`), fullPage: true })
}

const openAdminReviewCenter = async (page: Page) => {
  await page.goto('/admin', { waitUntil: 'networkidle' })

  await expect(page.getByRole('button', { name: '管理中心', exact: true })).toBeVisible()
  const reviewTab = page.getByRole('tab', { name: '審核中心', exact: true })
  await clickWhenVisible(reviewTab)
  await expect(reviewTab).toHaveAttribute('aria-selected', 'true')

  const reviewPanel = page.getByRole('tabpanel', { name: '審核中心', exact: true })
  await expect(reviewPanel).toBeVisible()
  const reviewTable = reviewPanel.locator('.review-request-table--new')
  await expect(reviewTable).toBeVisible()
  await expect(reviewTable).toContainText('Pending Core UI')
  await expect(reviewTable).toContainText('Takedown Core UI')
}

test.describe('Admin › Trash Core UI', () => {
  test.beforeEach(async ({ page }) => {
    await mockTrashCoreEndpoints(page)
  })

  test('keeps approved review actions usable across required Chrome widths and enlarged text', async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width: 1440, height: 1000 })
    await openAdminReviewCenter(page)

    const pendingRow = page.locator('.review-request-table--new tbody tr').filter({
      hasText: 'Pending Core UI',
    })
    const takedownRow = page.locator('.review-request-table--new tbody tr').filter({
      hasText: 'Takedown Core UI',
    })
    await assertActionRowFits(pendingRow, ['查看/編輯', '通過', '下架', '退回', '刪除'])
    await assertActionRowFits(takedownRow, ['查看/編輯', '重新上架', '刪除'])
    await captureEvidence(page, testInfo, 'pending-takedown-1440')

    for (const width of [337, 360, 390, 640, 1399, 1400]) {
      await page.setViewportSize({ width, height: 1000 })
      await assertActionRowFits(pendingRow, ['查看/編輯', '通過', '下架', '退回', '刪除'], {
        singleRow: width <= 1399,
      })
      if ([337, 390, 1399, 1400].includes(width)) {
        await captureEvidence(page, testInfo, `pending-${width}-100`)
      }
    }

    await page.setViewportSize({ width: 337, height: 1000 })
    await page.evaluate(() => {
      document.documentElement.style.setProperty('--app-effective-font-scale', '1.35')
      document.documentElement.style.fontSize = '135%'
      document.documentElement.dataset.appFontSizeDisplayPercent = '150'
    })
    await assertActionRowFits(pendingRow, ['查看/編輯', '通過', '下架', '退回', '刪除'], {
      singleRow: true,
    })
    await captureEvidence(page, testInfo, 'pending-337-150')

    await page.setViewportSize({ width: 390, height: 1000 })
    await assertActionRowFits(takedownRow, ['查看/編輯', '重新上架', '刪除'], {
      singleRow: true,
    })
    await captureEvidence(page, testInfo, 'takedown-390-150')
  })

  test('shows no-op feedback and gates Trash actions only by explicit booleans', async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width: 390, height: 1000 })
    await openAdminReviewCenter(page)

    const pendingRow = page.locator('.review-request-table--new tbody tr').filter({
      hasText: 'Pending Core UI',
    })
    await clickWhenVisible(pendingRow.getByRole('button', { name: '刪除', exact: true }))
    const confirmDialog = page.getByRole('alertdialog')
    await clickWhenVisible(confirmDialog.locator('.p-confirmdialog-accept-button'))
    await expect(page.getByText('此投稿已在垃圾桶中，未重複刪除。')).toBeVisible()

    await clickWhenVisible(page.getByRole('tab', { name: '垃圾桶' }))
    const blockedCard = page.locator('.trash-mobile-card').filter({ hasText: 'Blocked Trash Item' })
    const allowedCard = page.locator('.trash-mobile-card').filter({ hasText: 'Allowed Trash Item' })
    await expect(blockedCard).toContainText('關聯課程')
    await expect(blockedCard).toContainText('普通物理')
    await expect(blockedCard).toContainText('目前無可用操作')
    await expect(blockedCard.getByRole('button', { name: '還原' })).toHaveCount(0)
    await expect(blockedCard.getByRole('button', { name: '永久刪除' })).toHaveCount(0)
    await expect(allowedCard).toContainText('關聯考古題')
    await expect(allowedCard).toContainText('期中考')
    await expect(allowedCard.getByRole('button', { name: '還原' })).toBeVisible()
    await expect(allowedCard.getByRole('button', { name: '永久刪除' })).toBeVisible()
    await captureEvidence(page, testInfo, 'trash-390')

    await page.setViewportSize({ width: 1440, height: 1000 })
    await expect(
      page
        .locator('.admin-desktop-data-table tbody tr')
        .filter({ hasText: 'Blocked Trash Item' })
        .getByRole('button', { name: '還原' })
    ).toHaveCount(0)
    await captureEvidence(page, testInfo, 'trash-1440')
  })
})
