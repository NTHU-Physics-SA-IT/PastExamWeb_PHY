import { afterEach, describe, expect, it } from 'vitest'

import { setLocale } from '@/i18n'
import {
  DEFAULT_SUBMISSION_LEVELS,
  localizedSubmissionLevelName,
  validateContributorLevelSettings,
} from '@/utils/submissionLevel'

describe('submission level bilingual presentation', () => {
  afterEach(() => setLocale('zh-TW'))

  it('provides authoritative English metadata for all ten defaults', () => {
    expect(DEFAULT_SUBMISSION_LEVELS).toHaveLength(10)
    expect(DEFAULT_SUBMISSION_LEVELS.map((item) => item.level)).toEqual(
      Array.from({ length: 10 }, (_, index) => index + 1)
    )
    expect(DEFAULT_SUBMISSION_LEVELS.every((item) => item.name && item.name_en)).toBe(true)
  })

  it('uses English when present and canonical Chinese as the English fallback', () => {
    const levels = validateContributorLevelSettings([
      { level: 1, name: '自訂一級', name_en: 'Custom Level One', min_exp: 0 },
      ...DEFAULT_SUBMISSION_LEVELS.slice(1).map((item) => ({
        ...item,
        min_exp: item.minExp,
      })),
    ])

    setLocale('en')
    expect(localizedSubmissionLevelName(levels[0])).toBe('Custom Level One')
    expect(localizedSubmissionLevelName({ name: '只有中文', name_en: null })).toBe('只有中文')

    setLocale('zh-TW')
    expect(localizedSubmissionLevelName(levels[0])).toBe('自訂一級')
  })
})
