import { expect, test, type Page } from '@playwright/test'
import {
  defaultUsers,
  mockAdminCourseEndpoints,
  mockAdminUserEndpoints,
} from '../support/adminFixtures'
import { JSON_HEADERS } from '../support/constants'
import { buildJwt } from '../support/jwt'

const json = (value: unknown) => ({
  status: 200,
  headers: JSON_HEADERS,
  body: JSON.stringify(value),
})

const viewports = [
  { width: 320, height: 568 },
  { width: 360, height: 800 },
  { width: 375, height: 812 },
  { width: 390, height: 844 },
  { width: 402, height: 874 },
  { width: 414, height: 896 },
  { width: 430, height: 932 },
  { width: 768, height: 1024 },
  { width: 820, height: 1180 },
  { width: 834, height: 1210 },
  { width: 1024, height: 768 },
  { width: 1280, height: 800 },
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 },
  { width: 844, height: 390 },
  { width: 874, height: 402 },
]
const screenshotViewports = new Set(['375x812', '390x844', '430x932', '768x1024', '1440x900'])

const installAdminMocks = async (page: Page) => {
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

  await page.route('**/api/theme-management/active-theme', (route) =>
    route.fulfill(json({ active_theme: 'christmas' }))
  )
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
  await page.route('**/api/settings/contributor-levels', (route) =>
    route.fulfill(
      json(
        Array.from({ length: 10 }, (_, index) => ({
          level: index + 1,
          name: `等級 ${index + 1}`,
          name_en: `Level ${index + 1}`,
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
  await mockAdminUserEndpoints(page, defaultUsers)
}

test('keeps contributor level settings bounded and overlap-free across target viewports', async ({
  page,
}, testInfo) => {
  test.setTimeout(60_000)
  await installAdminMocks(page)
  await page.goto('/admin', { waitUntil: 'networkidle' })
  const settingsButton = page.getByRole('button', { name: '等級設定' })
  await expect(settingsButton).toBeVisible()
  const pagePaintState = await settingsButton.evaluate((element) => {
    const rect = element.getBoundingClientRect()
    const content = document.querySelector<HTMLElement>('.content-container')
    const hitTarget = document.elementFromPoint(
      rect.left + rect.width / 2,
      rect.top + rect.height / 2
    )
    return {
      documentHeight: document.documentElement.getBoundingClientRect().height,
      viewportHeight: window.innerHeight,
      contentHeight: content?.getBoundingClientRect().height ?? 0,
      buttonReceivesPointer:
        hitTarget === element || (hitTarget instanceof Node && element.contains(hitTarget)),
    }
  })
  expect(pagePaintState.documentHeight).toBeGreaterThanOrEqual(pagePaintState.viewportHeight)
  expect(pagePaintState.contentHeight).toBeGreaterThan(0)
  expect(pagePaintState.buttonReceivesPointer).toBe(true)
  await settingsButton.click()

  const dialog = page.getByRole('dialog', { name: '投稿等級設定' })
  const list = dialog.locator('.contributor-level-settings-list')
  const rows = dialog.locator('.contributor-level-settings-row')
  const badges = dialog.locator('.contributor-level__badge')
  const expInputs = dialog.locator('.p-inputnumber-input')
  const footer = dialog.locator('.contributor-level-settings-footer')
  await expect(dialog).toBeVisible()
  await expect(rows).toHaveCount(10)
  await expect(badges).toHaveCount(10)
  await expect(expInputs).toHaveCount(10)

  for (const viewport of viewports) {
    await page.setViewportSize(viewport)
    await expect(dialog).toBeVisible()

    const geometry = await dialog.evaluate((element) => {
      const rect = element.getBoundingClientRect()
      const listElement = element.querySelector('.contributor-level-settings-list')
      const footerElement = element.querySelector('.contributor-level-settings-footer')
      const rowElements = Array.from(
        element.querySelectorAll<HTMLElement>('.contributor-level-settings-row')
      )
      const rowGeometry = rowElements.map((row) => ({
        row: row.getBoundingClientRect(),
        children: Array.from(row.children).map((child) => child.getBoundingClientRect()),
      }))
      const firstInput = element.querySelector<HTMLInputElement>(
        '.contributor-level-settings-field input'
      )
      const badges = Array.from(element.querySelectorAll<HTMLElement>('.contributor-level__badge'))
      const expInputs = Array.from(
        element.querySelectorAll<HTMLInputElement>('.p-inputnumber-input')
      )
      const listRect = listElement?.getBoundingClientRect()
      const footerRect = footerElement?.getBoundingClientRect()
      return {
        dialog: { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom },
        documentHasHorizontalOverflow:
          document.documentElement.scrollWidth > document.documentElement.clientWidth,
        list:
          listElement && listRect
            ? {
                left: listRect.left,
                right: listRect.right,
                top: listRect.top,
                bottom: listRect.bottom,
                clientHeight: listElement.clientHeight,
                scrollHeight: listElement.scrollHeight,
                overflowY: getComputedStyle(listElement).overflowY,
              }
            : null,
        footer: footerRect
          ? {
              left: footerRect.left,
              right: footerRect.right,
              top: footerRect.top,
              bottom: footerRect.bottom,
            }
          : null,
        rowGeometry: rowGeometry.map(({ row, children }) => ({
          row: { left: row.left, right: row.right, top: row.top, bottom: row.bottom },
          children: children.map((child) => ({
            left: child.left,
            right: child.right,
            top: child.top,
            bottom: child.bottom,
          })),
        })),
        inputFontSize: firstInput ? Number.parseFloat(getComputedStyle(firstInput).fontSize) : 0,
        allBadgesRendered: badges.every((badge) => {
          const badgeRect = badge.getBoundingClientRect()
          return (
            getComputedStyle(badge).display !== 'none' &&
            badgeRect.width > 0 &&
            badgeRect.height > 0
          )
        }),
        allExpInputsRendered: expInputs.every((input) => {
          const inputRect = input.getBoundingClientRect()
          return (
            getComputedStyle(input).display !== 'none' &&
            inputRect.width > 0 &&
            inputRect.height > 0
          )
        }),
      }
    })

    expect(geometry.documentHasHorizontalOverflow, JSON.stringify(viewport)).toBe(false)
    expect(geometry.dialog.left, JSON.stringify(viewport)).toBeGreaterThanOrEqual(0)
    expect(geometry.dialog.right, JSON.stringify(viewport)).toBeLessThanOrEqual(viewport.width)
    expect(geometry.dialog.top, JSON.stringify(viewport)).toBeGreaterThanOrEqual(0)
    expect(geometry.dialog.bottom, JSON.stringify(viewport)).toBeLessThanOrEqual(viewport.height)
    expect(geometry.list?.overflowY, JSON.stringify(viewport)).toBe('auto')
    expect(geometry.allBadgesRendered, JSON.stringify(viewport)).toBe(true)
    expect(geometry.allExpInputsRendered, JSON.stringify(viewport)).toBe(true)
    expect(geometry.footer?.bottom, JSON.stringify(viewport)).toBeLessThanOrEqual(
      geometry.dialog.bottom + 1
    )

    for (const [rowIndex, row] of geometry.rowGeometry.entries()) {
      if (rowIndex > 0) {
        expect(row.row.top, JSON.stringify(viewport)).toBeGreaterThanOrEqual(
          geometry.rowGeometry[rowIndex - 1].row.bottom - 1
        )
      }
      expect(row.row.left, JSON.stringify(viewport)).toBeGreaterThanOrEqual(
        (geometry.list?.left ?? 0) - 1
      )
      expect(row.row.right, JSON.stringify(viewport)).toBeLessThanOrEqual(
        (geometry.list?.right ?? viewport.width) + 1
      )
      if (viewport.width <= 640) {
        for (let index = 1; index < row.children.length; index += 1) {
          expect(row.children[index].top, JSON.stringify(viewport)).toBeGreaterThanOrEqual(
            row.children[index - 1].bottom - 1
          )
        }
      } else {
        const childTops = row.children.map((child) => Math.round(child.top))
        expect(new Set(childTops).size, JSON.stringify(viewport)).toBe(1)
      }
    }

    if (viewport.width <= 640) {
      expect(geometry.list?.scrollHeight, JSON.stringify(viewport)).toBeGreaterThan(
        geometry.list?.clientHeight ?? Number.POSITIVE_INFINITY
      )
      expect(geometry.inputFontSize, JSON.stringify(viewport)).toBeGreaterThanOrEqual(16)
      const resetBox = await footer
        .locator('.contributor-level-settings-reset')
        .evaluate((element) => {
          const rect = element.getBoundingClientRect()
          return { left: rect.left, right: rect.right }
        })
      const actionBoxes = await footer.locator('.p-button').evaluateAll((elements) =>
        elements.map((element) => {
          const rect = element.getBoundingClientRect()
          return { left: rect.left, right: rect.right, top: rect.top }
        })
      )
      expect(resetBox.right - resetBox.left, JSON.stringify(viewport)).toBeGreaterThan(
        actionBoxes[1].right - actionBoxes[1].left
      )
      expect(Math.round(actionBoxes[1].top), JSON.stringify(viewport)).toBe(
        Math.round(actionBoxes[2].top)
      )
    }

    const viewportKey = `${viewport.width}x${viewport.height}`
    if (screenshotViewports.has(viewportKey)) {
      await page.screenshot({ path: testInfo.outputPath(`contributor-level-${viewportKey}.png`) })
    }
  }

  await list.evaluate((element) => {
    element.scrollTop = element.scrollHeight
  })
  const finalBounds = await page.evaluate(() => {
    const listElement = document.querySelector('.contributor-level-settings-list')
    const lastRow = document.querySelector('.contributor-level-settings-row:last-child')
    const footerElement = document.querySelector('.contributor-level-settings-footer')
    const listRect = listElement?.getBoundingClientRect()
    const rowRect = lastRow?.getBoundingClientRect()
    const footerRect = footerElement?.getBoundingClientRect()
    return {
      lastRowBottom: rowRect?.bottom ?? Number.POSITIVE_INFINITY,
      listBottom: listRect?.bottom ?? 0,
      footerTop: footerRect?.top ?? 0,
    }
  })
  expect(finalBounds.lastRowBottom).toBeLessThanOrEqual(finalBounds.listBottom + 1)
  expect(finalBounds.listBottom).toBeLessThanOrEqual(finalBounds.footerTop + 1)
  await expect(dialog.getByRole('button', { name: 'Close' })).toBeVisible()
  await expect(dialog.getByRole('button', { name: '保存全部設定' })).toBeVisible()
})
