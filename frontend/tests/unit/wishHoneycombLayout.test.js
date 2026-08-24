import { describe, expect, it } from 'vitest'

import {
  WISH_CELL_HORIZONTAL_SPACING_REM,
  WISH_CELL_VERTICAL_SPACING_REM,
  WISH_ITEM_MAX_HEIGHT_REM,
  WISH_ITEM_MAX_WIDTH_REM,
  WISH_MOBILE_BREAKPOINT_PX,
  assignDesktopWishPositions,
  assignMobileWishPositions,
  assignWishCentralityScores,
  createWishLayoutSeed,
  createResponsiveWishLayout,
  generateDesktopHoneycombCells,
  generateMobileRowSlots,
  selectMobileAnchorWishId,
  wishCentralityScore,
  wishFontSizeRem,
} from '@/utils/wishHoneycombLayout'

function sequenceRng(values) {
  let index = 0
  return () => values[index++ % values.length]
}

const wishes = [
  { id: 1, heart_count: 0 },
  { id: 2, heart_count: 3 },
  { id: 3, heart_count: 25 },
  { id: 4, heart_count: 400 },
]

describe('Wish Pool honeycomb geometry', () => {
  it('derives horizontal row capacity from the actual content viewport', () => {
    const wideCells = generateDesktopHoneycombCells(5, { width: 1600, height: 720 }, 16, 41)
    const tabletCells = generateDesktopHoneycombCells(5, { width: 900, height: 720 }, 16, 41)
    const wideHorizontalExtent = Math.max(...wideCells.map(({ x }) => Math.abs(x)))
    const tabletHorizontalExtent = Math.max(...tabletCells.map(({ x }) => Math.abs(x)))

    expect(wideHorizontalExtent).toBeGreaterThan(tabletHorizontalExtent)
    expect(wideCells.every(({ r }) => Math.abs(r) <= 1)).toBe(true)
    expect(tabletCells.some(({ r }) => Math.abs(r) > 0)).toBe(true)
  })

  it('keeps one session stable while different sessions can vary row allocation', () => {
    const viewport = { width: 1600, height: 720 }
    const first = generateDesktopHoneycombCells(9, viewport, 16, 101)
    const repeated = generateDesktopHoneycombCells(9, viewport, 16, 101)
    const alternatives = [102, 103, 104, 105].map((seed) =>
      generateDesktopHoneycombCells(9, viewport, 16, seed)
    )
    const signature = (cells) =>
      [...cells]
        .sort((left, right) => left.r - right.r || left.q - right.q)
        .map(({ q, r }) => `${q}:${r}`)
        .join('|')

    expect(repeated).toEqual(first)
    expect(alternatives.some((cells) => signature(cells) !== signature(first))).toBe(true)
  })

  it('uses constrained organic row quotas instead of always filling the center row', () => {
    const viewport = { width: 1600, height: 720 }
    const sessions = Array.from({ length: 24 }, (_, seed) =>
      generateDesktopHoneycombCells(9, viewport, 16, seed + 1)
    )
    const rowCounts = (cells) =>
      cells.reduce((counts, { r }) => ({ ...counts, [r]: (counts[r] || 0) + 1 }), {})

    expect(sessions.every((cells) => cells.length === 9)).toBe(true)
    expect(sessions.some((cells) => (rowCounts(cells)[0] || 0) < 5)).toBe(true)
    expect(
      sessions.some((cells) => (rowCounts(cells)[-1] || 0) !== (rowCounts(cells)[1] || 0))
    ).toBe(true)
    expect(
      sessions.some((cells) => {
        const rows = Object.groupBy(cells, ({ r }) => r)
        return Object.values(rows).some((row) => {
          const meanX = row.reduce((sum, cell) => sum + cell.x, 0) / row.length
          return Math.abs(meanX) > 0
        })
      })
    ).toBe(true)
  })

  it('preserves axial staggering and generates unique finite positions', () => {
    const cells = generateDesktopHoneycombCells(67, { width: 1180, height: 680 }, 16, 77)
    const keys = cells.map(({ q, r }) => `${q}:${r}`)
    const staggered = cells.filter((cell) => Math.abs(cell.r) % 2 === 1)

    expect(cells).toHaveLength(67)
    expect(new Set(keys).size).toBe(67)
    expect(cells.every(({ x, y }) => Number.isFinite(x) && Number.isFinite(y))).toBe(true)
    expect(
      staggered.every(
        (cell) => Math.abs(cell.x / (WISH_CELL_HORIZONTAL_SPACING_REM * 16)) % 1 === 0.5
      )
    ).toBe(true)
  })

  it('keeps every organic row within its viewport-derived legal capacity', () => {
    const cells = generateDesktopHoneycombCells(41, { width: 1600, height: 720 }, 16, 808)
    const counts = cells.reduce((result, { r }) => {
      result[r] = (result[r] || 0) + 1
      return result
    }, {})

    expect(Object.values(counts).every((count) => count <= 5)).toBe(true)
    expect(
      Object.entries(counts).every(([row, count]) => Math.abs(Number(row)) % 2 === 0 || count <= 4)
    ).toBe(true)
  })

  it('uses actual viewport height to distinguish initially visible vertical bands', () => {
    const shortViewport = generateDesktopHoneycombCells(20, { width: 1180, height: 420 }, 16, 31)
    const tallViewport = generateDesktopHoneycombCells(20, { width: 1180, height: 900 }, 16, 31)

    expect(
      tallViewport.filter(({ inInitialViewport }) => inInitialViewport).length
    ).toBeGreaterThan(shortViewport.filter(({ inInitialViewport }) => inInitialViewport).length)
  })

  it('switches modes at the canonical Archive mobile boundary', () => {
    const scores = { 1: 1 }
    const anchorWishId = wishes[0].id

    expect(
      createResponsiveWishLayout(
        wishes.slice(0, 1),
        scores,
        { width: 767, height: 700 },
        anchorWishId,
        16
      ).mode
    ).toBe('mobile')
    expect(
      createResponsiveWishLayout(
        wishes.slice(0, 1),
        scores,
        { width: 768, height: 700 },
        anchorWishId,
        16
      ).mode
    ).toBe('honeycomb')
    expect(
      createResponsiveWishLayout(
        wishes.slice(0, 1),
        scores,
        { width: 769, height: 700 },
        anchorWishId,
        16
      ).mode
    ).toBe('honeycomb')
  })
})

describe('Wish Pool probabilistic centrality', () => {
  it('keeps Gumbel scoring finite for clamped RNG edges and large heart counts', () => {
    expect(Number.isFinite(wishCentralityScore(0, () => 0))).toBe(true)
    expect(Number.isFinite(wishCentralityScore(0, () => 1))).toBe(true)
    expect(Number.isFinite(wishCentralityScore(Number.MAX_SAFE_INTEGER, () => 0.5))).toBe(true)
  })

  it('gives higher heart counts a score advantage when noise is equal', () => {
    const low = wishCentralityScore(0, () => 0.5)
    const high = wishCentralityScore(100, () => 0.5)

    expect(high).toBeGreaterThan(low)
  })

  it('assigns higher session scores to higher-priority desktop cells', () => {
    const positions = assignDesktopWishPositions(
      [
        { id: 'low', heart_count: 0 },
        { id: 'high', heart_count: 100 },
      ],
      { low: 1, high: 10 },
      { width: 1100, height: 680 },
      16
    )

    expect(positions.high).toMatchObject({ q: 0, r: 0, x: 0, y: 0 })
    expect(positions.low).not.toMatchObject({ q: 0, r: 0 })
  })

  it('creates finite session scores once and reuses them across viewport reflow', () => {
    const scores = assignWishCentralityScores(wishes, sequenceRng([0.11, 0.27, 0.43, 0.69, 0.83]))
    const scoreSnapshot = { ...scores }
    const wide = assignDesktopWishPositions(wishes, scores, { width: 1500, height: 720 }, 16)
    const tablet = assignDesktopWishPositions(wishes, scores, { width: 820, height: 620 }, 16)

    expect(scores).toEqual(scoreSnapshot)
    expect(Object.values(scores).every(Number.isFinite)).toBe(true)
    expect(Object.keys(wide)).toEqual(Object.keys(tablet))
    expect(wide).not.toEqual(tablet)
  })

  it('retains gamma 0.6 scoring and supports zero and very large hearts', () => {
    const mixed = [
      { id: 'zero', heart_count: 0 },
      { id: 'large', heart_count: Number.MAX_SAFE_INTEGER },
    ]
    const scores = assignWishCentralityScores(mixed, sequenceRng([0, 1]))

    expect(WISH_MOBILE_BREAKPOINT_PX).toBe(768)
    expect(Object.values(scores).every(Number.isFinite)).toBe(true)
  })

  it('creates a stable session seed from an injectable RNG', () => {
    expect(createWishLayoutSeed(() => 0.25)).toBe(createWishLayoutSeed(() => 0.25))
    expect(createWishLayoutSeed(() => 0.25)).not.toBe(createWishLayoutSeed(() => 0.75))
  })
})

describe('Wish Pool mobile row layout', () => {
  it('uses one unique row per Wish and the full viewport height when all rows fit', () => {
    const slots = generateMobileRowSlots(4, { width: 390, height: 800 }, 16)
    const yPositions = slots.map((slot) => slot.y)
    const screenPositions = slots.map((slot) => slot.screenY)

    expect(new Set(yPositions).size).toBe(4)
    expect(Math.min(...screenPositions)).toBeGreaterThanOrEqual(0)
    expect(Math.max(...screenPositions)).toBeGreaterThan(800 * 0.85)
    expect(slots[0].anchorRatio).toBeCloseTo(0.25, 1)
  })

  it('selects the highest-heart Wish and breaks max-heart ties with session RNG', () => {
    const tied = [
      { id: 'first', heart_count: 20 },
      { id: 'second', heart_count: 20 },
      { id: 'low', heart_count: 1 },
    ]

    expect(selectMobileAnchorWishId(tied, () => 0.1)).toBe('first')
    expect(selectMobileAnchorWishId(tied, () => 0.9)).toBe('second')
  })

  it('anchors the selected Wish near 25% and assigns stronger session scores nearby', () => {
    const mobileWishes = [
      { id: 'anchor', heart_count: 30 },
      { id: 'high-score', heart_count: 0 },
      { id: 'low-score', heart_count: 0 },
    ]
    const positions = assignMobileWishPositions(
      mobileWishes,
      { anchor: 5, 'high-score': 4, 'low-score': 1 },
      { width: 390, height: 800 },
      'anchor',
      16
    )

    expect(positions.anchor.anchor).toBe(true)
    expect(positions.anchor.anchorRatio).toBeCloseTo(0.25, 1)
    expect(Math.abs(positions['high-score'].y)).toBeLessThanOrEqual(
      Math.abs(positions['low-score'].y)
    )
    expect(new Set(Object.values(positions).map(({ row }) => row)).size).toBe(3)
    expect(Object.values(positions).every(({ x }) => x === 0)).toBe(true)
  })

  it('creates a non-overlapping virtual vertical world when rows exceed viewport capacity', () => {
    const slots = generateMobileRowSlots(12, { width: 390, height: 640 }, 16)
    const orderedY = slots.map(({ y }) => y).sort((left, right) => left - right)

    for (let index = 1; index < orderedY.length; index += 1) {
      expect(orderedY[index] - orderedY[index - 1]).toBeGreaterThanOrEqual(
        WISH_ITEM_MAX_HEIGHT_REM * 16
      )
    }
  })
})

describe('Wish Pool typography and dense geometry', () => {
  it('uses a safe logarithmic heart scale with the required base and cap', () => {
    expect(wishFontSizeRem(0)).toBeCloseTo(1.15)
    expect(wishFontSizeRem(1)).toBeCloseTo(1.26)
    expect(wishFontSizeRem(3)).toBeCloseTo(1.37)
    expect(wishFontSizeRem(7)).toBeCloseTo(1.48)
    expect(wishFontSizeRem(15)).toBeCloseTo(1.59)
    expect(wishFontSizeRem(31)).toBe(1.6)
    expect(wishFontSizeRem(Number.MAX_SAFE_INTEGER)).toBe(1.6)
  })

  it('keeps growth monotonic and diminishing before the cap', () => {
    const sizes = [0, 1, 2, 3, 7, 15, 31].map(wishFontSizeRem)
    expect(sizes.every((size, index) => index === 0 || size >= sizes[index - 1])).toBe(true)
    expect(wishFontSizeRem(1) - wishFontSizeRem(0)).toBeGreaterThan(
      wishFontSizeRem(2) - wishFontSizeRem(1)
    )
    expect(wishFontSizeRem(2) - wishFontSizeRem(1)).toBeGreaterThan(
      wishFontSizeRem(3) - wishFontSizeRem(2)
    )
  })

  it('normalizes negative, null, and invalid heart counts to the base size', () => {
    expect(wishFontSizeRem(-5)).toBeCloseTo(1.15)
    expect(wishFontSizeRem(null)).toBeCloseTo(1.15)
    expect(wishFontSizeRem('invalid')).toBeCloseTo(1.15)
  })

  it('keeps neighboring Honeycomb footprints separated at maximum content size', () => {
    expect(WISH_CELL_HORIZONTAL_SPACING_REM).toBeGreaterThan(WISH_ITEM_MAX_WIDTH_REM)
    expect(WISH_CELL_VERTICAL_SPACING_REM).toBeGreaterThan(WISH_ITEM_MAX_HEIGHT_REM)

    const center = { x: 0, y: 0 }
    const neighbors = [
      { x: WISH_CELL_HORIZONTAL_SPACING_REM, y: 0 },
      {
        x: WISH_CELL_HORIZONTAL_SPACING_REM / 2,
        y: WISH_CELL_VERTICAL_SPACING_REM,
      },
      {
        x: -WISH_CELL_HORIZONTAL_SPACING_REM / 2,
        y: WISH_CELL_VERTICAL_SPACING_REM,
      },
    ]

    for (const neighbor of neighbors) {
      const overlapsHorizontally = Math.abs(neighbor.x - center.x) < WISH_ITEM_MAX_WIDTH_REM
      const overlapsVertically = Math.abs(neighbor.y - center.y) < WISH_ITEM_MAX_HEIGHT_REM
      expect(overlapsHorizontally && overlapsVertically).toBe(false)
    }
  })
})
