import { userTest as test, expect } from '../support/userTest'
import { JSON_HEADERS } from '../support/constants'
import type { Page } from '@playwright/test'

const initialWishes = Array.from({ length: 12 }, (_, index) => ({
  id: index + 1,
  title:
    index === 2
      ? '這是一個用來驗證兩行標題仍然不會超出安全邊界的量子力學考古題許願'
      : `API 順序許願 ${index + 1}`,
  subject: '量子力學',
  professor: '王教授',
  academic_year: 1141,
  name: '期末考',
  creator_name: `使用者 ${index + 1}`,
  created_at: `2026-08-${String(29 - index).padStart(2, '0')}T00:00:00Z`,
  heart_count: index === 2 ? 30 : (index * index) % 31,
  hearted_by_me: false,
  fulfilled: false,
}))

const appendedWishes = [
  { ...initialWishes[0], id: 13, title: '追加許願 13', heart_count: 80 },
  { ...initialWishes[1], id: 14, title: '追加許願 14', heart_count: 1 },
]

async function installEmptyWishPoolRoutes(page: Page) {
  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (request.method() === 'GET' && url.pathname === '/api/wishes') {
      await route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify({ items: [], total: 0 }),
      })
      return
    }
    if (request.method() === 'GET' && url.pathname === '/api/courses/categories') {
      await route.fulfill({ status: 200, headers: JSON_HEADERS, body: '[]' })
      return
    }
    if (request.method() === 'GET' && url.pathname === '/api/courses') {
      await route.fulfill({ status: 200, headers: JSON_HEADERS, body: '{}' })
      return
    }
    if (request.method() === 'GET' && url.pathname === '/api/users/me') {
      await route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify({ id: 2, name: '一般使用者', nickname: '' }),
      })
      return
    }
    if (
      request.method() === 'GET' &&
      ['/api/notifications/active', '/api/notifications/unread-summary'].includes(url.pathname)
    ) {
      await route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body:
          url.pathname === '/api/notifications/active'
            ? '[]'
            : JSON.stringify({
                announcements: [],
                personal_notifications: [],
                counts: { announcements: 0, personal_notifications: 0, total: 0 },
              }),
      })
      return
    }
    if (request.method() === 'POST' && url.pathname === '/api/auth/heartbeat') {
      await route.fulfill({ status: 200, headers: JSON_HEADERS, body: '{}' })
      return
    }
    await route.continue()
  })
}

test.describe('User › Wish Pool responsive Honeycomb', () => {
  test('centers the successful empty state without creating a scrollable Honeycomb world', async ({
    page,
  }) => {
    await installEmptyWishPoolRoutes(page)
    const viewports = [
      { width: 375, height: 812 },
      { width: 390, height: 844 },
      { width: 402, height: 874 },
      { width: 429, height: 869 },
      { width: 766, height: 1024 },
      { width: 767, height: 1024 },
      { width: 768, height: 1024 },
      { width: 834, height: 1210 },
      { width: 1024, height: 768 },
      { width: 1440, height: 900 },
    ]

    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto('/archive')

    const archiveIcon = page.locator('i.pi-book.text-6xl')
    const archiveMessage = page.getByText('請從左側選單選擇課程', { exact: true })
    await expect(archiveIcon).toBeVisible()
    await expect(archiveMessage).toBeVisible()

    const archiveReference = await archiveMessage.evaluate((messageElement) => {
      const iconElement = document.querySelector('i.pi-book.text-6xl')!
      const iconStyle = getComputedStyle(iconElement)
      const messageStyle = getComputedStyle(messageElement)
      return {
        iconFontSize: iconStyle.fontSize,
        iconWidth: iconElement.getBoundingClientRect().width,
        messageColor: messageStyle.color,
        messageFontSize: messageStyle.fontSize,
        messageFontWeight: messageStyle.fontWeight,
        messageLineHeight: messageStyle.lineHeight,
      }
    })

    await page.getByRole('button', { name: '考古許願池', exact: true }).click()

    const emptyState = page.locator('.wish-empty-state')
    const icon = emptyState.locator('.wish-empty-state__icon')
    const message = emptyState.getByText('池水靜靜地等著，等一個願望落下第一圈漣漪。', {
      exact: true,
    })

    for (const viewport of viewports) {
      await page.setViewportSize(viewport)
      await expect(emptyState).toBeVisible()
      await expect(icon).toBeVisible()
      await expect(message).toBeVisible()
      await expect(page.locator('.wish-pool-stage')).toHaveCount(0)
      await expect(page.locator('.wish-pool-world')).toHaveCount(0)

      const visualMatch = await emptyState.evaluate((element) => {
        const iconElement = element.querySelector('.wish-empty-state__icon')!
        const messageElement = element.querySelector('p')!
        const messageLeadElement = element.querySelector('.wish-empty-state__message-lead')!
        const messageContinuationElement = element.querySelector(
          '.wish-empty-state__message-continuation'
        )!
        const mobileBreakElement = element.querySelector('.wish-empty-state__mobile-break')!
        const iconStyle = getComputedStyle(iconElement)
        const messageStyle = getComputedStyle(messageElement)
        const transform = new DOMMatrixReadOnly(iconStyle.transform)
        return {
          iconFontSize: iconStyle.fontSize,
          iconScaleX: transform.a,
          iconScaleY: transform.d,
          iconWidth: iconElement.getBoundingClientRect().width,
          messageColor: messageStyle.color,
          messageFontSize: messageStyle.fontSize,
          messageFontWeight: messageStyle.fontWeight,
          messageLineHeight: messageStyle.lineHeight,
          messageLeadTop: messageLeadElement.getBoundingClientRect().top,
          messageContinuationTop: messageContinuationElement.getBoundingClientRect().top,
          mobileBreakDisplay: getComputedStyle(mobileBreakElement).display,
        }
      })

      expect(visualMatch.iconFontSize).toBe(archiveReference.iconFontSize)
      expect(visualMatch.iconScaleX).toBeCloseTo(0.93, 2)
      expect(visualMatch.iconScaleY).toBeCloseTo(1, 2)
      expect(visualMatch.iconWidth / archiveReference.iconWidth).toBeCloseTo(0.93, 2)
      expect(visualMatch.messageColor).toBe(archiveReference.messageColor)
      expect(visualMatch.messageFontSize).toBe(archiveReference.messageFontSize)
      expect(visualMatch.messageFontWeight).toBe(archiveReference.messageFontWeight)
      expect(visualMatch.messageLineHeight).toBe(archiveReference.messageLineHeight)
      if (viewport.width <= 767) {
        expect(visualMatch.mobileBreakDisplay).toBe('inline')
        expect(visualMatch.messageContinuationTop).toBeGreaterThan(visualMatch.messageLeadTop)
      } else {
        expect(visualMatch.mobileBreakDisplay).toBe('none')
        expect(
          Math.abs(visualMatch.messageContinuationTop - visualMatch.messageLeadTop)
        ).toBeLessThan(1)
      }

      const metrics = await emptyState.evaluate((element) => {
        const stateRect = element.getBoundingClientRect()
        const iconRect = element.querySelector('.wish-empty-state__icon')!.getBoundingClientRect()
        const messageRect = element.querySelector('p')!.getBoundingClientRect()
        const headerRect = element.previousElementSibling!.getBoundingClientRect()
        return {
          stateLeft: stateRect.left,
          stateRight: stateRect.right,
          stateCenterX: stateRect.left + stateRect.width / 2,
          iconLeft: iconRect.left,
          iconRight: iconRect.right,
          iconTop: iconRect.top,
          iconCenterX: iconRect.left + iconRect.width / 2,
          messageLeft: messageRect.left,
          messageRight: messageRect.right,
          messageCenterX: messageRect.left + messageRect.width / 2,
          headerBottom: headerRect.bottom,
          documentScrollWidth: document.documentElement.scrollWidth,
          viewportWidth: window.innerWidth,
          stateScrollWidth: element.scrollWidth,
          stateClientWidth: element.clientWidth,
        }
      })

      expect(metrics.stateLeft).toBeGreaterThanOrEqual(0)
      expect(metrics.stateRight).toBeLessThanOrEqual(metrics.viewportWidth)
      expect(metrics.iconLeft).toBeGreaterThanOrEqual(metrics.stateLeft)
      expect(metrics.iconRight).toBeLessThanOrEqual(metrics.stateRight)
      expect(metrics.messageLeft).toBeGreaterThanOrEqual(metrics.stateLeft)
      expect(metrics.messageRight).toBeLessThanOrEqual(metrics.stateRight)
      expect(metrics.iconTop).toBeGreaterThanOrEqual(metrics.headerBottom)
      expect(Math.abs(metrics.iconCenterX - metrics.stateCenterX)).toBeLessThan(1)
      expect(Math.abs(metrics.messageCenterX - metrics.stateCenterX)).toBeLessThan(1)
      expect(metrics.stateScrollWidth).toBeLessThanOrEqual(metrics.stateClientWidth)
      expect(metrics.documentScrollWidth).toBeLessThanOrEqual(metrics.viewportWidth)
    }
  })

  test('shares stable Honeycomb cells across Mobile, Tablet, and Desktop', async ({ page }) => {
    let wishRequestCount = 0
    await page.route('**/api/**', async (route) => {
      const request = route.request()
      const url = new URL(request.url())
      if (request.method() === 'GET' && url.pathname === '/api/wishes') {
        wishRequestCount += 1
        const items = wishRequestCount === 1 ? initialWishes : appendedWishes
        await route.fulfill({
          status: 200,
          headers: JSON_HEADERS,
          body: JSON.stringify({ items, total: 14 }),
        })
        return
      }
      if (request.method() === 'GET' && url.pathname === '/api/courses/categories') {
        await route.fulfill({ status: 200, headers: JSON_HEADERS, body: '[]' })
        return
      }
      if (request.method() === 'GET' && url.pathname === '/api/courses') {
        await route.fulfill({ status: 200, headers: JSON_HEADERS, body: '{}' })
        return
      }
      if (request.method() === 'GET' && url.pathname === '/api/users/me') {
        await route.fulfill({
          status: 200,
          headers: JSON_HEADERS,
          body: JSON.stringify({ id: 2, name: '一般使用者', nickname: '' }),
        })
        return
      }
      if (request.method() === 'GET' && url.pathname === '/api/notifications/active') {
        await route.fulfill({ status: 200, headers: JSON_HEADERS, body: '[]' })
        return
      }
      if (request.method() === 'GET' && url.pathname === '/api/notifications/unread-summary') {
        await route.fulfill({
          status: 200,
          headers: JSON_HEADERS,
          body: JSON.stringify({
            announcements: [],
            personal_notifications: [],
            counts: { announcements: 0, personal_notifications: 0, total: 0 },
          }),
        })
        return
      }
      if (request.method() === 'POST' && url.pathname === '/api/auth/heartbeat') {
        await route.fulfill({ status: 200, headers: JSON_HEADERS, body: '{}' })
        return
      }
      await route.continue()
    })

    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto('/archive')
    await page.getByRole('button', { name: '考古許願池', exact: true }).click()

    const stage = page.locator('.wish-pool-stage')
    const nodes = page.locator('.wish-node')
    await expect(stage).toBeVisible()
    await expect(nodes).toHaveCount(initialWishes.length)

    const readCells = async (count = initialWishes.length) =>
      nodes.evaluateAll(
        (items, requestedCount) =>
          items.slice(0, requestedCount).map((item) => ({
            id: item.getAttribute('data-wish-id'),
            q: Number(item.getAttribute('data-wish-q')),
            r: Number(item.getAttribute('data-wish-r')),
          })),
        count
      )

    const assertHoneycomb = async () => {
      const cells = await readCells()
      expect(cells.map(({ id }) => id)).toEqual(initialWishes.map(({ id }) => String(id)))
      expect(new Set(cells.map(({ q, r }) => `${q}:${r}`)).size).toBe(cells.length)
      expect(cells.some(({ r }) => Math.abs(r) % 2 === 1)).toBe(true)
      expect(
        await nodes.evaluateAll((items) => {
          const boxes = items.map((item) =>
            item.querySelector('.wish-item')!.getBoundingClientRect()
          )
          return boxes.every((box, index) =>
            boxes
              .slice(index + 1)
              .every(
                (other) =>
                  box.right <= other.left ||
                  other.right <= box.left ||
                  box.bottom <= other.top ||
                  other.bottom <= box.top
              )
          )
        })
      ).toBe(true)
    }

    await assertHoneycomb()
    const desktopCells = await readCells()
    const desktopRows = [...new Set(desktopCells.map(({ r }) => r))].sort(
      (left, right) => left - right
    )

    await page.setViewportSize({ width: 390, height: 844 })
    await expect(stage).toHaveClass(/is-mobile-scroll/)
    await expect(stage).not.toHaveClass(/is-vertical-distribution/)
    await assertHoneycomb()
    const initialMobileCells = await readCells()
    expect(initialMobileCells).toEqual(desktopCells)
    expect(
      [...new Set(initialMobileCells.map(({ r }) => r))].sort((left, right) => left - right)
    ).toEqual(desktopRows)
    const nativeWorld = await stage.evaluate((element) => ({
      scrollWidth: element.scrollWidth,
      clientWidth: element.clientWidth,
      scrollHeight: element.scrollHeight,
      clientHeight: element.clientHeight,
      documentScrollWidth: document.documentElement.scrollWidth,
      viewportWidth: window.innerWidth,
    }))
    expect(nativeWorld.scrollWidth).toBeGreaterThan(nativeWorld.clientWidth)
    expect(nativeWorld.scrollHeight).toBeGreaterThan(nativeWorld.clientHeight)
    expect(nativeWorld.documentScrollWidth).toBeLessThanOrEqual(nativeWorld.viewportWidth)

    await page.emulateMedia({ reducedMotion: 'reduce' })
    await stage.dispatchEvent('pointerdown', {
      pointerId: 27,
      pointerType: 'touch',
      isPrimary: true,
      clientX: 100,
      clientY: 100,
    })
    const exploredPosition = await stage.evaluate((element) => {
      element.scrollLeft = element.scrollWidth
      element.scrollTop = element.scrollHeight
      element.dispatchEvent(new Event('scroll'))
      return { left: element.scrollLeft, top: element.scrollTop }
    })
    expect(exploredPosition.left).toBeGreaterThan(0)
    expect(exploredPosition.top).toBeGreaterThan(0)
    const returnButton = page.getByRole('button', { name: '回到中央' })
    await expect(returnButton).not.toHaveClass(/is-at-origin/)
    await returnButton.click()
    await expect
      .poll(async () => {
        const centeredPosition = await stage.evaluate((element) => ({
          left: element.scrollLeft,
          top: element.scrollTop,
          expectedLeft: (element.scrollWidth - element.clientWidth) / 2,
          expectedTop: (element.scrollHeight - element.clientHeight) / 2,
        }))
        return (
          Math.abs(centeredPosition.left - centeredPosition.expectedLeft) < 1 &&
          Math.abs(centeredPosition.top - centeredPosition.expectedTop) < 1
        )
      })
      .toBe(true)

    await page.getByRole('button', { name: '載入更多' }).click()
    await expect(nodes).toHaveCount(14)
    expect(await readCells()).toEqual(initialMobileCells)
    const appendedCells = await readCells(14)
    expect(new Set(appendedCells.map(({ q, r }) => `${q}:${r}`)).size).toBe(14)

    await page.setViewportSize({ width: 834, height: 1210 })
    await expect(stage).toHaveClass(/is-tablet-scroll/)
    await expect(stage).not.toHaveClass(/is-mobile-scroll/)
    await assertHoneycomb()
    expect(await readCells()).toEqual(desktopCells)
    const tabletWorld = await stage.evaluate((element) => ({
      scrollWidth: element.scrollWidth,
      clientWidth: element.clientWidth,
      scrollHeight: element.scrollHeight,
      clientHeight: element.clientHeight,
    }))
    expect(tabletWorld.scrollWidth).toBeGreaterThan(tabletWorld.clientWidth)
    expect(tabletWorld.scrollHeight).toBeGreaterThan(tabletWorld.clientHeight)

    await page.setViewportSize({ width: 390, height: 844 })
    expect(await readCells()).toEqual(initialMobileCells)

    await page.setViewportSize({ width: 1440, height: 900 })
    await expect(stage).not.toHaveClass(/is-native-scroll/)
    await assertHoneycomb()
    expect(await readCells()).toEqual(desktopCells)
  })
})
