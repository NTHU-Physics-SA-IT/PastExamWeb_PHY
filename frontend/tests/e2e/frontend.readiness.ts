import { test as readiness, expect } from '@playwright/test'
import {
  probeFrontendReadinessCycle,
  waitForStableFrontend,
} from './support/frontendReadiness'

readiness('prewarms a stable frontend and admin lazy-module graph', async ({ page }, testInfo) => {
  const result = await waitForStableFrontend({
    probe: (_attempt, remainingMs) => probeFrontendReadinessCycle(page, remainingMs),
    log: (message) => console.info(`[frontend-readiness] ${message}`),
  })

  await testInfo.attach('frontend-readiness.json', {
    body: Buffer.from(JSON.stringify(result, null, 2)),
    contentType: 'application/json',
  })
  expect(result.stableCycles).toBe(2)
})
