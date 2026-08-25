import { expect, test, type Locator, type Page } from '@playwright/test'
import { mockAdminCourseEndpoints } from '../support/adminFixtures'
import { JSON_HEADERS } from '../support/constants'
import { buildJwt } from '../support/jwt'

const json = (value: unknown) => ({
  status: 200,
  headers: JSON_HEADERS,
  body: JSON.stringify(value),
})

const reviewItems = [
  {
    id: 901,
    subject: '量子力學',
    subject_en: 'Quantum Mechanics',
    requested_course_name: '量子力學',
    requested_course_name_en: 'Quantum Mechanics',
    name: '期末考',
    academic_year: 2024,
    professor: 'New Course Professor',
    status: 'takedown',
    is_admin_upload: true,
    submitter_name: 'Administrator',
    reviewer_name: 'Administrator',
    reviewed_at: '2026-08-24T03:00:00Z',
    created_at: '2026-08-23T03:00:00Z',
    available_actions: ['republish', 'delete'],
  },
  {
    id: 902,
    subject: '普通物理(一)',
    subject_en: 'General Physics (I)',
    name: '期末考',
    academic_year: 2024,
    professor: 'Existing Course Professor',
    status: 'takedown',
    is_admin_upload: true,
    submitter_name: 'Administrator',
    reviewer_name: 'Administrator',
    reviewed_at: '2026-08-24T03:00:00Z',
    created_at: '2026-08-23T03:00:00Z',
    available_actions: ['republish', 'delete'],
  },
]

const buildSubmissionStatistics = () => {
  const bucketMinutes = 10
  const points = Array.from({ length: 144 }, (_, index) => {
    const start = new Date(Date.UTC(2026, 7, 24) + index * bucketMinutes * 60_000)
    return {
      start: start.toISOString(),
      end: new Date(start.getTime() + bucketMinutes * 60_000).toISOString(),
      count: 0,
    }
  })
  return {
    mode: 'time',
    range: '24h',
    timezone: 'Asia/Taipei',
    bucket_minutes: bucketMinutes,
    range_start: points[0].start,
    range_end: points.at(-1)?.end,
    summary: { total: 0, peak: 0, average: 0 },
    points,
  }
}

const mockReviewCenter = async (page: Page) => {
  const token = buildJwt({
    uid: 1,
    email: 'admin@example.com',
    name: 'Administrator',
    is_admin: true,
    exp: Math.floor(Date.now() / 1000) + 3600,
  })
  await page.addInitScript((value: string) => {
    window.sessionStorage.setItem('auth-token', value)
    window.localStorage.setItem('auth-token', value)
    window.localStorage.setItem('admin-current-tab', '3')
    window.localStorage.setItem('pastexam.locale', 'en')
  }, token)

  await page.route('**/api/auth/heartbeat', (route) => route.fulfill(json({})))
  await page.route('**/api/notifications/active', (route) => route.fulfill(json([])))
  await page.route('**/api/notifications/unread-summary**', (route) =>
    route.fulfill(
      json({
        announcements: [],
        personal_notifications: [],
        counts: { announcements: 0, personal_notifications: 0, total: 0 },
      })
    )
  )
  await page.route('**/api/wishes/admin/reports**', (route) =>
    route.fulfill(json({ items: [], total: 0 }))
  )
  await mockAdminCourseEndpoints(page)
  await page.route('**/api/archives/admin/submissions', (route) => route.fulfill(json(reviewItems)))
  await page.route('**/api/archives/admin/submission-statistics**', (route) =>
    route.fulfill(json(buildSubmissionStatistics()))
  )
}

const readStatusGeometry = async (tag: Locator) =>
  tag.evaluate((element) => {
    const root = element as HTMLElement
    const cell = root.closest('.admin-desktop-status-cell') as HTMLElement | null
    const tableCell = root.closest('td') as HTMLElement | null
    const label = root.querySelector('.p-tag-label') as HTMLElement | null
    const content = root.querySelector('.admin-desktop-status-label') as HTMLElement | null
    const rootStyle = getComputedStyle(root)
    const cellStyle = cell ? getComputedStyle(cell) : null
    const labelStyle = label ? getComputedStyle(label) : null
    const contentStyle = content ? getComputedStyle(content) : null
    const rootRect = root.getBoundingClientRect()
    const cellRect = cell?.getBoundingClientRect()
    const tableCellRect = tableCell?.getBoundingClientRect()
    const labelRect = label?.getBoundingClientRect()
    const contentRect = content?.getBoundingClientRect()
    const numeric = (value: string) => Number.parseFloat(value) || 0
    const usableCellWidth = cellRect
      ? cellRect.width -
        numeric(cellStyle?.paddingInlineStart ?? '0') -
        numeric(cellStyle?.paddingInlineEnd ?? '0')
      : 0

    return {
      text: root.textContent?.trim() ?? '',
      classes: root.className,
      dom: {
        root: root.tagName.toLowerCase(),
        label: label?.className ?? null,
        content: content?.className ?? null,
        parent: root.parentElement?.className ?? null,
      },
      rect: { width: rootRect.width, height: rootRect.height },
      labelRect: labelRect
        ? { width: labelRect.width, height: labelRect.height }
        : { width: 0, height: 0 },
      contentRect: contentRect
        ? { width: contentRect.width, height: contentRect.height }
        : { width: 0, height: 0 },
      cellRect: {
        width: cellRect?.width ?? 0,
        height: cellRect?.height ?? 0,
        usableWidth: usableCellWidth,
      },
      tableCellRect: {
        width: tableCellRect?.width ?? 0,
        height: tableCellRect?.height ?? 0,
      },
      sizing: {
        clientWidth: root.clientWidth,
        scrollWidth: root.scrollWidth,
        clientHeight: root.clientHeight,
        scrollHeight: root.scrollHeight,
      },
      style: {
        display: rootStyle.display,
        boxSizing: rootStyle.boxSizing,
        whiteSpace: rootStyle.whiteSpace,
        paddingInlineStart: rootStyle.paddingInlineStart,
        paddingInlineEnd: rootStyle.paddingInlineEnd,
        paddingBlockStart: rootStyle.paddingBlockStart,
        paddingBlockEnd: rootStyle.paddingBlockEnd,
        lineHeight: rootStyle.lineHeight,
        fontSize: rootStyle.fontSize,
        fontWeight: rootStyle.fontWeight,
        borderRadius: rootStyle.borderRadius,
        inlineSize: rootStyle.inlineSize,
        minInlineSize: rootStyle.minInlineSize,
        maxInlineSize: rootStyle.maxInlineSize,
        flexGrow: rootStyle.flexGrow,
        flexShrink: rootStyle.flexShrink,
        flexBasis: rootStyle.flexBasis,
        overflow: rootStyle.overflow,
      },
      labelStyle: {
        whiteSpace: labelStyle?.whiteSpace ?? '',
        lineHeight: labelStyle?.lineHeight ?? '',
        fontSize: labelStyle?.fontSize ?? '',
        fontWeight: labelStyle?.fontWeight ?? '',
      },
      contentStyle: {
        whiteSpace: contentStyle?.whiteSpace ?? '',
        lineHeight: contentStyle?.lineHeight ?? '',
        fontSize: contentStyle?.fontSize ?? '',
        fontWeight: contentStyle?.fontWeight ?? '',
      },
    }
  })

const visibleStatusTag = (page: Page) =>
  page
    .locator('.review-section:visible .admin-desktop-status-tag')
    .filter({ hasText: 'Taken Down' })

const selectReviewFamily = async (page: Page, name: string) => {
  const tab = page.getByRole('tab', { name, exact: true })
  await tab.click()
  await expect(tab).toHaveAttribute('aria-selected', 'true')
  const status = visibleStatusTag(page)
  await expect(status).toHaveCount(1)
  await expect(status).toBeVisible()
  return status
}

const readAdministratorBadge = async (page: Page) =>
  page
    .locator('.review-section:visible .review-admin-upload-chip')
    .first()
    .evaluate((element) => {
      const badge = element as HTMLElement
      return {
        whiteSpace: getComputedStyle(badge).whiteSpace,
        clientWidth: badge.clientWidth,
        scrollWidth: badge.scrollWidth,
      }
    })

test('keeps the same Review Center status pill geometry in both desktop tables', async ({
  page,
}) => {
  test.setTimeout(45_000)
  await mockReviewCenter(page)

  const viewport = { width: 1440, height: 737 }
  await page.setViewportSize(viewport)
  await page.goto('/admin', { waitUntil: 'networkidle' })
  await expect(page.getByRole('tab', { name: 'Review Center', exact: true })).toHaveAttribute(
    'aria-selected',
    'true'
  )

  const newStatus = await selectReviewFamily(page, 'New Course / Category Exam Requests')
  const newGeometry = await readStatusGeometry(newStatus)
  const newAdministrator = await readAdministratorBadge(page)

  const existingStatus = await selectReviewFamily(page, 'Existing Course Exam Requests')
  const existingGeometry = await readStatusGeometry(existingStatus)
  const existingAdministrator = await readAdministratorBadge(page)

  console.info(
    `review-status-geometry ${viewport.width}x${viewport.height}`,
    JSON.stringify({ new: newGeometry, existing: existingGeometry })
  )

  for (const geometry of [newGeometry, existingGeometry]) {
    const horizontalPadding =
      Number.parseFloat(geometry.style.paddingInlineStart) +
      Number.parseFloat(geometry.style.paddingInlineEnd)
    expect(geometry.text).toBe('Taken Down')
    expect(geometry.dom.root).toBe('span')
    expect(geometry.dom.content).toBe('admin-desktop-status-label')
    expect(['flex', 'inline-flex']).toContain(geometry.style.display)
    expect(geometry.style.whiteSpace).toBe('nowrap')
    expect(geometry.contentStyle.whiteSpace).toBe('nowrap')
    expect(geometry.style.borderRadius).toBe('999px')
    expect(geometry.style.lineHeight).toBe(geometry.contentStyle.lineHeight)
    expect(geometry.style.fontSize).toBe(geometry.contentStyle.fontSize)
    expect(geometry.style.fontWeight).toBe(geometry.contentStyle.fontWeight)
    expect(geometry.sizing.scrollHeight).toBeLessThanOrEqual(geometry.sizing.clientHeight + 1)
    expect(geometry.rect.width).toBeGreaterThanOrEqual(
      geometry.contentRect.width + horizontalPadding - 1
    )
    expect(geometry.rect.width).toBeLessThanOrEqual(geometry.cellRect.usableWidth + 1)
    expect(geometry.sizing.scrollWidth).toBeLessThanOrEqual(geometry.sizing.clientWidth + 1)
    expect(geometry.style.maxInlineSize).toBe('none')
    expect(geometry.style.flexGrow).toBe('0')
    expect(geometry.style.flexShrink).toBe('0')
    expect(geometry.style.flexBasis).toBe('auto')
  }

  expect(Math.abs(newGeometry.rect.height - existingGeometry.rect.height)).toBeLessThanOrEqual(1)
  expect(Math.abs(newGeometry.rect.width - existingGeometry.rect.width)).toBeLessThanOrEqual(1)
  expect(newGeometry.style.display).toBe(existingGeometry.style.display)
  expect(newGeometry.style.paddingInlineStart).toBe(existingGeometry.style.paddingInlineStart)
  expect(newGeometry.style.paddingInlineEnd).toBe(existingGeometry.style.paddingInlineEnd)
  expect(newGeometry.style.paddingBlockStart).toBe(existingGeometry.style.paddingBlockStart)
  expect(newGeometry.style.paddingBlockEnd).toBe(existingGeometry.style.paddingBlockEnd)
  expect(newGeometry.style.lineHeight).toBe(existingGeometry.style.lineHeight)
  expect(newGeometry.style.fontSize).toBe(existingGeometry.style.fontSize)
  expect(newGeometry.style.fontWeight).toBe(existingGeometry.style.fontWeight)
  expect(newGeometry.style.borderRadius).toBe(existingGeometry.style.borderRadius)

  for (const badge of [newAdministrator, existingAdministrator]) {
    expect(badge.whiteSpace).toBe('nowrap')
    expect(badge.scrollWidth).toBeLessThanOrEqual(badge.clientWidth + 1)
  }
})
