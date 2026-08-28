import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { validateI18nContract } from './check-i18n.mjs'

const missingReviewStatus = { rule: 'missing-english', key: '審核狀態' }

function validate({ englishCatalog = {}, content = '', sourceCatalog, baselineEntries = [] }) {
  return validateI18nContract({
    englishCatalog,
    sourceCatalog,
    sources: [{ file: 'src/Fixture.vue', content }],
    baselineEntries,
  })
}

describe('i18n contract checker baseline', () => {
  it('passes when the exact existing violation is baselined', () => {
    assert.deepEqual(
      validate({ content: "{{ $t('審核狀態') }}", baselineEntries: [missingReviewStatus] }),
      []
    )
  })

  it('fails for a new unbaselined missing translation', () => {
    assert.deepEqual(validate({ content: "{{ $t('審核狀態') }}" }), [
      'Unbaselined i18n violation:\nMissing English translation:\n  "審核狀態"\nUsed in:\n  src/Fixture.vue:1',
    ])
  })

  it('fails for a new unbaselined placeholder mismatch', () => {
    assert.deepEqual(
      validate({
        englishCatalog: { '{label}：{count} 位活躍使用者': '{count} active users' },
      }),
      [
        'Unbaselined i18n violation:\nPlaceholder mismatch for:\n  "{label}：{count} 位活躍使用者"\nSource placeholders:\n  count, label\nEnglish placeholders:\n  count',
      ]
    )
  })

  it('fails when a resolved violation leaves a stale baseline entry', () => {
    assert.deepEqual(
      validate({
        englishCatalog: { 審核狀態: 'Status' },
        content: "{{ $t('審核狀態') }}",
        baselineEntries: [missingReviewStatus],
      }),
      [
        'Stale i18n baseline entry:\n  {"rule":"missing-english","key":"審核狀態"}\n  The violation is resolved; remove this baseline entry.',
      ]
    )
  })

  it('passes after a resolved violation and its baseline entry are both removed', () => {
    assert.deepEqual(
      validate({
        englishCatalog: { 審核狀態: 'Status' },
        content: "{{ $t('審核狀態') }}",
      }),
      []
    )
  })

  it('passes when source and English placeholder sets match in a different order', () => {
    assert.deepEqual(
      validate({
        englishCatalog: { '{label}：{count} 位活躍使用者': '{count} active users in {label}' },
      }),
      []
    )
  })

  it('uses the source locale value for established semantic catalog keys', () => {
    assert.deepEqual(
      validate({
        englishCatalog: { activeUsersTooltip: '{count} active users in {label}' },
        sourceCatalog: { activeUsersTooltip: '{label}：{count} 位活躍使用者' },
      }),
      []
    )
  })
})
