export const WISH_BUBBLE_CONSTANTS = Object.freeze({
  minDiameter: 116,
  baseDiameter: 116,
  diameterGrowth: 18,
  maxDiameter: 220,
  gap: 12,
  minSpeed: 4,
  maxSpeed: 14,
  restitution: 0.7,
  dampingPerSecond: 0.995,
  centerAttraction: 0.00045,
  maxCenterAcceleration: 0.08,
  maxDeltaSeconds: 1 / 30,
  radiusTransitionMs: 320,
})

const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5))
const PLACEMENT_ATTEMPTS = 5000

const clamp = (value, minimum, maximum) => Math.min(maximum, Math.max(minimum, value))

export function normalizeHeartCount(value) {
  const count = Number(value)
  return Number.isFinite(count) ? Math.max(0, count) : 0
}

export function getWishBubbleDiameter(heartCount) {
  const { minDiameter, baseDiameter, diameterGrowth, maxDiameter } = WISH_BUBBLE_CONSTANTS
  return clamp(
    baseDiameter + diameterGrowth * Math.log1p(normalizeHeartCount(heartCount)),
    minDiameter,
    maxDiameter
  )
}

export function stableWishHash(value) {
  let hash = 2166136261
  for (const character of String(value)) {
    hash ^= character.charCodeAt(0)
    hash = Math.imul(hash, 16777619)
  }
  return hash >>> 0
}

function deterministicFraction(hash, shift = 0) {
  return ((hash >>> shift) & 0xffff) / 0xffff
}

function overlapsPlacedBubble(candidate, placed, gap) {
  return placed.some((bubble) => {
    const minimumDistance = candidate.radius + bubble.radius + gap
    return Math.hypot(candidate.x - bubble.x, candidate.y - bubble.y) < minimumDistance
  })
}

function insideViewport(candidate, width, height, gap) {
  return (
    Math.abs(candidate.x) + candidate.radius + gap <= width / 2 &&
    Math.abs(candidate.y) + candidate.radius + gap <= height / 2
  )
}

function candidateAt(wish, radius, attempt, viewportRatio) {
  const hash = stableWishHash(wish.id)
  const startAngle = deterministicFraction(hash) * Math.PI * 2
  const angle = startAngle + attempt * GOLDEN_ANGLE
  const distance = 5.5 * Math.sqrt(attempt)
  const jitter = (deterministicFraction(hash, 8) - 0.5) * 8
  return {
    x: Math.cos(angle) * (distance + jitter) * viewportRatio,
    y: Math.sin(angle) * (distance + jitter),
    radius,
  }
}

function initialVelocity(id) {
  const hash = stableWishHash(id)
  const angle = deterministicFraction(hash) * Math.PI * 2
  const speed = 5 + deterministicFraction(hash, 12) * 6
  return {
    vx: Math.cos(angle) * speed,
    vy: Math.sin(angle) * speed,
    driftAngle: angle,
  }
}

export function createInitialBubbleLayout(wishes, viewport = {}) {
  const width = Math.max(280, Number(viewport.width) || 960)
  const height = Math.max(280, Number(viewport.height) || 620)
  const gap = Number(viewport.gap) || WISH_BUBBLE_CONSTANTS.gap
  const ordered = [...wishes].sort(
    (left, right) =>
      normalizeHeartCount(right.heart_count) - normalizeHeartCount(left.heart_count) ||
      String(left.id).localeCompare(String(right.id), undefined, { numeric: true })
  )
  const totalBubbleArea = ordered.reduce((sum, wish) => {
    const radius = getWishBubbleDiameter(wish.heart_count) / 2
    return sum + Math.PI * radius * radius
  }, 0)
  const fitInsideViewport = totalBubbleArea * 1.75 <= width * height
  const viewportRatio = clamp(width / height, 0.8, 1.65)
  const placed = []

  for (const wish of ordered) {
    const radius = getWishBubbleDiameter(wish.heart_count) / 2
    let position = null
    for (let attempt = 0; attempt < PLACEMENT_ATTEMPTS; attempt += 1) {
      const candidate = candidateAt(wish, radius, attempt, viewportRatio)
      if (fitInsideViewport && !insideViewport(candidate, width, height, gap)) continue
      if (!overlapsPlacedBubble(candidate, placed, gap)) {
        position = candidate
        break
      }
    }
    if (!position) {
      for (let attempt = PLACEMENT_ATTEMPTS; attempt < PLACEMENT_ATTEMPTS * 3; attempt += 1) {
        const candidate = candidateAt(wish, radius, attempt, viewportRatio)
        if (!overlapsPlacedBubble(candidate, placed, gap)) {
          position = candidate
          break
        }
      }
    }
    position ||= { x: placed.length * (radius * 2 + gap), y: 0, radius }
    const velocity = initialVelocity(wish.id)
    placed.push({
      id: wish.id,
      ...position,
      targetRadius: radius,
      radiusTransition: null,
      mass: radius * radius,
      ...velocity,
    })
  }

  return placed
}

export function clampPhysicsDelta(deltaSeconds) {
  const numericDelta = Number(deltaSeconds)
  if (!Number.isFinite(numericDelta) || numericDelta <= 0) return 0
  return Math.min(numericDelta, WISH_BUBBLE_CONSTANTS.maxDeltaSeconds)
}

export function capBubbleSpeed(bubble, maximum = WISH_BUBBLE_CONSTANTS.maxSpeed) {
  const speed = Math.hypot(bubble.vx, bubble.vy)
  if (speed <= maximum || speed === 0) return bubble
  const scale = maximum / speed
  bubble.vx *= scale
  bubble.vy *= scale
  return bubble
}

export function applySoftCenterAttraction(bubble, deltaSeconds) {
  const distance = Math.hypot(bubble.x, bubble.y)
  if (distance === 0 || deltaSeconds <= 0) return bubble
  const acceleration = Math.min(
    distance * WISH_BUBBLE_CONSTANTS.centerAttraction,
    WISH_BUBBLE_CONSTANTS.maxCenterAcceleration
  )
  bubble.vx -= (bubble.x / distance) * acceleration * deltaSeconds
  bubble.vy -= (bubble.y / distance) * acceleration * deltaSeconds
  return bubble
}

function maintainDrift(bubble, deltaSeconds) {
  const speed = Math.hypot(bubble.vx, bubble.vy)
  if (speed >= WISH_BUBBLE_CONSTANTS.minSpeed) return
  const targetVx = Math.cos(bubble.driftAngle) * WISH_BUBBLE_CONSTANTS.minSpeed
  const targetVy = Math.sin(bubble.driftAngle) * WISH_BUBBLE_CONSTANTS.minSpeed
  const blend = Math.min(1, deltaSeconds * 0.35)
  bubble.vx += (targetVx - bubble.vx) * blend
  bubble.vy += (targetVy - bubble.vy) * blend
}

export function resolveBubbleCollision(left, right) {
  const dx = right.x - left.x
  const dy = right.y - left.y
  const distance = Math.hypot(dx, dy) || 0.0001
  const minimumDistance = left.radius + right.radius
  if (distance >= minimumDistance) return false

  const nx = dx / distance
  const ny = dy / distance
  const inverseLeftMass = 1 / Math.max(1, left.mass)
  const inverseRightMass = 1 / Math.max(1, right.mass)
  const inverseMassTotal = inverseLeftMass + inverseRightMass
  const overlap = minimumDistance - distance
  const correction = Math.max(0, overlap - 0.1) / inverseMassTotal

  left.x -= nx * correction * inverseLeftMass
  left.y -= ny * correction * inverseLeftMass
  right.x += nx * correction * inverseRightMass
  right.y += ny * correction * inverseRightMass

  const relativeVx = right.vx - left.vx
  const relativeVy = right.vy - left.vy
  const normalVelocity = relativeVx * nx + relativeVy * ny
  if (normalVelocity < 0) {
    const impulse = (-(1 + WISH_BUBBLE_CONSTANTS.restitution) * normalVelocity) / inverseMassTotal
    left.vx -= impulse * inverseLeftMass * nx
    left.vy -= impulse * inverseLeftMass * ny
    right.vx += impulse * inverseRightMass * nx
    right.vy += impulse * inverseRightMass * ny
    capBubbleSpeed(left)
    capBubbleSpeed(right)
  }
  return true
}

export function createCollisionPairs(bubbles) {
  const cellSize = WISH_BUBBLE_CONSTANTS.maxDiameter + WISH_BUBBLE_CONSTANTS.gap
  const grid = new Map()
  const pairs = []
  const pairKeys = new Set()

  bubbles.forEach((bubble, index) => {
    const cellX = Math.floor(bubble.x / cellSize)
    const cellY = Math.floor(bubble.y / cellSize)
    const key = `${cellX}:${cellY}`
    if (!grid.has(key)) grid.set(key, [])
    grid.get(key).push(index)
  })

  for (const [key, indexes] of grid) {
    const [cellX, cellY] = key.split(':').map(Number)
    for (let offsetX = -1; offsetX <= 1; offsetX += 1) {
      for (let offsetY = -1; offsetY <= 1; offsetY += 1) {
        const neighbors = grid.get(`${cellX + offsetX}:${cellY + offsetY}`) || []
        for (const leftIndex of indexes) {
          for (const rightIndex of neighbors) {
            if (leftIndex >= rightIndex) continue
            const pairKey = `${leftIndex}:${rightIndex}`
            if (pairKeys.has(pairKey)) continue
            pairKeys.add(pairKey)
            pairs.push([bubbles[leftIndex], bubbles[rightIndex]])
          }
        }
      }
    }
  }

  return pairs
}

export function stepBubblePhysics(bubbles, rawDeltaSeconds) {
  const deltaSeconds = clampPhysicsDelta(rawDeltaSeconds)
  if (!deltaSeconds) return bubbles
  const damping = Math.pow(WISH_BUBBLE_CONSTANTS.dampingPerSecond, deltaSeconds)

  for (const bubble of bubbles) {
    applySoftCenterAttraction(bubble, deltaSeconds)
    bubble.vx *= damping
    bubble.vy *= damping
    maintainDrift(bubble, deltaSeconds)
    capBubbleSpeed(bubble)
    bubble.x += bubble.vx * deltaSeconds
    bubble.y += bubble.vy * deltaSeconds
  }
  for (const [left, right] of createCollisionPairs(bubbles)) {
    resolveBubbleCollision(left, right)
  }
  return bubbles
}

export function beginRadiusTransition(bubble, nextRadius, startedAt) {
  const targetRadius = Math.max(WISH_BUBBLE_CONSTANTS.minDiameter / 2, Number(nextRadius))
  if (Math.abs(targetRadius - bubble.targetRadius) < 0.001) return false
  bubble.radiusTransition = {
    from: bubble.radius,
    to: targetRadius,
    startedAt,
  }
  bubble.targetRadius = targetRadius
  return true
}

export function updateBubbleRadius(bubble, timestamp) {
  const transition = bubble.radiusTransition
  if (!transition) return false
  const progress = clamp(
    (timestamp - transition.startedAt) / WISH_BUBBLE_CONSTANTS.radiusTransitionMs,
    0,
    1
  )
  bubble.radius = transition.from + (transition.to - transition.from) * progress
  bubble.mass = bubble.radius * bubble.radius
  if (progress >= 1) bubble.radiusTransition = null
  return true
}
