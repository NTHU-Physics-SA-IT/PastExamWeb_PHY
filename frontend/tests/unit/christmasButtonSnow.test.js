import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  createChristmasButtonSnowEngine,
  generateSnowPattern,
  isEligibleChristmasSnowButton,
} from '@/utils/christmasButtonSnow'

const mountedRoots = []

function mountRoot(markup = '') {
  const root = document.createElement('div')
  root.innerHTML = markup
  document.body.appendChild(root)
  mountedRoots.push(root)
  return root
}

function createMediaMatcher({ finePointer = true, reducedMotion = false } = {}) {
  return vi.fn((query) => ({
    matches:
      (query === '(hover: hover) and (pointer: fine)' && finePointer) ||
      (query === '(prefers-reduced-motion: reduce)' && reducedMotion),
    media: query,
  }))
}

function dispatchPointerEnter(button, relatedTarget = null) {
  const event = new Event('pointerover', { bubbles: true })
  Object.defineProperty(event, 'relatedTarget', { value: relatedTarget })
  button.dispatchEvent(event)
}

async function flushMutationObserver() {
  await Promise.resolve()
  await new Promise((resolve) => setTimeout(resolve, 0))
}

afterEach(() => {
  mountedRoots.splice(0).forEach((root) => root.remove())
})

describe('Christmas button snow pattern generator', () => {
  it('is deterministic for the same seed and varies for a different seed', () => {
    expect(generateSnowPattern(20261225)).toEqual(generateSnowPattern(20261225))
    expect(generateSnowPattern(20261225)).not.toEqual(generateSnowPattern(20261226))
  })

  it.each([0, 1, 42, 0xffffffff])('keeps every generated value finite and bounded', (seed) => {
    const pattern = generateSnowPattern(seed)

    expect(pattern.depth).toBeGreaterThanOrEqual(0.24)
    expect(pattern.depth).toBeLessThanOrEqual(0.42)
    expect(pattern.edgeOffset).toBeGreaterThanOrEqual(-0.06)
    expect(pattern.edgeOffset).toBeLessThanOrEqual(0.06)
    expect(pattern.dropBias).toBeGreaterThanOrEqual(0.15)
    expect(pattern.dropBias).toBeLessThanOrEqual(0.85)
    expect(pattern.mounds).toHaveLength(5)

    for (const mound of pattern.mounds) {
      expect(Number.isFinite(mound.x)).toBe(true)
      expect(Number.isFinite(mound.radius)).toBe(true)
      expect(Number.isFinite(mound.height)).toBe(true)
      expect(mound.x).toBeGreaterThanOrEqual(6)
      expect(mound.x).toBeLessThanOrEqual(94)
      expect(mound.radius).toBeGreaterThanOrEqual(14)
      expect(mound.radius).toBeLessThanOrEqual(34)
      expect(mound.height).toBeGreaterThanOrEqual(62)
      expect(mound.height).toBeLessThanOrEqual(100)
    }
  })
})

describe('Christmas button snow eligibility', () => {
  it('accepts action buttons and excludes pseudo controls or hidden controls', () => {
    const root = mountRoot(`
      <button id="action">Save</button>
      <button id="icon" class="p-button"><span class="pi pi-pencil"></span></button>
      <button id="loading" class="p-button p-button-loading" aria-busy="true">Loading</button>
      <button id="disabled" disabled>Disabled</button>
      <button id="switch" class="p-toggleswitch">Switch</button>
      <button id="hidden" hidden>Hidden</button>
      <div id="role" role="button">Pseudo</div>
      <div id="opt-in" data-christmas-snow-control="true">Select trigger</div>
    `)

    expect(isEligibleChristmasSnowButton(root.querySelector('#action'))).toBe(true)
    expect(isEligibleChristmasSnowButton(root.querySelector('#icon'))).toBe(true)
    expect(isEligibleChristmasSnowButton(root.querySelector('#loading'))).toBe(true)
    expect(isEligibleChristmasSnowButton(root.querySelector('#disabled'))).toBe(true)
    expect(isEligibleChristmasSnowButton(root.querySelector('#switch'))).toBe(false)
    expect(isEligibleChristmasSnowButton(root.querySelector('#hidden'))).toBe(false)
    expect(isEligibleChristmasSnowButton(root.querySelector('#role'))).toBe(false)
    expect(isEligibleChristmasSnowButton(root.querySelector('#opt-in'))).toBe(true)
  })

  it('excludes admin tabs, table headings, and paginator controls while retaining row action snow', () => {
    const root = mountRoot(`
      <main class="admin-container">
        <div class="p-tablist"><button id="admin-tab">Review center</button></div>
        <table>
          <thead class="p-datatable-thead">
            <tr><th><button id="sort-heading">Course</button></th></tr>
          </thead>
          <tbody><tr><td><button id="row-action">Review</button></td></tr></tbody>
        </table>
        <div class="p-paginator">
          <button id="page-first" class="p-paginator-first">First</button>
          <button id="page-prev" class="p-paginator-prev">Previous</button>
          <button id="page-number" class="p-paginator-page">1</button>
          <button id="page-next" class="p-paginator-next">Next</button>
          <button id="page-last" class="p-paginator-last">Last</button>
        </div>
      </main>
      <div class="p-tablist"><button id="non-admin-tab">Archive tab</button></div>
    `)

    expect(isEligibleChristmasSnowButton(root.querySelector('#admin-tab'))).toBe(false)
    expect(isEligibleChristmasSnowButton(root.querySelector('#sort-heading'))).toBe(false)
    expect(isEligibleChristmasSnowButton(root.querySelector('#page-first'))).toBe(false)
    expect(isEligibleChristmasSnowButton(root.querySelector('#page-prev'))).toBe(false)
    expect(isEligibleChristmasSnowButton(root.querySelector('#page-number'))).toBe(false)
    expect(isEligibleChristmasSnowButton(root.querySelector('#page-next'))).toBe(false)
    expect(isEligibleChristmasSnowButton(root.querySelector('#page-last'))).toBe(false)
    expect(isEligibleChristmasSnowButton(root.querySelector('#row-action'))).toBe(true)
    expect(isEligibleChristmasSnowButton(root.querySelector('#non-admin-tab'))).toBe(true)
  })
})

describe('Christmas button snow engine', () => {
  it('decorates existing buttons idempotently with stable, varied patterns and cleans up', () => {
    const root = mountRoot(`
      <button>Edit</button><button>Delete</button><button>Save</button>
      <button>Cancel</button><button>Confirm</button>
    `)
    let seed = 10
    const engine = createChristmasButtonSnowEngine({
      root,
      seedFactory: () => seed++,
      matchMedia: createMediaMatcher(),
    })

    engine.start()
    const buttons = [...root.querySelectorAll('button')]
    const fingerprints = buttons.map((button) => button.dataset.christmasSnowPattern)

    expect(buttons.every((button) => button.dataset.christmasButtonSnow === 'true')).toBe(true)
    expect(new Set(fingerprints).size).toBeGreaterThanOrEqual(4)
    engine.decorateButton(buttons[0])
    expect(buttons[0].dataset.christmasSnowPattern).toBe(fingerprints[0])

    engine.stop()
    expect(buttons.every((button) => button.dataset.christmasButtonSnow === undefined)).toBe(true)
    expect(buttons.every((button) => button.getAttribute('style') === null)).toBe(true)
  })

  it('covers shared admin actions without changing their box-model styles or handlers', () => {
    const root = mountRoot(`
      <button class="p-button">Edit</button><button class="p-button">Delete</button>
      <button class="p-button">Save</button><button class="p-button">Cancel</button>
      <button class="p-button">Confirm</button>
    `)
    const buttons = [...root.querySelectorAll('button')]
    const handlers = buttons.map(() => vi.fn())
    const keyboardHandler = vi.fn()
    buttons.forEach((button, index) => button.addEventListener('click', handlers[index]))
    buttons[0].addEventListener('keydown', keyboardHandler)
    let seed = 40
    const engine = createChristmasButtonSnowEngine({
      root,
      seedFactory: () => seed++,
      matchMedia: createMediaMatcher(),
    })

    engine.start()
    expect(buttons.every((button) => button.dataset.christmasButtonSnow === 'true')).toBe(true)
    expect(new Set(buttons.map((button) => button.dataset.christmasSnowPattern)).size).toBe(5)
    expect(
      buttons.every(
        (button) =>
          button.style.width === '' &&
          button.style.height === '' &&
          button.style.padding === '' &&
          button.style.margin === ''
      )
    ).toBe(true)

    buttons.forEach((button) => button.click())
    handlers.forEach((handler) => expect(handler).toHaveBeenCalledOnce())
    buttons[0].focus()
    buttons[0].dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    expect(document.activeElement).toBe(buttons[0])
    expect(keyboardHandler).toHaveBeenCalledOnce()
    engine.stop()
  })

  it('decorates dynamically inserted buttons with one observer and stops observing on cleanup', async () => {
    const root = mountRoot('<button>Existing</button>')
    const engine = createChristmasButtonSnowEngine({
      root,
      seedFactory: () => 99,
      matchMedia: createMediaMatcher(),
    })

    engine.start()
    expect(engine.getDebugState().observerCount).toBe(1)

    const dynamicButton = document.createElement('button')
    dynamicButton.textContent = 'Modal save'
    root.appendChild(dynamicButton)
    await flushMutationObserver()
    expect(dynamicButton.dataset.christmasButtonSnow).toBe('true')
    const originalPattern = dynamicButton.dataset.christmasSnowPattern

    const dynamicContainer = document.createElement('div')
    root.appendChild(dynamicContainer)
    dynamicContainer.appendChild(dynamicButton)
    await flushMutationObserver()
    expect(dynamicButton.dataset.christmasSnowPattern).toBe(originalPattern)

    dynamicButton.remove()
    await flushMutationObserver()
    expect(engine.getDebugState().decoratedButtonCount).toBe(1)

    engine.stop()
    expect(engine.getDebugState().observerCount).toBe(0)
    const afterStop = document.createElement('button')
    afterStop.textContent = 'After stop'
    root.appendChild(afterStop)
    await flushMutationObserver()
    expect(afterStop.dataset.christmasButtonSnow).toBeUndefined()
  })

  it('decorates an explicitly opted-in Select trigger and restores it on cleanup', () => {
    const root = mountRoot(
      '<div class="p-select-dropdown" data-christmas-snow-control="true">Select trigger</div>'
    )
    const trigger = root.querySelector('.p-select-dropdown')
    const engine = createChristmasButtonSnowEngine({
      root,
      seedFactory: () => 125,
      matchMedia: createMediaMatcher(),
    })

    engine.start()
    expect(trigger.dataset.christmasButtonSnow).toBe('true')
    expect(trigger.dataset.christmasSnowPattern).toBeTruthy()

    dispatchPointerEnter(trigger)
    expect(
      trigger.querySelectorAll('.christmas-button-snow-particle').length
    ).toBeGreaterThanOrEqual(2)

    engine.stop()
    expect(trigger.dataset.christmasButtonSnow).toBeUndefined()
    expect(trigger.dataset.christmasSnowControl).toBe('true')
    expect(trigger.querySelector('.christmas-button-snow-particle')).toBeNull()
  })

  it('creates two to five bounded hover particles without changing click behavior', () => {
    const root = mountRoot('<button>Save</button>')
    const button = root.querySelector('button')
    const clickHandler = vi.fn()
    button.addEventListener('click', clickHandler)
    let seed = 300
    const engine = createChristmasButtonSnowEngine({
      root,
      seedFactory: () => seed++,
      matchMedia: createMediaMatcher(),
    })

    engine.start()
    dispatchPointerEnter(button)
    const particles = button.querySelectorAll('.christmas-button-snow-particle')
    expect(particles.length).toBeGreaterThanOrEqual(2)
    expect(particles.length).toBeLessThanOrEqual(5)
    expect(
      [...particles].every((particle) => particle.getAttribute('aria-hidden') === 'true')
    ).toBe(true)

    for (let index = 0; index < 20; index += 1) dispatchPointerEnter(button)
    expect(button.querySelectorAll('.christmas-button-snow-particle').length).toBeLessThanOrEqual(8)

    button.click()
    expect(clickHandler).toHaveBeenCalledOnce()

    const firstParticle = button.querySelector('.christmas-button-snow-particle')
    firstParticle.dispatchEvent(new Event('animationend'))
    expect(firstParticle.isConnected).toBe(false)
    const cancelledParticle = button.querySelector('.christmas-button-snow-particle')
    cancelledParticle.dispatchEvent(new Event('animationcancel'))
    expect(cancelledParticle.isConnected).toBe(false)
    engine.stop()
  })

  it('keeps static snow but suppresses particles for disabled, touch, and reduced-motion cases', () => {
    const scenarios = [
      { markup: '<button disabled>Disabled</button>', media: createMediaMatcher() },
      { markup: '<button>Touch</button>', media: createMediaMatcher({ finePointer: false }) },
      {
        markup: '<button>Reduced</button>',
        media: createMediaMatcher({ reducedMotion: true }),
      },
    ]

    for (const scenario of scenarios) {
      const root = mountRoot(scenario.markup)
      const button = root.querySelector('button')
      const engine = createChristmasButtonSnowEngine({
        root,
        seedFactory: () => 7,
        matchMedia: scenario.media,
      })

      engine.start()
      expect(button.dataset.christmasButtonSnow).toBe('true')
      dispatchPointerEnter(button)
      expect(button.querySelector('.christmas-button-snow-particle')).toBeNull()
      engine.stop()
    }
  })
})
