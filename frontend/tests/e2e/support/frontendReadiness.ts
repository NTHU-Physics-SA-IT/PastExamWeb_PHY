import type { ConsoleMessage, Page, Request, Response } from '@playwright/test'
import { createConsoleErrorCollector, type ConsoleDiagnostic } from './consoleDiagnostics'

const ROUTER_OPTIMIZER_ERROR = /VUE_ROUTER_R0010|VUE_ROUTER_R0011|Outdated Optimize Dep/i

export type FrontendReadinessCycle = {
  appReady: boolean
  adminPrewarmed: boolean
  unexpectedReload: boolean
  optimizerFailures: string[]
  routerSignals: string[]
  consoleErrors: ConsoleDiagnostic[]
  pageErrors: string[]
  operationError: string | null
  dependencyFingerprint: string[]
}

type ReadinessOptions = {
  probe: (attempt: number, remainingMs: number) => Promise<FrontendReadinessCycle>
  timeoutMs?: number
  maxAttempts?: number
  requiredStableCycles?: number
  now?: () => number
  log?: (message: string) => void
}

const boundedMessage = (value: string) =>
  value.length <= 500 ? value : `${value.slice(0, 500)}…[truncated]`

const diagnosticSummary = (cycle: FrontendReadinessCycle) => ({
  appReady: cycle.appReady,
  adminPrewarmed: cycle.adminPrewarmed,
  unexpectedReload: cycle.unexpectedReload,
  optimizerFailures: cycle.optimizerFailures,
  routerSignals: cycle.routerSignals,
  consoleErrors: cycle.consoleErrors,
  pageErrors: cycle.pageErrors,
  operationError: cycle.operationError,
  dependencyFingerprint: cycle.dependencyFingerprint,
})

export const waitForStableFrontend = async ({
  probe,
  timeoutMs = 25_000,
  maxAttempts = 6,
  requiredStableCycles = 2,
  now = Date.now,
  log = () => undefined,
}: ReadinessOptions) => {
  const deadline = now() + timeoutMs
  let stableCycles = 0
  let stableFingerprint = ''
  const attempts: FrontendReadinessCycle[] = []

  for (let attempt = 1; attempt <= maxAttempts && now() < deadline; attempt += 1) {
    const cycle = await probe(attempt, Math.max(1, deadline - now()))
    attempts.push(cycle)

    const unknownConsoleErrors = cycle.consoleErrors.filter((entry) =>
      !ROUTER_OPTIMIZER_ERROR.test(`${entry.text} ${JSON.stringify(entry.args)}`)
    )
    const unknownPageErrors = cycle.pageErrors.filter(
      (message) => !ROUTER_OPTIMIZER_ERROR.test(message)
    )
    if (unknownPageErrors.length > 0 || unknownConsoleErrors.length > 0) {
      throw new Error(
        `Frontend readiness failed closed on an application error: ${JSON.stringify(
          diagnosticSummary(cycle)
        )}`
      )
    }

    const stable =
      cycle.appReady &&
      cycle.adminPrewarmed &&
      !cycle.unexpectedReload &&
      cycle.optimizerFailures.length === 0 &&
      cycle.routerSignals.length === 0 &&
      cycle.consoleErrors.length === 0 &&
      cycle.pageErrors.length === 0 &&
      cycle.operationError === null

    if (!stable) {
      stableCycles = 0
      stableFingerprint = ''
      log(`Frontend readiness cycle ${attempt} was unstable: ${JSON.stringify(diagnosticSummary(cycle))}`)
      continue
    }

    const fingerprint = JSON.stringify(cycle.dependencyFingerprint)
    if (stableCycles > 0 && fingerprint !== stableFingerprint) {
      stableCycles = 1
      stableFingerprint = fingerprint
      log(`Frontend dependency fingerprint changed during cycle ${attempt}; restarting stability count`)
      continue
    }

    stableCycles += 1
    stableFingerprint = fingerprint
    log(`Frontend readiness cycle ${attempt} stable (${stableCycles}/${requiredStableCycles})`)
    if (stableCycles >= requiredStableCycles) {
      return { attempts, stableCycles, dependencyFingerprint: cycle.dependencyFingerprint }
    }
  }

  throw new Error(
    `Frontend readiness did not reach ${requiredStableCycles} consecutive stable cycles within ${timeoutMs}ms: ${boundedMessage(
      JSON.stringify(attempts.map(diagnosticSummary))
    )}`
  )
}

const dependencyFingerprint = async (page: Page) =>
  page.evaluate(() => {
    const optimizerGenerations = performance
      .getEntriesByType('resource')
      .map((entry) => entry.name)
      .filter((url) => url.includes('/node_modules/.vite/deps/'))
      .map((value) => new URL(value).searchParams.get('v') ?? 'missing-version')
    return [...new Set(optimizerGenerations)].sort()
  })

const withTimeout = async <T>(operation: Promise<T>, timeoutMs: number, label: string) => {
  let timeout: ReturnType<typeof setTimeout> | undefined
  try {
    return await Promise.race([
      operation,
      new Promise<T>((_, reject) => {
        timeout = setTimeout(() => reject(new Error(`${label} exceeded ${timeoutMs}ms`)), timeoutMs)
      }),
    ])
  } finally {
    if (timeout) clearTimeout(timeout)
  }
}

export const probeFrontendReadinessCycle = async (
  page: Page,
  remainingMs: number
): Promise<FrontendReadinessCycle> => {
  const optimizerFailures: string[] = []
  const routerSignals: string[] = []
  const pageErrors: string[] = []
  let unexpectedReload = false
  let appReady = false
  let adminPrewarmed = false
  let operationError: string | null = null

  const consoleCollector = createConsoleErrorCollector(page)
  const onConsole = (message: ConsoleMessage) => {
    if (ROUTER_OPTIMIZER_ERROR.test(message.text())) routerSignals.push(boundedMessage(message.text()))
  }
  const onPageError = (error: Error) => pageErrors.push(boundedMessage(error.message))
  const onResponse = (response: Response) => {
    const url = response.url()
    if (url.includes('/node_modules/.vite/deps/') && response.status() === 504) {
      optimizerFailures.push(`504 ${new URL(url).pathname}`)
    }
  }
  const onRequestFailed = (request: Request) => {
    if (!request.url().includes('/node_modules/.vite/deps/')) return
    optimizerFailures.push(
      `${request.failure()?.errorText ?? 'request failed'} ${new URL(request.url()).pathname}`
    )
  }
  page.on('console', onConsole)
  page.on('pageerror', onPageError)
  page.on('response', onResponse)
  page.on('requestfailed', onRequestFailed)

  try {
    const operationTimeout = Math.max(500, Math.min(5_000, remainingMs))
    await withTimeout(
      page.goto('/', { waitUntil: 'domcontentloaded' }).then(() => undefined),
      operationTimeout,
      'homepage navigation'
    )
    await page.waitForFunction(
      () => typeof window.__pastexam?.openLoginModal === 'function',
      undefined,
      { timeout: operationTimeout }
    )
    appReady = true
    const timeOrigin = await page.evaluate(() => performance.timeOrigin)

    adminPrewarmed = await withTimeout(
      page.evaluate(async () => Boolean((await import('/src/views/Admin.vue')).default)),
      operationTimeout,
      'admin lazy module prewarm'
    )
    await page.waitForLoadState('networkidle', { timeout: operationTimeout })

    const finalState = await page.evaluate((expectedTimeOrigin) => ({
      sameDocument: performance.timeOrigin === expectedTimeOrigin,
      appReady: typeof window.__pastexam?.openLoginModal === 'function',
    }), timeOrigin)
    unexpectedReload ||= !finalState.sameDocument
    appReady &&= finalState.appReady
  } catch (error) {
    operationError = boundedMessage(error instanceof Error ? error.message : String(error))
  } finally {
    page.off('console', onConsole)
    page.off('pageerror', onPageError)
    page.off('response', onResponse)
    page.off('requestfailed', onRequestFailed)
    consoleCollector.stop()
  }

  const consoleErrors = await consoleCollector.errors()
  let fingerprint: string[] = []
  try {
    fingerprint = await dependencyFingerprint(page)
  } catch {
    // A reload may destroy the execution context. The cycle is already unstable.
  }

  return {
    appReady,
    adminPrewarmed,
    unexpectedReload,
    optimizerFailures,
    routerSignals,
    consoleErrors,
    pageErrors,
    operationError,
    dependencyFingerprint: fingerprint,
  }
}
