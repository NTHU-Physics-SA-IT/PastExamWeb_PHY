export function parseAcademicTerm(value) {
  if (value === null || value === undefined || typeof value === 'boolean') return null
  if (typeof value === 'string' && value.trim() === '') return null

  const code = Number(value)
  if (!Number.isFinite(code) || !Number.isInteger(code) || code <= 0) return null

  const semester = code % 10
  if (semester !== 1 && semester !== 2) return null

  const academicYear = Math.floor(code / 10)
  if (academicYear <= 0) return null

  return { academicYear, semester }
}

export function formatAcademicTerm(value, translate) {
  const term = parseAcademicTerm(value)
  if (!term) return ''

  return translate(term.semester === 1 ? '{year}上學期' : '{year}下學期', {
    year: term.academicYear,
  })
}
