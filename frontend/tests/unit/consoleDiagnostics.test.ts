import { describe, expect, it, vi } from 'vitest'
import type { ConsoleMessage, JSHandle } from '@playwright/test'
import { serializeConsoleMessage } from '../e2e/support/consoleDiagnostics'

const handle = (value: unknown): JSHandle =>
  ({
    jsonValue: vi.fn().mockResolvedValue(value),
    toString: () => 'JSHandle@object',
  }) as unknown as JSHandle

const message = (args: JSHandle[]): Pick<ConsoleMessage, 'args' | 'location' | 'text' | 'type'> => ({
  args: () => args,
  location: () => ({
    url: 'http://nginx:8080/app.js?token=must-not-leak',
    lineNumber: 12,
    columnNumber: 4,
  }),
  text: () => 'request failed token=must-not-leak',
  type: () => 'error',
})

describe('console diagnostics', () => {
  it('serializes object arguments while redacting sensitive values and URL queries', async () => {
    const result = await serializeConsoleMessage(
      message([
        handle({
          message: 'route import failed',
          token: 'secret-token',
          nested: { password: 'secret-password', ok: true },
        }),
      ])
    )

    expect(result).toMatchObject({
      type: 'error',
      text: 'request failed token=[REDACTED]',
      args: [
        {
          message: 'route import failed',
          token: '[REDACTED]',
          nested: { password: '[REDACTED]', ok: true },
        },
      ],
      location: {
        url: 'http://nginx:8080/app.js',
        line: 12,
        column: 4,
      },
    })
  })

  it('retains a strict diagnostic when argument serialization fails', async () => {
    const brokenHandle = {
      jsonValue: vi.fn().mockRejectedValue(new Error('cyclic token=secret-value')),
      toString: () => 'JSHandle@object',
    } as unknown as JSHandle

    const result = await serializeConsoleMessage(message([brokenHandle]))

    expect(result.args).toEqual([
      {
        preview: 'JSHandle@object',
        serializationError: 'cyclic token=[REDACTED]',
      },
    ])
    expect(result.type).toBe('error')
  })
})
