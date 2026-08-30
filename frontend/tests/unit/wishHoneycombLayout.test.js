import { describe, expect, it } from 'vitest'

import {
  WISH_CELL_HORIZONTAL_SPACING_REM,
  WISH_CELL_VERTICAL_BASE_SPACING_REM,
  WISH_CELL_VERTICAL_SPACING_REM,
  WISH_FONT_SIZE_BASE_REM,
  WISH_FONT_SIZE_MAX_REM,
  WISH_FONT_SIZE_SQRT5_TARGET_REM,
  WISH_ITEM_BASE_HEIGHT_REM,
  WISH_ITEM_MAX_HEIGHT_REM,
  WISH_ITEM_MAX_WIDTH_REM,
  WISH_MOBILE_BREAKPOINT_PX,
  WISH_NATIVE_DENSITY_CENTER_ROW_CAPACITY,
  WISH_TABLET_MAX_WIDTH_PX,
  appendResponsiveWishPositions,
  assignWishCentralityScores,
  assignWishHoneycombPositions,
  createResponsiveWishLayout,
  createWishLayoutSeed,
  createWishWorldGeometry,
  generateWishHoneycombCells,
  reprojectWishHoneycombPositions,
  wishCentralityScore,
  wishFontSizeRem,
  wishHoneycombCenterRowCapacity,
  wishHoneycombGeometry,
  wishHoneycombLayoutMetrics,
  wishHoneycombLogicalDensityWidth,
  wishHoneycombRequiredWidthForCapacity,
  wishInteractionMode,
} from '@/utils/wishHoneycombLayout'

function sequenceRng(values) {
  let index = 0
  return () => values[index++ % values.length]
}

function cellSignature(cells) {
  return [...cells]
    .sort((left, right) => left.r - right.r || left.q - right.q)
    .map(({ q, r }) => `${q}:${r}`)
    .join('|')
}

const wishes = [
  { id: 1, heart_count: 0 },
  { id: 2, heart_count: 3 },
  { id: 3, heart_count: 25 },
  { id: 4, heart_count: 400 },
]

const densityWishes = [0, 1, 5, 6, 8, 9, 10, 15, 30, 2, 3, 4, 12, 18, 20, 25].map(
  (heart_count, index) => ({
    id: index + 1,
    heart_count,
    fulfilled: heart_count === 30,
  })
)
const densityScores = Object.fromEntries(
  densityWishes.map(({ id }, index) => [id, densityWishes.length - index])
)

const responsiveViewports = [
  { width: 375, height: 812, interactionMode: 'mobile' },
  { width: 390, height: 844, interactionMode: 'mobile' },
  { width: 402, height: 874, interactionMode: 'mobile' },
  { width: 429, height: 869, interactionMode: 'mobile' },
  { width: 768, height: 1024, interactionMode: 'tablet' },
  { width: 834, height: 1210, interactionMode: 'tablet' },
  { width: 1024, height: 768, interactionMode: 'tablet' },
  { width: 1440, height: 900, interactionMode: 'desktop' },
]

describe('Wish Pool shared honeycomb geometry', () => {
  it.each(responsiveViewports)(
    'uses Honeycomb cells at $width × $height',
    ({ width, height, interactionMode }) => {
      const viewport = { width, height }
      const cells = generateWishHoneycombCells(12, viewport, 16, 1729)
      const layout = createResponsiveWishLayout(
        wishes,
        { 1: 1, 2: 2, 3: 3, 4: 4 },
        viewport,
        16,
        1729
      )
      const keys = cells.map(({ q, r }) => `${q}:${r}`)

      expect(layout.mode).toBe('honeycomb')
      expect(layout.interactionMode).toBe(interactionMode)
      expect(cells).toHaveLength(12)
      expect(new Set(keys).size).toBe(12)
      expect(cells.every(({ q, r, x, y }) => [q, r, x, y].every(Number.isFinite))).toBe(true)
      expect(cells.some(({ r }) => Math.abs(r) % 2 === 1)).toBe(true)
    }
  )

  it.each(responsiveViewports.filter(({ width }) => width <= WISH_TABLET_MAX_WIDTH_PX))(
    'provides a genuine multi-column native Honeycomb at $width × $height',
    ({ width, height }) => {
      const cells = generateWishHoneycombCells(12, { width, height }, 16, 1729)
      const rowCounts = cells.reduce((counts, { r }) => {
        counts[r] = (counts[r] || 0) + 1
        return counts
      }, {})

      expect(Math.max(...Object.values(rowCounts))).toBeGreaterThan(1)
      expect(new Set(cells.map(({ x }) => x)).size).toBeGreaterThan(1)
    }
  )

  it('keeps axial staggering and item footprints separated at every responsive scale', () => {
    for (const viewport of responsiveViewports) {
      const geometry = wishHoneycombGeometry(viewport, 16)
      const cells = generateWishHoneycombCells(24, viewport, 16, 77)
      const oddRows = cells.filter(({ r }) => Math.abs(r) % 2 === 1)

      expect(geometry.horizontalSpacing).toBeGreaterThan(geometry.itemWidth)
      expect(geometry.verticalSpacing).toBeGreaterThan(geometry.itemHeight)
      expect(
        oddRows.every(({ x }) => {
          const xUnits = Math.abs(x / geometry.horizontalSpacing)
          return Math.abs((xUnits % 1) - 0.5) < 1e-10
        })
      ).toBe(true)
    }
  })

  it('reserves enough vertical space for a capped two-line title, fulfilled label, and heart row', () => {
    const titleLineHeight = 1.35
    const fulfilledLabelScale = 0.7
    const titleToLabelGapRem = 0.2
    const itemToHeartGapRem = 0.15
    const itemVerticalPaddingRem = 1.1
    const itemBorderRem = 0.125
    const heartRowMinHeightRem = 2
    const worstCaseHeightRem =
      WISH_FONT_SIZE_MAX_REM * titleLineHeight * 2 +
      WISH_FONT_SIZE_MAX_REM * fulfilledLabelScale * titleLineHeight +
      titleToLabelGapRem +
      itemToHeartGapRem +
      itemVerticalPaddingRem +
      itemBorderRem +
      heartRowMinHeightRem

    expect(WISH_ITEM_MAX_HEIGHT_REM).toBeGreaterThanOrEqual(worstCaseHeightRem)
    for (const viewport of responsiveViewports) {
      const geometry = wishHoneycombGeometry(viewport, 16)
      expect(geometry.verticalSpacing).toBeGreaterThan(geometry.itemHeight)
    }
  })

  it('uses the shared desktop lattice geometry in native and desktop navigation', () => {
    const phone = wishHoneycombGeometry({ width: 375, height: 812 }, 16)
    const desktop = wishHoneycombGeometry({ width: 1440, height: 900 }, 16)

    expect(phone.nativeNavigation).toBe(true)
    expect(phone.horizontalScale).toBe(1)
    expect(phone.verticalScale).toBe(1)
    expect(phone.itemWidth).toBe(WISH_ITEM_MAX_WIDTH_REM * 16)
    expect(phone.itemHeight).toBe(desktop.itemHeight)
    expect(phone.horizontalSpacing).toBe(desktop.horizontalSpacing)
    expect(phone.verticalSpacing).toBe(desktop.verticalSpacing)
    expect(desktop.nativeNavigation).toBe(false)
    expect(desktop.horizontalScale).toBe(1)
    expect(desktop.verticalScale).toBe(1)
    expect(desktop.itemWidth).toBe(WISH_ITEM_MAX_WIDTH_REM * 16)
    expect(desktop.itemHeight).toBe(WISH_ITEM_MAX_HEIGHT_REM * 16)
    expect(desktop.horizontalSpacing).toBe(WISH_CELL_HORIZONTAL_SPACING_REM * 16)
    expect(desktop.verticalSpacing).toBe(WISH_CELL_VERTICAL_SPACING_REM * 16)
  })

  it('derives the native desktop-density width and center capacity from shared geometry', () => {
    for (const viewport of responsiveViewports.filter(
      ({ width }) => width <= WISH_TABLET_MAX_WIDTH_PX
    )) {
      const geometry = wishHoneycombGeometry(viewport, 16)
      const requiredWidth = wishHoneycombRequiredWidthForCapacity(
        WISH_NATIVE_DENSITY_CENTER_ROW_CAPACITY,
        geometry
      )

      expect(requiredWidth).toBe(
        geometry.itemWidth +
          (WISH_NATIVE_DENSITY_CENTER_ROW_CAPACITY - 1) * geometry.horizontalSpacing +
          geometry.safeMargin * 2
      )
      expect(wishHoneycombLogicalDensityWidth(viewport.width, geometry)).toBeGreaterThanOrEqual(
        requiredWidth
      )
      expect(wishHoneycombCenterRowCapacity(viewport.width, geometry)).toBe(
        WISH_NATIVE_DENSITY_CENTER_ROW_CAPACITY
      )
    }
  })

  it('keeps the same desktop-density topology across fresh native and desktop layouts', () => {
    const layoutMetrics = wishHoneycombLayoutMetrics(densityWishes)
    const viewports = [
      { width: 390, height: 844 },
      { width: 768, height: 1024 },
      { width: 834, height: 1210 },
      { width: 1440, height: 900 },
    ]
    const layouts = viewports.map((viewport) =>
      createResponsiveWishLayout(
        densityWishes,
        densityScores,
        viewport,
        16,
        20260830,
        layoutMetrics
      )
    )
    const topology = ({ positions }) =>
      Object.fromEntries(Object.entries(positions).map(([id, { q, r }]) => [id, { q, r }]))
    const activeRows = ({ positions }) =>
      [...new Set(Object.values(positions).map(({ r }) => r))].sort((left, right) => left - right)
    const desktopTopology = topology(layouts.at(-1))
    const desktopRows = activeRows(layouts.at(-1))

    expect(desktopRows).toEqual([-2, -1, 0, 1, 2])
    for (const layout of layouts.slice(0, -1)) {
      expect(topology(layout)).toEqual(desktopTopology)
      expect(activeRows(layout)).toEqual(desktopRows)
    }
  })

  it('projects the shared topology into a wider reachable native world without extra rows', () => {
    const layoutMetrics = wishHoneycombLayoutMetrics(densityWishes)
    const mobileViewport = { width: 390, height: 844 }
    const desktopViewport = { width: 1440, height: 900 }
    const mobileLayout = createResponsiveWishLayout(
      densityWishes,
      densityScores,
      mobileViewport,
      16,
      20260830,
      layoutMetrics
    )
    const desktopLayout = createResponsiveWishLayout(
      densityWishes,
      densityScores,
      desktopViewport,
      16,
      20260830,
      layoutMetrics
    )
    const mobileGeometry = wishHoneycombGeometry(mobileViewport, 16, layoutMetrics)
    const mobileWorld = createWishWorldGeometry(mobileLayout.positions, mobileViewport, 16, {
      native2DOverflow: true,
      layoutMetrics,
    })
    const desktopWorld = createWishWorldGeometry(desktopLayout.positions, desktopViewport, 16, {
      layoutMetrics,
    })

    expect(mobileWorld.width).toBeGreaterThan(mobileViewport.width)
    expect(mobileWorld.height).toBeGreaterThan(mobileViewport.height)
    expect(mobileWorld.height).toBeCloseTo(desktopWorld.height, 10)
    for (const position of Object.values(mobileLayout.positions)) {
      const centerX = position.x + mobileWorld.offsetX
      const centerY = position.y + mobileWorld.offsetY
      expect(centerX).toBeGreaterThanOrEqual(mobileGeometry.itemWidth / 2)
      expect(centerX).toBeLessThanOrEqual(mobileWorld.width - mobileGeometry.itemWidth / 2)
      expect(centerY).toBeGreaterThanOrEqual(mobileGeometry.itemHeight / 2)
      expect(centerY).toBeLessThanOrEqual(mobileWorld.height - mobileGeometry.itemHeight / 2)
    }
  })

  it('keeps a native viewport on the same density profile as a matching wide desktop', () => {
    const wideCells = generateWishHoneycombCells(5, { width: 1600, height: 720 }, 16, 41)
    const tabletCells = generateWishHoneycombCells(5, { width: 900, height: 720 }, 16, 41)

    expect(cellSignature(tabletCells)).toBe(cellSignature(wideCells))
    expect(wideCells.every(({ r }) => Math.abs(r) <= 1)).toBe(true)
    expect(tabletCells.every(({ r }) => Math.abs(r) <= 1)).toBe(true)
  })

  it('keeps one session stable while different sessions can vary organic row allocation', () => {
    const viewport = { width: 1600, height: 720 }
    const first = generateWishHoneycombCells(9, viewport, 16, 101)
    const repeated = generateWishHoneycombCells(9, viewport, 16, 101)
    const alternatives = [102, 103, 104, 105].map((seed) =>
      generateWishHoneycombCells(9, viewport, 16, seed)
    )

    expect(repeated).toEqual(first)
    expect(alternatives.some((cells) => cellSignature(cells) !== cellSignature(first))).toBe(true)
  })

  it('uses actual viewport height to flag cells outside the initial view', () => {
    const shortViewport = generateWishHoneycombCells(20, { width: 1180, height: 420 }, 16, 31)
    const tallViewport = generateWishHoneycombCells(20, { width: 1180, height: 1024 }, 16, 31)

    expect(
      tallViewport.filter(({ inInitialViewport }) => inInitialViewport).length
    ).toBeGreaterThan(shortViewport.filter(({ inInitialViewport }) => inInitialViewport).length)
  })

  it('builds a real centered two-axis scroll world without changing cells', () => {
    const viewport = { width: 402, height: 874 }
    const cells = generateWishHoneycombCells(60, viewport, 16, 404)
    const positions = Object.fromEntries(cells.map((cell, index) => [index + 1, cell]))
    const geometry = createWishWorldGeometry(positions, viewport, 16, {
      native2DOverflow: true,
    })
    const footprint = wishHoneycombGeometry(viewport, 16)

    expect(geometry.width).toBeGreaterThan(viewport.width)
    expect(geometry.height).toBeGreaterThan(viewport.height)
    for (const position of Object.values(positions)) {
      const centerX = position.x + geometry.offsetX
      const centerY = position.y + geometry.offsetY
      expect(centerX).toBeGreaterThanOrEqual(footprint.itemWidth / 2)
      expect(centerX).toBeLessThanOrEqual(geometry.width - footprint.itemWidth / 2)
      expect(centerY).toBeGreaterThanOrEqual(footprint.itemHeight / 2)
      expect(centerY).toBeLessThanOrEqual(geometry.height - footprint.itemHeight / 2)
    }
  })

  it('keeps two-axis native scroll range even for one Wish', () => {
    const viewport = { width: 834, height: 1210 }
    const geometry = createWishWorldGeometry({ 1: { x: 0, y: 0 } }, viewport, 16, {
      native2DOverflow: true,
    })

    expect(geometry.width).toBeGreaterThan(viewport.width)
    expect(geometry.height).toBeGreaterThan(viewport.height)
  })

  it('separates only the navigation model by container width', () => {
    expect(wishInteractionMode({ width: WISH_MOBILE_BREAKPOINT_PX - 1, height: 600 })).toBe(
      'mobile'
    )
    expect(wishInteractionMode({ width: WISH_MOBILE_BREAKPOINT_PX, height: 1200 })).toBe('tablet')
    expect(wishInteractionMode({ width: WISH_TABLET_MAX_WIDTH_PX, height: 700 })).toBe('tablet')
    expect(wishInteractionMode({ width: WISH_TABLET_MAX_WIDTH_PX + 1, height: 700 })).toBe(
      'desktop'
    )
  })
})

describe('Wish Pool probabilistic centrality and stability', () => {
  it('uses the compact desktop baseline until visible title emphasis needs more room', () => {
    const compact = wishHoneycombLayoutMetrics([
      { id: 1, heart_count: 0, fulfilled: false },
      { id: 2, heart_count: 1, fulfilled: false },
    ])
    const emphasized = wishHoneycombLayoutMetrics([{ id: 3, heart_count: 30, fulfilled: true }])

    expect(compact).toEqual({
      itemHeightRem: WISH_ITEM_BASE_HEIGHT_REM,
      verticalSpacingRem: WISH_CELL_VERTICAL_BASE_SPACING_REM,
    })
    expect(wishHoneycombGeometry({ width: 1440, height: 900 }, 16, compact)).toMatchObject({
      itemHeight: WISH_ITEM_BASE_HEIGHT_REM * 16,
      verticalSpacing: WISH_CELL_VERTICAL_BASE_SPACING_REM * 16,
    })
    expect(emphasized.itemHeightRem).toBeGreaterThan(compact.itemHeightRem)
    expect(emphasized.verticalSpacingRem).toBeGreaterThan(compact.verticalSpacingRem)
    expect(emphasized.verticalSpacingRem).toBeGreaterThan(emphasized.itemHeightRem)
    expect(emphasized.itemHeightRem).toBeLessThanOrEqual(WISH_ITEM_MAX_HEIGHT_REM)
    expect(emphasized.verticalSpacingRem).toBeLessThanOrEqual(WISH_CELL_VERTICAL_SPACING_REM)
  })

  it('keeps Gumbel scoring finite and gives higher hearts an equal-noise advantage', () => {
    expect(Number.isFinite(wishCentralityScore(0, () => 0))).toBe(true)
    expect(Number.isFinite(wishCentralityScore(0, () => 1))).toBe(true)
    expect(Number.isFinite(wishCentralityScore(Number.MAX_SAFE_INTEGER, () => 0.5))).toBe(true)
    expect(wishCentralityScore(100, () => 0.5)).toBeGreaterThan(wishCentralityScore(0, () => 0.5))
  })

  it('assigns the highest session score to the central cell on mobile and desktop', () => {
    for (const viewport of [
      { width: 390, height: 844 },
      { width: 1440, height: 900 },
    ]) {
      const positions = assignWishHoneycombPositions(
        [
          { id: 'low', heart_count: 0 },
          { id: 'high', heart_count: 100 },
        ],
        { low: 1, high: 10 },
        viewport,
        16,
        55
      )

      expect(positions.high).toMatchObject({ q: 0, r: 0, x: 0, y: 0 })
      expect(positions.low).not.toMatchObject({ q: 0, r: 0 })
    }
  })

  it('reuses finite session scores through responsive reflow and heart updates', () => {
    const scores = assignWishCentralityScores(wishes, sequenceRng([0.11, 0.27, 0.43, 0.69, 0.83]))
    const snapshot = { ...scores }
    const phone = assignWishHoneycombPositions(wishes, scores, { width: 390, height: 844 }, 16, 9)
    const tablet = assignWishHoneycombPositions(wishes, scores, { width: 834, height: 1194 }, 16, 9)
    const heartUpdated = assignWishHoneycombPositions(
      wishes.map((wish) => ({ ...wish, heart_count: wish.heart_count + 10 })),
      scores,
      { width: 390, height: 844 },
      16,
      9
    )

    expect(scores).toEqual(snapshot)
    expect(Object.values(scores).every(Number.isFinite)).toBe(true)
    expect(Object.keys(phone)).toEqual(Object.keys(tablet))
    expect(heartUpdated).toEqual(phone)
  })

  it('appends into unused cells without moving existing Wishes', () => {
    const viewport = { width: 390, height: 844 }
    const initialWishes = wishes.slice(0, 2)
    const newWishes = wishes.slice(2)
    const scores = { 1: 1, 2: 2, 3: 3, 4: 4 }
    const initial = assignWishHoneycombPositions(initialWishes, scores, viewport, 16, 2718)
    const appended = appendResponsiveWishPositions(initial, newWishes, scores, viewport, 16, 2718)
    const keys = Object.values(appended).map(({ q, r }) => `${q}:${r}`)

    expect(appended[1]).toEqual(initial[1])
    expect(appended[2]).toEqual(initial[2])
    expect(new Set(keys).size).toBe(4)
  })

  it('reprojects viewport changes without changing allocated cells', () => {
    const initial = assignWishHoneycombPositions(
      wishes,
      { 1: 1, 2: 2, 3: 3, 4: 4 },
      { width: 390, height: 640 },
      16,
      2718
    )
    const resizedHeight = reprojectWishHoneycombPositions(initial, { width: 390, height: 1000 }, 16)
    const resizedWidth = reprojectWishHoneycombPositions(initial, { width: 834, height: 1000 }, 16)
    const cells = (positions) =>
      Object.fromEntries(Object.entries(positions).map(([id, { q, r }]) => [id, { q, r }]))

    expect(cells(resizedHeight)).toEqual(cells(initial))
    expect(cells(resizedWidth)).toEqual(cells(initial))
    expect(Object.values(resizedHeight).map(({ x, y }) => ({ x, y }))).toEqual(
      Object.values(initial).map(({ x, y }) => ({ x, y }))
    )
  })

  it('creates a stable session seed from an injectable RNG', () => {
    expect(createWishLayoutSeed(() => 0.25)).toBe(createWishLayoutSeed(() => 0.25))
    expect(createWishLayoutSeed(() => 0.25)).not.toBe(createWishLayoutSeed(() => 0.75))
  })
})

describe('Wish Pool typography', () => {
  const smoothstep = (value) => 3 * value ** 2 - 2 * value ** 3

  it('preserves the exact logarithmic stage through four hearts', () => {
    for (const hearts of [0, 1, 2, 3, 4]) {
      expect(wishFontSizeRem(hearts)).toBeCloseTo(
        WISH_FONT_SIZE_BASE_REM + 0.11 * Math.log2(hearts + 1),
        12
      )
    }
  })

  it('eases from the low-heart size to sqrt(5) times base through 18 hearts', () => {
    for (const hearts of [5, 12, 18]) {
      const progress = hearts / 18
      const expected =
        WISH_FONT_SIZE_BASE_REM +
        (WISH_FONT_SIZE_SQRT5_TARGET_REM - WISH_FONT_SIZE_BASE_REM) * smoothstep(progress)
      expect(wishFontSizeRem(hearts)).toBeCloseTo(expected, 12)
    }
  })

  it('eases from the sqrt(5) target to three times base before capping at 30 hearts', () => {
    for (const hearts of [19, 24, 29]) {
      const progress = (hearts - 18) / 12
      const expected =
        WISH_FONT_SIZE_SQRT5_TARGET_REM +
        (WISH_FONT_SIZE_MAX_REM - WISH_FONT_SIZE_SQRT5_TARGET_REM) * smoothstep(progress)
      expect(wishFontSizeRem(hearts)).toBeCloseTo(expected, 12)
    }
    expect(wishFontSizeRem(30)).toBe(WISH_FONT_SIZE_MAX_REM)
    expect(wishFontSizeRem(80)).toBe(WISH_FONT_SIZE_MAX_REM)
    expect(wishFontSizeRem(Number.MAX_SAFE_INTEGER)).toBe(WISH_FONT_SIZE_MAX_REM)
  })

  it('keeps every integer step monotonic across both transitions and the cap', () => {
    const sizes = Array.from({ length: 101 }, (_, hearts) => wishFontSizeRem(hearts))

    expect(sizes.every((size, index) => index === 0 || size >= sizes[index - 1])).toBe(true)
    expect(wishFontSizeRem(5)).toBeGreaterThan(wishFontSizeRem(4))
    expect(wishFontSizeRem(19)).toBeGreaterThan(wishFontSizeRem(18))
    expect(wishFontSizeRem(30)).toBeGreaterThan(wishFontSizeRem(29))
  })

  it('normalizes invalid inputs without producing non-finite CSS values', () => {
    for (const input of [-5, null, undefined, Number.NaN, 'invalid']) {
      expect(wishFontSizeRem(input)).toBe(WISH_FONT_SIZE_BASE_REM)
      expect(Number.isFinite(wishFontSizeRem(input))).toBe(true)
    }
    expect(wishFontSizeRem('18')).toBeCloseTo(WISH_FONT_SIZE_SQRT5_TARGET_REM, 12)
    expect(wishFontSizeRem(Number.POSITIVE_INFINITY)).toBe(WISH_FONT_SIZE_MAX_REM)
  })
})
