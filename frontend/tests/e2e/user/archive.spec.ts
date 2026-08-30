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
    let previewFileRouteCallCount = 0
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
    expect(await consoleErrors.errors()).toEqual([])
    expect(pageErrors).toEqual([])
    const downloadPromise = page.waitForEvent('download')
    await clickWhenVisible(previewDialog.getByRole('button', { name: '下載' }))
    const download = await downloadPromise

    await expect.poll(() => downloadEndpointCalled).toBeTruthy()
    expect(download.suggestedFilename()).toBe('2024_普通物理(一)_王教授_期末考.pdf')

    await clickWhenVisible(previewDialog.getByRole('button', { name: 'Close' }))
    await expect(previewDialog).toBeHidden()

    await expect(archiveCard).toContainText('4 次下載')
  })
})
