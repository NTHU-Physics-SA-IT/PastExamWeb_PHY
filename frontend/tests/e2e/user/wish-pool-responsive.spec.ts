import { userTest as test, expect } from '../support/userTest'
import { JSON_HEADERS } from '../support/constants'

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

test.describe('User › Wish Pool responsive Honeycomb', () => {
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
      if (request.method() === 'GET' && url.pathname === '/api/auth/heartbeat') {
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

    await page.setViewportSize({ width: 390, height: 844 })
    await expect(stage).toHaveClass(/is-mobile-scroll/)
    await expect(stage).not.toHaveClass(/is-vertical-distribution/)
    await assertHoneycomb()
    const initialMobileCells = await readCells()
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

    await page.getByRole('button', { name: '載入更多' }).click()
    await expect(nodes).toHaveCount(14)
    expect(await readCells()).toEqual(initialMobileCells)
    const appendedCells = await readCells(14)
    expect(new Set(appendedCells.map(({ q, r }) => `${q}:${r}`)).size).toBe(14)

    await page.setViewportSize({ width: 834, height: 1210 })
    await expect(stage).toHaveClass(/is-tablet-scroll/)
    await expect(stage).not.toHaveClass(/is-mobile-scroll/)
    await assertHoneycomb()

    await page.setViewportSize({ width: 390, height: 844 })
    expect(await readCells()).toEqual(initialMobileCells)

    await page.setViewportSize({ width: 1440, height: 900 })
    await expect(stage).not.toHaveClass(/is-native-scroll/)
    await assertHoneycomb()
  })
})
