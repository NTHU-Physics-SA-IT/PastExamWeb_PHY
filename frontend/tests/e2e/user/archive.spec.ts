import { userTest as test, expect } from '../support/userTest'
import { JSON_HEADERS } from '../support/constants'
import { fromBase64ToBinaryString } from '../support/jwt'
import { clickWhenVisible } from '../support/ui'
import { createConsoleErrorCollector } from '../support/consoleDiagnostics'

test.describe('User › Archive browsing', () => {
  test('renders the requested Christmas archive surfaces and navbar-blue snow background', async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width: 1920, height: 1080 })
    await page.route('**/api/theme-management/active-theme', (route) =>
      route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify({ active_theme: 'christmas' }),
      })
    )
    await page.route('**/api/auth/heartbeat', (route) =>
      route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify({}) })
    )
    await page.route('**/api/notifications/active', (route) =>
      route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify([]) })
    )
    await page.route('**/api/notifications/unread-summary**', (route) =>
      route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify({
          announcements: [],
          personal_notifications: [],
          counts: { announcements: 0, personal_notifications: 0, total: 0 },
        }),
      })
    )
    await page.route('**/api/courses', (route) =>
      route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify({
          fundamental: [
            { id: 101, name: '普通物理(一)' },
            { id: 102, name: '電磁學' },
            { id: 103, name: '量子力學' },
          ],
          required: [],
          experience: [],
          optional: [],
          graduate: [],
          'math-department': [],
        }),
      })
    )
    await page.route('**/api/courses/categories', (route) =>
      route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify([]) })
    )
    await page.route(/\/api\/courses\/101\/archives(?:\?.*)?$/, (route) =>
      route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify([
          {
            id: 201,
            academic_year: 1142,
            name: 'final',
            archive_type: 'final',
            professor: '王教授',
            has_answers: true,
            download_count: 12,
            uploader_id: 9,
          },
          {
            id: 202,
            academic_year: 1142,
            name: 'quiz2',
            archive_type: 'quiz',
            professor: '王教授',
            has_answers: false,
            download_count: 4,
            uploader_id: 10,
          },
          {
            id: 203,
            academic_year: 1141,
            name: 'midterm2',
            archive_type: 'midterm',
            professor: '李教授',
            has_answers: true,
            download_count: 27,
            uploader_id: 11,
          },
        ]),
      })
    )

    await page.goto('/archive')
    await expect(page).toHaveURL(/\/archive$/)
    await expect(page.locator('.card.navbar-christmas')).toBeVisible()

    const christmasApp = page.locator('#app.app-christmas-frosted-window')
    const snowfall = christmasApp.locator(':scope > .christmas-snowfall')
    await expect(christmasApp).toBeVisible()
    await expect(snowfall).toBeVisible()
    await expect(snowfall.locator('.christmas-background-snowflake')).toHaveCount(72)
    await expect(snowfall.locator('.christmas-decorative-snowflake')).toHaveCount(18)

    const searchInput = page.getByPlaceholder('搜尋課程')
    await searchInput.fill('普通物理')
    const courseButton = page.getByRole('button', { name: '普通物理(一)', exact: true })
    await clickWhenVisible(courseButton)
    await searchInput.fill('')

    const selectedCourseItem = page.locator('.active-course-menu-item').first()
    const selectedCourseContent = selectedCourseItem.locator('.p-panelmenu-item-content')
    const selectedCourseLink = selectedCourseItem.locator('.p-panelmenu-item-link')
    const desktopSidebar = page.locator('.archive-christmas .sidebar')
    const desktopUploadSection = desktopSidebar.locator('.upload-section')
    const subjectHeader = page.locator('.archive-christmas .subject-header')

    const semesterHeaders = page.locator('.p-accordionheader')
    const semesterHeader = semesterHeaders.first()
    const semesterPanel = page.locator('.p-accordionpanel').first()
    const semesterContentOuter = page.locator('.p-accordioncontent').first()
    const semesterContent = page.locator('.p-accordioncontent-content').first()
    const archiveCards = page.locator('.archive-record-card')
    await expect(selectedCourseLink).toBeVisible()
    await expect(subjectHeader).toBeVisible()
    await expect(semesterHeader).toBeVisible()
    await expect(semesterHeaders).toHaveCount(2)
    await expect(semesterHeaders).toContainText(['114下學期', '114上學期'])
    await expect(archiveCards).toHaveCount(3)
    await expect(archiveCards).toContainText(['final', 'quiz2', 'midterm2'])

    const selectedCourseStyles = await Promise.all(
      [selectedCourseItem, selectedCourseContent, selectedCourseLink].map((locator) =>
        locator.evaluate((element) => {
          const style = getComputedStyle(element)
          return {
            color: style.backgroundColor,
            image: style.backgroundImage,
            beforeImage: getComputedStyle(element, '::before').backgroundImage,
            afterImage: getComputedStyle(element, '::after').backgroundImage,
            shadow: style.boxShadow,
            backdrop: style.backdropFilter,
            filter: style.filter,
          }
        })
      )
    )
    const desktopSidebarStyle = await desktopSidebar.evaluate((element) => {
      const style = getComputedStyle(element)
      return {
        color: style.backgroundColor,
        image: style.backgroundImage,
        borderRightColor: style.borderRightColor,
        shadow: style.boxShadow,
      }
    })
    const desktopUploadSectionStyle = await desktopUploadSection.evaluate((element) => {
      const style = getComputedStyle(element)
      return {
        color: style.backgroundColor,
        image: style.backgroundImage,
        borderTopColor: style.borderTopColor,
      }
    })
    const subjectHeaderStyle = await subjectHeader.evaluate((element) => {
      const style = getComputedStyle(element)
      const afterStyle = getComputedStyle(element, '::after')
      return {
        color: style.backgroundColor,
        image: style.backgroundImage,
        borderBottomColor: style.borderBottomColor,
        shadow: style.boxShadow,
        afterContent: afterStyle.content,
        afterImage: afterStyle.backgroundImage,
      }
    })
    const christmasAppStyle = await christmasApp.evaluate((element) => {
      const style = getComputedStyle(element)
      return { color: style.backgroundColor, image: style.backgroundImage }
    })
    const snowfallStyle = await snowfall.evaluate((element) => {
      const style = getComputedStyle(element)
      return {
        opacity: style.opacity,
        pointerEvents: style.pointerEvents,
        position: style.position,
        zIndex: style.zIndex,
      }
    })
    const navbarStyle = await page.locator('.card.navbar-christmas').evaluate((element) => {
      const style = getComputedStyle(element)
      return {
        color: style.backgroundColor,
        image: style.backgroundImage,
        beforeImage: getComputedStyle(element, '::before').backgroundImage,
        afterImage: getComputedStyle(element, '::after').backgroundImage,
        shadow: style.boxShadow,
      }
    })
    const navbarMenubarStyle = await page
      .locator('.card.navbar-christmas .p-menubar')
      .evaluate((element) => {
        const style = getComputedStyle(element)
        return { color: style.backgroundColor, image: style.backgroundImage }
      })
    const semesterStyles = await semesterHeaders.evaluateAll((elements) =>
      elements.map((element) => {
        const style = getComputedStyle(element)
        return {
          color: style.backgroundColor,
          image: style.backgroundImage,
          beforeImage: getComputedStyle(element, '::before').backgroundImage,
          afterImage: getComputedStyle(element, '::after').backgroundImage,
          shadow: style.boxShadow,
        }
      })
    )
    const archiveCardStyles = await archiveCards.evaluateAll((elements) =>
      elements.map((element) => {
        const style = getComputedStyle(element)
        return {
          color: style.backgroundColor,
          image: style.backgroundImage,
          beforeImage: getComputedStyle(element, '::before').backgroundImage,
          afterImage: getComputedStyle(element, '::after').backgroundImage,
          shadow: style.boxShadow,
        }
      })
    )
    const semesterPanelStyles = await Promise.all(
      [semesterPanel, semesterContentOuter, semesterContent].map((locator) =>
        locator.evaluate((element) => {
          const style = getComputedStyle(element)
          return {
            color: style.backgroundColor,
            image: style.backgroundImage,
            beforeImage: getComputedStyle(element, '::before').backgroundImage,
            afterImage: getComputedStyle(element, '::after').backgroundImage,
            shadow: style.boxShadow,
            backdrop: style.backdropFilter,
            filter: style.filter,
          }
        })
      )
    )

    expect(selectedCourseStyles[0]).toEqual({
      color: christmasAppStyle.color,
      image: christmasAppStyle.image,
      beforeImage: 'none',
      afterImage: 'none',
      shadow: 'none',
      backdrop: 'none',
      filter: 'none',
    })
    expect(selectedCourseStyles.slice(1)).toEqual([
      {
        color: 'rgba(0, 0, 0, 0)',
        image: 'none',
        beforeImage: 'none',
        afterImage: 'none',
        shadow: 'none',
        backdrop: 'none',
        filter: 'none',
      },
      {
        color: 'rgba(0, 0, 0, 0)',
        image: 'none',
        beforeImage: 'none',
        afterImage: 'none',
        shadow: 'none',
        backdrop: 'none',
        filter: 'none',
      },
    ])
    expect(desktopSidebarStyle).toEqual({
      color: 'rgba(0, 0, 0, 0)',
      image: 'none',
      borderRightColor: 'rgba(0, 0, 0, 0)',
      shadow: 'none',
    })
    expect(desktopUploadSectionStyle).toEqual({
      color: 'rgba(0, 0, 0, 0)',
      image: 'none',
      borderTopColor: 'rgba(0, 0, 0, 0)',
    })
    expect(subjectHeaderStyle).toEqual({
      color: 'rgba(0, 0, 0, 0)',
      image: 'none',
      borderBottomColor: 'rgba(0, 0, 0, 0)',
      shadow: 'none',
      afterContent: 'none',
      afterImage: 'none',
    })
    expect(christmasAppStyle.color).toBe('rgb(66, 104, 120)')
    expect(christmasAppStyle.image).toContain('linear-gradient')
    expect(christmasAppStyle.image).toContain('rgb(66, 104, 120)')
    expect(snowfallStyle).toEqual({
      opacity: '0.75',
      pointerEvents: 'none',
      position: 'absolute',
      zIndex: '1',
    })
    expect(navbarStyle).toEqual({
      color: 'rgb(66, 104, 120)',
      image: 'none',
      beforeImage: 'none',
      afterImage: 'none',
      shadow: 'none',
    })
    expect(navbarMenubarStyle).toEqual({ color: 'rgb(66, 104, 120)', image: 'none' })
    expect(semesterStyles).toEqual([
      {
        color: 'rgb(41, 63, 82)',
        image: 'none',
        beforeImage: 'none',
        afterImage: 'none',
        shadow: 'none',
      },
      {
        color: 'rgb(41, 63, 82)',
        image: 'none',
        beforeImage: 'none',
        afterImage: 'none',
        shadow: 'none',
      },
    ])
    expect(archiveCardStyles).toEqual([
      {
        color: 'rgb(62, 95, 114)',
        image: 'none',
        beforeImage: 'none',
        afterImage: 'none',
        shadow: 'none',
      },
      {
        color: 'rgb(62, 95, 114)',
        image: 'none',
        beforeImage: 'none',
        afterImage: 'none',
        shadow: 'none',
      },
      {
        color: 'rgb(62, 95, 114)',
        image: 'none',
        beforeImage: 'none',
        afterImage: 'none',
        shadow: 'none',
      },
    ])
    expect(semesterPanelStyles).toEqual([
      {
        color: 'rgb(16, 47, 53)',
        image: 'none',
        beforeImage: 'none',
        afterImage: 'none',
        shadow: 'none',
        backdrop: 'none',
        filter: 'none',
      },
      {
        color: 'rgb(16, 47, 53)',
        image: 'none',
        beforeImage: 'none',
        afterImage: 'none',
        shadow: 'none',
        backdrop: 'none',
        filter: 'none',
      },
      {
        color: 'rgb(16, 47, 53)',
        image: 'none',
        beforeImage: 'none',
        afterImage: 'none',
        shadow: 'none',
        backdrop: 'none',
        filter: 'none',
      },
    ])

    const unselectedCourseColors = await page
      .locator('.p-panelmenu-item:not(.active-course-menu-item) .p-panelmenu-item-link')
      .evaluateAll((elements) =>
        elements.map((element) => getComputedStyle(element).backgroundColor)
      )
    expect(unselectedCourseColors.length).toBeGreaterThanOrEqual(2)
    expect(unselectedCourseColors).not.toContain('rgb(44, 89, 77)')

    const badgeStyles = await page.locator('.exam-type-tag').evaluateAll((elements) =>
      elements.map((element) => ({
        className: element.className,
        color: getComputedStyle(element).backgroundColor,
      }))
    )
    expect(badgeStyles.map(({ className }) => className)).toEqual(
      expect.arrayContaining([
        expect.stringContaining('exam-type-tag--final'),
        expect.stringContaining('exam-type-tag--quiz'),
        expect.stringContaining('exam-type-tag--midterm'),
      ])
    )
    expect(new Set(badgeStyles.map(({ color }) => color)).size).toBe(3)

    const archiveActions = page.locator('.archive-record-actions .archive-action-neutral')
    await expect(archiveActions).toHaveCount(6)
    expect(
      await archiveActions.evaluateAll((elements) => elements.map((element) => element.className))
    ).toEqual(
      expect.arrayContaining([
        expect.stringContaining('archive-action-preview'),
        expect.stringContaining('archive-action-download'),
      ])
    )
    await page.screenshot({
      path: testInfo.outputPath('christmas-selected-course-solid-and-darker-terms.png'),
      fullPage: true,
    })

    const viewports = [
      { width: 390, height: 844 },
      { width: 834, height: 1210 },
      { width: 1024, height: 768 },
      { width: 1440, height: 900 },
    ]
    for (const viewport of viewports) {
      await page.setViewportSize(viewport)
      await page.waitForTimeout(50)

      if (viewport.width < 768) {
        const mobileDrawer = page.locator('.mobile-drawer-christmas')
        if (!(await mobileDrawer.isVisible())) {
          await page.locator('.sidebar-toggle').click()
        }
        await expect(mobileDrawer).toBeVisible()
        expect(
          await mobileDrawer.locator('.p-drawer-content').evaluate((element) => {
            const style = getComputedStyle(element)
            return { color: style.backgroundColor, image: style.backgroundImage }
          })
        ).toEqual({ color: christmasAppStyle.color, image: christmasAppStyle.image })
        expect(
          await mobileDrawer.locator('.mobile-upload-section').evaluate((element) => {
            const style = getComputedStyle(element)
            return {
              color: style.backgroundColor,
              image: style.backgroundImage,
              borderTopColor: style.borderTopColor,
              shadow: style.boxShadow,
            }
          })
        ).toEqual({
          color: 'rgba(0, 0, 0, 0)',
          image: 'none',
          borderTopColor: 'rgba(0, 0, 0, 0)',
          shadow: 'none',
        })
        const mobileSearchInput = mobileDrawer.getByPlaceholder('搜尋課程')
        await mobileSearchInput.fill('普通物理')
        const mobileSelectedCourse = mobileDrawer.locator('.active-course-search-result').first()
        await expect(mobileSelectedCourse).toBeVisible()
        expect(
          await mobileSelectedCourse.evaluate((element) => ({
            color: getComputedStyle(element).backgroundColor,
            image: getComputedStyle(element).backgroundImage,
            beforeImage: getComputedStyle(element, '::before').backgroundImage,
            afterImage: getComputedStyle(element, '::after').backgroundImage,
          }))
        ).toEqual({
          color: christmasAppStyle.color,
          image: christmasAppStyle.image,
          beforeImage: 'none',
          afterImage: 'none',
        })
        await mobileSearchInput.fill('')
        await page.keyboard.press('Escape')
        await expect(mobileDrawer).toBeHidden()
      }

      await expect(semesterHeaders).toHaveCount(2)
      await expect(archiveCards).toHaveCount(3)
      await expect(page.locator('.archive-record-card h3')).toContainText([
        'final',
        'quiz2',
        'midterm2',
      ])
      expect(
        await page.evaluate(() => ({
          documentOverflow:
            document.documentElement.scrollWidth > document.documentElement.clientWidth,
          bodyOverflow: document.body.scrollWidth > document.body.clientWidth,
        }))
      ).toEqual({ documentOverflow: false, bodyOverflow: false })
      await page.screenshot({
        path: testInfo.outputPath(`christmas-archive-${viewport.width}x${viewport.height}.png`),
        fullPage: true,
      })
    }

    await page.screenshot({ path: testInfo.outputPath('christmas-solid-archive-surfaces.png') })
  })

  test('restricts admin area and supports archive browsing', async ({ page }) => {
    const coursesResponse = {
      fundamental: [
        { id: 101, name: '普通物理(一)' },
        { id: 102, name: '微積分(一)' },
      ],
      required: [],
      experience: [],
      optional: [],
      graduate: [],
      'math-department': [],
    }

    let archiveDownloadCount = 3
    let previewRouteCallCount = 0
    let previewFileRouteCallCount = 0
    let wsTicketRequestCount = 0
    let ownerPendingQuerySeen = false
    const consoleErrors = createConsoleErrorCollector(page)
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))

    const pdfBody = fromBase64ToBinaryString(
      'JVBERi0xLjUKJcTl8uXrPgoxIDAgb2JqPDwvVHlwZS9DYXRhbG9nL1BhZ2VzIDIgMCBSPj4KZW5kb2JqCjIgMCBvYmo8PC9UeXBlL1BhZ2VzL0tpZHMgWzMgMCBSXS9Db3VudCAxPj4KZW5kb2JqCjMgMCBvYmo8PC9UeXBlL1BhZ2UvUGFyZW50IDIgMCBSL01lZGlhQm94WzAgMCA1OTUgODQyXS9Db250ZW50cyA0IDAgUi9SZXNvdXJjZXMgPDwvUHJvY1Nl0dDU2V0Wy9QREZdPj4+Pj4KZW5kb2JqCjQgMCBvYmo8PC9MZW5ndGggNTI+PnN0cmVhbQpIL0YgMTIgVGYgMTIgVG0gMCBUZgoKZW5kc3RyZWFtCmVuZG9iagogNSAwIG9iag8+PnN0YXJ0eHJlZgoxNjYKJSVFT0YK'
    )
    const archivesResponse = () => [
      {
        id: 201,
        academic_year: 2024,
        name: '期末考',
        archive_type: 'final',
        professor: '王教授',
        has_answers: true,
        download_count: archiveDownloadCount,
        uploader_id: 9,
      },
    ]

    await page.route('**/api/notifications/active', async (route) => {
      await route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify([]),
      })
    })
    await page.route('**/api/notifications/unread-summary**', (route) =>
      route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify({
          announcements: [],
          personal_notifications: [],
          counts: { announcements: 0, personal_notifications: 0, total: 0 },
        }),
      })
    )

    await page.route('**/api/auth/heartbeat', (route) =>
      route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify({}) })
    )

    await page.route('**/api/courses', async (route) => {
      await route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify(coursesResponse),
      })
    })
    await page.route('**/api/courses/categories', (route) =>
      route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify([]) })
    )

    await page.route(/\/api\/courses\/101\/archives(?:\?.*)?$/, async (route) => {
      const requestUrl = new URL(route.request().url())

      expect(requestUrl.pathname).toBe('/api/courses/101/archives')
      const includeOwnerPending = requestUrl.searchParams.get('include_owner_pending')
      if (includeOwnerPending !== null) {
        expect(includeOwnerPending).toBe('true')
        ownerPendingQuerySeen = true
      }

      await route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify(archivesResponse()),
      })
    })

    await page.route('**/api/courses/101/archives/201/preview', async (route) => {
      previewRouteCallCount += 1
      await route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify({
          url: `${new URL(route.request().url()).origin}/minio/archives/201.pdf?X-Amz-Signature=preview`,
        }),
      })
    })

    await page.route('**/minio/archives/201.pdf?X-Amz-Signature=preview', async (route) => {
      previewFileRouteCallCount += 1
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'application/pdf', 'accept-ranges': 'bytes' },
        body: pdfBody,
      })
    })

    await page.route('**/api/users/me', async (route) => {
      await route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify({ id: 2, name: '一般使用者', nickname: '' }),
      })
    })

    await page.route('**/api/courses/101/archives/201/discussion/ws-ticket', async (route) => {
      wsTicketRequestCount += 1
      expect(route.request().method()).toBe('POST')
      expect(route.request().headers().authorization).toMatch(/^Bearer /)
      await route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify({ ticket: 'w'.repeat(43), expires_in: 30 }),
      })
    })

    let downloadEndpointCalled = false
    await page.route('**/api/courses/101/archives/201/download', async (route) => {
      downloadEndpointCalled = true
      archiveDownloadCount = 4
      await route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify({
          url: `${new URL(route.request().url()).origin}/minio/archives/201.pdf?X-Amz-Signature=download`,
        }),
      })
    })

    await page.route('**/pdf.worker*.js', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'application/javascript' },
        body: '',
      })
    })

    await page.route('**/minio/archives/201.pdf?X-Amz-Signature=download', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'application/pdf' },
        body: pdfBody,
      })
    })

    await page.addInitScript(() => {
      const OriginalWebSocket = window.WebSocket
      const testWindow = window as Window & { __discussionWsUrls: string[] }
      testWindow.__discussionWsUrls = []

      class FakeDiscussionWebSocket {
        static OPEN = 1
        static CLOSED = 3

        constructor(url) {
          this.url = url
          this.readyState = FakeDiscussionWebSocket.OPEN
          this.onopen = null
          this.onmessage = null
          this.onerror = null
          this.onclose = null
          this.__listeners = {}

          setTimeout(() => {
            this.onopen?.()
            this.__emit('open', {})

            const history = { type: 'history', messages: [] }
            const evt = { data: JSON.stringify(history) }
            this.onmessage?.(evt)
            this.__emit('message', evt)
          }, 0)
        }

        addEventListener(type, handler) {
          this.__listeners[type] = this.__listeners[type] || []
          this.__listeners[type].push(handler)
        }

        removeEventListener(type, handler) {
          const list = this.__listeners[type] || []
          this.__listeners[type] = list.filter((h) => h !== handler)
        }

        __emit(type, event) {
          ;(this.__listeners[type] || []).forEach((handler) => {
            try {
              handler(event)
            } catch {
              // ignore
            }
          })
        }

        send() {
          // ignore in test
        }

        close(code = 1000) {
          this.readyState = FakeDiscussionWebSocket.CLOSED
          const evt = { code }
          this.onclose?.(evt)
          this.__emit('close', evt)
        }
      }

      window.WebSocket = class PatchedWebSocket {
        constructor(url, protocols) {
          if (typeof url === 'string' && url.includes('/discussion/ws')) {
            testWindow.__discussionWsUrls.push(url)
            return new FakeDiscussionWebSocket(url)
          }
          return new OriginalWebSocket(url, protocols)
        }
      }
    })

    await page.goto('/admin')

    await expect(page).toHaveURL(/\/archive$/)

    const uploadButton = page.getByRole('button', { name: '上傳考古題' })
    await expect(uploadButton).toBeVisible()

    const searchInput = page.getByPlaceholder('搜尋課程')
    await searchInput.fill('普通物理')

    await clickWhenVisible(page.getByRole('button', { name: '普通物理(一)', exact: true }))

    const archiveCard = page
      .getByRole('article')
      .filter({ has: page.getByRole('heading', { name: '期末考' }) })
    await expect(archiveCard).toBeVisible()
    expect(ownerPendingQuerySeen).toBe(true)
    await expect(archiveCard.getByRole('button', { name: '編輯' })).toHaveCount(0)
    await expect(archiveCard.getByRole('button', { name: '刪除' })).toHaveCount(0)

    const previewRequestPromise = page.waitForRequest(
      (request) =>
        request.method() === 'GET' &&
        new URL(request.url()).pathname === '/api/courses/101/archives/201/preview'
    )
    const previewResponsePromise = page.waitForResponse(
      (response) =>
        response.request().method() === 'GET' &&
        new URL(response.url()).pathname === '/api/courses/101/archives/201/preview'
    )
    await clickWhenVisible(archiveCard.getByRole('button', { name: '預覽' }))
    const [previewRequest, previewResponse] = await Promise.all([
      previewRequestPromise,
      previewResponsePromise,
    ])

    expect(previewRequest.method()).toBe('GET')
    expect(previewResponse.status()).toBe(200)
    expect(previewResponse.headers()['content-type']).toContain('application/json')
    expect(previewRouteCallCount).toBe(1)
    await expect.poll(() => previewFileRouteCallCount).toBeGreaterThan(0)

    const previewDialog = page.getByRole('dialog', { name: /期末考/ })
    await expect(previewDialog).toBeVisible()
    await expect(previewDialog).toContainText('期末考')

    await expect.poll(() => wsTicketRequestCount).toBeGreaterThan(0)
    const discussionWsUrl = await page.evaluate(() => {
      const testWindow = window as Window & { __discussionWsUrls: string[] }
      return testWindow.__discussionWsUrls.at(-1)
    })
    expect(discussionWsUrl).toBeTruthy()
    const discussionWsSearch = new URL(discussionWsUrl).searchParams
    expect(discussionWsSearch.get('ticket')).toBe('w'.repeat(43))
    expect(discussionWsSearch.has('token')).toBe(false)

    expect(await consoleErrors.errors()).toEqual([])
    expect(pageErrors).toEqual([])
    const downloadPromise = page.waitForEvent('download')
    await clickWhenVisible(previewDialog.getByRole('button', { name: '下載' }))
    const download = await downloadPromise

    await expect.poll(() => downloadEndpointCalled).toBeTruthy()
    expect(download.suggestedFilename()).toBe('2024_普通物理(一)_王教授_期末考.pdf')

    await clickWhenVisible(previewDialog.getByRole('button', { name: '關閉', exact: true }))
    await expect(previewDialog).toBeHidden()

    await expect(archiveCard).toContainText('4 次下載')
  })
})
