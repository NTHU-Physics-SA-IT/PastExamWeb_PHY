import { expect, test } from '@playwright/test'
import { mockAdminCourseEndpoints, mockAdminNotificationEndpoints } from '../support/adminFixtures'
import { JSON_HEADERS } from '../support/constants'
import { buildJwt } from '../support/jwt'
import { clickWhenVisible } from '../support/ui'

const json = (value: unknown) => ({
  status: 200,
  headers: JSON_HEADERS,
  body: JSON.stringify(value),
})

const themeCapabilities = {
  general_theme: { active: false, user_selectable: true, supported_modes: ['light', 'dark'] },
  festival_theme: {
    active: 'christmas',
    themes: [
      {
        id: 'christmas',
        name: '聖誕模式',
        name_en: 'Christmas Theme',
        description: '這是專門為聖誕節準備的主題，只會在聖誕節使用。',
        description_en: 'A theme prepared especially for Christmas.',
        supports_color_modes: false,
        starts_at: null,
        ends_at: null,
      },
      {
        id: 'spring',
        name: '春節主題',
        name_en: 'Spring Festival Theme',
        description: '農曆新年期間使用的節慶視覺主題，保留足夠長度以驗證窄螢幕文字換行。',
        description_en: 'A Lunar New Year visual theme with wrapping content.',
        supports_color_modes: true,
        starts_at: null,
        ends_at: null,
      },
      {
        id: 'halloween',
        name: '萬聖節主題',
        name_en: 'Halloween Theme',
        description: '萬聖節限定外觀。',
        description_en: 'A Halloween appearance.',
        supports_color_modes: true,
        starts_at: null,
        ends_at: null,
      },
    ],
  },
}

const viewports = [
  { label: 'phone portrait', width: 390, height: 844 },
  { label: 'tablet portrait', width: 834, height: 1210 },
  { label: 'tablet landscape', width: 1024, height: 768 },
  { label: 'desktop', width: 1440, height: 900 },
]

test.describe('Admin › Festival Theme card gallery responsive contract', () => {
  test.beforeEach(async ({ page }) => {
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
      window.localStorage.setItem('admin-current-tab', '2')
    }, token)

    await page.route('**/api/auth/heartbeat', (route) => route.fulfill(json({})))
    await page.route('**/api/theme-management/active-theme', (route) =>
      route.fulfill(json({ active_theme: 'christmas' }))
    )
    await page.route('**/api/admin/theme-management', (route) =>
      route.fulfill(json(themeCapabilities))
    )
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
    await mockAdminCourseEndpoints(page)
    await mockAdminNotificationEndpoints(page, [])
  })

  for (const viewport of viewports) {
    test(`${viewport.label} keeps every theme card and action readable`, async ({ page }) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height })
      await page.emulateMedia({ reducedMotion: 'reduce' })
      await page.goto('/admin', { waitUntil: 'networkidle' })
      await clickWhenVisible(page.getByRole('tab', { name: '節日主題管理', exact: true }))

      const gallery = page.getByTestId('theme-overview-gallery')
      const cards = page.getByTestId('theme-overview-card')
      await expect(gallery).toBeVisible()
      await expect(cards).toHaveCount(4)
      await expect(cards.first()).toHaveAttribute('aria-current', 'true')
      await expect(cards.first()).toContainText('聖誕模式')
      await expect(cards.nth(1)).toContainText('經典模式')

      await expect
        .poll(() =>
          page.evaluate(
            () => document.documentElement.scrollWidth <= document.documentElement.clientWidth
          )
        )
        .toBe(true)

      const geometry = await cards.evaluateAll((elements) =>
        elements.map((element) => {
          const rect = element.getBoundingClientRect()
          return {
            left: rect.left,
            right: rect.right,
            width: rect.width,
            scrollWidth: element.scrollWidth,
            clientWidth: element.clientWidth,
          }
        })
      )
      for (const card of geometry) {
        expect(card.left).toBeGreaterThanOrEqual(0)
        expect(card.right).toBeLessThanOrEqual(viewport.width + 1)
        expect(card.scrollWidth).toBeLessThanOrEqual(card.clientWidth)
      }

      const visibleActions = cards.getByRole('button')
      expect(await visibleActions.count()).toBeGreaterThan(0)
      for (const action of await visibleActions.all()) {
        await expect(action).toBeVisible()
      }

      const editAction = cards.first().getByRole('button', { name: '編輯', exact: true })
      await expect(editAction).toHaveAttribute('data-christmas-button-snow', 'true')
      await editAction.focus()
      await expect(editAction).toBeFocused()
      await expect
        .poll(() => cards.first().evaluate((element) => element.matches(':focus-within')))
        .toBe(true)

      await cards.first().hover()
      await expect
        .poll(() => cards.first().evaluate((element) => getComputedStyle(element).transform))
        .toBe('none')

      if (viewport.width === 390) {
        const leftEdges = geometry.map((card) => Math.round(card.left))
        expect(new Set(leftEdges).size).toBe(1)
      }
    })
  }
})
