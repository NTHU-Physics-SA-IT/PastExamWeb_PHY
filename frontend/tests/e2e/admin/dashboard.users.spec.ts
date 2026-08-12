import { adminTest as test, expect } from '../support/adminTest'
import { mockAdminCourseEndpoints, mockAdminUserEndpoints } from '../support/adminFixtures'
import { JSON_HEADERS } from '../support/constants'
import { clickWhenVisible } from '../support/ui'

test.describe('Admin Dashboard › Users', () => {
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

  test('allows creating, editing, and deleting users', async ({ page }) => {
    await mockAdminCourseEndpoints(page)
    const { createPayloads, updatePayloads, deleteIds } = await mockAdminUserEndpoints(page)

    await page.goto('/admin', { waitUntil: 'networkidle' })
    await expect(page).toHaveURL(/\/admin$/)

    await clickWhenVisible(page.getByRole('tab', { name: '使用者管理' }))
    await clickWhenVisible(page.getByRole('tab', { name: '本地帳號', exact: true }))

    await expect(page.getByRole('article').filter({ hasText: '一般使用者' })).toBeVisible()

    await clickWhenVisible(page.getByRole('button', { name: '新增使用者' }))

    const createDialog = page.getByRole('dialog', { name: '新增使用者' })
    await expect(createDialog).toBeVisible()

    const nameInput = createDialog.getByPlaceholder('輸入使用者名稱')
    const emailInput = createDialog.getByPlaceholder('輸入電子郵件')
    const passwordInput = createDialog.getByPlaceholder('輸入密碼')
    await nameInput.fill('新用戶')
    await emailInput.fill('newuser@example.com')
    await passwordInput.fill('Passw0rd!')
    await expect(nameInput).toHaveValue('新用戶')
    await expect(emailInput).toHaveValue('newuser@example.com')
    await expect(passwordInput).toHaveValue('Passw0rd!')
    await clickWhenVisible(createDialog.getByLabel('管理員權限'))

    const previousCreateCount = createPayloads.length
    const createRequestPromise = page.waitForRequest(
      (request) =>
        request.method() === 'POST' && new URL(request.url()).pathname === '/api/users/admin/users'
    )
    await clickWhenVisible(createDialog.getByRole('button', { name: '新增' }))
    const createRequest = await createRequestPromise
    expect(createRequest.postDataJSON()).toMatchObject({
      name: '新用戶',
      email: 'newuser@example.com',
      is_admin: true,
    })
    await expect
      .poll(() => createPayloads.length, { message: '等待建立 API 完成' })
      .toBe(previousCreateCount + 1)

    expect(createPayloads.at(-1)).toMatchObject({
      name: '新用戶',
      email: 'newuser@example.com',
      is_admin: true,
    })
    await expect(page.getByRole('article').filter({ hasText: '新用戶' })).toBeVisible()

    const targetCard = page.getByRole('article').filter({ hasText: '一般使用者' })
    await clickWhenVisible(targetCard.getByRole('button', { name: '編輯使用者' }))

    const editDialog = page.getByRole('dialog', { name: '編輯使用者' })
    await expect(editDialog).toBeVisible()

    await editDialog.getByPlaceholder('輸入使用者名稱').fill('一般使用者 (更新)')
    await clickWhenVisible(editDialog.getByLabel('管理員權限'))

    const previousUpdateCount = updatePayloads.length
    await clickWhenVisible(editDialog.getByRole('button', { name: '更新' }))
    await expect
      .poll(() => updatePayloads.length, { message: '等待更新 API 完成' })
      .toBe(previousUpdateCount + 1)

    expect(updatePayloads.at(-1)).toMatchObject({
      payload: {
        name: '一般使用者 (更新)',
        email: 'user@example.com',
        is_admin: true,
      },
    })
    const updatedUserCard = page.getByRole('article').filter({ hasText: '一般使用者 (更新)' })
    await expect(updatedUserCard).toBeVisible()
    await expect(updatedUserCard).toContainText('管理員')

    const deleteCard = page.getByRole('article').filter({ hasText: '新用戶' })
    await clickWhenVisible(deleteCard.getByRole('button', { name: '刪除使用者' }))

    const dialog = page.getByRole('alertdialog', { name: '刪除確認' })
    await expect(dialog).toBeVisible()

    const previousDeleteCount = deleteIds.length
    await clickWhenVisible(dialog.getByLabel('刪除'))
    await expect
      .poll(() => deleteIds.length, { message: '等待刪除 API 完成' })
      .toBe(previousDeleteCount + 1)

    expect(deleteIds.length).toBeGreaterThan(0)
    await expect(page.getByRole('article').filter({ hasText: '新用戶' })).toHaveCount(0)
  })
})
