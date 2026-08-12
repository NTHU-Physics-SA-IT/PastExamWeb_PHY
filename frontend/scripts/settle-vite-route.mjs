/* global Buffer, process */

import { setTimeout as delay } from 'node:timers/promises'

import { chromium, firefox, webkit } from '@playwright/test'

const BROWSERS = { chromium, firefox, webkit }
const QUIET_WINDOW_MS = 10_000
const PHASE_TIMEOUT_MS = 45_000
const POLL_INTERVAL_MS = 100
const ARCHIVE_SEARCH_PLACEHOLDER = '搜尋課程'
const JSON_HEADERS = { 'content-type': 'application/json' }

const encodeTokenSegment = (value) => Buffer.from(JSON.stringify(value)).toString('base64url')

const adminToken = `${encodeTokenSegment({ alg: 'HS256', typ: 'JWT' })}.${encodeTokenSegment({
  uid: 1,
  email: 'warmup@example.invalid',
  name: 'Vite warmup',
  is_admin: true,
  exp: 4_102_444_800,
})}.signature`

const family = process.env.E2E_FAMILY
const baseURL = process.env.PLAYWRIGHT_BASE_URL

if (!Object.hasOwn(BROWSERS, family)) {
  throw new Error(`Unsupported E2E_FAMILY: ${family ?? '<unset>'}`)
}
if (!baseURL) {
  throw new Error('PLAYWRIGHT_BASE_URL is required')
}

const archiveURL = new URL('/archive', baseURL).toString()
const startedAt = Date.now()
const browser = await BROWSERS[family].launch()

try {
  const page = await browser.newPage()
  const dependencyVersions = new Map()
  let documentRequests = 0
  let viteConnections = 0
  let lastSemanticEventAt = Date.now()
  let verification = null
  let verificationFailure = null

  await page.addInitScript((token) => {
    window.localStorage.setItem('auth-token', token)
    window.sessionStorage.setItem('auth-token', token)
  }, adminToken)
  await page.route('**/api/auth/heartbeat', (route) =>
    route.fulfill({ status: 200, headers: JSON_HEADERS, body: '{}' })
  )
  await page.route('**/api/notifications/active', (route) =>
    route.fulfill({ status: 200, headers: JSON_HEADERS, body: '[]' })
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
  await page.route('**/api/courses/categories', (route) =>
    route.fulfill({ status: 200, headers: JSON_HEADERS, body: '[]' })
  )
  await page.route('**/api/courses', (route) =>
    route.fulfill({
      status: 200,
      headers: JSON_HEADERS,
      body: JSON.stringify({
        fundamental: [{ id: 101, name: '暖機課程' }],
        required: [],
        experience: [],
        optional: [],
        graduate: [],
        'math-department': [],
      }),
    })
  )

  const recordSemanticEvent = (kind) => {
    lastSemanticEventAt = Date.now()
    console.log(`vite-warmup: family=${family} event=${kind}`)
  }

  page.on('request', (request) => {
    const requestURL = new URL(request.url())

    if (
      request.isNavigationRequest() &&
      request.frame() === page.mainFrame() &&
      requestURL.pathname === '/archive'
    ) {
      documentRequests += 1
      recordSemanticEvent(`archive-document-${documentRequests}`)
      if (verification && documentRequests > verification.documentRequests + 1) {
        verificationFailure = new Error(
          'Archive performed an unexpected full-document navigation during verification'
        )
      }
    }

    if (!requestURL.pathname.includes('/node_modules/.vite/deps/')) {
      return
    }

    const dependency = requestURL.pathname
    const version = requestURL.searchParams.get('v')
    if (!version) {
      return
    }

    const previousVersion = dependencyVersions.get(dependency)
    if (verification && previousVersion !== version) {
      const reason = previousVersion ? 'changed' : 'was discovered'
      verificationFailure = new Error(`Vite dependency ${dependency} ${reason} during verification`)
    }
    dependencyVersions.set(dependency, version)
  })

  page.on('console', (message) => {
    if (message.text() !== '[vite] connected.') {
      return
    }
    viteConnections += 1
    recordSemanticEvent(`vite-connected-${viteConnections}`)
    if (verification && viteConnections > verification.viteConnections + 1) {
      verificationFailure = new Error(
        'Vite reconnected unexpectedly during the stable-generation verification'
      )
    }
  })

  const archiveSearch = page.getByPlaceholder(ARCHIVE_SEARCH_PLACEHOLDER)

  const waitForSemanticQuiet = async (phase) => {
    const deadline = Date.now() + PHASE_TIMEOUT_MS
    while (Date.now() < deadline) {
      if (verificationFailure) {
        throw verificationFailure
      }

      const uiReady = await archiveSearch.isVisible().catch(() => false)
      if (uiReady && viteConnections > 0 && Date.now() - lastSemanticEventAt >= QUIET_WINDOW_MS) {
        console.log(`vite-warmup: family=${family} phase=${phase} quiet_ms=${QUIET_WINDOW_MS}`)
        return
      }
      await delay(POLL_INTERVAL_MS)
    }
    throw new Error(`Archive Vite readiness did not settle during ${phase}`)
  }

  await page.goto(archiveURL, { waitUntil: 'domcontentloaded', timeout: PHASE_TIMEOUT_MS })
  await archiveSearch.waitFor({ state: 'visible', timeout: PHASE_TIMEOUT_MS })
  await waitForSemanticQuiet('initial-settlement')

  if (documentRequests < 1 || dependencyVersions.size === 0) {
    throw new Error('Archive warmup did not observe its document and Vite dependencies')
  }

  verification = {
    documentRequests,
    viteConnections,
    dependencyCount: dependencyVersions.size,
  }
  await page.reload({ waitUntil: 'domcontentloaded', timeout: PHASE_TIMEOUT_MS })
  await archiveSearch.waitFor({ state: 'visible', timeout: PHASE_TIMEOUT_MS })
  await waitForSemanticQuiet('stable-generation-verification')

  const verificationDocuments = documentRequests - verification.documentRequests
  const verificationConnections = viteConnections - verification.viteConnections
  if (verificationDocuments !== 1 || verificationConnections !== 1) {
    throw new Error(
      `Stable verification observed ${verificationDocuments} documents and ` +
        `${verificationConnections} Vite connections`
    )
  }
  if (dependencyVersions.size !== verification.dependencyCount) {
    throw new Error('Stable verification discovered an unexpected Vite dependency')
  }

  console.log(
    `vite-warmup: family=${family} status=settled documents=${documentRequests} ` +
      `optimizer_reloads=${Math.max(0, verification.documentRequests - 1)} ` +
      `dependencies=${dependencyVersions.size} duration_ms=${Date.now() - startedAt}`
  )
} finally {
  await browser.close()
}
