import { describe, expect, it } from 'vitest'
import {
  WISH_BUBBLE_CONSTANTS,
  applySoftCenterAttraction,
  beginRadiusTransition,
  capBubbleSpeed,
  clampPhysicsDelta,
  createInitialBubbleLayout,
  getWishBubbleDiameter,
  resolveBubbleCollision,
  stepBubblePhysics,
  updateBubbleRadius,
} from '@/utils/wishBubblePhysics'

const wish = (id, heartCount) => ({ id, heart_count: heartCount, title: `Wish ${id}` })

describe('wish bubble sizing', () => {
  it('is bounded, monotonic, concave, and stable for representative heart counts', () => {
    const counts = [0, 1, 10, 100, 100_000_000]
    const sizes = counts.map(getWishBubbleDiameter)

    expect(sizes[0]).toBe(WISH_BUBBLE_CONSTANTS.minDiameter)
    expect(sizes).toEqual([...sizes].sort((left, right) => left - right))
    expect(sizes.at(-1)).toBe(WISH_BUBBLE_CONSTANTS.maxDiameter)
    expect(getWishBubbleDiameter(10) - getWishBubbleDiameter(0)).toBeGreaterThan(
      getWishBubbleDiameter(20) - getWishBubbleDiameter(10)
    )
    expect(getWishBubbleDiameter(10)).toBe(getWishBubbleDiameter(10))
    expect(getWishBubbleDiameter(-5)).toBe(WISH_BUBBLE_CONSTANTS.minDiameter)
  })
})

describe('wish bubble initial placement', () => {
  const wishes = [wish(1, 120), wish(2, 40), wish(3, 15), wish(4, 5), wish(5, 0)]

  it('is deterministic, avoids initial overlap, and keeps a reasonable set in view', () => {
    const first = createInitialBubbleLayout(wishes, { width: 1100, height: 680 })
    const second = createInitialBubbleLayout(wishes, { width: 1100, height: 680 })

    expect(first).toEqual(second)
    for (const bubble of first) {
      expect(Math.abs(bubble.x) + bubble.radius).toBeLessThanOrEqual(1100 / 2)
      expect(Math.abs(bubble.y) + bubble.radius).toBeLessThanOrEqual(680 / 2)
    }
    for (let leftIndex = 0; leftIndex < first.length; leftIndex += 1) {
      for (let rightIndex = leftIndex + 1; rightIndex < first.length; rightIndex += 1) {
        const left = first[leftIndex]
        const right = first[rightIndex]
        expect(Math.hypot(left.x - right.x, left.y - right.y)).toBeGreaterThanOrEqual(
          left.radius + right.radius
        )
      }
    }
  })

  it('places higher-heart wishes closer to the center before overflow extends the world', () => {
    const manyWishes = Array.from({ length: 36 }, (_, index) => wish(index + 1, 360 - index * 10))
    const layout = createInitialBubbleLayout(manyWishes, { width: 480, height: 360 })
    const distance = (bubble) => Math.hypot(bubble.x, bubble.y)
    const highHeartAverage =
      layout.slice(0, 6).reduce((sum, bubble) => sum + distance(bubble), 0) / 6
    const lowHeartAverage = layout.slice(-6).reduce((sum, bubble) => sum + distance(bubble), 0) / 6

    expect(highHeartAverage).toBeLessThan(lowHeartAverage)
  })
})

describe('wish bubble physics', () => {
  const bubble = (overrides = {}) => ({
    id: 1,
    x: 0,
    y: 0,
    vx: 0,
    vy: 0,
    radius: 50,
    targetRadius: 50,
    radiusTransition: null,
    mass: 2500,
    driftAngle: 0,
    ...overrides,
  })

  it('resolves overlap and gives the smaller mass the larger velocity change', () => {
    const small = bubble({ id: 1, x: 0, vx: 8, radius: 30, targetRadius: 30, mass: 900 })
    const large = bubble({ id: 2, x: 70, vx: -1, radius: 60, targetRadius: 60, mass: 3600 })
    const smallBefore = small.vx
    const largeBefore = large.vx

    expect(resolveBubbleCollision(small, large)).toBe(true)
    expect(Math.hypot(small.x - large.x, small.y - large.y)).toBeGreaterThanOrEqual(89.9)
    expect(Math.abs(small.vx - smallBefore)).toBeGreaterThan(Math.abs(large.vx - largeBefore))
    expect(small.vx).toBeLessThan(smallBefore)
  })

  it('caps speed, clamps extreme delta, and attracts distant bubbles toward the center', () => {
    const fast = bubble({ x: 1000, vx: 100, vy: 0 })
    capBubbleSpeed(fast)
    expect(Math.hypot(fast.vx, fast.vy)).toBeCloseTo(WISH_BUBBLE_CONSTANTS.maxSpeed)

    const beforeVx = fast.vx
    applySoftCenterAttraction(fast, 1)
    expect(fast.vx).toBeLessThan(beforeVx)
    expect(clampPhysicsDelta(5)).toBe(WISH_BUBBLE_CONSTANTS.maxDeltaSeconds)
    expect(clampPhysicsDelta(-1)).toBe(0)
  })

  it('uses one collection step and keeps every bubble within the speed cap', () => {
    const bubbles = [
      bubble({ id: 1, x: -30, vx: 80 }),
      bubble({ id: 2, x: 30, vx: -80, driftAngle: Math.PI }),
    ]

    expect(stepBubblePhysics(bubbles, 10)).toBe(bubbles)
    for (const item of bubbles) {
      expect(Math.hypot(item.vx, item.vy)).toBeLessThanOrEqual(WISH_BUBBLE_CONSTANTS.maxSpeed)
    }
  })

  it('keeps the collision radius synchronized with the bounded visual transition', () => {
    const item = bubble()
    expect(beginRadiusTransition(item, 80, 1000)).toBe(true)
    updateBubbleRadius(item, 1160)
    expect(item.radius).toBeCloseTo(65)
    expect(item.mass).toBeCloseTo(65 * 65)
    updateBubbleRadius(item, 1320)
    expect(item.radius).toBe(80)
    expect(item.radiusTransition).toBeNull()
  })
})
