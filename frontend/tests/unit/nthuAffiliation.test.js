import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { cwd } from 'node:process'

import { afterEach, describe, expect, it } from 'vitest'

import { i18n } from '@/i18n'
import {
  NTHU_DEPARTMENT_PRESENTATIONS,
  localizedNthuDepartmentName,
  localizedNthuDepartmentOptions,
} from '@/utils/nthuAffiliation'

const backendCatalogSource = readFileSync(
  resolve(cwd(), '../backend/app/services/nthu_affiliation.py'),
  'utf8'
)
const canonicalDepartments = [...backendCatalogSource.matchAll(/\("(\d{3})", "([^"]+)"\)/g)].map(
  ([, code, name]) => ({ code, name })
)

describe('NTHU affiliation presentation coverage', () => {
  afterEach(() => {
    i18n.global.locale.value = 'zh-TW'
  })

  it('covers every canonical backend department with English and provenance metadata', () => {
    expect(canonicalDepartments).toHaveLength(128)
    expect(Object.keys(NTHU_DEPARTMENT_PRESENTATIONS)).toHaveLength(128)

    canonicalDepartments.forEach(({ code, name }) => {
      const presentation = NTHU_DEPARTMENT_PRESENTATIONS[code]
      expect(presentation, `${code} ${name}`).toBeDefined()
      expect(presentation.name).toBe(name)
      expect(presentation.name_en.trim()).not.toBe('')
      expect(['official-current', 'official-historical', 'curated']).toContain(
        presentation.provenance
      )
    })
  })

  it('keeps both English and canonical Chinese names searchable in English mode', () => {
    i18n.global.locale.value = 'en'
    const [option] = localizedNthuDepartmentOptions([
      {
        code: '022',
        name: '物理學系',
        college_code: '02',
        college_name: '理學院',
      },
    ])

    expect(option.name).toBe('Department of Physics')
    expect(option.canonical_name).toBe('物理學系')
    expect(localizedNthuDepartmentName(option)).toBe('Department of Physics')
  })

  it('localizes interdisciplinary group labels without changing canonical metadata', () => {
    i18n.global.locale.value = 'en'
    const [option] = localizedNthuDepartmentOptions([
      {
        code: '000',
        name: '清華學院學士班／跨系所招生',
        college_code: '00',
        college_name: '跨院系所',
      },
    ])

    expect(option.college_name).toBe('Interdisciplinary Programs')
    expect(option.canonical_college_name).toBe('跨院系所')
  })
})
