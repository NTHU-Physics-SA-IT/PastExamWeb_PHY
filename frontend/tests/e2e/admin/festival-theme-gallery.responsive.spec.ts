import { expect, test, type Page } from '@playwright/test'
import { mockAdminCourseEndpoints, mockAdminNotificationEndpoints } from '../support/adminFixtures'
import { JSON_HEADERS } from '../support/constants'
import { buildJwt } from '../support/jwt'

const json = (value: unknown) => ({
  status: 200,
  headers: JSON_HEADERS,
  body: JSON.stringify(value),
})

type ThemeScenario = {
  label: string
  activeTheme: 'general' | 'christmas'
  userPreference: 'light' | 'dark'
  effectiveTheme: 'light' | 'dark' | 'christmas'
  classicIcon: 'pi-sun' | 'pi-moon'
  classicSurface: string
  classicFooter: string
  classicText: string
}

const createThemeCapabilities = (activeTheme: ThemeScenario['activeTheme']) => ({
  general_theme: {
    active: activeTheme === 'general',
    user_selectable: true,
    supported_modes: ['light', 'dark'],
  },
  festival_theme: {
    active: activeTheme === 'christmas' ? 'christmas' : null,
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
    ],
  },
})

const themeScenarios: ThemeScenario[] = [
  {
    label: 'classic light',
    activeTheme: 'general',
    userPreference: 'light',
    effectiveTheme: 'light',
    classicIcon: 'pi-sun',
    classicSurface: 'rgb(238, 246, 242)',
    classicFooter: 'rgb(247, 251, 251)',
    classicText: 'rgb(23, 37, 34)',
  },
  {
    label: 'classic dark',
    activeTheme: 'general',
    userPreference: 'dark',
    effectiveTheme: 'dark',
    classicIcon: 'pi-moon',
    classicSurface: 'rgb(23, 34, 31)',
    classicFooter: 'rgb(16, 23, 21)',
    classicText: 'rgb(243, 251, 248)',
  },
  {
    label: 'Christmas',
    activeTheme: 'christmas',
    userPreference: 'light',
    effectiveTheme: 'christmas',
    classicIcon: 'pi-sun',
    classicSurface: 'rgb(238, 246, 242)',
    classicFooter: 'rgb(247, 251, 251)',
    classicText: 'rgb(23, 37, 34)',
  },
]

const viewports = [
  { label: 'phone portrait', width: 390, height: 844 },
  { label: 'tablet portrait', width: 834, height: 1210 },
  { label: 'tablet landscape', width: 1024, height: 768 },
  { label: 'desktop', width: 1440, height: 900 },
]

const openFestivalThemePanel = async (page: Page) => {
  await expect(page).toHaveURL(/\/admin$/)

  const adminRoot = page.locator('.admin-container')
  await expect(adminRoot).toBeVisible()

  const announcementTab = adminRoot.locator('.admin-primary-tab-list').getByRole('tab', {
    name: '公告管理',
    exact: true,
  })
  await expect(announcementTab).toBeVisible()
  await announcementTab.click()
  await expect(announcementTab).toHaveAttribute('aria-selected', 'true')

  const announcementManagementTabs = adminRoot.locator('.announcement-management-tabs')
  await expect(announcementManagementTabs).toBeVisible()

  const festivalTab = announcementManagementTabs.getByRole('tab', {
    name: '節日主題管理',
    exact: true,
  })
  const gallery = page.getByTestId('theme-overview-gallery')

  await expect(festivalTab).toBeVisible()
  await festivalTab.click()
  await expect(festivalTab).toHaveAttribute('aria-selected', 'true')
  await expect(gallery).toBeVisible()
}

const configureThemeScenario = async (page: Page, scenario: ThemeScenario) => {
  await page.addInitScript((preference: ThemeScenario['userPreference']) => {
    window.localStorage.setItem('theme-preference', preference)
  }, scenario.userPreference)
  await page.route('**/api/theme-management/active-theme', (route) =>
    route.fulfill(json({ active_theme: scenario.activeTheme }))
  )
  await page.route('**/api/admin/theme-management', (route) =>
    route.fulfill(json(createThemeCapabilities(scenario.activeTheme)))
  )
}

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
    await mockAdminNotificationEndpoints(page, [])
  })

  for (const scenario of themeScenarios) {
    for (const viewport of viewports) {
      test(`${scenario.label} at ${viewport.label} keeps every theme card and action readable`, async ({
        page,
      }) => {
        await configureThemeScenario(page, scenario)
        await page.setViewportSize({ width: viewport.width, height: viewport.height })
        await page.emulateMedia({ reducedMotion: 'reduce' })
        await page.goto('/admin', { waitUntil: 'networkidle' })
        await openFestivalThemePanel(page)

        const gallery = page.getByTestId('theme-overview-gallery')
        const cards = page.getByTestId('theme-overview-card')
        const classicCard = page.locator(
          '[data-testid="theme-overview-card"][data-theme-kind="classic"]'
        )
        const festivalCard = page.locator(
          '[data-testid="theme-overview-card"][data-theme-kind="festival"]'
        )
        await expect(gallery).toBeVisible()
        await expect(cards).toHaveCount(2)
        await expect(page.locator('html')).toHaveAttribute(
          'data-effective-theme',
          scenario.effectiveTheme
        )
        await expect(
          scenario.activeTheme === 'general' ? classicCard : festivalCard
        ).toHaveAttribute('aria-current', 'true')
        await expect(classicCard).toContainText('經典模式')
        await expect(festivalCard).toContainText('聖誕模式')
        await expect(cards.getByTestId('festival-theme-delete')).toHaveCount(0)
        await expect(cards.getByRole('button', { name: '刪除', exact: true })).toHaveCount(0)
        await expect(cards.locator('.pi-trash')).toHaveCount(0)
        for (const card of await cards.all()) {
          await expect(card.getByTestId('theme-mode-visual')).toHaveCount(1)
          await expect(card.getByTestId('theme-card-details')).toHaveCount(1)
          await expect(card.getByTestId('theme-palette-swatch')).toHaveCount(0)
        }

        const classicIcon = classicCard.getByTestId('theme-mode-icon')
        const festivalIcon = festivalCard.getByTestId('theme-mode-icon')
        await expect(classicIcon).toHaveClass(new RegExp(`\\b${scenario.classicIcon}\\b`))
        await expect(festivalIcon).toHaveClass(/\bpi-bell\b/)
        await expect(classicIcon).toHaveAttribute('aria-hidden', 'true')
        await expect(festivalIcon).toHaveAttribute('aria-hidden', 'true')

        await expect(classicCard.getByTestId('theme-mode-visual')).toHaveCSS(
          'background-color',
          scenario.classicSurface
        )
        await expect(classicCard.locator('.theme-gallery-card__footer')).toHaveCSS(
          'background-color',
          scenario.classicFooter
        )
        await expect(classicCard).toHaveCSS('color', scenario.classicText)
        if (scenario.effectiveTheme === 'dark') {
          const evidence = await classicCard.evaluate((card) => {
            const style = getComputedStyle(card)
            const visual = card.querySelector('[data-testid="theme-mode-visual"]')!
            const matchedDarkSelectors: string[] = []
            const inspectRules = (rules: CSSRuleList) => {
              for (const rule of Array.from(rules)) {
                if (
                  rule instanceof CSSStyleRule &&
                  rule.selectorText.includes('data-effective-theme') &&
                  rule.selectorText.includes('.festival-theme-management') &&
                  rule.style.getPropertyValue('--theme-card-surface') &&
                  card.matches(rule.selectorText)
                ) {
                  matchedDarkSelectors.push(rule.selectorText)
                }
                if (rule instanceof CSSGroupingRule) inspectRules(rule.cssRules)
              }
            }
            for (const sheet of Array.from(document.styleSheets)) {
              if (sheet.href && new URL(sheet.href).origin !== location.origin) continue
              inspectRules(sheet.cssRules)
            }
            return {
              rootClasses: document.documentElement.className,
              effectiveTheme: document.documentElement.dataset.effectiveTheme,
              mainBackground: getComputedStyle(visual).backgroundColor,
              footerBackground: getComputedStyle(card.querySelector('.theme-gallery-card__footer')!)
                .backgroundColor,
              primaryText: style.color,
              secondaryText: getComputedStyle(
                card.querySelector('.theme-gallery-card__description')!
              ).color,
              borderColor: style.borderTopColor,
              borderToken: style.getPropertyValue('--theme-card-border').trim(),
              canonicalBorderToken: style.getPropertyValue('--border-color').trim(),
              iconClass: card.querySelector('[data-testid="theme-mode-icon"]')!.className,
              matchedDarkSelectors,
              backgroundImage: getComputedStyle(visual).backgroundImage,
            }
          })
          await test.info().attach('classic-dark-computed-style', {
            body: JSON.stringify({ viewport, ...evidence }, null, 2),
            contentType: 'application/json',
          })
          expect(evidence.rootClasses.split(/\s+/)).toContain('dark')
          expect(evidence.secondaryText).toBe('rgb(170, 187, 181)')
          expect(evidence.borderToken).toBe(evidence.canonicalBorderToken)
          expect(evidence.matchedDarkSelectors).not.toHaveLength(0)
          expect(evidence.backgroundImage).toBe('none')
          await expect(classicCard.locator('.pi-sun, .pi-bell')).toHaveCount(0)
        }
        await expect(festivalCard.getByTestId('theme-mode-visual')).toHaveCSS(
          'background-color',
          'rgb(66, 104, 120)'
        )
        await expect(festivalCard.locator('.theme-gallery-card__footer')).toHaveCSS(
          'background-color',
          'rgb(54, 89, 104)'
        )

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

        for (const card of [classicCard, festivalCard]) {
          const visualBox = await card.getByTestId('theme-mode-visual').boundingBox()
          const iconBox = await card.getByTestId('theme-mode-icon').boundingBox()
          expect(visualBox).not.toBeNull()
          expect(iconBox).not.toBeNull()
          expect(
            Math.abs(iconBox!.x + iconBox!.width / 2 - (visualBox!.x + visualBox!.width / 2))
          ).toBeLessThan(2)
          expect(
            Math.abs(iconBox!.y + iconBox!.height / 2 - (visualBox!.y + visualBox!.height / 2))
          ).toBeLessThan(2)
          expect(iconBox!.x).toBeGreaterThanOrEqual(visualBox!.x)
          expect(iconBox!.x + iconBox!.width).toBeLessThanOrEqual(visualBox!.x + visualBox!.width)
          expect(iconBox!.y).toBeGreaterThanOrEqual(visualBox!.y)
          expect(iconBox!.y + iconBox!.height).toBeLessThanOrEqual(visualBox!.y + visualBox!.height)
        }

        if (viewport.width > 767.98) {
          const galleryWidth = await gallery.evaluate(
            (element) => element.getBoundingClientRect().width
          )
          expect(geometry[0].width).toBeLessThan(galleryWidth)
          expect(Math.abs(geometry[0].width - geometry[1].width)).toBeLessThan(2)

          const firstDetails = cards.first().getByTestId('theme-card-details')
          await expect(firstDetails).toHaveCSS('opacity', '0')
          await cards.first().hover()
          await expect(firstDetails).toHaveCSS('opacity', '1')

          const expandedWidths = await cards.evaluateAll((elements) =>
            elements.map((element) => element.getBoundingClientRect().width)
          )
          expect(expandedWidths[0] - expandedWidths[1]).toBeGreaterThan(20)

          const dividerHeights = await cards
            .locator('.theme-gallery-card__footer')
            .evaluateAll((elements) =>
              elements.map((element) => element.getBoundingClientRect().top)
            )
          expect(Math.abs(dividerHeights[0] - dividerHeights[1])).toBeLessThan(1)
        } else {
          for (const details of await cards.getByTestId('theme-card-details').all()) {
            await expect(details).toHaveCSS('opacity', '1')
          }
        }

        for (const card of await cards.all()) {
          await card.hover()
          await expect(card.getByTestId('theme-card-details')).toHaveCSS('opacity', '1')
          for (const action of await card.getByRole('button').all()) {
            await expect(action).toBeVisible()
          }
        }

        const editAction = festivalCard.getByRole('button', { name: '編輯', exact: true })
        const inactiveCard = scenario.activeTheme === 'general' ? festivalCard : classicCard
        const activateAction = inactiveCard.getByRole('button', { name: '啟用', exact: true })
        await expect(activateAction).toBeVisible()
        if (scenario.effectiveTheme === 'christmas') {
          await expect(editAction).toHaveAttribute('data-christmas-button-snow', 'true')
          await expect(activateAction).toHaveAttribute('data-christmas-button-snow', 'true')
        } else {
          await expect(editAction).not.toHaveAttribute('data-christmas-button-snow', 'true')
          await expect(activateAction).not.toHaveAttribute('data-christmas-button-snow', 'true')
        }
        await editAction.focus()
        await expect(editAction).toBeFocused()
        await expect
          .poll(() => festivalCard.evaluate((element) => element.matches(':focus-within')))
          .toBe(true)
        await expect(festivalCard.getByTestId('theme-card-details')).toHaveCSS('opacity', '1')

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
  }
})
