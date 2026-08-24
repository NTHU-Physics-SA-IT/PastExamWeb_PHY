import { userTest as test, expect } from '../support/userTest'
import { JSON_HEADERS } from '../support/constants'
import { fromBase64ToBinaryString } from '../support/jwt'
import { clickWhenVisible } from '../support/ui'
import { createConsoleErrorCollector } from '../support/consoleDiagnostics'

test.describe('User › Archive browsing', () => {
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

    await page.route('**/api/courses/101/archives', async (route) => {
      await route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify(archivesResponse()),
      })
    })

    await page.route('**/api/courses/101/archives/201/preview-file', async (route) => {
      previewRouteCallCount += 1
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'application/pdf' },
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

    let downloadEndpointCalled = false
    await page.route('**/api/courses/101/archives/201/download', async (route) => {
      downloadEndpointCalled = true
      archiveDownloadCount = 4
      await route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify({ url: 'https://example.com/download.pdf' }),
      })
    })

    await page.route('**/pdf.worker*.js', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'application/javascript' },
        body: '',
      })
    })

    await page.route('https://example.com/download.pdf', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'application/pdf' },
        body: pdfBody,
      })
    })

    await page.addInitScript(() => {
      const OriginalWebSocket = window.WebSocket

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
    await expect(archiveCard.getByRole('button', { name: '編輯' })).toHaveCount(0)
    await expect(archiveCard.getByRole('button', { name: '刪除' })).toHaveCount(0)

    const previewRequestPromise = page.waitForRequest(
      (request) =>
        request.method() === 'GET' &&
        new URL(request.url()).pathname === '/api/courses/101/archives/201/preview-file'
    )
    const previewResponsePromise = page.waitForResponse(
      (response) =>
        response.request().method() === 'GET' &&
        new URL(response.url()).pathname === '/api/courses/101/archives/201/preview-file'
    )
    await clickWhenVisible(archiveCard.getByRole('button', { name: '預覽' }))
    const [previewRequest, previewResponse] = await Promise.all([
      previewRequestPromise,
      previewResponsePromise,
    ])

    expect(previewRequest.method()).toBe('GET')
    expect(previewResponse.status()).toBe(200)
    expect(previewResponse.headers()['content-type']).toContain('application/pdf')
    expect(previewRouteCallCount).toBe(1)

    const previewDialog = page.getByRole('dialog', { name: /期末考/ })
    await expect(previewDialog).toBeVisible()
    await expect(previewDialog).toContainText('期末考')
    expect(await consoleErrors.errors()).toEqual([])
    expect(pageErrors).toEqual([])
    await clickWhenVisible(previewDialog.getByRole('button', { name: '下載' }))

    await expect.poll(() => downloadEndpointCalled).toBeTruthy()

    await clickWhenVisible(previewDialog.getByRole('button', { name: 'Close' }))
    await expect(previewDialog).toBeHidden()

    await expect(archiveCard).toContainText('4 次下載')
  })

  test('opens Wish bubbles on click while preserving pan and heart isolation', async ({ page }) => {
    const wishTitle = '量子資訊期末考'
    let heartRequestCount = 0

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
    await page.route('**/api/auth/heartbeat', (route) =>
      route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify({}) })
    )
    await page.route('**/api/users/me', (route) =>
      route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify({ id: 2, name: '一般使用者', nickname: '' }),
      })
    )
    await page.route('**/api/courses', (route) =>
      route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify({
          fundamental: [],
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
    await page.route('**/api/wishes**', async (route) => {
      const request = route.request()
      const path = new URL(request.url()).pathname
      if (request.method() === 'POST' && path === '/api/wishes/7/heart') {
        heartRequestCount += 1
        await route.fulfill({
          status: 200,
          headers: JSON_HEADERS,
          body: JSON.stringify({ hearted: true, heart_count: 3 }),
        })
        return
      }
      if (request.method() === 'GET' && path === '/api/wishes') {
        await route.fulfill({
          status: 200,
          headers: JSON_HEADERS,
          body: JSON.stringify({
            items: [
              {
                id: 7,
                title: wishTitle,
                subject: '量子資訊',
                professor: 'Prof. Lin',
                academic_year: 1141,
                name: 'final',
                creator_name: 'Alice',
                created_at: '2026-08-18T00:00:00Z',
                heart_count: 2,
                hearted_by_me: false,
                fulfilled: false,
              },
            ],
            total: 1,
          }),
        })
        return
      }
      await route.abort()
    })

    await page.goto('/archive')
    await clickWhenVisible(page.getByRole('button', { name: '考古許願池' }))

    const viewport = page.locator('.wish-bubble-viewport')
    const world = page.locator('.wish-bubble-world')
    const bubbleButton = page.getByRole('button', { name: wishTitle })
    const dialog = page.getByRole('dialog').filter({ hasText: wishTitle })
    await expect(viewport).toBeVisible()
    await expect(bubbleButton).toBeVisible()

    await bubbleButton.click()
    await expect(dialog).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(dialog).toBeHidden()

    const bubbleBounds = await bubbleButton.boundingBox()
    if (!bubbleBounds) throw new Error('Wish bubble was not measurable before pan')
    const initialTransform = await world.evaluate((element) => element.style.transform)
    const startX = bubbleBounds.x + bubbleBounds.width / 2
    const startY = bubbleBounds.y + bubbleBounds.height / 2
    await page.mouse.move(startX, startY)
    await page.mouse.down()
    await page.mouse.move(startX + 36, startY + 24, { steps: 3 })
    await page.mouse.up()

    await expect
      .poll(() => world.evaluate((element) => element.style.transform))
      .not.toBe(initialTransform)
    await expect(dialog).toBeHidden()

    await bubbleButton.click()
    await expect(dialog).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(dialog).toBeHidden()

    await page.getByRole('button', { name: '愛心 2' }).click()
    await expect.poll(() => heartRequestCount).toBe(1)
    await expect(page.getByRole('button', { name: '愛心 3' })).toBeVisible()
    await expect(dialog).toBeHidden()
  })
})
