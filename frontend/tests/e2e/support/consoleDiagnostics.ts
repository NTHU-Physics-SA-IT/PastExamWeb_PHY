import type { ConsoleMessage, JSHandle, Page } from '@playwright/test'

const MAX_STRING_LENGTH = 500
const MAX_ARRAY_ITEMS = 10
const MAX_OBJECT_KEYS = 20
const MAX_DEPTH = 3
const SENSITIVE_KEY = /authorization|cookie|password|secret|token/i

export type ConsoleDiagnostic = {
  type: string
  text: string
  args: unknown[]
  location: {
    url: string
    line: number
    column: number
  }
}

const redactString = (value: string) => {
  const redacted = value
    .replace(/\b(Bearer\s+)[A-Za-z0-9._~+/=-]+/gi, '$1[REDACTED]')
    .replace(
      /\b(authorization|cookie|password|secret|token)(\s*[:=]\s*)[^\s,;}\]]+/gi,
      '$1$2[REDACTED]'
    )

  return redacted.length <= MAX_STRING_LENGTH
    ? redacted
    : `${redacted.slice(0, MAX_STRING_LENGTH)}…[truncated]`
}

const sanitizeValue = (value: unknown, depth = 0): unknown => {
  if (typeof value === 'string') return redactString(value)
  if (value === null || typeof value === 'number' || typeof value === 'boolean') return value
  if (typeof value === 'bigint') return `${value.toString()}n`
  if (typeof value === 'undefined') return '[undefined]'
  if (typeof value === 'function') return '[function]'
  if (typeof value === 'symbol') return value.toString()
  if (depth >= MAX_DEPTH) return '[max-depth]'

  if (Array.isArray(value)) {
    const items = value
      .slice(0, MAX_ARRAY_ITEMS)
      .map((item) => sanitizeValue(item, depth + 1))
    if (value.length > MAX_ARRAY_ITEMS) items.push(`[${value.length - MAX_ARRAY_ITEMS} more items]`)
    return items
  }

  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>).slice(0, MAX_OBJECT_KEYS)
    const sanitized: Record<string, unknown> = {}
    for (const [key, item] of entries) {
      sanitized[key] = SENSITIVE_KEY.test(key) ? '[REDACTED]' : sanitizeValue(item, depth + 1)
    }
    if (Object.keys(value as object).length > MAX_OBJECT_KEYS) {
      sanitized['[truncated]'] = true
    }
    return sanitized
  }

  return redactString(String(value))
}

const safeLocationUrl = (value: string) => {
  if (!value) return ''
  try {
    const url = new URL(value)
    return `${url.origin}${url.pathname}`
  } catch {
    return redactString(value.split(/[?#]/, 1)[0] ?? '')
  }
}

const serializeHandle = async (handle: JSHandle) => {
  try {
    return sanitizeValue(await handle.jsonValue())
  } catch (error) {
    return {
      preview: redactString(handle.toString()),
      serializationError: redactString(error instanceof Error ? error.message : String(error)),
    }
  }
}

export const serializeConsoleMessage = async (
  message: Pick<ConsoleMessage, 'args' | 'location' | 'text' | 'type'>
): Promise<ConsoleDiagnostic> => {
  const location = message.location()
  const args = await Promise.all(message.args().slice(0, MAX_ARRAY_ITEMS).map(serializeHandle))

  return {
    type: message.type(),
    text: redactString(message.text()),
    args,
    location: {
      url: safeLocationUrl(location.url),
      line: location.lineNumber,
      column: location.columnNumber,
    },
  }
}

export const createConsoleErrorCollector = (page: Page) => {
  const entries: ConsoleDiagnostic[] = []
  const pending = new Set<Promise<void>>()

  const onConsole = (message: ConsoleMessage) => {
    if (message.type() !== 'error') return

    const task = serializeConsoleMessage(message)
      .then((entry) => {
        entries.push(entry)
      })
      .catch((error) => {
        entries.push({
          type: 'error',
          text: redactString(message.text()),
          args: [
            {
              serializationError: redactString(
                error instanceof Error ? error.message : String(error)
              ),
            },
          ],
          location: { url: '', line: 0, column: 0 },
        })
      })

    pending.add(task)
    void task.finally(() => pending.delete(task))
  }

  page.on('console', onConsole)

  return {
    async errors() {
      while (pending.size > 0) {
        await Promise.all([...pending])
      }
      return [...entries]
    },
    stop() {
      page.off('console', onConsole)
    },
  }
}
