import { expect, test, type Locator, type Page } from '@playwright/test'
import { JSON_HEADERS } from '../support/constants'
import { buildJwt } from '../support/jwt'

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
    window.localStorage.setItem('admin-current-tab', '5')
  }, token)
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
      whiteSpace: computed.whiteSpace,
      overflowWrap: computed.overflowWrap,
      wordBreak: computed.wordBreak,
      overflow: computed.overflow,
    }
  })
  expect(style.borderWidth).toBe('1px')
  expect(style.borderStyle).toBe('solid')
  expect(style.borderColor).not.toBe('rgba(0, 0, 0, 0)')
  expect(style.backgroundColor).toBe('rgba(0, 0, 0, 0)')
  expect(style.expectedBorder).not.toBe('')
  expect(style.whiteSpace).toBe('pre-wrap')
  expect(style.overflowWrap).toBe('anywhere')
  expect(style.wordBreak).toBe('break-word')
  expect(style.overflow).toBe('hidden')
}

async function readRuntimeStyle(locator: Locator) {
  return locator.evaluate((element) => {
    const properties = [
      'background-color',
      'background-image',
      'color',
      'border-color',
      'box-shadow',
    ]
    const computed = window.getComputedStyle(element)
    const summarize = (style: CSSStyleDeclaration) => ({
      backgroundColor: style.backgroundColor,
      backgroundImage: style.backgroundImage,
      color: style.color,
      borderColor: style.borderColor,
      boxShadow: style.boxShadow,
    })
    const matchedRules: Array<{ selector: string; declarations: Record<string, string> }> = []
    const visitRules = (rules: CSSRuleList) => {
      for (const rule of Array.from(rules)) {
        if (rule instanceof CSSStyleRule) {
          let matches
          try {
            matches = element.matches(rule.selectorText)
          } catch {
            continue
          }
          if (!matches) continue
          const declarations = Object.fromEntries(
            properties
              .map((property) => [property, rule.style.getPropertyValue(property)])
              .filter(([, value]) => value)
          )
          if (Object.keys(declarations).length > 0) {
            matchedRules.push({ selector: rule.selectorText, declarations })
          }
        } else if ('cssRules' in rule) {
          visitRules((rule as CSSGroupingRule).cssRules)
        }
      }
    }
    for (const sheet of Array.from(document.styleSheets)) {
      try {
        visitRules(sheet.cssRules)
      } catch {
        // The app's styles are same-origin; ignore unrelated inaccessible sheets.
      }
    }
    return {
      computed: summarize(computed),
      before: summarize(window.getComputedStyle(element, '::before')),
      after: summarize(window.getComputedStyle(element, '::after')),
      matchedReportRules: matchedRules.filter((rule) =>
        /report-management|report-filter|report-row-actions/.test(rule.selector)
      ),
      matchedOtherRules: matchedRules.filter(
        (rule) => !/report-management|report-filter|report-row-actions/.test(rule.selector)
      ),
    }
  })
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

test('applies the Christmas structural and content hierarchy to Admin report surfaces at runtime', async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.route('**/api/theme-management/active-theme', (route) =>
    route.fulfill({
      status: 200,
      headers: JSON_HEADERS,
      body: JSON.stringify({ active_theme: 'christmas' }),
    })
  )
  await page.goto('/admin', { waitUntil: 'networkidle' })
  await expect(page.locator('html')).toHaveAttribute('data-effective-theme', 'christmas')

  const adminPage = await readRuntimeStyle(page.locator('.admin-container'))
  const appShell = await readRuntimeStyle(page.locator('#app.app-christmas-frosted-window'))
  const root = page.locator('.report-management')
  const archiveSection = page.locator('.report-section').filter({ hasText: '考古題回報' })
  const filters = archiveSection.locator('.report-management__filters')
  const table = archiveSection.locator('.report-management__archive-table')
  const actionButton = table.getByRole('button', { name: '檢視或審核考古題回報' }).first()
  const dangerButton = table.getByRole('button', { name: '刪除考古題回報' }).first()
  const styles = {
    reportRoot: await readRuntimeStyle(root),
    inactiveTab: await readRuntimeStyle(root.getByRole('tab', { name: '留言回報' })),
    activeTab: await readRuntimeStyle(root.getByRole('tab', { name: '考古題回報' })),
    filterPanel: await readRuntimeStyle(filters),
    searchInput: await readRuntimeStyle(filters.locator('.p-inputtext')),
    statusSelect: await readRuntimeStyle(filters.locator('.p-select').nth(0)),
    reasonSelect: await readRuntimeStyle(filters.locator('.p-select').nth(1)),
    searchButton: await readRuntimeStyle(filters.getByRole('button', { name: '搜尋' })),
    tableWrapper: await readRuntimeStyle(table),
    tableHeader: await readRuntimeStyle(table.locator('.p-datatable-thead > tr > th').first()),
    tableBody: await readRuntimeStyle(table.locator('.p-datatable-tbody')),
    tableRow: await readRuntimeStyle(table.locator('.p-datatable-tbody > tr').first()),
    tableCell: await readRuntimeStyle(table.locator('.p-datatable-tbody > tr > td').first()),
    paginator: await readRuntimeStyle(table.locator('.p-paginator')),
    actionButton: await readRuntimeStyle(actionButton),
    dangerButton: await readRuntimeStyle(dangerButton),
  }

  expect(adminPage.computed).toMatchObject({
    backgroundColor: 'rgba(0, 0, 0, 0)',
    backgroundImage: 'none',
  })
  expect(appShell.computed.backgroundColor).toBe('rgb(66, 104, 120)')
  expect(appShell.computed.backgroundImage).toContain('linear-gradient')
  expect(styles.reportRoot.computed).toMatchObject({
    backgroundColor: 'rgba(0, 0, 0, 0)',
    backgroundImage: 'none',
    color: 'rgb(245, 238, 220)',
  })
  expect(styles.inactiveTab.computed).toMatchObject({
    backgroundColor: 'rgba(0, 0, 0, 0)',
    backgroundImage: 'none',
    color: 'rgb(197, 213, 210)',
  })
  expect(styles.activeTab.computed).toMatchObject({
    backgroundColor: 'rgb(66, 104, 120)',
    backgroundImage: 'none',
    color: 'rgb(248, 242, 232)',
    borderColor: 'rgb(222, 199, 142)',
  })
  expect(styles.filterPanel.computed).toMatchObject({
    backgroundColor: 'rgba(0, 0, 0, 0)',
    backgroundImage: 'none',
    borderColor: 'rgba(222, 199, 142, 0.38)',
  })
  for (const control of [styles.searchInput, styles.statusSelect, styles.reasonSelect]) {
    expect(control.computed).toMatchObject({
      backgroundColor: 'rgb(41, 63, 82)',
      backgroundImage: 'none',
      color: 'rgb(248, 242, 232)',
      borderColor: 'rgba(222, 199, 142, 0.38)',
    })
  }
  expect(styles.searchButton.computed).toMatchObject({
    backgroundColor: 'rgba(0, 0, 0, 0)',
    backgroundImage: 'none',
    color: 'rgb(16, 185, 129)',
    borderColor: 'rgb(167, 243, 208)',
  })
  expect(styles.actionButton.computed).toMatchObject({
    backgroundColor: 'rgb(215, 237, 245)',
    backgroundImage: 'none',
    color: 'rgb(36, 83, 104)',
    borderColor: 'rgba(225, 246, 252, 0.96)',
  })
  expect(styles.dangerButton.computed).toMatchObject({
    backgroundColor: 'rgb(121, 57, 65)',
    backgroundImage: 'none',
    color: 'rgb(245, 238, 220)',
  })
  expect(styles.tableWrapper.computed.backgroundColor).toBe('rgb(62, 95, 114)')
  expect(styles.tableHeader.computed).toMatchObject({
    backgroundColor: 'rgb(41, 63, 82)',
    backgroundImage: 'none',
    color: 'rgb(245, 238, 220)',
    borderColor: 'rgba(222, 199, 142, 0.38)',
  })
  for (const bodySurface of [styles.tableBody, styles.tableRow, styles.tableCell]) {
    expect(bodySurface.computed.backgroundColor).toBe('rgb(62, 95, 114)')
    expect(bodySurface.computed.backgroundImage).toBe('none')
  }
  expect(styles.tableHeader.computed.backgroundColor).not.toBe(
    styles.tableRow.computed.backgroundColor
  )
  expect(styles.paginator.computed).toMatchObject({
    backgroundColor: 'rgb(62, 95, 114)',
    backgroundImage: 'none',
    color: 'rgb(197, 213, 210)',
    borderColor: 'rgba(222, 199, 142, 0.38)',
  })
  for (const surface of [
    styles.reportRoot,
    styles.inactiveTab,
    styles.activeTab,
    styles.filterPanel,
    styles.searchInput,
    styles.statusSelect,
    styles.reasonSelect,
    styles.tableWrapper,
    styles.tableHeader,
    styles.tableBody,
    styles.tableRow,
    styles.tableCell,
    styles.paginator,
    styles.dangerButton,
  ]) {
    expect(
      surface.matchedReportRules.some((rule) =>
        rule.selector.includes('report-management--christmas')
      )
    ).toBe(true)
  }
  expect(styles.actionButton.after.backgroundImage).toContain('radial-gradient')

  await testInfo.attach('report-christmas-1440x900', {
    body: await page.screenshot(),
    contentType: 'image/png',
  })

  await actionButton.click()
  const dialog = page.getByRole('dialog', { name: '考古題回報審核' })
  await expect(dialog).toBeVisible()
  const dialogStyle = await readRuntimeStyle(dialog)
  expect(dialogStyle.computed).toMatchObject({
    backgroundColor: 'rgb(62, 95, 114)',
    backgroundImage: 'none',
    color: 'rgb(248, 242, 232)',
    borderColor: 'rgba(222, 199, 142, 0.38)',
  })
  expect(
    dialogStyle.matchedReportRules.some(
      (rule) =>
        rule.selector.includes('report-management-panel-dialog') &&
        rule.selector.includes('data-effective-theme')
    )
  ).toBe(true)
  await dialog.getByRole('button', { name: '關閉' }).click()
})

test('keeps responsive Christmas report cards bounded with their row-owned surface', async ({
  page,
}, testInfo) => {
  await page.route('**/api/theme-management/active-theme', (route) =>
    route.fulfill({
      status: 200,
      headers: JSON_HEADERS,
      body: JSON.stringify({ active_theme: 'christmas' }),
    })
  )
  await page.goto('/admin', { waitUntil: 'networkidle' })
  await expect(page.locator('html')).toHaveAttribute('data-effective-theme', 'christmas')

  const root = page.locator('.report-management')
  const archiveSection = page.locator('.report-section').filter({ hasText: '考古題回報' })
  const table = archiveSection.locator('.report-management__archive-table')

  for (const viewport of [
    { width: 1024, height: 768 },
    { width: 834, height: 1210 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport)
    const row = table.locator('.p-datatable-tbody > tr').first()
    const card = row.locator('.report-mobile-card-content')
    await expect(card).toBeVisible()
    const rowStyle = await readRuntimeStyle(row)
    const cardStyle = await readRuntimeStyle(card)
    expect(rowStyle.computed).toMatchObject({
      backgroundColor: 'rgb(62, 95, 114)',
      backgroundImage: 'none',
      borderColor: 'rgba(222, 199, 142, 0.38)',
    })
    expect(
      rowStyle.matchedReportRules.some((rule) =>
        rule.selector.includes('report-management--christmas')
      )
    ).toBe(true)
    expect(cardStyle.computed).toMatchObject({
      backgroundColor: 'rgba(0, 0, 0, 0)',
      backgroundImage: 'none',
    })
    const geometry = await root.evaluate((element) => {
      const rect = element.getBoundingClientRect()
      return {
        left: rect.left,
        right: rect.right,
        viewportWidth: window.innerWidth,
        scrollWidth: element.scrollWidth,
        clientWidth: element.clientWidth,
      }
    })
    expect(geometry.left).toBeGreaterThanOrEqual(-1)
    expect(geometry.right).toBeLessThanOrEqual(geometry.viewportWidth + 1)
    expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.clientWidth + 1)
    await testInfo.attach(`report-christmas-${viewport.width}x${viewport.height}`, {
      body: await page.screenshot(),
      contentType: 'image/png',
    })
  }
})
