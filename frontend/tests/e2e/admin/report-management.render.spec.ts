import type { Locator, Page } from '@playwright/test'
import { adminTest as test, expect } from '../support/adminTest'
import { JSON_HEADERS } from '../support/constants'

const systemReport = {
  id: 11,
  reporter_name: '系統回報者',
  created_at: '2026-07-28T01:00:00Z',
  report_type: 'bug',
  title: '版面在特定瀏覽器顯示異常',
  description: `第一行描述
https://example.com/${'very-long-path-'.repeat(12)}
commit-${'a'.repeat(80)}`,
  contact: 'reporter@example.com',
  is_read: false,
  read_at: null,
  read_by_username: null,
}

const commentReport = {
  id: 21,
  reporter_name: '留言回報者',
  created_at: '2026-07-28T02:00:00Z',
  reason: 'misinformation',
  comment_content_snapshot: `ya
${'snapshot-without-spaces-'.repeat(12)}`,
  comment_created_at_snapshot: '2026-07-27T12:00:00Z',
  custom_message: null,
  comment_author_name: '留言作者',
  course_name: '普通物理',
  archive_name: '期中考',
  thread_id: 31,
  comment_id: 32,
  status: 'pending',
  reviewer_name: null,
  reviewed_at: null,
  source_exists: true,
}

const archiveReports = [
  {
    id: 31,
    reporter_name: '考古題回報者',
    created_at: '2026-07-28T03:00:00Z',
    reason: 'incomplete_or_low_quality',
    supplementary_detail: `第三頁模糊
${'archive-detail-without-spaces-'.repeat(10)}`,
    course_name: '電磁學',
    archive_name: '期末考',
    archive_id: 88,
    archive_id_snapshot: 88,
    academic_year: 2026,
    professor: '王老師',
    status: 'pending',
    reviewer_name: null,
    reviewed_at: null,
    admin_response: null,
    source_exists: true,
    source_state: 'available',
    can_take_down: true,
    archive_taken_down: false,
  },
  {
    id: 32,
    reporter_name: '另一位回報者',
    created_at: '2026-07-27T03:00:00Z',
    reason: 'metadata_mismatch',
    supplementary_detail: null,
    course_name: '量子物理',
    archive_name: '第一次小考',
    archive_id: 89,
    archive_id_snapshot: 89,
    academic_year: 2025,
    professor: '陳老師',
    status: 'dismissed',
    reviewer_name: '審核管理員',
    reviewed_at: '2026-07-28T04:00:00Z',
    admin_response: null,
    source_exists: true,
    source_state: 'available',
    can_take_down: false,
    archive_taken_down: false,
  },
]

async function mockReportManagement(page: Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem('admin-current-tab', '5')
  })
  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (!path.startsWith('/api/')) return route.continue()

    if (path === '/api/auth/heartbeat') {
      return route.fulfill({ status: 200, headers: JSON_HEADERS, body: '{}' })
    }
    if (path === '/api/notifications/active') {
      return route.fulfill({ status: 200, headers: JSON_HEADERS, body: '[]' })
    }
    if (path === '/api/notifications/unread-summary') {
      return route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify({
          announcements: [],
          personal_notifications: [],
          counts: { announcements: 0, personal_notifications: 0, total: 0 },
        }),
      })
    }
    if (path === '/api/courses/admin/categories') {
      return route.fulfill({ status: 200, headers: JSON_HEADERS, body: '[]' })
    }
    if (path === '/api/reports/admin/system-issues') {
      return route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify({ items: [systemReport], total: 1 }),
      })
    }
    if (path === `/api/reports/admin/system-issues/${systemReport.id}`) {
      return route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify(systemReport),
      })
    }
    if (path === '/api/reports/admin/comments') {
      return route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify({ items: [commentReport], total: 1 }),
      })
    }
    if (path === `/api/reports/admin/comments/${commentReport.id}`) {
      return route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify(commentReport),
      })
    }
    if (path === '/api/reports/admin/archives') {
      return route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify({ items: archiveReports, total: archiveReports.length }),
      })
    }
    const archiveMatch = path.match(/^\/api\/reports\/admin\/archives\/(\d+)$/)
    if (archiveMatch) {
      const report = archiveReports.find((item) => item.id === Number(archiveMatch[1]))
      return route.fulfill({
        status: report ? 200 : 404,
        headers: JSON_HEADERS,
        body: JSON.stringify(report || { detail: 'Not found' }),
      })
    }

    return route.fulfill({ status: 200, headers: JSON_HEADERS, body: '[]' })
  })
}

async function expectVisibleContentFrame(frame: Locator, expectedText: string) {
  await expect(frame).toBeVisible()
  await expect(frame).toContainText(expectedText)
  const style = await frame.evaluate((element) => {
    const computed = window.getComputedStyle(element)
    const root = window.getComputedStyle(document.documentElement)
    return {
      borderWidth: computed.borderTopWidth,
      borderStyle: computed.borderTopStyle,
      borderColor: computed.borderTopColor,
      backgroundColor: computed.backgroundColor,
      expectedBorder: root.getPropertyValue('--border-color').trim(),
      expectedBackground: root.getPropertyValue('--bg-secondary').trim(),
      whiteSpace: computed.whiteSpace,
      overflowWrap: computed.overflowWrap,
      wordBreak: computed.wordBreak,
      overflow: computed.overflow,
    }
  })
  expect(style.borderWidth).toBe('1px')
  expect(style.borderStyle).toBe('solid')
  expect(style.borderColor).not.toBe('rgba(0, 0, 0, 0)')
  expect(style.backgroundColor).not.toBe('rgba(0, 0, 0, 0)')
  expect(style.expectedBorder).not.toBe('')
  expect(style.expectedBackground).not.toBe('')
  expect(style.whiteSpace).toBe('pre-wrap')
  expect(style.overflowWrap).toBe('anywhere')
  expect(style.wordBreak).toBe('break-word')
  expect(style.overflow).toBe('hidden')
}

test.beforeEach(async ({ page }) => {
  await mockReportManagement(page)
})

test('renders visible report content frames in light and dark themes', async ({ page }) => {
  await page.setViewportSize({ width: 1400, height: 900 })
  await page.goto('/admin', { waitUntil: 'networkidle' })
  await page.evaluate(() => document.documentElement.classList.remove('dark'))
  await expect(page.locator('html')).not.toHaveClass(/dark/)

  await page.getByRole('tab', { name: '系統問題回報' }).click()
  const systemSection = page.locator('.report-section').filter({ hasText: '系統問題回報' })
  await systemSection.getByRole('button', { name: '檢視系統問題回報' }).click()
  const systemDialog = page.getByRole('dialog', { name: '系統問題回報詳情' })
  await expectVisibleContentFrame(
    systemDialog.locator('.report-review__content-block').nth(0),
    '版面在特定瀏覽器顯示異常'
  )
  await expectVisibleContentFrame(
    systemDialog.locator('.report-review__content-block').nth(1),
    '第一行描述'
  )
  await systemDialog.getByRole('button', { name: '關閉' }).click()

  await page.getByRole('tab', { name: '留言回報' }).click()
  const commentSection = page.locator('.report-section').filter({ hasText: '留言回報' })
  await commentSection.getByRole('button', { name: '檢視或審核留言回報' }).click()
  const commentDialog = page.getByRole('dialog', { name: '留言回報審核' })
  await expectVisibleContentFrame(
    commentDialog.locator('.report-review__content-block').nth(0),
    'ya'
  )
  await expectVisibleContentFrame(
    commentDialog.locator('.report-review__content-block').nth(1),
    '未提供補充'
  )
  await commentDialog.getByRole('button', { name: '關閉' }).click()

  await page.getByRole('tab', { name: '考古題回報' }).click()
  const archiveSection = page.locator('.report-section').filter({ hasText: '考古題回報' })
  await archiveSection.getByRole('button', { name: '檢視或審核考古題回報' }).first().click()
  let archiveDialog = page.getByRole('dialog', { name: '考古題回報審核' })
  await expectVisibleContentFrame(
    archiveDialog.locator('.report-review__content-block'),
    '第三頁模糊'
  )
  await archiveDialog.getByRole('button', { name: '關閉' }).click()

  await archiveSection.getByRole('button', { name: '檢視或審核考古題回報' }).nth(1).click()
  archiveDialog = page.getByRole('dialog', { name: '考古題回報審核' })
  await expectVisibleContentFrame(
    archiveDialog.locator('.report-review__content-block'),
    '未提供補充說明'
  )
  await archiveDialog.getByRole('button', { name: '關閉' }).click()

  await page.evaluate(() => document.documentElement.classList.add('dark'))
  await expect(page.locator('html')).toHaveClass(/dark/)
  await page.getByRole('tab', { name: '系統問題回報' }).click()
  await systemSection.getByRole('button', { name: '檢視系統問題回報' }).click()
  await expectVisibleContentFrame(
    page
      .getByRole('dialog', { name: '系統問題回報詳情' })
      .locator('.report-review__content-block')
      .first(),
    '版面在特定瀏覽器顯示異常'
  )
})

test('uses one responsive boundary and renders populated archive cards', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/admin', { waitUntil: 'networkidle' })

  const archiveTable = page.locator('.report-management__archive-table')
  const archiveHead = archiveTable.locator('.p-datatable-thead')
  const archiveCards = archiveTable.locator('.report-mobile-card')

  for (const width of [1440, 1400]) {
    await page.setViewportSize({ width, height: 900 })
    await expect(archiveHead).toBeVisible()
    await expect(archiveCards).toHaveCount(0)
  }

  for (const width of [1399, 1200, 1197, 1024]) {
    await page.setViewportSize({ width, height: 900 })
    await expect(archiveHead).toBeHidden()
    await expect(archiveCards).toHaveCount(archiveReports.length)
    const firstCard = archiveCards.first()
    await expect(firstCard).toContainText('檔案模糊、缺頁或內容不完整')
    await expect(firstCard).toContainText('考古題回報者')
    await expect(firstCard).toContainText('電磁學')
    await expect(firstCard).toContainText('期末考')
    await expect(firstCard).toContainText('#88')
    await expect(firstCard).toContainText('審核時間')
    await expect(firstCard).toContainText('--')
    await expect(firstCard.getByRole('button', { name: '檢視或審核考古題回報' })).toBeVisible()
    await expect(firstCard.getByRole('button', { name: '刪除考古題回報' })).toBeVisible()
  }
})
