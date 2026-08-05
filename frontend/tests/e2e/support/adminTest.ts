import { test as base, expect } from '@playwright/test'

const AUTH_FILE = 'playwright/.auth/admin.json'

const adminTest = base.extend({
  storageState: AUTH_FILE,
  context: async ({ context }, use) => {
    await context.addInitScript(() => {
      const token = window.localStorage.getItem('auth-token')
      if (token) {
        window.sessionStorage.setItem('auth-token', token)
      }
    })

    await use(context)
  },
})

export { adminTest }
export { expect }
