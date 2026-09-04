const EXPLICIT_CONTROL_SELECTOR = '[data-christmas-snow-control="true"]'
const SNOW_CONTROL_SELECTOR = `button,${EXPLICIT_CONTROL_SELECTOR}`
const SNOW_ATTRIBUTE = 'data-christmas-button-snow'
const PATTERN_ATTRIBUTE = 'data-christmas-snow-pattern'
const PARTICLE_CLASS = 'christmas-button-snow-particle'
const FINE_POINTER_QUERY = '(hover: hover) and (pointer: fine)'
const REDUCED_MOTION_QUERY = '(prefers-reduced-motion: reduce)'
const MAX_ACTIVE_PARTICLES_PER_BUTTON = 8

const EXCLUDED_CONTROL_SELECTOR = [
  '.p-checkbox',
  '.p-radiobutton',
  '.p-toggleswitch',
  '.p-slider',
  '[role="checkbox"]',
  '[role="radio"]',
  '[role="switch"]',
  '[role="slider"]',
  '.admin-container .p-tablist',
  '.admin-container .p-datatable-thead',
  '.admin-container .p-paginator-first',
  '.admin-container .p-paginator-prev',
  '.admin-container .p-paginator-page',
  '.admin-container .p-paginator-next',
  '.admin-container .p-paginator-last',
  '[data-christmas-snow="off"]',
].join(',')

const OWNED_CUSTOM_PROPERTIES = [
  '--christmas-snow-depth',
  '--christmas-snow-edge-offset',
  '--christmas-snow-drop-bias',
  ...Array.from({ length: 5 }, (_, index) => [
    `--christmas-snow-x-${index + 1}`,
    `--christmas-snow-radius-${index + 1}`,
    `--christmas-snow-height-${index + 1}`,
  ]).flat(),
]

function normalizeSeed(seed) {
  const numericSeed = Number(seed)
  return Number.isFinite(numericSeed) ? numericSeed >>> 0 : 0
}

function createSeededRandom(seed) {
  let state = normalizeSeed(seed)

  return () => {
    state += 0x6d2b79f5
    let value = state
    value = Math.imul(value ^ (value >>> 15), value | 1)
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61)
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296
  }
}

function numberInRange(random, minimum, maximum, precision = 3) {
  const value = minimum + random() * (maximum - minimum)
  return Number(value.toFixed(precision))
}

export function generateSnowPattern(seed, { compact = false } = {}) {
  const random = createSeededRandom(seed)
  const depth = compact ? numberInRange(random, 0.16, 0.24) : numberInRange(random, 0.24, 0.42)
  const moundAnchors = [10, 29, 50, 71, 90]

  return Object.freeze({
    depth,
    edgeOffset: numberInRange(random, -0.06, 0.06),
    dropBias: numberInRange(random, 0.15, 0.85),
    mounds: Object.freeze(
      moundAnchors.map((anchor) =>
        Object.freeze({
          x: numberInRange(random, Math.max(6, anchor - 6), Math.min(94, anchor + 6), 2),
          radius: numberInRange(random, compact ? 14 : 18, compact ? 24 : 34, 2),
          height: numberInRange(random, compact ? 62 : 68, 100, 2),
        })
      )
    ),
  })
}

function patternFingerprint(pattern) {
  return [
    pattern.depth,
    pattern.edgeOffset,
    pattern.dropBias,
    ...pattern.mounds.flatMap((mound) => [mound.x, mound.radius, mound.height]),
  ].join(':')
}

function createBrowserSeed() {
  if (globalThis.crypto?.getRandomValues) {
    const values = new Uint32Array(1)
    globalThis.crypto.getRandomValues(values)
    return values[0]
  }

  return Math.floor(Math.random() * 4294967296)
}

function isExplicitlyHidden(element) {
  if (element.hidden || element.closest('[hidden],[inert]')) return true
  if (element.getAttribute('aria-hidden') === 'true') return true

  if (typeof globalThis.getComputedStyle !== 'function') return false
  const styles = globalThis.getComputedStyle(element)
  if (styles.display === 'none' || styles.visibility === 'hidden') return true

  const rect = element.getBoundingClientRect?.()
  return Boolean(
    rect &&
    rect.width === 0 &&
    rect.height === 0 &&
    styles.width === '0px' &&
    styles.height === '0px'
  )
}

function isTinyNonActionControl(element) {
  const rect = element.getBoundingClientRect?.()
  return Boolean(rect && rect.width > 0 && rect.height > 0 && rect.width < 16 && rect.height < 16)
}

export function isEligibleChristmasSnowButton(element) {
  if (!element || element.nodeType !== 1) return false
  if (element.tagName !== 'BUTTON' && !element.matches(EXPLICIT_CONTROL_SELECTOR)) return false
  if (element.matches(EXCLUDED_CONTROL_SELECTOR) || element.closest(EXCLUDED_CONTROL_SELECTOR)) {
    return false
  }
  if (isExplicitlyHidden(element) || isTinyNonActionControl(element)) return false
  return true
}

function isIconOnlyButton(button) {
  const label = button.querySelector('.p-button-label')
  if (label?.textContent?.trim()) return false

  const clone = button.cloneNode(true)
  clone
    .querySelectorAll('.pi,.p-button-icon,svg,[aria-hidden="true"]')
    .forEach((node) => node.remove())
  return clone.textContent.trim().length === 0
}

function applyPatternVariables(button, pattern) {
  button.style.setProperty('--christmas-snow-depth', `${pattern.depth}rem`)
  button.style.setProperty('--christmas-snow-edge-offset', `${pattern.edgeOffset}rem`)
  button.style.setProperty('--christmas-snow-drop-bias', `${pattern.dropBias}`)
  pattern.mounds.forEach((mound, index) => {
    const suffix = index + 1
    button.style.setProperty(`--christmas-snow-x-${suffix}`, `${mound.x}%`)
    button.style.setProperty(`--christmas-snow-radius-${suffix}`, `${mound.radius}%`)
    button.style.setProperty(`--christmas-snow-height-${suffix}`, `${mound.height}%`)
  })
}

function createParticlePattern(seed, dropBias) {
  const random = createSeededRandom(seed)
  const count = 2 + Math.floor(random() * 4)

  return Array.from({ length: count }, () => ({
    x: numberInRange(
      random,
      Math.max(5, dropBias * 100 - 40),
      Math.min(95, dropBias * 100 + 40),
      2
    ),
    size: numberInRange(random, 0.12, 0.26),
    fallDistance: numberInRange(random, 1.2, 2.7),
    drift: numberInRange(random, -0.72, 0.72),
    rotation: numberInRange(random, -95, 125, 1),
    duration: Math.round(numberInRange(random, 350, 850, 0)),
    delay: Math.round(numberInRange(random, 0, 70, 0)),
    opacity: numberInRange(random, 0.68, 0.96, 2),
  }))
}

export function createChristmasButtonSnowEngine({
  root,
  seedFactory = createBrowserSeed,
  matchMedia = globalThis.matchMedia?.bind(globalThis),
  MutationObserverClass = globalThis.MutationObserver,
} = {}) {
  if (!root || root.nodeType !== 1) {
    throw new TypeError('Christmas button snow engine requires an Element root')
  }

  const patternCache = new WeakMap()
  const decorationState = new WeakMap()
  const decoratedButtons = new Set()
  const activeParticles = new Map()
  let observer = null
  let active = false

  function rememberOwnedState(button) {
    const properties = new Map()
    for (const property of OWNED_CUSTOM_PROPERTIES) {
      properties.set(property, {
        value: button.style.getPropertyValue(property),
        priority: button.style.getPropertyPriority(property),
      })
    }

    return {
      hadStyleAttribute: button.hasAttribute('style'),
      snowAttribute: button.getAttribute(SNOW_ATTRIBUTE),
      patternAttribute: button.getAttribute(PATTERN_ATTRIBUTE),
      properties,
    }
  }

  function decorateButton(button) {
    if (!active || !isEligibleChristmasSnowButton(button)) return null
    if (decoratedButtons.has(button)) return patternCache.get(button)

    let pattern = patternCache.get(button)
    if (!pattern) {
      pattern = generateSnowPattern(seedFactory(), { compact: isIconOnlyButton(button) })
      patternCache.set(button, pattern)
    }

    decorationState.set(button, rememberOwnedState(button))
    applyPatternVariables(button, pattern)
    button.setAttribute(SNOW_ATTRIBUTE, 'true')
    button.setAttribute(PATTERN_ATTRIBUTE, patternFingerprint(pattern))
    decoratedButtons.add(button)
    return pattern
  }

  function restoreAttribute(button, name, previousValue) {
    if (previousValue === null) button.removeAttribute(name)
    else button.setAttribute(name, previousValue)
  }

  function removeParticles(button) {
    const particles = activeParticles.get(button)
    if (!particles) return
    particles.forEach((particle) => particle.remove())
    activeParticles.delete(button)
  }

  function undecorateButton(button, { releasePattern = false } = {}) {
    removeParticles(button)
    const state = decorationState.get(button)
    if (state) {
      for (const [property, previous] of state.properties) {
        if (previous.value) button.style.setProperty(property, previous.value, previous.priority)
        else button.style.removeProperty(property)
      }
      restoreAttribute(button, SNOW_ATTRIBUTE, state.snowAttribute)
      restoreAttribute(button, PATTERN_ATTRIBUTE, state.patternAttribute)
      if (!state.hadStyleAttribute && button.getAttribute('style') === '') {
        button.removeAttribute('style')
      }
    }

    decorationState.delete(button)
    decoratedButtons.delete(button)
    if (releasePattern) patternCache.delete(button)
  }

  function forEachEligibleButton(node, callback) {
    if (!node || node.nodeType !== 1) return
    if (node.matches(SNOW_CONTROL_SELECTOR)) callback(node)
    node.querySelectorAll?.(SNOW_CONTROL_SELECTOR).forEach(callback)
  }

  function decorateTree(node) {
    forEachEligibleButton(node, decorateButton)
  }

  function cleanupTree(node) {
    forEachEligibleButton(node, (button) => undecorateButton(button, { releasePattern: true }))
  }

  function removeParticle(button, particle) {
    particle.remove()
    const particles = activeParticles.get(button)
    particles?.delete(particle)
    if (particles?.size === 0) activeParticles.delete(button)
  }

  function makeRoomForParticles(button, incomingCount) {
    const particles = activeParticles.get(button)
    if (!particles) return

    while (particles.size + incomingCount > MAX_ACTIVE_PARTICLES_PER_BUTTON) {
      const oldest = particles.values().next().value
      if (!oldest) break
      removeParticle(button, oldest)
    }
  }

  function createSnowDropParticles(button, pattern) {
    const particles = createParticlePattern(seedFactory(), pattern.dropBias)
    makeRoomForParticles(button, particles.length)

    let activeForButton = activeParticles.get(button)
    if (!activeForButton) {
      activeForButton = new Set()
      activeParticles.set(button, activeForButton)
    }

    for (const particlePattern of particles) {
      const particle = button.ownerDocument.createElement('span')
      particle.className = PARTICLE_CLASS
      particle.setAttribute('aria-hidden', 'true')
      particle.style.setProperty('--christmas-particle-x', `${particlePattern.x}%`)
      particle.style.setProperty('--christmas-particle-size', `${particlePattern.size}rem`)
      particle.style.setProperty('--christmas-particle-fall', `${particlePattern.fallDistance}rem`)
      particle.style.setProperty('--christmas-particle-drift', `${particlePattern.drift}rem`)
      particle.style.setProperty('--christmas-particle-rotation', `${particlePattern.rotation}deg`)
      particle.style.setProperty('--christmas-particle-duration', `${particlePattern.duration}ms`)
      particle.style.setProperty('--christmas-particle-delay', `${particlePattern.delay}ms`)
      particle.style.setProperty('--christmas-particle-opacity', `${particlePattern.opacity}`)
      const cleanupParticle = () => removeParticle(button, particle)
      particle.addEventListener('animationend', cleanupParticle, { once: true })
      particle.addEventListener('animationcancel', cleanupParticle, { once: true })
      activeForButton.add(particle)
      button.appendChild(particle)
    }
  }

  function mediaMatches(query) {
    return Boolean(matchMedia?.(query)?.matches)
  }

  function handlePointerOver(event) {
    if (!active || !mediaMatches(FINE_POINTER_QUERY) || mediaMatches(REDUCED_MOTION_QUERY)) return
    const button = event.target?.closest?.(SNOW_CONTROL_SELECTOR)
    if (!button || (button !== root && !root.contains(button))) return
    if (event.relatedTarget && button.contains(event.relatedTarget)) return
    if (button.disabled || button.getAttribute('aria-disabled') === 'true') return

    const pattern = decorateButton(button)
    if (pattern) createSnowDropParticles(button, pattern)
  }

  function handleMutations(records) {
    for (const record of records) {
      record.removedNodes.forEach((node) => {
        // Moving a button inside the app is not the end of its DOM lifecycle.
        if (!root.contains(node)) cleanupTree(node)
      })
      record.addedNodes.forEach(decorateTree)
    }
  }

  function start() {
    if (active) return
    active = true
    decorateTree(root)
    root.addEventListener('pointerover', handlePointerOver)
    if (MutationObserverClass) {
      observer = new MutationObserverClass(handleMutations)
      observer.observe(root, { childList: true, subtree: true })
    }
  }

  function stop() {
    if (!active && !observer) return
    active = false
    observer?.disconnect()
    observer = null
    root.removeEventListener('pointerover', handlePointerOver)
    ;[...decoratedButtons].forEach((button) => undecorateButton(button))
  }

  function getDebugState() {
    return Object.freeze({
      active,
      observerCount: observer ? 1 : 0,
      decoratedButtonCount: decoratedButtons.size,
      activeParticleCount: [...activeParticles.values()].reduce(
        (count, particles) => count + particles.size,
        0
      ),
    })
  }

  return Object.freeze({
    start,
    stop,
    decorateButton,
    getDebugState,
  })
}
