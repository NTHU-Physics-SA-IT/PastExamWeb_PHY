export const WISH_CENTRALITY_GAMMA = 0.6
export const WISH_ITEM_MAX_WIDTH_REM = 15
export const WISH_ITEM_MAX_HEIGHT_REM = 9.5
export const WISH_CELL_HORIZONTAL_SPACING_REM = 16
export const WISH_CELL_VERTICAL_SPACING_REM = 12
export const WISH_MOBILE_BREAKPOINT_PX = 768

const WISH_FONT_SIZE_BASE_REM = 1.15
const WISH_FONT_SIZE_GROWTH_REM = 0.11
const WISH_FONT_SIZE_MAX_REM = 1.6
const WISH_LAYOUT_SAFE_MARGIN_REM = 1
const WISH_MOBILE_ROW_GAP_REM = 1
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

function desktopCenterRowCapacity(viewportWidth, rootFontSize) {
  const itemWidth = WISH_ITEM_MAX_WIDTH_REM * rootFontSize
  const spacing = WISH_CELL_HORIZONTAL_SPACING_REM * rootFontSize
  const safeWidth = Math.max(
    itemWidth,
    viewportWidth - WISH_LAYOUT_SAFE_MARGIN_REM * rootFontSize * 2
  )
  const rawCapacity = Math.max(1, Math.floor((safeWidth - itemWidth) / spacing) + 1)
  return rawCapacity % 2 === 0 ? Math.max(1, rawCapacity - 1) : rawCapacity
}

function desktopCell(row, q, viewport, rootFontSize) {
  const x = (q + row / 2) * WISH_CELL_HORIZONTAL_SPACING_REM * rootFontSize
  const y = row * WISH_CELL_VERTICAL_SPACING_REM * rootFontSize
  const safeMargin = WISH_LAYOUT_SAFE_MARGIN_REM * rootFontSize
  const horizontalLimit = Math.max(
    0,
    (viewport.width - WISH_ITEM_MAX_WIDTH_REM * rootFontSize) / 2 - safeMargin
  )
  const verticalLimit = Math.max(
    0,
    (viewport.height - WISH_ITEM_MAX_HEIGHT_REM * rootFontSize) / 2 - safeMargin
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

function mobileRowSpacing(rootFontSize) {
  return (WISH_ITEM_MAX_HEIGHT_REM + WISH_MOBILE_ROW_GAP_REM) * rootFontSize
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

export function selectMobileAnchorWishId(wishes, rng = Math.random) {
  if (!wishes.length) return null
  const highestHeartCount = Math.max(
    ...wishes.map((wish) => Math.max(0, Number(wish?.heart_count) || 0))
  )
  const candidates = wishes.filter(
    (wish) => Math.max(0, Number(wish?.heart_count) || 0) === highestHeartCount
  )
  const candidateIndex = Math.floor(normalizedRandom(rng) * candidates.length)
  return candidates[candidateIndex]?.id ?? null
}

export function wishFontSizeRem(heartCount) {
  const hearts = Math.max(0, Number(heartCount) || 0)
  return Math.min(
    WISH_FONT_SIZE_MAX_REM,
    WISH_FONT_SIZE_BASE_REM + WISH_FONT_SIZE_GROWTH_REM * Math.log2(hearts + 1)
  )
}

export function generateDesktopHoneycombCells(count, viewport, rootFontSize = 16, sessionSeed = 0) {
  const requestedCount = normalizedCount(count)
  if (!requestedCount) return []
  const normalizedSize = normalizedViewport(viewport)
  const rootSize = normalizedRootFontSize(rootFontSize)
  const centerCapacity = desktopCenterRowCapacity(normalizedSize.width, rootSize)
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
      desktopCell(row, q, normalizedSize, rootSize)
    )
  })
  const horizontalScale = WISH_CELL_HORIZONTAL_SPACING_REM * rootSize
  const verticalScale = WISH_CELL_VERTICAL_SPACING_REM * rootSize
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

export function assignDesktopWishPositions(
  wishes,
  scores,
  viewport,
  rootFontSize = 16,
  sessionSeed = 0
) {
  const cells = generateDesktopHoneycombCells(wishes.length, viewport, rootFontSize, sessionSeed)
  const positions = {}
  rankWishesBySessionScore(wishes, scores).forEach((wish, index) => {
    positions[wish.id] = { ...cells[index] }
  })
  return positions
}

export function generateMobileRowSlots(count, viewport, rootFontSize = 16) {
  const requestedCount = normalizedCount(count)
  if (!requestedCount) return []
  const normalizedSize = normalizedViewport(viewport)
  const rootSize = normalizedRootFontSize(rootFontSize)
  const itemHeight = WISH_ITEM_MAX_HEIGHT_REM * rootSize
  const safeMargin = WISH_LAYOUT_SAFE_MARGIN_REM * rootSize
  const effectiveHeight = Math.max(normalizedSize.height, itemHeight + safeMargin * 2)
  const safeTop = itemHeight / 2 + safeMargin
  const safeBottom = effectiveHeight - itemHeight / 2 - safeMargin
  const targetY = Math.min(safeBottom, Math.max(safeTop, effectiveHeight * 0.25))
  const minimumSpacing = mobileRowSpacing(rootSize)
  const visibleCapacity = Math.max(1, Math.floor((safeBottom - safeTop) / minimumSpacing) + 1)
  const anchorRatio = targetY / effectiveHeight
  const screenRows = [{ row: 0, screenY: targetY }]

  if (requestedCount <= visibleCapacity) {
    const remainingCount = requestedCount - 1
    const capacityAbove = Math.floor((targetY - safeTop) / minimumSpacing)
    const capacityBelow = Math.floor((safeBottom - targetY) / minimumSpacing)
    let aboveCount = Math.min(capacityAbove, Math.floor(remainingCount * 0.25))
    let belowCount = remainingCount - aboveCount
    if (belowCount > capacityBelow) {
      const shiftedAbove = Math.min(capacityAbove - aboveCount, belowCount - capacityBelow)
      aboveCount += shiftedAbove
      belowCount -= shiftedAbove
    }

    for (let index = 1; index <= belowCount; index += 1) {
      screenRows.push({
        row: index,
        screenY: targetY + ((safeBottom - targetY) * index) / Math.max(1, belowCount),
      })
    }
    for (let index = 1; index <= aboveCount; index += 1) {
      screenRows.push({
        row: -index,
        screenY: targetY - ((targetY - safeTop) * index) / Math.max(1, aboveCount),
      })
    }
  } else {
    for (let distance = 1; screenRows.length < requestedCount; distance += 1) {
      screenRows.push({ row: distance, screenY: targetY + distance * minimumSpacing })
      if (screenRows.length === requestedCount) break
      screenRows.push({ row: -distance, screenY: targetY - distance * minimumSpacing })
    }
  }

  return screenRows
    .sort(
      (left, right) =>
        Math.abs(left.screenY - targetY) - Math.abs(right.screenY - targetY) ||
        right.screenY - left.screenY
    )
    .map(({ row, screenY }, index) => ({
      mode: 'mobile',
      row,
      x: 0,
      y: screenY - targetY,
      screenY,
      anchor: index === 0,
      anchorRatio,
      inInitialViewport: screenY >= safeTop && screenY <= safeBottom,
    }))
}

export function assignMobileWishPositions(
  wishes,
  scores,
  viewport,
  anchorWishId,
  rootFontSize = 16
) {
  const slots = generateMobileRowSlots(wishes.length, viewport, rootFontSize)
  const positions = {}
  const anchorWish = wishes.find((wish) => wish.id === anchorWishId) || wishes[0]
  if (!anchorWish || !slots.length) return positions

  positions[anchorWish.id] = { ...slots[0], anchor: true }
  const remainingWishes = rankWishesBySessionScore(
    wishes.filter((wish) => wish.id !== anchorWish.id),
    scores
  )
  remainingWishes.forEach((wish, index) => {
    positions[wish.id] = { ...slots[index + 1], anchor: false }
  })
  return positions
}

export function createResponsiveWishLayout(
  wishes,
  scores,
  viewport,
  anchorWishId,
  rootFontSize = 16,
  sessionSeed = 0
) {
  const normalizedSize = normalizedViewport(viewport)
  const mobile = normalizedSize.width < WISH_MOBILE_BREAKPOINT_PX
  const positions = mobile
    ? assignMobileWishPositions(wishes, scores, normalizedSize, anchorWishId, rootFontSize)
    : assignDesktopWishPositions(wishes, scores, normalizedSize, rootFontSize, sessionSeed)
  const anchorPosition = mobile ? positions[anchorWishId] : null
  return {
    mode: mobile ? 'mobile' : 'honeycomb',
    positions,
    camera: {
      x: 0,
      y: mobile
        ? (anchorPosition?.anchorRatio ?? 0.25) * normalizedSize.height - normalizedSize.height / 2
        : 0,
    },
  }
}

export function appendResponsiveWishPositions(
  existingPositions,
  newWishes,
  scores,
  viewport,
  anchorWishId,
  rootFontSize = 16,
  sessionSeed = 0
) {
  if (!newWishes.length) return { ...existingPositions }
  const rootSize = normalizedRootFontSize(rootFontSize)
  const normalizedSize = normalizedViewport(viewport)
  const mobile = normalizedSize.width < WISH_MOBILE_BREAKPOINT_PX
  const nextPositions = { ...existingPositions }
  const orderedWishes = rankWishesBySessionScore(newWishes, scores)

  if (mobile) {
    const existingRows = Object.values(existingPositions)
    const lowestY = existingRows.length ? Math.max(...existingRows.map(({ y }) => y)) : 0
    const highestRow = existingRows.length
      ? Math.max(0, ...existingRows.map(({ row }) => Number(row) || 0))
      : 0
    orderedWishes.forEach((wish, index) => {
      nextPositions[wish.id] = {
        mode: 'mobile',
        row: highestRow + index + 1,
        x: 0,
        y: lowestY + mobileRowSpacing(rootSize) * (index + 1),
        anchor: false,
        anchorRatio: nextPositions[anchorWishId]?.anchorRatio ?? 0.25,
        inInitialViewport: false,
      }
    })
    return nextPositions
  }

  const usedCells = new Set(Object.values(existingPositions).map(({ q, r }) => `${q}:${r}`))
  let requestedCount = usedCells.size + orderedWishes.length
  let availableCells = []
  while (availableCells.length < orderedWishes.length) {
    availableCells = generateDesktopHoneycombCells(
      requestedCount,
      normalizedSize,
      rootSize,
      sessionSeed
    ).filter(({ q, r }) => !usedCells.has(`${q}:${r}`))
    requestedCount += orderedWishes.length
  }
  orderedWishes.forEach((wish, index) => {
    nextPositions[wish.id] = { ...availableCells[index] }
  })
  return nextPositions
}
