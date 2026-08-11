import { test, expect } from '@playwright/test'
import { clickWhenVisible } from '../support/ui'

const STAT_LABELS = ['考古題', '課程', '下載', '使用者', '今日活躍', '在線']

const STATISTICS_RESPONSE = {
  totalUsers: 12,
  totalDownloads: 34,
  onlineUsers: 2,
  totalArchives: 56,
  totalCourses: 7,
  activeToday: 3,
}

test.describe('Home page', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/statistics', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ data: STATISTICS_RESPONSE }),
      })
    )
  })

  test('centers hero content at the tablet breakpoint', async ({ page }) => {
    await page.setViewportSize({ width: 820, height: 701 })
    await page.goto('/')

    const heading = page.getByRole('heading', { name: '清大物理考古系統' })
    const subtitle = page.getByText('書卷沒有，考古這有', { exact: true })
    const nthuLoginAction = page.getByRole('button', {
      name: '清華校務系統登入',
      exact: true,
    })
    const localLoginAction = page.getByRole('button', { name: '本地帳號登入', exact: true })
    const catalogAction = page.getByRole('button', { name: '瀏覽公開課程目錄', exact: true })
    await expect(heading).toBeVisible()
    await expect(subtitle).toBeVisible()
    await expect(nthuLoginAction).toBeVisible()
    await expect(localLoginAction).toBeVisible()
    await expect(catalogAction).toBeVisible()
    await expect(page.getByRole('button', { name: '登入開始使用', exact: true })).toHaveCount(0)
    await expect(page.locator('.hero-seo-summary')).toHaveCount(0)

    const heroActions = page.locator('.hero-actions button')
    await expect(heroActions).toHaveCount(3)
    expect(await heroActions.allTextContents()).toEqual([
      '清華校務系統登入',
      '本地帳號登入',
      '瀏覽公開課程目錄',
    ])
    const [nthuClasses, localClasses, catalogClasses] = await heroActions.evaluateAll((buttons) =>
      buttons.map((button) => button.className)
    )
    expect(nthuClasses).toBe(localClasses)
    expect(nthuClasses).not.toContain('p-button-secondary')
    expect(nthuClasses).not.toContain('p-button-outlined')
    expect(catalogClasses).toContain('p-button-secondary')
    expect(catalogClasses).toContain('p-button-outlined')

    const textCenter = (locator: typeof heading) =>
      locator.evaluate((element) => {
        const textCenter = (element: Element) => {
          const range = document.createRange()
          range.selectNodeContents(element)
          const { left, right } = range.getBoundingClientRect()
          return (left + right) / 2
        }
        return textCenter(element)
      })
    const actionBoxes = await Promise.all([
      nthuLoginAction.boundingBox(),
      localLoginAction.boundingBox(),
      catalogAction.boundingBox(),
    ])
    expect(actionBoxes.every(Boolean)).toBe(true)
    const actionLeft = Math.min(...actionBoxes.map((box) => box?.x ?? 0))
    const actionRight = Math.max(...actionBoxes.map((box) => (box?.x ?? 0) + (box?.width ?? 0)))
    const centers = {
      subtitle: await textCenter(subtitle),
      title: await textCenter(heading),
      actions: (actionLeft + actionRight) / 2,
    }

    expect(Math.abs(centers.subtitle - centers.title)).toBeLessThanOrEqual(0.5)
    expect(Math.abs(centers.subtitle - centers.actions)).toBeLessThanOrEqual(0.5)
  })

  test('keeps the mobile action order accessible without horizontal overflow', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto('/')

    const heroActions = page.locator('.hero-actions button')
    await expect(heroActions).toHaveCount(3)
    expect(await heroActions.allTextContents()).toEqual([
      '清華校務系統登入',
      '本地帳號登入',
      '瀏覽公開課程目錄',
    ])

    const actionLayout = await heroActions.evaluateAll((buttons) =>
      buttons.map((button) => {
        const { left, right, top, width, height } = button.getBoundingClientRect()
        return { left, right, top, width, height, tabIndex: (button as HTMLButtonElement).tabIndex }
      })
    )

    expect(actionLayout.every(({ left, right }) => left >= 0 && right <= 390)).toBe(true)
    expect(actionLayout.map(({ top }) => top)).toEqual(
      [...actionLayout.map(({ top }) => top)].sort()
    )
    expect(actionLayout.map(({ tabIndex }) => tabIndex)).toEqual([0, 0, 0])
    expect(actionLayout[0].width).toBeCloseTo(actionLayout[1].width, 3)
    expect(actionLayout[0].height).toBeCloseTo(actionLayout[1].height, 3)
  })

  test('public catalog renders canonical courses and a zero-archive detail', async ({ page }) => {
    await page.goto('/')

    await page.getByRole('button', { name: '瀏覽公開課程目錄', exact: true }).click()

    await expect(page).toHaveURL(/\/courses$/)
    await expect(page.getByRole('heading', { name: '清大物理考古題課程目錄' })).toBeVisible()

    const courseCards = page.locator('.course-card')
    await expect(courseCards).toHaveCount(71)
    await expect(page.locator('.public-catalog > .empty-state')).toHaveCount(0)

    const zeroArchiveCourse = page.locator('a[href="/courses/1"]')
    await expect(zeroArchiveCourse).toBeVisible()
    await zeroArchiveCourse.click()

    await expect(page).toHaveURL(/\/courses\/1$/)
    await expect(page.getByRole('heading', { name: '普通化學(一)考古題' })).toBeVisible()
    await expect(page.getByRole('heading', { name: '目前尚未有可公開瀏覽的考古題' })).toBeVisible()
    await expect(page.locator('a, button').filter({ hasText: '下載' })).toHaveCount(0)
    await expect(page.locator('meta[name="robots"]')).toHaveAttribute('content', 'noindex, follow')
  })

  test('homepage local login action opens the existing login dialog', async ({ page }) => {
    await page.goto('/')

    const localLoginAction = page.getByRole('button', { name: '本地帳號登入', exact: true })
    await expect(localLoginAction).toBeVisible({ timeout: 15000 })
    await clickWhenVisible(localLoginAction)
    const loginDialog = page.getByRole('dialog', { name: '登入' })
    await expect(loginDialog).toBeVisible()
    await expect(loginDialog.getByLabel('帳號')).toBeVisible()
    await expect(loginDialog.getByLabel('密碼')).toBeVisible()
    await expect(loginDialog.getByRole('button', { name: '登入', exact: true })).toBeVisible()
    await expect(
      loginDialog.getByRole('button', { name: '清華校務系統登入', exact: true })
    ).toHaveCount(0)
    await expect(loginDialog.getByText('或', { exact: true })).toHaveCount(0)
  })

  test('homepage NTHU login action initiates the canonical OAuth boundary once', async ({
    page,
  }) => {
    let initiationCount = 0
    await page.route('**/api/auth/nthu/login', (route) => {
      initiationCount += 1
      return route.fulfill({
        status: 200,
        contentType: 'text/html',
        body: '<!doctype html><title>NTHU OAuth boundary</title>',
      })
    })
    await page.goto('/')

    await page.getByRole('button', { name: '清華校務系統登入', exact: true }).click()

    await expect(page).toHaveURL(/\/api\/auth\/nthu\/login$/)
    expect(initiationCount).toBe(1)
  })

  test('renders hero section with backend data and interactive navbar', async ({ page }) => {
    await page.goto('/')

    const brand = page.getByRole('button', { name: /Physics Archive · NTHU/ })
    await expect(brand).toBeVisible()
    await expect(page.getByRole('img', { name: '清大物理考古系統' })).toBeVisible()
    const loginButton = page.getByRole('button', { name: 'Login', exact: true })
    await expect(loginButton).toBeVisible({ timeout: 15000 })

    const themeToggle = page.getByRole('button', { name: /切換至(?:深色|淺色)模式/ })
    await expect(themeToggle).toBeVisible()
    const initialTheme = await page.evaluate(() =>
      document.documentElement.classList.contains('dark')
    )
    await clickWhenVisible(themeToggle)
    await expect
      .poll(async () => page.evaluate(() => document.documentElement.classList.contains('dark')))
      .not.toBe(initialTheme)

    await expect(page.getByRole('heading', { name: '清大物理考古系統' })).toBeVisible()

    await page.evaluate(() => {
      const globalWindow = window as typeof window & {
        __pastexam?: {
          openLoginModal?: () => void
        }
      }
      const pastexam = globalWindow.__pastexam
      if (pastexam && typeof pastexam.openLoginModal === 'function') {
        pastexam.openLoginModal()
      }
    })
    const loginDialog = page.getByRole('dialog', { name: '登入' })
    await expect(loginDialog).toBeVisible()
    await expect(loginButton).toHaveAttribute('aria-expanded', 'true')
    const closeButton = loginDialog.getByRole('button', { name: 'Close' })
    await expect(closeButton).toBeVisible()
    await clickWhenVisible(closeButton)
    await expect(loginButton).toHaveAttribute('aria-expanded', 'false')

    const statCards = page.getByRole('article')
    await expect(statCards).toHaveCount(STAT_LABELS.length, { timeout: 15000 })

    for (const label of STAT_LABELS) {
      const card = statCards.filter({ hasText: label })
      await expect(card, `${label} card should be visible`).toBeVisible()
      await expect(card.locator('strong')).toHaveText(/^[0-9]+$/, { timeout: 15000 })
    }
  })
})
