import { describe, expect, it, vi } from 'vitest'
import {
  type FrontendReadinessCycle,
  waitForStableFrontend,
} from '../e2e/support/frontendReadiness'

const cycle = (overrides: Partial<FrontendReadinessCycle> = {}): FrontendReadinessCycle => ({
  appReady: true,
  adminPrewarmed: true,
  unexpectedReload: false,
  optimizerFailures: [],
  routerSignals: [],
  consoleErrors: [],
  pageErrors: [],
  operationError: null,
  dependencyFingerprint: ['/node_modules/.vite/deps/vue.js?v=stable'],
  ...overrides,
})

describe('frontend E2E readiness contract', () => {
  it('requires two consecutive app-ready cycles with the admin graph prewarmed', async () => {
    const probe = vi.fn().mockResolvedValue(cycle())

    const result = await waitForStableFrontend({ probe })

    expect(probe).toHaveBeenCalledTimes(2)
    expect(result.stableCycles).toBe(2)
  })

  it('does not accept HTTP availability without the application marker', async () => {
    const probe = vi.fn().mockResolvedValue(cycle({ appReady: false }))

    await expect(waitForStableFrontend({ probe, maxAttempts: 2 })).rejects.toThrow(
      'did not reach 2 consecutive stable cycles'
    )
  })

  it('resets stability after an optimizer 504', async () => {
    const probe = vi
      .fn()
      .mockResolvedValueOnce(cycle())
      .mockResolvedValueOnce(
        cycle({ optimizerFailures: ['504 /node_modules/.vite/deps/primevue_button.js'] })
      )
      .mockResolvedValueOnce(cycle())
      .mockResolvedValueOnce(cycle())

    const result = await waitForStableFrontend({ probe })

    expect(probe).toHaveBeenCalledTimes(4)
    expect(result.stableCycles).toBe(2)
  })

  it('rechecks the full contract when an optimizer router error carries an object console arg', async () => {
    const routerObjectError = {
      type: 'error',
      text: 'JSHandle@object',
      args: [{ message: 'VUE_ROUTER_R0010 failed to fetch dynamically imported module' }],
      location: { url: '/node_modules/.vite/deps/vue-router.js', line: 1, column: 1 },
    }
    const probe = vi
      .fn()
      .mockResolvedValueOnce(
        cycle({
          routerSignals: ['VUE_ROUTER_R0010'],
          consoleErrors: [routerObjectError],
        })
      )
      .mockResolvedValueOnce(cycle())
      .mockResolvedValueOnce(cycle())

    const result = await waitForStableFrontend({ probe })

    expect(probe).toHaveBeenCalledTimes(3)
    expect(result.stableCycles).toBe(2)
  })

  it('rechecks the full contract after an optimizer page error', async () => {
    const probe = vi
      .fn()
      .mockResolvedValueOnce(cycle({ pageErrors: ['Outdated Optimize Dep'] }))
      .mockResolvedValueOnce(cycle())
      .mockResolvedValueOnce(cycle())

    const result = await waitForStableFrontend({ probe })

    expect(probe).toHaveBeenCalledTimes(3)
    expect(result.stableCycles).toBe(2)
  })

  it('requires the optimizer fingerprint to remain stable after a reload', async () => {
    const probe = vi
      .fn()
      .mockResolvedValueOnce(cycle({ dependencyFingerprint: ['?v=first'] }))
      .mockResolvedValueOnce(cycle({ dependencyFingerprint: ['?v=second'] }))
      .mockResolvedValueOnce(cycle({ dependencyFingerprint: ['?v=second'] }))

    const result = await waitForStableFrontend({ probe })

    expect(probe).toHaveBeenCalledTimes(3)
    expect(result.dependencyFingerprint).toEqual(['?v=second'])
  })

  it('fails closed when the admin lazy graph never prewarms', async () => {
    const probe = vi.fn().mockResolvedValue(cycle({ adminPrewarmed: false }))

    await expect(waitForStableFrontend({ probe, maxAttempts: 2 })).rejects.toThrow(
      'did not reach 2 consecutive stable cycles'
    )
  })

  it('fails closed on application console errors instead of retrying them away', async () => {
    const probe = vi.fn().mockResolvedValue(
      cycle({
        consoleErrors: [
          {
            type: 'error',
            text: 'unexpected application error',
            args: [],
            location: { url: '', line: 0, column: 0 },
          },
        ],
      })
    )

    await expect(waitForStableFrontend({ probe })).rejects.toThrow(
      'failed closed on an application error'
    )
    expect(probe).toHaveBeenCalledTimes(1)
  })

  it('does not hide an unrelated application error behind optimizer churn', async () => {
    const probe = vi.fn().mockResolvedValue(
      cycle({
        optimizerFailures: ['504 /node_modules/.vite/deps/vue.js'],
        consoleErrors: [
          {
            type: 'error',
            text: 'unexpected application error',
            args: [{ message: 'not an optimizer diagnostic' }],
            location: { url: '', line: 0, column: 0 },
          },
        ],
      })
    )

    await expect(waitForStableFrontend({ probe })).rejects.toThrow(
      'failed closed on an application error'
    )
    expect(probe).toHaveBeenCalledTimes(1)
  })

  it('honors the bounded readiness deadline', async () => {
    let now = 0
    const probe = vi.fn(async () => {
      now += 60
      return cycle({ appReady: false })
    })

    await expect(
      waitForStableFrontend({ probe, timeoutMs: 100, maxAttempts: 10, now: () => now })
    ).rejects.toThrow('within 100ms')
    expect(probe).toHaveBeenCalledTimes(2)
  })
})
