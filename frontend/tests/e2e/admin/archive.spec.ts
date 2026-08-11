import { adminTest as test, expect } from '../support/adminTest'
import { JSON_HEADERS } from '../support/constants'
import { buildJwt } from '../support/jwt'
import { clickWhenVisible } from '../support/ui'

const ADMIN_TOKEN = buildJwt({
  uid: 1,
  email: 'admin@example.com',
  name: 'Admin',
  is_admin: true,
  exp: 4_102_444_800,
})

const COURSES_FIXTURE = {
  fundamental: [
    { id: 101, name: '普通物理(一)' },
    { id: 102, name: '電磁學(一)' },
  ],
  required: [],
  experience: [],
  optional: [],
  graduate: [],
  'math-department': [],
}

const ARCHIVES_FIXTURE: Record<number, Array<Record<string, unknown>>> = {
  101: [
    {
      id: 201,
      academic_year: 2024,
      name: '期末考',
      archive_type: 'final',
      professor: '王教授',
      has_answers: true,
      download_count: 12,
      uploader_id: 9,
    },
  ],
  102: [
    {
      id: 301,
      academic_year: 2023,
      name: '期中考',
      archive_type: 'midterm',
      professor: '李教授',
      has_answers: false,
      download_count: 7,
      uploader_id: 10,
    },
  ],
}

test.describe('Admin › Archive management', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript((token) => {
      window.sessionStorage.setItem('auth-token', token)
    }, ADMIN_TOKEN)

    await page.route('**/api/auth/heartbeat', (route) =>
      route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify({}) })
    )

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

    await page.route('**/api/courses', async (route) => {
      if (route.request().method() !== 'GET') {
        await route.continue()
        return
      }

      await route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify(COURSES_FIXTURE),
      })
    })
    await page.route('**/api/courses/categories', (route) =>
      route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify([]) })
    )

    await page.route('**/api/courses/*/archives', async (route) => {
      if (route.request().method() !== 'GET') {
        await route.continue()
        return
      }

      const courseIdMatch = route
        .request()
        .url()
        .match(/courses\/(\d+)\/archives/)
      const courseId = courseIdMatch ? Number(courseIdMatch[1]) : null
      const responseBody = courseId ? (ARCHIVES_FIXTURE[courseId] ?? []) : []

      await route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify(responseBody),
      })
    })
  })

  test('allows searching courses and opening upload dialog', async ({ page }) => {
    await page.goto('/archive')
    await expect(page).toHaveURL(/\/archive$/)

    const uploadButton = page.getByRole('button', { name: '上傳考古題' })
    await expect(uploadButton).toBeVisible({ timeout: 15000 })

    const searchInput = page.getByPlaceholder('搜尋課程')
    await expect(searchInput).toBeVisible({ timeout: 15000 })
    await searchInput.fill('普通物理')

    const courseButton = page.getByRole('button', { name: '普通物理(一)', exact: true })
    await expect(courseButton).toBeVisible({ timeout: 15000 })
    await Promise.all([
      page.waitForResponse((response) => {
        return (
          response.url().includes('/api/courses/') &&
          response.url().endsWith('/archives') &&
          response.request().method() === 'GET'
        )
      }),
      clickWhenVisible(courseButton),
    ])

    const archiveToolbar = page.getByRole('toolbar')
    await expect(archiveToolbar).toContainText('目前顯示：普通物理(一) · 共 1 份考古題', {
      timeout: 15000,
    })

    await clickWhenVisible(uploadButton)

    const uploadDialog = page.getByRole('dialog', { name: '上傳考古題' })
    await expect(uploadDialog).toBeVisible({ timeout: 10000 })
    await expect(uploadDialog.getByRole('tab', { name: '選擇課程' })).toBeVisible()
    await expect(uploadDialog.getByRole('tab', { name: '考試資訊' })).toBeVisible()
  })

  test('persists last selected course across reloads', async ({ page }) => {
    await page.goto('/archive')

    const searchInput = page.getByPlaceholder('搜尋課程')
    await searchInput.fill('電磁學')

    const courseButton = page.getByRole('button', { name: '電磁學(一)', exact: true })
    await Promise.all([
      page.waitForResponse((response) => {
        return (
          response.url().includes('/api/courses/') &&
          response.url().endsWith('/archives') &&
          response.request().method() === 'GET'
        )
      }),
      clickWhenVisible(courseButton),
    ])

    const archiveToolbar = page.getByRole('toolbar')
    await expect(archiveToolbar).toContainText('目前顯示：電磁學(一) · 共 1 份考古題', {
      timeout: 15000,
    })

    await page.reload()

    await expect(page).toHaveURL(/\/archive$/)
    await expect(archiveToolbar).toContainText('目前顯示：電磁學(一) · 共 1 份考古題', {
      timeout: 15000,
    })
  })

  test('keeps Archive edit state for approved 404 and 409 move conflicts', async ({
    page,
  }, testInfo) => {
    let courseListRequestCount = 0
    let moveResponse = {
      status: 404,
      detail: {
        code: 'archive_move_target_course_not_found',
        message: '目標課程不存在，請先建立課程。',
        reload_required: false,
      },
    }

    await page.route('**/api/courses', async (route) => {
      if (route.request().method() !== 'GET') {
        await route.continue()
        return
      }
      courseListRequestCount += 1
      await route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify(COURSES_FIXTURE),
      })
    })
    await page.route('**/api/courses/101/archives/201', (route) =>
      route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify(ARCHIVES_FIXTURE[101][0]),
      })
    )
    await page.route('**/api/courses/101/archives/201/course', (route) =>
      route.fulfill({
        status: moveResponse.status,
        headers: JSON_HEADERS,
        body: JSON.stringify({ detail: moveResponse.detail }),
      })
    )

    const courseSearch = page.getByPlaceholder('搜尋課程')

    // Vite can invalidate the first document after discovering dependencies for this lazy
    // route. Finish that discovery before exercising the dialog so a dev-server reload
    // cannot detach controls in the middle of the 404/409 state-preservation assertions.
    await page.goto('/archive', { waitUntil: 'networkidle' })
    await expect(courseSearch).toBeVisible()
    await page.reload({ waitUntil: 'networkidle' })
    await expect(courseSearch).toBeVisible()

    await courseSearch.fill('普通物理')
    await clickWhenVisible(page.getByRole('button', { name: '普通物理(一)', exact: true }))

    const openEditor = async () => {
      const visibleEditButton = page.locator('.archive-action-edit:visible')
      if ((await visibleEditButton.count()) === 0) {
        await clickWhenVisible(page.locator('.p-accordionheader').filter({ hasText: '2024 年' }))
      }
      await expect(visibleEditButton).toBeVisible()
      await clickWhenVisible(page.locator('.archive-action-edit:visible'))
      const dialog = page.getByRole('dialog', { name: '編輯考古題' })
      await expect(dialog).toBeVisible()
      await dialog.locator('#archive-edit-name').fill('保留的考試名稱')
      await dialog.locator('#archive-edit-should-transfer').check({ force: true })
      await clickWhenVisible(dialog.locator('#archive-edit-target-category'))
      await clickWhenVisible(page.getByRole('option').first())
      return dialog
    }

    let dialog = await openEditor()
    await dialog.locator('#archive-edit-target-course').fill('不存在課程')
    const requestCountBeforeMissingMove = courseListRequestCount
    await clickWhenVisible(dialog.getByRole('button', { name: '儲存並轉移' }))
    await expect(page.getByText('目標課程不存在，請先建立課程。')).toBeVisible()
    await expect(dialog).toBeVisible()
    await expect(dialog.locator('#archive-edit-name')).toHaveValue('保留的考試名稱')
    await expect(dialog.locator('#archive-edit-target-course')).toHaveValue('不存在課程')
    expect(courseListRequestCount).toBe(requestCountBeforeMissingMove)
    await page.screenshot({
      path: testInfo.outputPath('archive-move-404-dialog.png'),
      fullPage: true,
    })

    await clickWhenVisible(dialog.getByRole('button', { name: '取消' }))
    moveResponse = {
      status: 409,
      detail: {
        code: 'course_lifecycle_conflict',
        message: '目標課程已在垃圾桶，請先恢復課程。',
        reload_required: false,
      },
    }
    dialog = await openEditor()
    await dialog.locator('#archive-edit-target-course').fill('已刪除課程')
    const requestCountBeforeLifecycleConflict = courseListRequestCount
    await clickWhenVisible(dialog.getByRole('button', { name: '儲存並轉移' }))
    await expect(page.getByText('目標課程已在垃圾桶，請先恢復課程。')).toBeVisible()
    await expect(dialog).toBeVisible()
    await expect(dialog.locator('#archive-edit-name')).toHaveValue('保留的考試名稱')
    await expect(dialog.locator('#archive-edit-target-course')).toHaveValue('已刪除課程')
    expect(courseListRequestCount).toBe(requestCountBeforeLifecycleConflict)
    await page.screenshot({
      path: testInfo.outputPath('archive-move-409-dialog.png'),
      fullPage: true,
    })
  })
})
