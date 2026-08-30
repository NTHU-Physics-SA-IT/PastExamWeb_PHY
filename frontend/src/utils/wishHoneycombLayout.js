export const WISH_CENTRALITY_GAMMA = 0.6
export const WISH_ITEM_MAX_WIDTH_REM = 15
export const WISH_ITEM_BASE_HEIGHT_REM = 9.5
export const WISH_ITEM_MAX_HEIGHT_REM = 16.5
export const WISH_CELL_HORIZONTAL_SPACING_REM = 15.6
export const WISH_CELL_VERTICAL_BASE_SPACING_REM = 11.25
export const WISH_CELL_VERTICAL_SPACING_REM = 19.5
export const WISH_MOBILE_BREAKPOINT_PX = 768
export const WISH_TABLET_MAX_WIDTH_PX = 1024
export const WISH_NATIVE_DENSITY_CENTER_ROW_CAPACITY = 5

export const WISH_FONT_SIZE_BASE_REM = 1.15
export const WISH_FONT_SIZE_LOW_HEART_GROWTH_REM = 0.11
export const WISH_FONT_SIZE_SQRT5_TARGET_REM = WISH_FONT_SIZE_BASE_REM * Math.sqrt(5)
export const WISH_FONT_SIZE_MAX_REM = 3.45
const WISH_FONT_SIZE_LOG_STAGE_MAX_HEARTS = 4
const WISH_FONT_SIZE_SQRT5_STAGE_MAX_HEARTS = 18
const WISH_FONT_SIZE_CAP_START_HEARTS = 30
const WISH_LAYOUT_SAFE_MARGIN_REM = 1
const WISH_TITLE_LINE_HEIGHT = 1.35
const WISH_FULFILLED_LABEL_SCALE = 0.7
const WISH_TITLE_TO_LABEL_GAP_REM = 0.2
const WISH_ITEM_TO_HEART_GAP_REM = 0.15
const WISH_ITEM_VERTICAL_PADDING_REM = 1.1
const WISH_ITEM_BORDER_REM = 0.125
const WISH_HEART_ROW_MIN_HEIGHT_REM = 2
const RNG_EPSILON = 1e-7
const UINT32_RANGE = 0x100000000

function normalizedRandom(rng) {
  const value = Number(rng())
  if (!Number.isFinite(value)) return 0.5
  return Math.min(1 - RNG_EPSILON, Math.max(RNG_EPSILON, value))
}

function normalizedCount(value) {
  return Math.max(0, Math.floor(Number(value) || 0))
}

function normalizedRootFontSize(value) {
  const numericValue = Number(value)
  return Number.isFinite(numericValue) && numericValue > 0 ? numericValue : 16
}

function smoothstep(value) {
  const progress = Math.min(1, Math.max(0, value))
  return 3 * progress ** 2 - 2 * progress ** 3
}

function normalizedViewport(viewport) {
  return {
    width: Math.max(0, Number(viewport?.width) || 0),
    height: Math.max(0, Number(viewport?.height) || 0),
  }
}

function hashString(value) {
  let hash = 2166136261
  for (const character of String(value)) {
    hash ^= character.charCodeAt(0)
    hash = Math.imul(hash, 16777619)
  }
  return hash >>> 0
}

function seededUnit(seed, scope) {
  let value = ((Number(seed) >>> 0) ^ hashString(scope)) >>> 0
  value += 0x6d2b79f5
  value = Math.imul(value ^ (value >>> 15), value | 1)
  value ^= value + Math.imul(value ^ (value >>> 7), value | 61)
  return ((value ^ (value >>> 14)) >>> 0) / UINT32_RANGE
}

function rowCapacity(row, centerCapacity) {
  return Math.abs(row) % 2 === 0 ? centerCapacity : Math.max(1, centerCapacity - 1)
}

function organicRowOrder(count, sessionSeed) {
  const rows = [0]
  for (let band = 1; rows.length < count; band += 1) {
    const upperFirst = seededUnit(sessionSeed, `band:${band}:order`) < 0.5
    rows.push(upperFirst ? -band : band)
    if (rows.length < count) rows.push(upperFirst ? band : -band)
  }
  return rows
}

function allocateOrganicRowCounts(count, rows, centerCapacity, sessionSeed) {
  const occupancy = 0.68 + seededUnit(sessionSeed, 'row-occupancy') * 0.14
  const counts = Object.fromEntries(rows.map((row) => [row, 1]))
  const preferredCaps = Object.fromEntries(
    rows.map((row) => {
      const capacity = rowCapacity(row, centerCapacity)
      const variation = (seededUnit(sessionSeed, `row:${row}:capacity`) - 0.5) * 1.5
      return [row, Math.min(capacity, Math.max(1, Math.round(capacity * occupancy + variation)))]
    })
  )

  for (let item = rows.length; item < count; item += 1) {
    let eligibleRows = rows.filter((row) => counts[row] < preferredCaps[row])
    if (!eligibleRows.length) {
      eligibleRows = rows.filter((row) => counts[row] < rowCapacity(row, centerCapacity))
    }
    const weightedRows = eligibleRows.map((row) => ({
      row,
      weight:
        (1 / (1 + Math.abs(row) * 0.16)) *
        (0.78 + seededUnit(sessionSeed, `row:${row}:weight`) * 0.44),
    }))
    const totalWeight = weightedRows.reduce((sum, entry) => sum + entry.weight, 0)
    let cursor = seededUnit(sessionSeed, `row-allocation:${item}`) * totalWeight
    let selectedRow = weightedRows.at(-1).row
    for (const entry of weightedRows) {
      cursor -= entry.weight
      if (cursor <= 0) {
        selectedRow = entry.row
        break
      }
    }
    counts[selectedRow] += 1
  }
  return counts
}

function contiguousRowQValues(row, capacity, count, sessionSeed) {
  const legalValues = centerOutQValues(row, capacity).sort(
    (left, right) => left + row / 2 - (right + row / 2)
  )
  const maxStart = capacity - count
  if (maxStart <= 0) return legalValues
  if (row === 0) {
    const centerIndex = legalValues.indexOf(0)
    const centeredStart = Math.min(maxStart, Math.max(0, centerIndex - Math.floor((count - 1) / 2)))
    return legalValues.slice(centeredStart, centeredStart + count)
  }
  const centeredStart = maxStart / 2
  const bias = (seededUnit(sessionSeed, `row:${row}:horizontal-bias`) - 0.5) * Math.min(2, maxStart)
  const start = Math.min(maxStart, Math.max(0, Math.round(centeredStart + bias)))
  return legalValues.slice(start, start + count)
}

function rankWishesBySessionScore(wishes, scores) {
  return wishes
    .map((wish, index) => ({
      wish,
      index,
      score: Number.isFinite(scores?.[wish.id]) ? scores[wish.id] : Number.NEGATIVE_INFINITY,
    }))
    .sort((left, right) => right.score - left.score || left.index - right.index)
    .map(({ wish }) => wish)
}

function centerOutQValues(row, capacity) {
  const candidates = []
  const searchRadius = Math.max(2, capacity + Math.abs(row) + 2)
  for (let q = -searchRadius; q <= searchRadius; q += 1) {
    candidates.push({ q, xUnits: q + row / 2 })
  }
  return candidates
    .sort(
      (left, right) => Math.abs(left.xUnits) - Math.abs(right.xUnits) || left.xUnits - right.xUnits
    )
    .slice(0, capacity)
    .map(({ q }) => q)
}

export function wishHoneycombGeometry(viewport, rootFontSize = 16, layoutMetrics = null) {
  const normalizedSize = normalizedViewport(viewport)
  const rootSize = normalizedRootFontSize(rootFontSize)
  const itemHeightRem = Number.isFinite(layoutMetrics?.itemHeightRem)
    ? layoutMetrics.itemHeightRem
    : WISH_ITEM_MAX_HEIGHT_REM
  const verticalSpacingRem = Number.isFinite(layoutMetrics?.verticalSpacingRem)
    ? layoutMetrics.verticalSpacingRem
    : WISH_CELL_VERTICAL_SPACING_REM
  const nativeNavigation = normalizedSize.width <= WISH_TABLET_MAX_WIDTH_PX
  const horizontalScale = 1
  const verticalScale = 1
  return {
    nativeNavigation,
    horizontalScale,
    verticalScale,
    itemWidth: WISH_ITEM_MAX_WIDTH_REM * rootSize * horizontalScale,
    itemHeight: itemHeightRem * rootSize,
    horizontalSpacing: WISH_CELL_HORIZONTAL_SPACING_REM * rootSize * horizontalScale,
    verticalSpacing: verticalSpacingRem * rootSize * verticalScale,
    safeMargin: WISH_LAYOUT_SAFE_MARGIN_REM * rootSize,
  }
}

export function wishHoneycombRequiredWidthForCapacity(centerCapacity, geometry) {
  const normalizedCapacity = Math.max(1, Math.floor(Number(centerCapacity) || 1))
  const { itemWidth, horizontalSpacing, safeMargin } = geometry
  return itemWidth + (normalizedCapacity - 1) * horizontalSpacing + safeMargin * 2
}

export function wishHoneycombLogicalDensityWidth(viewportWidth, geometry) {
  const normalizedWidth = Math.max(0, Number(viewportWidth) || 0)
  if (!geometry.nativeNavigation) return normalizedWidth
  return Math.max(
    normalizedWidth,
    wishHoneycombRequiredWidthForCapacity(WISH_NATIVE_DENSITY_CENTER_ROW_CAPACITY, geometry)
  )
}

export function wishHoneycombCenterRowCapacity(viewportWidth, geometry) {
  const { itemWidth, horizontalSpacing, safeMargin } = geometry
  const logicalDensityWidth = wishHoneycombLogicalDensityWidth(viewportWidth, geometry)
  const safeWidth = Math.max(itemWidth, logicalDensityWidth - safeMargin * 2)
  const rawCapacity = Math.max(1, Math.floor((safeWidth - itemWidth) / horizontalSpacing) + 1)
  const oddCapacity = rawCapacity % 2 === 0 ? Math.max(1, rawCapacity - 1) : rawCapacity
  return oddCapacity
}

function honeycombCell(row, q, viewport, geometry) {
  const x = (q + row / 2) * geometry.horizontalSpacing
  const y = row * geometry.verticalSpacing
  const horizontalLimit = Math.max(
    0,
    (viewport.width - geometry.itemWidth) / 2 - geometry.safeMargin
  )
  const verticalLimit = Math.max(
    0,
    (viewport.height - geometry.itemHeight) / 2 - geometry.safeMargin
  )
  return {
    mode: 'honeycomb',
    q,
    r: row,
    x,
    y,
    inInitialViewport: Math.abs(x) <= horizontalLimit && Math.abs(y) <= verticalLimit,
  }
}

export function wishInteractionMode(viewport) {
  const { width } = normalizedViewport(viewport)
  if (width < WISH_MOBILE_BREAKPOINT_PX) return 'mobile'
  if (width <= WISH_TABLET_MAX_WIDTH_PX) return 'tablet'
  return 'desktop'
}

export function createWishWorldGeometry(
  positions,
  viewport,
  rootFontSize = 16,
  { native2DOverflow = false, layoutMetrics = null } = {}
) {
  const normalizedSize = normalizedViewport(viewport)
  const geometry = wishHoneycombGeometry(normalizedSize, rootFontSize, layoutMetrics)
  const { itemWidth, itemHeight, safeMargin: margin } = geometry
  const positionList = Object.values(positions || {}).filter(
    ({ x, y }) => Number.isFinite(x) && Number.isFinite(y)
  )

  if (!positionList.length) {
    return {
      width: normalizedSize.width,
      height: normalizedSize.height,
      offsetX: normalizedSize.width / 2,
      offsetY: normalizedSize.height / 2,
    }
  }

  const xValues = positionList.map(({ x }) => x)
  const yValues = positionList.map(({ y }) => y)
  const minimumWidth = normalizedSize.width + (native2DOverflow ? itemWidth : 0)
  const contentWidth = Math.max(...xValues) - Math.min(...xValues) + itemWidth + margin * 2
  const contentHeight = Math.max(...yValues) - Math.min(...yValues) + itemHeight + margin * 2
  const width = Math.max(minimumWidth, contentWidth)
  const minimumHeight = normalizedSize.height + (native2DOverflow ? itemHeight : 0)
  const height = Math.max(minimumHeight, contentHeight)
  const offsetX = (width - contentWidth) / 2 + margin + itemWidth / 2 - Math.min(...xValues)
  const offsetY = (height - contentHeight) / 2 + margin + itemHeight / 2 - Math.min(...yValues)

  return { width, height, offsetX, offsetY }
}

export function wishCentralityScore(heartCount, rng) {
  const hearts = Math.max(0, Number(heartCount) || 0)
  const randomValue = normalizedRandom(rng)
  const gumbelNoise = -Math.log(-Math.log(randomValue))
  return WISH_CENTRALITY_GAMMA * Math.log1p(hearts) + gumbelNoise
}

export function createWishLayoutSeed(rng = Math.random) {
  return Math.floor(normalizedRandom(rng) * UINT32_RANGE) >>> 0
}

export function createSeededWishRng(seed, scope = 'default') {
  let index = 0
  return () => seededUnit(seed, `${scope}:${index++}`)
}

export function assignWishCentralityScores(wishes, rng = Math.random, existingScores = {}) {
  const scores = { ...existingScores }
  for (const wish of wishes) {
    if (!Number.isFinite(scores[wish.id])) {
      scores[wish.id] = wishCentralityScore(wish?.heart_count, rng)
    }
  }
  return scores
}

export function wishFontSizeRem(heartCount) {
  const hearts = Math.max(0, Number(heartCount) || 0)
  if (hearts <= WISH_FONT_SIZE_LOG_STAGE_MAX_HEARTS) {
    return WISH_FONT_SIZE_BASE_REM + WISH_FONT_SIZE_LOW_HEART_GROWTH_REM * Math.log2(hearts + 1)
  }
  if (hearts <= WISH_FONT_SIZE_SQRT5_STAGE_MAX_HEARTS) {
    const progress = smoothstep(hearts / WISH_FONT_SIZE_SQRT5_STAGE_MAX_HEARTS)
    return (
      WISH_FONT_SIZE_BASE_REM +
      (WISH_FONT_SIZE_SQRT5_TARGET_REM - WISH_FONT_SIZE_BASE_REM) * progress
    )
  }
  if (hearts < WISH_FONT_SIZE_CAP_START_HEARTS) {
    const progress = smoothstep(
      (hearts - WISH_FONT_SIZE_SQRT5_STAGE_MAX_HEARTS) /
        (WISH_FONT_SIZE_CAP_START_HEARTS - WISH_FONT_SIZE_SQRT5_STAGE_MAX_HEARTS)
    )
    return (
      WISH_FONT_SIZE_SQRT5_TARGET_REM +
      (WISH_FONT_SIZE_MAX_REM - WISH_FONT_SIZE_SQRT5_TARGET_REM) * progress
    )
  }
  return WISH_FONT_SIZE_MAX_REM
}

function wishItemFootprintRem(wish) {
  const fontSize = wishFontSizeRem(wish?.heart_count)
  return (
    fontSize * WISH_TITLE_LINE_HEIGHT * 2 +
    (wish?.fulfilled
      ? fontSize * WISH_FULFILLED_LABEL_SCALE * WISH_TITLE_LINE_HEIGHT + WISH_TITLE_TO_LABEL_GAP_REM
      : 0) +
    WISH_ITEM_TO_HEART_GAP_REM +
    WISH_ITEM_VERTICAL_PADDING_REM +
    WISH_ITEM_BORDER_REM +
    WISH_HEART_ROW_MIN_HEIGHT_REM
  )
}

export function wishHoneycombLayoutMetrics(wishes = []) {
  const requiredHeightRem = wishes.reduce(
    (maximum, wish) => Math.max(maximum, wishItemFootprintRem(wish)),
    WISH_ITEM_BASE_HEIGHT_REM
  )
  const itemHeightRem = Math.min(
    WISH_ITEM_MAX_HEIGHT_REM,
    Math.max(WISH_ITEM_BASE_HEIGHT_REM, requiredHeightRem)
  )
  const spacingRatio = WISH_CELL_VERTICAL_SPACING_REM / WISH_ITEM_MAX_HEIGHT_REM
  const verticalSpacingRem = Math.min(
    WISH_CELL_VERTICAL_SPACING_REM,
    Math.max(WISH_CELL_VERTICAL_BASE_SPACING_REM, itemHeightRem * spacingRatio)
  )
  return { itemHeightRem, verticalSpacingRem }
}

export function generateWishHoneycombCells(
  count,
  viewport,
  rootFontSize = 16,
  sessionSeed = 0,
  layoutMetrics = null
) {
  const requestedCount = normalizedCount(count)
  if (!requestedCount) return []
  const normalizedSize = normalizedViewport(viewport)
  const geometry = wishHoneycombGeometry(normalizedSize, rootFontSize, layoutMetrics)
  const centerCapacity = wishHoneycombCenterRowCapacity(normalizedSize.width, geometry)
  const targetOccupancy = 0.68 + seededUnit(sessionSeed, 'row-occupancy') * 0.14
  const maximumRows = requestedCount
  const orderedRows = organicRowOrder(maximumRows, sessionSeed)
  let activeRowCount = 1
  let capacity = centerCapacity
  while (activeRowCount < maximumRows && capacity * targetOccupancy < requestedCount) {
    capacity += rowCapacity(orderedRows[activeRowCount], centerCapacity)
    activeRowCount += 1
  }
  while (capacity < requestedCount && activeRowCount < maximumRows) {
    capacity += rowCapacity(orderedRows[activeRowCount], centerCapacity)
    activeRowCount += 1
  }

  const activeRows = orderedRows.slice(0, activeRowCount)
  const rowCounts = allocateOrganicRowCounts(
    requestedCount,
    activeRows,
    centerCapacity,
    sessionSeed
  )
  const selectedCells = activeRows.flatMap((row) => {
    const capacityForRow = rowCapacity(row, centerCapacity)
    return contiguousRowQValues(row, capacityForRow, rowCounts[row], sessionSeed).map((q) =>
      honeycombCell(row, q, normalizedSize, geometry)
    )
  })
  const horizontalScale = geometry.horizontalSpacing
  const verticalScale = geometry.verticalSpacing
  return selectedCells.sort((left, right) => {
    const leftDistance = Math.hypot(left.x / horizontalScale, left.y / verticalScale)
    const rightDistance = Math.hypot(right.x / horizontalScale, right.y / verticalScale)
    if (leftDistance !== rightDistance) return leftDistance - rightDistance
    return (
      seededUnit(sessionSeed, `cell:${left.q}:${left.r}:priority`) -
      seededUnit(sessionSeed, `cell:${right.q}:${right.r}:priority`)
    )
  })
}

export function assignWishHoneycombPositions(
  wishes,
  scores,
  viewport,
  rootFontSize = 16,
  sessionSeed = 0,
  layoutMetrics = null
) {
  const cells = generateWishHoneycombCells(
    wishes.length,
    viewport,
    rootFontSize,
    sessionSeed,
    layoutMetrics
  )
  const positions = {}
  rankWishesBySessionScore(wishes, scores).forEach((wish, index) => {
    positions[wish.id] = { ...cells[index] }
  })
  return positions
}

export function reprojectWishHoneycombPositions(
  positions,
  viewport,
  rootFontSize = 16,
  layoutMetrics = null
) {
  const normalizedSize = normalizedViewport(viewport)
  const geometry = wishHoneycombGeometry(normalizedSize, rootFontSize, layoutMetrics)
  return Object.fromEntries(
    Object.entries(positions || {}).map(([wishId, position]) => [
      wishId,
      honeycombCell(position.r, position.q, normalizedSize, geometry),
    ])
  )
}

export function createResponsiveWishLayout(
  wishes,
  scores,
  viewport,
  rootFontSize = 16,
  sessionSeed = 0,
  layoutMetrics = null
) {
  const normalizedSize = normalizedViewport(viewport)
  const positions = assignWishHoneycombPositions(
    wishes,
    scores,
    normalizedSize,
    rootFontSize,
    sessionSeed,
    layoutMetrics
  )
  return {
    mode: 'honeycomb',
    interactionMode: wishInteractionMode(normalizedSize),
    positions,
    camera: { x: 0, y: 0 },
  }
}

export function appendResponsiveWishPositions(
  existingPositions,
  newWishes,
  scores,
  viewport,
  rootFontSize = 16,
  sessionSeed = 0,
  layoutMetrics = null
) {
  if (!newWishes.length) return { ...existingPositions }
  const rootSize = normalizedRootFontSize(rootFontSize)
  const normalizedSize = normalizedViewport(viewport)
  const nextPositions = { ...existingPositions }
  const orderedWishes = rankWishesBySessionScore(newWishes, scores)

  const usedCells = new Set(Object.values(existingPositions).map(({ q, r }) => `${q}:${r}`))
  let requestedCount = usedCells.size + orderedWishes.length
  let availableCells = []
  while (availableCells.length < orderedWishes.length) {
    availableCells = generateWishHoneycombCells(
      requestedCount,
      normalizedSize,
      rootSize,
      sessionSeed,
      layoutMetrics
    ).filter(({ q, r }) => !usedCells.has(`${q}:${r}`))
    requestedCount += orderedWishes.length
  }
  orderedWishes.forEach((wish, index) => {
    nextPositions[wish.id] = { ...availableCells[index] }
  })
  return nextPositions
}
