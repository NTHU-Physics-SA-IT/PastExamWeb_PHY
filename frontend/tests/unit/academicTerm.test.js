import { describe, expect, it } from 'vitest'

import { formatAcademicTerm, parseAcademicTerm } from '@/utils/academicTerm'

const translate = (key, values) => key.replace('{year}', String(values.year))

describe('academic term formatting', () => {
  it.each([
    [981, { academicYear: 98, semester: 1 }, '98上學期'],
    [982, { academicYear: 98, semester: 2 }, '98下學期'],
    [991, { academicYear: 99, semester: 1 }, '99上學期'],
    [992, { academicYear: 99, semester: 2 }, '99下學期'],
    [1001, { academicYear: 100, semester: 1 }, '100上學期'],
    [1002, { academicYear: 100, semester: 2 }, '100下學期'],
    [1131, { academicYear: 113, semester: 1 }, '113上學期'],
    [1132, { academicYear: 113, semester: 2 }, '113下學期'],
  ])('parses and formats %s', (value, parsed, formatted) => {
    expect(parseAcademicTerm(value)).toEqual(parsed)
    expect(formatAcademicTerm(value, translate)).toBe(formatted)
  })

  it.each([null, undefined, '', '   ', 'not-a-term', 1000, 1003])(
    'rejects invalid academic term value %s',
    (value) => {
      expect(parseAcademicTerm(value)).toBeNull()
      expect(formatAcademicTerm(value, translate)).toBe('')
    }
  )

  it('accepts integer-like string values without using digit length', () => {
    expect(parseAcademicTerm('992')).toEqual({ academicYear: 99, semester: 2 })
  })
})
