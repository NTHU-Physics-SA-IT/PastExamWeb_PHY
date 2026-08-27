import { readdir, readFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { messages } from '../src/i18n/messages.js'

const SOURCE_EXTENSIONS = new Set(['.js', '.ts', '.vue'])
const PLACEHOLDER_PATTERN = /\{([A-Za-z_][A-Za-z0-9_.-]*)\}/g
const LITERAL_CALL_PATTERN =
  /(?:i18n\.global\.t|\$t|(?<![\w$.])t|(?<![\w$.])getMessageTemplate)\s*\(\s*(?:'((?:\\.|[^'\\])*)'|"((?:\\.|[^"\\])*)")/g

function decodeStringLiteral(raw) {
  const simpleEscapes = {
    '0': '\0',
    b: '\b',
    f: '\f',
    n: '\n',
    r: '\r',
    t: '\t',
    v: '\v',
  }
  let decoded = ''

  for (let index = 0; index < raw.length; index += 1) {
    if (raw[index] !== '\\' || index === raw.length - 1) {
      decoded += raw[index]
      continue
    }

    const escaped = raw[index + 1]
    if (escaped === 'u') {
      const braced = raw.slice(index + 2).match(/^\{([0-9A-Fa-f]+)\}/)
      const fixed = raw.slice(index + 2, index + 6)
      if (braced) {
        decoded += String.fromCodePoint(Number.parseInt(braced[1], 16))
        index += braced[0].length + 1
        continue
      }
      if (/^[0-9A-Fa-f]{4}$/.test(fixed)) {
        decoded += String.fromCharCode(Number.parseInt(fixed, 16))
        index += 5
        continue
      }
    }
    if (escaped === 'x') {
      const hex = raw.slice(index + 2, index + 4)
      if (/^[0-9A-Fa-f]{2}$/.test(hex)) {
        decoded += String.fromCharCode(Number.parseInt(hex, 16))
        index += 3
        continue
      }
    }

    decoded += simpleEscapes[escaped] ?? escaped
    index += 1
  }

  return decoded
}

function compareText(left, right) {
  return left < right ? -1 : left > right ? 1 : 0
}

function sameValues(left, right) {
  return left.length === right.length && left.every((value, index) => value === right[index])
}

export function extractPlaceholders(message) {
  return [...new Set([...message.matchAll(PLACEHOLDER_PATTERN)].map((match) => match[1]))].sort(
    compareText
  )
}

export function collectStaticKeyUsages(source, file) {
  return [...source.matchAll(LITERAL_CALL_PATTERN)].map((match) => ({
    key: decodeStringLiteral(match[1] ?? match[2]),
    file,
    line: source.slice(0, match.index).split('\n').length,
  }))
}

export function violationIdentity(violation) {
  if (violation.rule === 'missing-english') {
    return JSON.stringify({ rule: violation.rule, key: violation.key })
  }
  if (violation.rule === 'placeholder-parity') {
    return JSON.stringify({
      rule: violation.rule,
      key: violation.key,
      sourcePlaceholders: [...violation.sourcePlaceholders].sort(compareText),
      englishPlaceholders: [...violation.englishPlaceholders].sort(compareText),
    })
  }
  throw new TypeError(`Unknown i18n violation rule: ${violation.rule}`)
}

export function collectI18nViolations({ englishCatalog, sourceCatalog, sources }) {
  const missingUsages = new Map()

  for (const source of sources) {
    for (const usage of collectStaticKeyUsages(source.content, source.file)) {
      if (!Object.hasOwn(englishCatalog, usage.key)) {
        const usages = missingUsages.get(usage.key) ?? []
        usages.push({ file: usage.file, line: usage.line })
        missingUsages.set(usage.key, usages)
      }
    }
  }

  const violations = [...missingUsages].map(([key, sites]) => ({
    rule: 'missing-english',
    key,
    sites,
  }))

  for (const [key, englishMessage] of Object.entries(englishCatalog)) {
    const sourceMessage = sourceCatalog?.[key] ?? key
    const sourcePlaceholders = extractPlaceholders(sourceMessage)
    const englishPlaceholders = extractPlaceholders(englishMessage)

    if (!sameValues(sourcePlaceholders, englishPlaceholders)) {
      violations.push({
        rule: 'placeholder-parity',
        key,
        sourcePlaceholders,
        englishPlaceholders,
      })
    }
  }

  return violations.sort((left, right) =>
    compareText(violationIdentity(left), violationIdentity(right))
  )
}

function formatViolation(violation) {
  if (violation.rule === 'missing-english') {
    const sites = violation.sites.map(({ file, line }) => `  ${file}:${line}`).join('\n')
    return `Missing English translation:\n  "${violation.key}"\nUsed in:\n${sites}`
  }

  const sourcePlaceholders = violation.sourcePlaceholders.join(', ') || '(none)'
  const englishPlaceholders = violation.englishPlaceholders.join(', ') || '(none)'
  return `Placeholder mismatch for:\n  "${violation.key}"\nSource placeholders:\n  ${sourcePlaceholders}\nEnglish placeholders:\n  ${englishPlaceholders}`
}

export function compareViolationsToBaseline(violations, baselineEntries) {
  const actualByIdentity = new Map(
    violations.map((violation) => [violationIdentity(violation), violation])
  )
  const baselineByIdentity = new Map()

  for (const entry of baselineEntries) {
    const identity = violationIdentity(entry)
    if (baselineByIdentity.has(identity)) {
      throw new TypeError(`Duplicate i18n baseline entry: ${identity}`)
    }
    baselineByIdentity.set(identity, entry)
  }

  const errors = []
  for (const [identity, violation] of actualByIdentity) {
    if (!baselineByIdentity.has(identity)) {
      errors.push(`Unbaselined i18n violation:\n${formatViolation(violation)}`)
    }
  }
  for (const identity of baselineByIdentity.keys()) {
    if (!actualByIdentity.has(identity)) {
      errors.push(
        `Stale i18n baseline entry:\n  ${identity}\n  The violation is resolved; remove this baseline entry.`
      )
    }
  }

  return errors
}

export function validateI18nContract({ englishCatalog, sourceCatalog, sources, baselineEntries }) {
  const violations = collectI18nViolations({ englishCatalog, sourceCatalog, sources })
  return compareViolationsToBaseline(violations, baselineEntries)
}

async function findSourceFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true })
  const files = []

  for (const entry of entries.sort((left, right) => compareText(left.name, right.name))) {
    const entryPath = path.join(directory, entry.name)
    if (entry.isDirectory()) {
      files.push(...(await findSourceFiles(entryPath)))
    } else if (SOURCE_EXTENSIONS.has(path.extname(entry.name))) {
      files.push(entryPath)
    }
  }

  return files
}

export async function checkRepository(frontendRoot) {
  const sourceRoot = path.join(frontendRoot, 'src')
  const baselinePath = path.join(frontendRoot, 'scripts', 'i18n-baseline.json')
  const files = await findSourceFiles(sourceRoot)
  const [sources, baselineDocument] = await Promise.all([
    Promise.all(
      files.map(async (file) => ({
        file: path.relative(frontendRoot, file).replaceAll(path.sep, '/'),
        content: await readFile(file, 'utf8'),
      }))
    ),
    readFile(baselinePath, 'utf8').then(JSON.parse),
  ])

  if (baselineDocument.version !== 1 || !Array.isArray(baselineDocument.violations)) {
    throw new TypeError('i18n baseline must have version 1 and a violations array')
  }

  return validateI18nContract({
    englishCatalog: messages.en,
    sourceCatalog: messages['zh-TW'],
    sources,
    baselineEntries: baselineDocument.violations,
  })
}

async function main() {
  const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
  const errors = await checkRepository(frontendRoot)

  if (errors.length > 0) {
    console.error(`i18n contract check failed with ${errors.length} error(s):`)
    for (const error of errors) console.error(`\n${error}`)
    process.exitCode = 1
    return
  }

  console.log('i18n contract check passed (static literal keys, placeholder parity, and baseline).')
}

if (path.resolve(process.argv[1] ?? '') === fileURLToPath(import.meta.url)) {
  await main()
}
