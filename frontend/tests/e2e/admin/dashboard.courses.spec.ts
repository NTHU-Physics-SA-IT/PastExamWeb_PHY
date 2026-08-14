import { adminTest as test, expect } from '../support/adminTest'
import {
  defaultCourseCategories,
  mockAdminCourseEndpoints,
  mockAdminNotificationEndpoints,
  mockAdminUserEndpoints,
  type Course,
  type Notification,
  type User,
} from '../support/adminFixtures'
import { JSON_HEADERS } from '../support/constants'
import { clickWhenVisible } from '../support/ui'

test.describe('Admin Dashboard › Courses', () => {
  test.beforeEach(async ({ page }) => {
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
  })

  test('allows creating, editing, and deleting courses', async ({ page }) => {
    const { createPayloads, updatePayloads, deleteIds, getCategoryRequestCount } =
      await mockAdminCourseEndpoints(page)
    const mathCategory = defaultCourseCategories.find(
      (category) => category.key === 'math-department'
    )!
    const graduateCategory = defaultCourseCategories.find(
      (category) => category.key === 'graduate'
    )!

    await page.goto('/admin', { waitUntil: 'networkidle' })
    await expect(page).toHaveURL(/\/admin$/)

    await clickWhenVisible(page.getByRole('tab', { name: '課程管理' }))
    await expect
      .poll(getCategoryRequestCount, { message: '等待課程分類 API 完成' })
      .toBeGreaterThan(0)
    await expect(page.getByRole('article').filter({ hasText: '普通物理(一)' })).toBeVisible()
    await expect(page.getByRole('article').filter({ hasText: '電磁學(一)' })).toBeVisible()

    const createButton = page.getByRole('button', { name: '新增課程' })
    await clickWhenVisible(createButton)

    const createDialog = page.getByRole('dialog', { name: '新增課程' })
    await expect(createDialog).toBeVisible()

    await createDialog.getByPlaceholder('輸入課程中文名稱').fill('線性代數(一)')

    const categoryTrigger = createDialog
      .locator('label', { hasText: '分類' })
      .locator('xpath=following-sibling::*[1]')
    await clickWhenVisible(categoryTrigger)
    await clickWhenVisible(page.getByRole('option', { name: mathCategory.name, exact: true }))

    await Promise.all([
      page.waitForResponse(
        (response) =>
          response.url().includes('/api/courses/admin/courses') &&
          response.request().method() === 'POST'
      ),
      page.waitForResponse(
        (response) =>
          response.url().includes('/api/courses/admin/courses') &&
          response.request().method() === 'GET'
      ),
      clickWhenVisible(createDialog.getByRole('button', { name: '新增' })),
    ])

    await expect(page.getByRole('article').filter({ hasText: '線性代數(一)' })).toBeVisible()
    expect(createPayloads.at(-1)).toMatchObject({
      name: '線性代數(一)',
      category: mathCategory.key,
    })

    const editCard = page.getByRole('article').filter({ hasText: '普通物理(一)' })
    await clickWhenVisible(editCard.getByRole('button', { name: '編輯課程' }))

    const editDialog = page.getByRole('dialog', { name: '編輯課程' })
    await expect(editDialog).toBeVisible()

    const nameInput = editDialog.getByPlaceholder('輸入課程中文名稱')
    await nameInput.fill('普通物理(一) (更新)')

    const editCategoryTrigger = editDialog
      .locator('label', { hasText: '分類' })
      .locator('xpath=following-sibling::*[1]')
    await clickWhenVisible(editCategoryTrigger)
    await clickWhenVisible(page.getByRole('option', { name: graduateCategory.name, exact: true }))

    await Promise.all([
      page.waitForResponse(
        (response) =>
          response.url().includes('/api/courses/admin/courses') &&
          response.request().method() === 'PUT'
      ),
      page.waitForResponse(
        (response) =>
          response.url().includes('/api/courses/admin/courses') &&
          response.request().method() === 'GET'
      ),
      clickWhenVisible(editDialog.getByRole('button', { name: '更新' })),
    ])

    expect(updatePayloads.at(-1)).toMatchObject({
      payload: { name: '普通物理(一) (更新)', category: graduateCategory.key },
    })
    const updatedCourseCard = page.getByRole('article').filter({ hasText: '普通物理(一) (更新)' })
    await expect(updatedCourseCard).toBeVisible()
    await expect(updatedCourseCard).toContainText(graduateCategory.name)

    const deleteCard = page.getByRole('article').filter({ hasText: '線性代數(一)' })
    await clickWhenVisible(deleteCard.getByRole('button', { name: '刪除課程' }))

    const dialog = page.getByRole('alertdialog', { name: '刪除確認' })
    await expect(dialog).toBeVisible()

    await Promise.all([
      page.waitForResponse(
        (response) =>
          response.url().includes('/api/courses/admin/courses') &&
          response.request().method() === 'DELETE'
      ),
      page.waitForResponse(
        (response) =>
          response.url().includes('/api/courses/admin/courses') &&
          response.request().method() === 'GET'
      ),
      clickWhenVisible(dialog.getByLabel('刪除')),
    ])

    expect(deleteIds.length).toBeGreaterThan(0)
    await expect(page.getByRole('article').filter({ hasText: '線性代數(一)' })).toHaveCount(0)
  })

  test('keeps mobile pagination operational and synchronized with desktop', async ({ page }) => {
    const courses: Course[] = Array.from({ length: 12 }, (_, index) => ({
      id: index + 1,
      name: `分頁課程 ${String(index + 1).padStart(2, '0')}`,
      category: 'freshman',
    }))
    const users: User[] = Array.from({ length: 12 }, (_, index) => ({
      id: index + 10,
      name: `分頁使用者 ${String(index + 1).padStart(2, '0')}`,
      email: `page-user-${index + 1}@example.com`,
      is_admin: index % 2 === 0,
      is_local: true,
      account_source: 'local',
      last_login: null,
    }))
    const notifications: Notification[] = Array.from({ length: 11 }, (_, index) => ({
      id: index + 20,
      title: `分頁公告 ${String(index + 1).padStart(2, '0')}`,
      body: `公告內容 ${index + 1}`,
      severity: index % 2 === 0 ? 'info' : 'danger',
      is_active: true,
      created_at: `2025-10-${String(index + 1).padStart(2, '0')}T15:00:00Z`,
      updated_at: `2025-10-${String(index + 1).padStart(2, '0')}T15:00:00Z`,
      starts_at: null,
      ends_at: null,
    }))

    await mockAdminCourseEndpoints(page, courses)
    await mockAdminUserEndpoints(page, users)
    const { deleteIds } = await mockAdminNotificationEndpoints(page, notifications)
    await page.setViewportSize({ width: 375, height: 812 })
    await page.goto('/admin', { waitUntil: 'networkidle' })

    await clickWhenVisible(page.getByRole('tab', { name: '課程管理' }))
    const courseList = page.locator('.admin-mobile-list--courses')
    const coursePaginator = courseList.locator('.admin-mobile-paginator')
    await expect(coursePaginator).toBeVisible()
    await expect(coursePaginator.locator('.p-paginator-first')).toBeDisabled()
    await expect(coursePaginator.locator('.p-paginator-prev')).toBeDisabled()
    await expect(courseList.locator('.admin-course-card')).toHaveCount(10)
    await clickWhenVisible(coursePaginator.locator('.p-paginator-next'))
    await expect(courseList.locator('.admin-course-card')).toHaveCount(2)
    await expect(coursePaginator.locator('.p-paginator-next')).toBeDisabled()
    await expect(coursePaginator.locator('.p-paginator-last')).toBeDisabled()

    await page.setViewportSize({ width: 1440, height: 900 })
    const courseTable = page.getByRole('table').filter({
      has: page.getByRole('columnheader', { name: '課程名稱' }),
    })
    await expect(courseTable.getByRole('row', { name: /分頁課程 11/ })).toBeVisible()
    await page.setViewportSize({ width: 375, height: 812 })
    await expect(courseList.locator('.admin-course-card')).toHaveCount(2)
    await clickWhenVisible(coursePaginator.locator('.p-paginator-first'))
    await expect(coursePaginator.locator('.p-paginator-prev')).toBeDisabled()

    await clickWhenVisible(coursePaginator.getByRole('combobox'))
    await clickWhenVisible(page.getByRole('option', { name: '5', exact: true }))
    await expect(courseList.locator('.admin-course-card')).toHaveCount(5)
    await clickWhenVisible(coursePaginator.locator('.p-paginator-next'))
    await page.getByPlaceholder('搜尋課程').fill('分頁課程 01')
    await expect(courseList.locator('.admin-course-card')).toHaveCount(1)
    await expect(coursePaginator.locator('.p-paginator-prev')).toBeDisabled()

    await clickWhenVisible(page.getByRole('tab', { name: '使用者管理' }))
    await clickWhenVisible(page.getByRole('tab', { name: '本地帳號', exact: true }))
    const userList = page.locator('.admin-mobile-list--users')
    const userPaginator = userList.locator('.admin-mobile-paginator')
    await expect(userList.locator('.admin-user-card')).toHaveCount(10)
    await clickWhenVisible(userPaginator.locator('.p-paginator-last'))
    await expect(userList.locator('.admin-user-card')).toHaveCount(2)
    await page.getByPlaceholder('搜尋使用者').fill('分頁使用者 01')
    await expect(userList.locator('.admin-user-card')).toHaveCount(1)
    await expect(userPaginator.locator('.p-paginator-prev')).toBeDisabled()

    await clickWhenVisible(page.getByRole('tab', { name: '公告管理' }))
    const notificationList = page.locator('.admin-mobile-list--notifications')
    const notificationPaginator = notificationList.locator('.admin-mobile-paginator')
    await clickWhenVisible(notificationPaginator.locator('.p-paginator-last'))
    await expect(notificationList.locator('.admin-announcement-card')).toHaveCount(1)
    await clickWhenVisible(
      notificationList.locator('.admin-announcement-card').getByRole('button', { name: '刪除' })
    )
    const dialog = page.getByRole('alertdialog', { name: '刪除確認' })
    await clickWhenVisible(dialog.getByLabel('刪除'))
    await expect.poll(() => deleteIds.length).toBe(1)
    await expect(notificationList.locator('.admin-announcement-card')).toHaveCount(10)
    await expect(notificationPaginator.locator('.p-paginator-prev')).toBeDisabled()

    expect(
      await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)
    ).toBe(false)
  })
})
