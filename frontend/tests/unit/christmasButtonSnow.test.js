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

describe('Christmas button snow redundant-work and lifecycle contracts', () => {
  const engines = []

  function createEngine(root, options = {}) {
    const engine = createChristmasButtonSnowEngine({
      root,
      seedFactory: () => 42,
      matchMedia: createMediaMatcher(),
      ...options,
    })
    engines.push(engine)
    return engine
  }

  function measureButton(button) {
    const rect = vi
      .spyOn(button, 'getBoundingClientRect')
      .mockReturnValue({ width: 100, height: 32 })
    const styles = vi.spyOn(globalThis, 'getComputedStyle')
    return { rect, styles }
  }

  afterEach(() => {
    engines.splice(0).forEach((engine) => engine.stop())
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('reads one current rect for both hidden and tiny eligibility checks', () => {
    const button = mountRoot('<button>Semester</button>').querySelector('button')
    const { rect, styles } = measureButton(button)

    expect(isEligibleChristmasSnowButton(button)).toBe(true)
    expect(styles).toHaveBeenCalledOnce()
    expect(rect).toHaveBeenCalledOnce()
  })

  it('rescans an already-owned moved subtree without reading style or geometry again', async () => {
    const root = mountRoot('<button>Semester</button>')
    const button = root.querySelector('button')
    const { rect, styles } = measureButton(button)
    const seedFactory = vi.fn(() => 42)
    const engine = createEngine(root, { seedFactory })
    engine.start()
    const before = button.outerHTML
    rect.mockClear()
    styles.mockClear()

    const container = document.createElement('section')
    root.appendChild(container)
    container.appendChild(button)
    await flushMutationObserver()

    expect(button.outerHTML).toBe(before)
    expect(engine.getDebugState().decoratedButtonCount).toBe(1)
    expect(seedFactory).toHaveBeenCalledOnce()
    expect(styles).not.toHaveBeenCalled()
    expect(rect).not.toHaveBeenCalled()
  })

  it('still reads fresh hover geometry once and does not reuse an old eligibility result', () => {
    const root = mountRoot('<button>Semester</button>')
    const button = root.querySelector('button')
    const { rect, styles } = measureButton(button)
    const engine = createEngine(root)
    engine.start()
    rect.mockClear()
    styles.mockClear()

    rect.mockReturnValue({ width: 8, height: 8 })
    dispatchPointerEnter(button)
    expect(engine.getDebugState().activeParticleCount).toBe(0)
    expect(rect).toHaveBeenCalledOnce()
    expect(styles).toHaveBeenCalledOnce()

    rect.mockClear()
    rect.mockReturnValue({ width: 100, height: 32 })
    dispatchPointerEnter(button)
    expect(rect).toHaveBeenCalledOnce()
    expect(engine.getDebugState().activeParticleCount).toBeGreaterThanOrEqual(2)
  })

  it.each([
    ['non-control', '<div id="target">Text</div>'],
    ['opt-out', '<button id="target" data-christmas-snow="off">No snow</button>'],
    ['excluded owner', '<div class="p-checkbox"><button id="target">Check</button></div>'],
    ['hidden', '<button id="target" hidden>Hidden</button>'],
    ['hidden ancestor', '<div hidden><button id="target">Hidden</button></div>'],
    ['inert ancestor', '<div inert><button id="target">Inert</button></div>'],
    ['ARIA hidden', '<button id="target" aria-hidden="true">Hidden</button>'],
  ])('rejects %s before computed style or rect reads', (_name, markup) => {
    const button = mountRoot(markup).querySelector('#target')
    const { rect, styles } = measureButton(button)
    expect(isEligibleChristmasSnowButton(button)).toBe(false)
    expect(styles).not.toHaveBeenCalled()
    expect(rect).not.toHaveBeenCalled()
  })

  it.each([
    ['display none', 'none', 'visible', '100px', '32px', 100, 32, false, 0],
    ['visibility hidden', 'block', 'hidden', '100px', '32px', 100, 32, false, 0],
    ['explicit zero box', 'block', 'visible', '0px', '0px', 0, 0, false, 1],
    ['unmeasured auto box', 'block', 'visible', 'auto', 'auto', 0, 0, true, 1],
    ['tiny action', 'block', 'visible', '15px', '15px', 15, 15, false, 1],
    ['width boundary', 'block', 'visible', '16px', '15px', 16, 15, true, 1],
    ['height boundary', 'block', 'visible', '15px', '16px', 15, 16, true, 1],
    ['one zero dimension', 'block', 'visible', '0px', '15px', 0, 15, true, 1],
  ])(
    'preserves geometry semantics for %s',
    (_name, display, visibility, width, height, rectWidth, rectHeight, eligible, reads) => {
      const button = mountRoot('<button>Action</button>').querySelector('button')
      const { rect, styles } = measureButton(button)
      styles.mockReturnValue({ display, visibility, width, height })
      rect.mockReturnValue({ width: rectWidth, height: rectHeight })
      expect(isEligibleChristmasSnowButton(button)).toBe(eligible)
      expect(rect).toHaveBeenCalledTimes(reads)
    }
  )

  it('still rejects tiny controls when computed style is unavailable', () => {
    const button = mountRoot('<button>Tiny</button>').querySelector('button')
    const { rect } = measureButton(button)
    vi.stubGlobal('getComputedStyle', undefined)
    rect.mockReturnValue({ width: 8, height: 8 })
    expect(isEligibleChristmasSnowButton(button)).toBe(false)
    rect.mockReturnValue({ width: 100, height: 32 })
    expect(isEligibleChristmasSnowButton(button)).toBe(true)
  })

  it.each(['hidden', 'display', 'visibility'])(
    'can decorate initially %s controls after they become visible',
    async (kind) => {
      const root = mountRoot('<button>Initially hidden</button>')
      const button = root.querySelector('button')
      if (kind === 'hidden') button.hidden = true
      else button.style[kind] = kind === 'display' ? 'none' : 'hidden'
      const engine = createEngine(root)
      engine.start()
      expect(button.dataset.christmasButtonSnow).toBeUndefined()

      if (kind === 'hidden') button.hidden = false
      else button.style.removeProperty(kind)
      await flushMutationObserver()
      // Attribute-only visibility changes remain outside the childList observer.
      expect(button.dataset.christmasButtonSnow).toBeUndefined()
      dispatchPointerEnter(button)
      expect(button.dataset.christmasButtonSnow).toBe('true')
      expect(engine.getDebugState().activeParticleCount).toBeGreaterThanOrEqual(2)
    }
  )

  it.each([
    [
      'disabled',
      (button, _root, blocked) => {
        button.disabled = blocked
      },
    ],
    [
      'ARIA disabled',
      (button, _root, blocked) => {
        button.setAttribute('aria-disabled', String(blocked))
      },
    ],
    [
      'hidden',
      (button, _root, blocked) => {
        button.hidden = blocked
      },
    ],
    [
      'display',
      (button, _root, blocked) => {
        button.style.display = blocked ? 'none' : ''
      },
    ],
    [
      'visibility',
      (button, _root, blocked) => {
        button.style.visibility = blocked ? 'hidden' : ''
      },
    ],
    [
      'opt-out',
      (button, _root, blocked) => {
        button.setAttribute('data-christmas-snow', blocked ? 'off' : 'on')
      },
    ],
    [
      'excluded owner',
      (_button, root, blocked) => {
        root.classList.toggle('p-checkbox', blocked)
      },
    ],
  ])('preserves dynamic %s checks for already-decorated hover', (_name, change) => {
    const root = mountRoot('<button>Dynamic action</button>')
    const button = root.querySelector('button')
    const engine = createEngine(root)
    engine.start()
    const pattern = button.dataset.christmasSnowPattern
    change(button, root, true)
    dispatchPointerEnter(button)
    expect(engine.getDebugState().activeParticleCount).toBe(0)
    expect(button.dataset.christmasSnowPattern).toBe(pattern)
    change(button, root, false)
    dispatchPointerEnter(button)
    expect(engine.getDebugState().activeParticleCount).toBeGreaterThanOrEqual(2)
  })

  it('retains full eligibility for direct decoration calls, not just pointer entry', () => {
    const root = mountRoot('<button>Action</button>')
    const button = root.querySelector('button')
    const engine = createEngine(root)
    engine.start()
    button.hidden = true
    expect(engine.decorateButton(button)).toBeNull()
    button.hidden = false
    button.setAttribute('data-christmas-snow', 'off')
    expect(engine.decorateButton(button)).toBeNull()
    button.removeAttribute('data-christmas-snow')
    expect(engine.decorateButton(button)).toEqual(generateSnowPattern(42))
  })

  it('already suppresses nested-child pointer movement but allows genuine re-entry', () => {
    const root = mountRoot(
      '<button><span>Semester</span><i class="pi pi-angle-down"></i></button><div id="outside"></div>'
    )
    const button = root.querySelector('button')
    const label = button.querySelector('span')
    const icon = button.querySelector('i')
    const outside = root.querySelector('#outside')
    const { rect, styles } = measureButton(button)
    const seedFactory = vi.fn(() => 42)
    const engine = createEngine(root, { seedFactory })
    engine.start()
    dispatchPointerEnter(label, outside)
    const initialParticles = [...button.querySelectorAll('.christmas-button-snow-particle')]
    expect(initialParticles.length).toBeGreaterThanOrEqual(2)
    expect(seedFactory).toHaveBeenCalledTimes(2)
    rect.mockClear()
    styles.mockClear()
    dispatchPointerEnter(icon, label)
    dispatchPointerEnter(label, icon)
    expect([...button.querySelectorAll('.christmas-button-snow-particle')]).toEqual(
      initialParticles
    )
    expect(rect).not.toHaveBeenCalled()
    expect(styles).not.toHaveBeenCalled()
    expect(seedFactory).toHaveBeenCalledTimes(2)
    dispatchPointerEnter(outside, label)
    dispatchPointerEnter(icon, outside)
    expect(seedFactory).toHaveBeenCalledTimes(3)
    expect(engine.getDebugState().activeParticleCount).toBe(
      Math.min(initialParticles.length * 2, 8)
    )
  })

  it('does not mistake v-show styles or non-control toggle-icon replacement for a button rescan', async () => {
    const root = mountRoot(
      '<button>Semester<svg></svg></button><section><button>Preview</button></section>'
    )
    const header = root.querySelector('button')
    const content = root.querySelector('section')
    const { rect, styles } = measureButton(header)
    const engine = createEngine(root)
    engine.start()
    rect.mockClear()
    styles.mockClear()
    content.style.display = 'none'
    content.style.display = ''
    header
      .querySelector('svg')
      .replaceWith(document.createElementNS('http://www.w3.org/2000/svg', 'svg'))
    await flushMutationObserver()
    expect(engine.getDebugState().decoratedButtonCount).toBe(2)
    expect(styles).not.toHaveBeenCalled()
    expect(rect).not.toHaveBeenCalled()
  })

  it('decorates body-level dialog subtrees and releases removed/reinserted controls', async () => {
    const app = mountRoot('<button>App action</button>')
    let seed = 100
    const engine = createEngine(document.body, { seedFactory: () => seed++ })
    engine.start()
    const portal = mountRoot('<div role="dialog"><button>Dialog save</button></div>')
    const button = portal.querySelector('button')
    await flushMutationObserver()
    expect(app.contains(button)).toBe(false)
    expect(button.dataset.christmasButtonSnow).toBe('true')
    const firstPattern = button.dataset.christmasSnowPattern
    dispatchPointerEnter(button)
    expect(engine.getDebugState().activeParticleCount).toBeGreaterThanOrEqual(2)
    portal.remove()
    await flushMutationObserver()
    expect(engine.getDebugState().decoratedButtonCount).toBe(1)
    expect(engine.getDebugState().activeParticleCount).toBe(0)
    expect(button.dataset.christmasButtonSnow).toBeUndefined()
    document.body.appendChild(portal)
    await flushMutationObserver()
    expect(button.dataset.christmasButtonSnow).toBe('true')
    expect(button.dataset.christmasSnowPattern).not.toBe(firstPattern)
  })

  it('keeps deterministic particle styles, duration ranges, the cap and animation cleanup', () => {
    function burst() {
      const root = mountRoot('<button>Save</button>')
      const button = root.querySelector('button')
      let seed = 300
      const engine = createEngine(root, { seedFactory: () => seed++ })
      engine.start()
      dispatchPointerEnter(button)
      const particles = [...button.querySelectorAll('.christmas-button-snow-particle')]
      const styles = particles.map((particle) => particle.getAttribute('style'))
      expect(particles.length).toBeGreaterThanOrEqual(2)
      expect(particles.length).toBeLessThanOrEqual(5)
      for (const particle of particles) {
        const duration = parseFloat(
          particle.style.getPropertyValue('--christmas-particle-duration')
        )
        const delay = parseFloat(particle.style.getPropertyValue('--christmas-particle-delay'))
        expect(duration).toBeGreaterThanOrEqual(350)
        expect(duration).toBeLessThanOrEqual(850)
        expect(delay).toBeGreaterThanOrEqual(0)
        expect(delay).toBeLessThanOrEqual(70)
      }
      for (let i = 0; i < 20; i += 1) dispatchPointerEnter(button)
      expect(engine.getDebugState().activeParticleCount).toBe(8)
      ;[...button.querySelectorAll('.christmas-button-snow-particle')].forEach(
        (particle, index) => {
          particle.dispatchEvent(new Event(index % 2 ? 'animationcancel' : 'animationend'))
        }
      )
      expect(engine.getDebugState().activeParticleCount).toBe(0)
      return styles
    }
    expect(burst()).toEqual(burst())
  })

  it('rechecks changing fine-pointer and reduced-motion settings without removing static snow', () => {
    const root = mountRoot('<button>Save</button>')
    const button = root.querySelector('button')
    const matchMedia = createMediaMatcher()
    const engine = createEngine(root, { matchMedia })
    engine.start()
    for (const media of [{ finePointer: false }, { reducedMotion: true }]) {
      matchMedia.mockImplementation(createMediaMatcher(media))
      dispatchPointerEnter(button)
      expect(engine.getDebugState().activeParticleCount).toBe(0)
      expect(button.dataset.christmasButtonSnow).toBe('true')
    }
    matchMedia.mockImplementation(createMediaMatcher())
    dispatchPointerEnter(button)
    expect(engine.getDebugState().activeParticleCount).toBeGreaterThanOrEqual(2)
  })

  it('restores owned state, removes listeners/observer/particles and retains unrelated style changes', async () => {
    const root = mountRoot(
      '<button data-christmas-button-snow="prior" data-christmas-snow-pattern="original" style="--christmas-snow-depth: 0.7rem !important; color: red">Save</button>'
    )
    const button = root.querySelector('button')
    const disconnect = vi.spyOn(MutationObserver.prototype, 'disconnect')
    const removeListener = vi.spyOn(root, 'removeEventListener')
    const engine = createEngine(root)
    engine.start()
    dispatchPointerEnter(button)
    const activePattern = button.dataset.christmasSnowPattern
    button.style.color = 'blue'
    engine.stop()
    expect(disconnect).toHaveBeenCalledOnce()
    expect(removeListener).toHaveBeenCalledWith('pointerover', expect.any(Function))
    expect(engine.getDebugState()).toEqual({
      active: false,
      observerCount: 0,
      decoratedButtonCount: 0,
      activeParticleCount: 0,
    })
    expect(button.style.getPropertyValue('--christmas-snow-depth')).toBe('0.7rem')
    expect(button.style.getPropertyPriority('--christmas-snow-depth')).toBe('important')
    expect(button.style.color).toBe('blue')
    expect(button.dataset.christmasButtonSnow).toBe('prior')
    expect(button.dataset.christmasSnowPattern).toBe('original')
    expect(button.querySelector('.christmas-button-snow-particle')).toBeNull()
    root.appendChild(document.createElement('button'))
    dispatchPointerEnter(button)
    await flushMutationObserver()
    expect(engine.getDebugState().activeParticleCount).toBe(0)
    expect(engine.getDebugState().decoratedButtonCount).toBe(0)
    engine.start()
    expect(button.dataset.christmasSnowPattern).toBe(activePattern)
  })
})
