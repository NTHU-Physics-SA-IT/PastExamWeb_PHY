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
    const actionDivider = page.locator('.hero-action-divider')
    await expect(heroActions).toHaveCount(3)
    await expect(actionDivider).toBeVisible()
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
    expect(actionBoxes.every((box) => Math.abs((box?.width ?? 0) - (actionBoxes[0]?.width ?? 0)) <= 1)).toBe(
      true
    )
    expect(
      actionBoxes.every((box) => Math.abs((box?.height ?? 0) - (actionBoxes[0]?.height ?? 0)) <= 1)
    ).toBe(true)
    expect(actionBoxes.map((box) => box?.top ?? 0)).toEqual(
      [...actionBoxes.map((box) => box?.top ?? 0)].sort((left, right) => left - right)
    )
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
    expect(actionLayout.every(({ width }) => Math.abs(width - actionLayout[0].width) <= 1)).toBe(true)
    expect(actionLayout.every(({ height }) => Math.abs(height - actionLayout[0].height) <= 1)).toBe(
      true
    )

    const actionStyles = await heroActions.evaluateAll((buttons) =>
      buttons.map((button) => {
        const style = getComputedStyle(button)
        return {
          backgroundColor: style.backgroundColor,
          borderColor: style.borderColor,
          borderRadius: style.borderRadius,
        }
      })
    )
    expect(actionStyles[0].backgroundColor).not.toBe('rgba(0, 0, 0, 0)')
    expect(actionStyles[1].backgroundColor).toBe('rgba(0, 0, 0, 0)')
    expect(actionStyles[1].borderColor).not.toBe('rgba(0, 0, 0, 0)')
    expect(actionStyles[2].backgroundColor).toBe('rgba(0, 0, 0, 0)')
    expect(actionStyles[2].borderColor).toBe('rgba(0, 0, 0, 0)')
    expect(actionStyles.every(({ borderRadius }) => borderRadius === actionStyles[0].borderRadius)).toBe(
      true
    )
    await expect(page.getByText('書卷沒有，考古這有', { exact: true })).toBeVisible()

    const titleLines = await page.locator('.title-line').evaluateAll((lines) =>
      lines.map((line) => {
        const { left, right, top } = line.getBoundingClientRect()
        return { center: (left + right) / 2, top }
      })
    )
    expect(titleLines).toHaveLength(2)
    expect(titleLines[1].top).toBeGreaterThan(titleLines[0].top)
    expect(Math.abs(titleLines[0].center - titleLines[1].center)).toBeLessThanOrEqual(1)
    await expect(page.locator('.hero-action-divider')).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  })

  test('preserves the desktop hero action row and right-side metrics', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto('/')

    const heroActions = page.locator('.hero-actions button')
    const catalogAction = page.getByRole('button', {
      name: '瀏覽公開課程目錄',
      exact: true,
    })
    const catalogTarget = page.locator('#desktop-catalog-action')
    const statCards = page.locator('.dashboard-strip .stat-card')
    await expect(heroActions).toHaveCount(2)
    const actionBoxes = await heroActions.evaluateAll((buttons) =>
      buttons.map((button) => {
        const { height, left, top, width } = button.getBoundingClientRect()
        return { height, left, top, width }
      })
    )
    const actionStyles = await heroActions.evaluateAll((buttons) =>
      buttons.map((button) => {
        const style = getComputedStyle(button)
        return { backgroundColor: style.backgroundColor, borderColor: style.borderColor }
      })
    )
    const heroBox = await page.locator('.hero-copy').boundingBox()
    const metricsBox = await page.locator('.dashboard-strip').boundingBox()

    expect(actionBoxes).toHaveLength(2)
    expect(actionBoxes.every(({ top }) => Math.abs(top - actionBoxes[0].top) <= 1)).toBe(true)
    expect(actionBoxes[1].width).toBeLessThan(actionBoxes[0].width)
    expect(actionBoxes[1].height).toBeCloseTo(actionBoxes[0].height, 3)
    expect(actionStyles[0].backgroundColor).not.toBe('rgba(0, 0, 0, 0)')
    expect(actionStyles[1].backgroundColor).toBe('rgba(0, 0, 0, 0)')
    expect(actionStyles[1].borderColor).not.toBe('rgba(0, 0, 0, 0)')
    expect(actionBoxes.map(({ left }) => left)).toEqual(
      [...actionBoxes.map(({ left }) => left)].sort((left, right) => left - right)
    )
    await expect(page.locator('.hero-action-divider')).toBeHidden()
    await expect(catalogTarget.getByRole('button')).toHaveCount(1)
    await expect(page.getByRole('button', { name: '瀏覽公開課程目錄' })).toHaveCount(1)
    await expect(statCards).toHaveCount(6)
    await expect(statCards.last()).toHaveCSS('opacity', '1')
    expect(heroBox).not.toBeNull()
    expect(metricsBox).not.toBeNull()
    expect(metricsBox?.x ?? 0).toBeGreaterThan((heroBox?.x ?? 0) + (heroBox?.width ?? 0) / 2)
    expect(
      Math.abs(
        (heroBox?.y ?? 0) + (heroBox?.height ?? 0) / 2 -
          ((metricsBox?.y ?? 0) + (metricsBox?.height ?? 0) / 2)
      )
    ).toBeLessThanOrEqual(2)

    const onlineBox = await statCards.last().boundingBox()
    const catalogBox = await catalogAction.boundingBox()
    const catalogTargetBox = await catalogTarget.boundingBox()
    const separatorStyle = await catalogTarget.evaluate((target) => {
      const style = getComputedStyle(target, '::before')
      return { backgroundColor: style.backgroundColor, height: style.height, width: style.width }
    })
    expect(onlineBox).not.toBeNull()
    expect(catalogBox).not.toBeNull()
    expect(catalogTargetBox).not.toBeNull()
    expect(catalogBox?.y ?? 0).toBeGreaterThan((onlineBox?.y ?? 0) + (onlineBox?.height ?? 0))
    expect(Math.abs((catalogBox?.x ?? 0) - (onlineBox?.x ?? 0))).toBeLessThanOrEqual(1)
    expect(catalogBox?.width ?? 0).toBeLessThan(onlineBox?.width ?? 0)
    expect(catalogTargetBox?.width ?? 0).toBeCloseTo(onlineBox?.width ?? 0, 1)
    expect(separatorStyle.height).toBe('1px')
    expect(Number.parseFloat(separatorStyle.width)).toBeCloseTo(catalogTargetBox?.width ?? 0, 1)
    expect(separatorStyle.backgroundColor).not.toBe('rgba(0, 0, 0, 0)')
  })

  test('drifts the desktop mass core from between 理 and 考 to its neutral position', async ({
    page,
  }) => {
    await page.emulateMedia({ reducedMotion: 'no-preference' })
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.addInitScript(() => {
      const testWindow = window as typeof window & {
        __massCoreEntryInitialGeometry?: {
          circle: { cx: string | null; cy: string | null; r: string | null }
          renderedStart: { x: number; y: number }
          titleJunction: { x: number; y: number }
        }
      }

      const observer = new MutationObserver(() => {
        const titleLeading = document.querySelector('.title-line-leading')
        const titleTrailing = document.querySelector('.title-line-trailing')
        const entryGroup = document.querySelector('.mass-core-entry')
        const circle = document.querySelector('.mass-core')
        if (
          !titleLeading ||
          !titleTrailing ||
          !entryGroup?.classList.contains('mass-core-entry-animate') ||
          !circle
        ) {
          return
        }

        // Capture the first visible geometry before the independently animated SVG parent advances.
        const leadingRect = titleLeading.getBoundingClientRect()
        const trailingRect = titleTrailing.getBoundingClientRect()
        const circleRect = circle.getBoundingClientRect()
        testWindow.__massCoreEntryInitialGeometry = {
          circle: {
            cx: circle.getAttribute('cx'),
            cy: circle.getAttribute('cy'),
            r: circle.getAttribute('r'),
          },
          renderedStart: {
            x: circleRect.left + circleRect.width / 2,
            y: circleRect.top + circleRect.height / 2,
          },
          titleJunction: {
            x: (leadingRect.right + trailingRect.left) / 2,
            y: (leadingRect.top + leadingRect.bottom + trailingRect.top + trailingRect.bottom) / 4,
          },
        }
        observer.disconnect()
      })

      observer.observe(document, {
        attributes: true,
        attributeFilter: ['class'],
        childList: true,
        subtree: true,
      })
    })
    await page.goto('/')

    const entry = page.locator('.mass-core-entry')
    await expect(entry).toHaveClass(/mass-core-entry-animate/)

    const initialGeometry = await page.evaluate(() => {
      const testWindow = window as typeof window & {
        __massCoreEntryInitialGeometry?: {
          circle: { cx: string | null; cy: string | null; r: string | null }
          renderedStart: { x: number; y: number }
          titleJunction: { x: number; y: number }
        }
      }
      return testWindow.__massCoreEntryInitialGeometry ?? null
    })

    expect(initialGeometry).not.toBeNull()
    expect(initialGeometry?.circle).toEqual({ cx: '760', cy: '380', r: '92' })
    expect(
      Math.abs((initialGeometry?.renderedStart.x ?? 0) - (initialGeometry?.titleJunction.x ?? 0))
    ).toBeLessThanOrEqual(16)
    expect(
      Math.abs((initialGeometry?.renderedStart.y ?? 0) - (initialGeometry?.titleJunction.y ?? 0))
    ).toBeLessThanOrEqual(16)

    await expect(entry).not.toHaveClass(/mass-core-entry-animate/, { timeout: 6500 })
    const completedState = await entry.evaluate((element) => ({
      transform: getComputedStyle(element).transform,
      x: element.style.getPropertyValue('--mass-core-entry-x'),
      y: element.style.getPropertyValue('--mass-core-entry-y'),
    }))
    expect(['none', 'matrix(1, 0, 0, 1, 0, 0)']).toContain(completedState.transform)
    expect(completedState.x).toBe('')
    expect(completedState.y).toBe('')

    const circle = page.locator('.mass-core')
    const home = page.locator('.physics-home')
    const initialThemeIsDark = await home.evaluate((element) =>
      element.classList.contains('physics-home-dark')
    )
    const initialFill = await circle.evaluate((element) => getComputedStyle(element).fill)
    await page.locator('.theme-toggle-button').click()
    await expect(home).toHaveClass(initialThemeIsDark ? /physics-home(?!-dark)/ : /physics-home-dark/)
    await expect(entry).not.toHaveClass(/mass-core-entry-animate/)
    expect(await circle.evaluate((element) => getComputedStyle(element).fill)).not.toBe(initialFill)
  })

  test('sweeps a scoped sheen across the homepage actions without shifting layout', async ({
    page,
  }) => {
    await page.emulateMedia({ reducedMotion: 'no-preference' })
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto('/')

    const heroActions = page.locator('.hero-actions button')
    const catalogAction = page.getByRole('button', {
      name: '瀏覽公開課程目錄',
      exact: true,
    })
    const catalogTarget = page.locator('#desktop-catalog-action')
    await expect(heroActions).toHaveCount(2)

    const readButtonState = (buttonLocator: typeof catalogAction) =>
      buttonLocator.evaluate((button) => {
        const buttonStyle = getComputedStyle(button)
        const sheenStyle = getComputedStyle(button, '::before')
        const iconStyle = getComputedStyle(button.querySelector('.p-button-icon') as Element)
        const label = button.querySelector('.p-button-label') as Element
        const labelStyle = getComputedStyle(label)
        const labelRevealStyle = getComputedStyle(label, '::before')
        const labelUnderlineStyle = getComputedStyle(label, '::after')
        const labelBox = label.getBoundingClientRect()
        const { left, top, width, height } = button.getBoundingClientRect()
        const transform = new DOMMatrixReadOnly(sheenStyle.transform)

        return {
          backgroundColor: buttonStyle.backgroundColor,
          border: buttonStyle.border,
          color: buttonStyle.color,
          height,
          iconTransform: iconStyle.transform,
          labelRevealTransitionDuration: labelRevealStyle.transitionDuration,
          labelRevealWidth: Number.parseFloat(labelRevealStyle.width),
          labelTransform: labelStyle.transform,
          labelUnderlineWidth: Number.parseFloat(labelUnderlineStyle.width),
          labelWidth: labelBox.width,
          left,
          sheenDisplay: sheenStyle.display,
          sheenPointerEvents: sheenStyle.pointerEvents,
          sheenTransitionDuration: sheenStyle.transitionDuration,
          sheenTranslateX: transform.m41,
          top,
          width,
        }
      })

    const beforeHover = await readButtonState(heroActions.nth(0))
    expect(beforeHover.sheenDisplay).toBe('block')
    expect(beforeHover.sheenPointerEvents).toBe('none')
    expect(beforeHover.sheenTranslateX).toBeCloseTo(0, 3)

    await heroActions.nth(0).hover()
    await page.waitForTimeout(1050)
    const afterHover = await readButtonState(heroActions.nth(0))

    expect(afterHover.sheenTransitionDuration).toBe('1s')
    expect(afterHover.sheenTranslateX).toBeGreaterThan(0)
    expect(afterHover.left).toBeCloseTo(beforeHover.left, 3)
    expect(afterHover.top).toBeCloseTo(beforeHover.top, 3)
    expect(afterHover.width).toBeCloseTo(beforeHover.width, 3)
    expect(afterHover.height).toBeCloseTo(beforeHover.height, 3)

    const catalogBeforeHover = await readButtonState(catalogAction)
    expect(catalogBeforeHover.sheenDisplay).toBe('none')
    expect(catalogBeforeHover.labelRevealWidth).toBeCloseTo(0, 3)
    expect(catalogBeforeHover.labelUnderlineWidth).toBeCloseTo(0, 3)
    await catalogAction.hover()
    await expect
      .poll(
        async () => {
          const state = await readButtonState(catalogAction)
          return Math.max(
            Math.abs(state.labelRevealWidth - state.labelWidth),
            Math.abs(state.labelUnderlineWidth - state.labelWidth)
          )
        },
        { timeout: 1500 }
      )
      .toBeCloseTo(0, 1)
    const catalogAfterHover = await readButtonState(catalogAction)
    expect(catalogAfterHover.sheenDisplay).toBe('none')
    expect(catalogAfterHover.backgroundColor).toBe(catalogBeforeHover.backgroundColor)
    expect(catalogAfterHover.border).toBe(catalogBeforeHover.border)
    expect(catalogAfterHover.color).toBe(catalogBeforeHover.color)
    expect(catalogAfterHover.iconTransform).toBe(catalogBeforeHover.iconTransform)
    expect(catalogAfterHover.labelTransform).toBe(catalogBeforeHover.labelTransform)
    expect(catalogAfterHover.labelRevealTransitionDuration).toBe('0.3s')
    expect(catalogAfterHover.labelRevealWidth).toBeCloseTo(catalogAfterHover.labelWidth, 1)
    expect(catalogAfterHover.labelUnderlineWidth).toBeCloseTo(catalogAfterHover.labelWidth, 1)
    expect(catalogAfterHover.left).toBeCloseTo(catalogBeforeHover.left, 3)
    expect(catalogAfterHover.top).toBeCloseTo(catalogBeforeHover.top, 3)

    const initialThemeIsDark = await page
      .locator('.physics-home')
      .evaluate((home) => home.classList.contains('physics-home-dark'))
    await page.locator('.theme-toggle-button').click()
    await expect(page.locator('.physics-home')).toHaveClass(
      initialThemeIsDark ? /physics-home(?!-dark)/ : /physics-home-dark/
    )
    await expect(heroActions).toHaveCount(2)
    await expect(
      catalogTarget.getByRole('button', { name: '瀏覽公開課程目錄', exact: true })
    ).toHaveCount(1)

    await page.setViewportSize({ width: 390, height: 844 })
    await expect(heroActions).toHaveCount(3)
    await expect(catalogTarget.getByRole('button')).toHaveCount(0)
    const mobileLayout = await heroActions.evaluateAll((buttons) =>
      buttons.map((button) => {
        const { left, right, width, height } = button.getBoundingClientRect()
        return { height, left, right, width }
      })
    )
    expect(mobileLayout.every(({ left, right }) => left >= 0 && right <= 390)).toBe(true)
    expect(mobileLayout.every(({ width, height }) => width > 0 && height > 0)).toBe(true)

    await page.emulateMedia({ reducedMotion: 'reduce' })
    const reducedMotionDisplays = await heroActions.evaluateAll((buttons) =>
      buttons.map((button) => getComputedStyle(button, '::before').display)
    )
    expect(reducedMotionDisplays).toEqual(['none', 'none', 'none'])
  })

  test('public catalog renders canonical courses and a zero-archive detail', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('button', { name: 'Login', exact: true })).toHaveCount(0)

    await page.getByRole('button', { name: '瀏覽公開課程目錄', exact: true }).click()

    await expect(page).toHaveURL(/\/courses$/)
    await expect(page.getByRole('heading', { name: '清大物理考古題課程目錄' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Login', exact: true })).toHaveCount(0)

    const courseCards = page.locator('.course-card')
    await expect(courseCards).toHaveCount(71)
    await expect(page.locator('.public-catalog > .empty-state')).toHaveCount(0)
    expect(await courseCards.first().evaluate((card) => getComputedStyle(card).borderTopWidth)).toBe(
      '1px'
    )

    const zeroArchiveCourse = page.locator('a[href="/courses/1"]')
    await expect(zeroArchiveCourse).toBeVisible()
    await zeroArchiveCourse.click()

    await expect(page).toHaveURL(/\/courses\/1$/)
    await expect(page.getByRole('heading', { name: '普通化學(一)考古題' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Login', exact: true })).toHaveCount(0)
    await expect(page.getByRole('heading', { name: '目前尚未有可公開瀏覽的考古題' })).toBeVisible()
    await expect(page.locator('a, button').filter({ hasText: '下載' })).toHaveCount(0)
    await expect(page.locator('meta[name="robots"]')).toHaveAttribute('content', 'noindex, follow')

    const breadcrumbCenters = await page.locator('.breadcrumbs > *').evaluateAll((items) =>
      items.map((item) => {
        const { top, height } = item.getBoundingClientRect()
        return top + height / 2
      })
    )
    expect(Math.max(...breadcrumbCenters) - Math.min(...breadcrumbCenters)).toBeLessThanOrEqual(1)
  })

  test('applies the default user preference once over the application font baseline', async ({
    page,
  }) => {
    await page.goto('/')

    expect(
      await page.evaluate(() => ({
        computedRootSize: getComputedStyle(document.documentElement).fontSize,
        baseline: getComputedStyle(document.documentElement)
          .getPropertyValue('--app-font-baseline')
          .trim(),
        userScale: getComputedStyle(document.documentElement)
          .getPropertyValue('--app-user-font-scale')
          .trim(),
        effectiveScale: getComputedStyle(document.documentElement)
          .getPropertyValue('--app-effective-font-scale')
          .trim(),
        displayPercent: document.documentElement.dataset.appFontSizeDisplayPercent,
      }))
    ).toEqual({
      computedRootSize: '14.4px',
      baseline: '0.9',
      userScale: '1',
      effectiveScale: '0.9',
      displayPercent: '100',
    })
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

    const brand = page.getByRole('link', { name: '回到首頁', exact: true })
    await expect(brand).toBeVisible()
    await expect(brand).toHaveAttribute('href', '/')
    await expect(page.getByRole('img', { name: '清大物理考古系統' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Login', exact: true })).toHaveCount(0)

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

    const statCards = page.getByRole('article')
    await expect(statCards).toHaveCount(STAT_LABELS.length, { timeout: 15000 })

    for (const label of STAT_LABELS) {
      const card = statCards.filter({ hasText: label })
      await expect(card, `${label} card should be visible`).toBeVisible()
      await expect(card.locator('strong')).toHaveText(/^[0-9]+$/, { timeout: 15000 })
    }

    await page.goto('/not-found-for-navbar-check')
    const loginButton = page.getByRole('button', { name: 'Login', exact: true })
    await expect(loginButton).toBeVisible({ timeout: 15000 })
    await clickWhenVisible(loginButton)
    const loginDialog = page.getByRole('dialog', { name: '登入' })
    await expect(loginDialog).toBeVisible()
    await expect(loginButton).toHaveAttribute('aria-expanded', 'true')
    const closeButton = loginDialog.getByRole('button', { name: 'Close' })
    await expect(closeButton).toBeVisible()
    await clickWhenVisible(closeButton)
    await expect(loginButton).toHaveAttribute('aria-expanded', 'false')
  })
})
