import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import process from 'node:process'
import { describe, expect, it } from 'vitest'

const adminSource = readFileSync(resolve(process.cwd(), 'src/views/Admin.vue'), 'utf8').replace(
  /\r\n?/g,
  '\n'
)
const durationChartSource = readFileSync(
  resolve(process.cwd(), 'src/components/UserOnlineDurationChart.vue'),
  'utf8'
)

const getRule = (source, selector) => {
  const escapedSelector = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const matches = [
    ...source.matchAll(new RegExp(`(?:^|\\n)${escapedSelector}\\s*\\{([^}]+)\\}`, 'g')),
  ]
  return matches.at(-1)?.[1] || ''
}

describe('user statistics chart layout styles', () => {
  it('keeps the primary and secondary control rows compact without changing card padding', () => {
    const cardRule = getRule(adminSource, '.admin-insights-card')
    const userCardRule = getRule(adminSource, '.user-insights.admin-insights-card')

    expect(cardRule).toContain('padding: 0.85rem')
    expect(userCardRule).toContain('row-gap: 0.5rem')
    expect(adminSource).not.toContain(
      '<p class="user-insights__description">{{ loginDistributionDescription }}</p>'
    )
  })

  it('matches the user data statistics bar gap without changing either data grid', () => {
    const userStatisticsBars = getRule(adminSource, '.user-login-column-chart__bars')
    const durationBars = getRule(durationChartSource, '.user-duration-chart__bars')

    expect(userStatisticsBars).toContain('gap: clamp(1px, 0.25vw, 3px)')
    expect(durationBars).toContain('gap: clamp(1px, 0.25vw, 3px)')
    expect(adminSource).toContain(
      'grid-template-columns: repeat(var(--login-chart-columns), minmax(0, 1fr))'
    )
  })

  it('places review submission statistics before review search and reuses chart styling', () => {
    const statisticsIndex = adminSource.indexOf('id="review-submission-insights-title"')
    const searchIndex = adminSource.indexOf('class="review-search-toolbar')

    expect(statisticsIndex).toBeGreaterThan(-1)
    expect(searchIndex).toBeGreaterThan(statisticsIndex)
    expect(adminSource).toContain("$t('統計時區：{zone}', { zone: PRODUCT_TIME_ZONE_LABEL })")
    expect(adminSource).toContain(':aria-label="reviewSubmissionChartData.ariaLabel"')
    expect(adminSource).toContain('class="user-login-column-chart__bar"')
  })

  it('keeps statistics narrow layouts on a fixed 640px container boundary', () => {
    expect(adminSource).toMatch(
      /\.admin-insights-card \.chart-summary-item\s*\{[^}]*justify-items: center;[^}]*text-align: center;/s
    )
    expect(adminSource).toMatch(
      /@container admin-insights \(max-width: 640px\)[\s\S]*?\.admin-insights-card \.chart-summary-control-row\s*\{[^}]*grid-template-areas:[^}]*'controls'[^}]*'summary'[^}]*'timezone'/
    )
    expect(adminSource).toMatch(
      /\.admin-insights-card\s*\{[^}]*container: admin-insights \/ inline-size;/
    )
    expect(adminSource).toMatch(
      /\.admin-insights-card \.chart-summary-group\s*\{[^}]*grid-template-columns: repeat\(3, minmax\(0, 1fr\)\)/s
    )
    expect(adminSource).toMatch(
      /\.admin-insights-card \.chart-control-stack \.user-insights__range\s*\{[^}]*display: inline-flex;[^}]*width: max-content;[^}]*flex-wrap: nowrap;[^}]*justify-self: end;/s
    )
    expect(adminSource).toMatch(
      /\.admin-insights-card \.user-insights__switch\s*\{[^}]*flex-wrap: nowrap;/
    )
    expect(adminSource).not.toContain('@container admin-insights (max-width: 40rem)')
  })

  it('keeps the <=640px chart controls compact and right-aligned as one group', () => {
    expect(adminSource).toMatch(
      /@media \(max-width: 640px\)[\s\S]*?\.user-insights__actions\s*\{[^}]*align-items: center;[^}]*justify-content: flex-end;/
    )
    expect(adminSource).toMatch(
      /@media \(max-width: 640px\)[\s\S]*?\.user-insights__switch\s*\{[^}]*margin-inline-start: 0;[^}]*justify-content: flex-end;/
    )
    expect(adminSource).toMatch(
      /@media \(max-width: 640px\)[\s\S]*?\.user-insights__toggle\s*\{[^}]*margin-inline-start: 0;/
    )
  })

  it.each([641, 700, 768, 797, 820, 871])(
    'covers the %spx intermediate width with shared right-aligned actions',
    (width) => {
      expect(width).toBeGreaterThanOrEqual(641)
      expect(width).toBeLessThanOrEqual(871)
      expect(adminSource).toMatch(
        /@media \(min-width: 641px\) and \(max-width: 871px\)[\s\S]*?\.user-insights__actions\s*\{[^}]*margin-inline-start: auto;[^}]*justify-content: flex-end;/
      )
      expect(adminSource).toMatch(
        /@media \(min-width: 641px\) and \(max-width: 871px\)[\s\S]*?\.user-insights__switch\s*\{[^}]*justify-content: flex-end;/
      )
    }
  )

  it.each([908, 964])('keeps the expand control at the far right at %spx', (width) => {
    expect(width).toBeGreaterThan(899)
    expect(adminSource).toMatch(
      /\.user-insights__actions\s*\{[^}]*flex: 1 1 auto;[^}]*min-width: 0;[^}]*justify-content: flex-end;/s
    )
    expect(adminSource).toMatch(
      /\.user-insights__toggle\s*\{[^}]*flex: 0 0 auto;[^}]*margin-inline-start: 0;/s
    )
    expect(adminSource.match(/class="user-insights__actions"/g)).toHaveLength(2)
    const statisticsActionRules =
      adminSource.match(/\.user-insights__(?:actions|toggle)\s*\{[^}]*\}/g) ?? []
    expect(statisticsActionRules.every((rule) => !rule.includes('dark'))).toBe(true)
  })

  it.each([320, 344, 375, 393, 399, 420, 437, 438, 640])(
    'uses complete segmented grids at the %spx narrow width',
    (width) => {
      expect(width).toBeLessThanOrEqual(640)
      expect(adminSource).toContain('class="user-insights__switch user-insights__switch--three"')
      expect(adminSource).toContain('class="user-insights__switch user-insights__switch--two"')
      expect(adminSource).toContain(
        'class="user-insights__switch-option user-insights__switch-option--wide"'
      )
      expect(adminSource).toMatch(
        /@media \(max-width: 640px\)[\s\S]*?\.user-insights__switch\.user-insights__switch--two,[\s\S]*?\.user-insights__switch\.user-insights__switch--three\s*\{[^}]*display: grid;[^}]*grid-template-columns: repeat\(2, minmax\(0, 1fr\)\);[^}]*width: 100%;/
      )
      expect(adminSource).toMatch(
        /\.user-insights__switch--three\s*> \.user-insights__switch-option--wide\s*\{[^}]*grid-column: 1 \/ -1;[^}]*justify-self: stretch;[^}]*width: 100%;[^}]*min-width: 0;/
      )
      expect(adminSource).toMatch(
        /\.user-insights__switch > \.user-insights__switch-option\s*\{[^}]*display: block;[^}]*flex: none;[^}]*width: 100%;[^}]*min-width: 0;[^}]*max-width: none;/
      )
    }
  )

  it.each([641, 1280, 1440])('keeps mobile tab grids out of the %spx layout', (width) => {
    expect(width).toBeGreaterThan(640)
    expect(adminSource).not.toContain('@media (max-width: 641px)')
  })

  it('observes the effective x-axis without changing the responsive tick owner', () => {
    expect(adminSource).toContain(
      'ref="userStatisticsChartElement"\n                          class="user-login-column-chart__x-axis"'
    )
    expect(adminSource).toContain(
      'ref="reviewSubmissionChartElement"\n                          class="user-login-column-chart__x-axis"'
    )
  })

  it('uses one simple level tag throughout the card layout without changing the desktop cell', () => {
    const cardStart = adminSource.indexOf(
      '<div v-if="!usersLoading" class="admin-mobile-list admin-mobile-list--users">'
    )
    const cardEnd = adminSource.indexOf('<Paginator', cardStart)
    const cardMarkup = adminSource.slice(cardStart, cardEnd)

    expect(adminSource).toContain('Lv{{ user.contributorLevel.level }}')
    expect(adminSource).toMatch(
      /\.admin-mobile-list--users \.mobile-user-level-tag\s*\{[^}]*display: inline-flex;[^}]*flex: 0 0 auto;/
    )
    expect(cardMarkup).not.toContain('<ContributorLevelBadge')
    expect(cardMarkup).not.toContain('show-title')
    expect(adminSource).toContain('Lv. {{ data.contributorLevel.level }}')
  })
})
