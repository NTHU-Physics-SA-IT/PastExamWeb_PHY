import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const source = readFileSync(resolve(globalThis.process.cwd(), 'src/views/Admin.vue'), 'utf8')
const template = source.split('<script setup>')[0]

describe('Admin bilingual content and desktop status-pill contracts', () => {
  it('binds all four announcement fields and sends nullable English metadata', () => {
    for (const model of [
      'notificationForm.title',
      'notificationForm.title_en',
      'notificationForm.body',
      'notificationForm.body_en',
    ]) {
      expect(template).toContain(`v-model="${model}"`)
    }
    expect(source).toContain('title_en: notificationForm.value.title_en.trim() || null')
    expect(source).toContain('body_en: notificationForm.value.body_en.trim() || null')
    expect(source.match(/localizedAnnouncementTitle\((?:data|notification)\)/g)).toHaveLength(3)
    expect(source).toContain(
      'announcementMatchesSearch(notification, notificationSearchQuery.value)'
    )
  })

  it('gives pending, approved, and takedown the same compact desktop pill contract', () => {
    expect(template.match(/'existing-course-status-pill'/g)).toHaveLength(1)
    expect(template).toMatch(
      /toggleReviewSort\('existing', 'status'\)[\s\S]*?'existing-course-status-pill'[\s\S]*?getSubmissionStatusClass\(data\.status\)/
    )
    expect(source).toMatch(
      /if \(normalized === 'approved'\) return 'review-status-approved'[\s\S]*?if \(normalized === 'takedown'\) return 'review-status-takedown'[\s\S]*?return 'review-status-pending'/
    )
    expect(source).toMatch(
      /admin-desktop-status-cell \.existing-course-status-pill\.soft-badge[\s\S]*?inline-size:\s*fit-content[\s\S]*?max-inline-size:\s*100%[\s\S]*?block-size:\s*1\.8rem[\s\S]*?padding-block:\s*0\.28rem[\s\S]*?padding-inline:\s*0\.68rem[\s\S]*?border-radius:\s*999px[\s\S]*?font-size:\s*var\(--app-badge-font-size\)[\s\S]*?font-weight:\s*650[\s\S]*?line-height:\s*1\.25[\s\S]*?vertical-align:\s*middle[\s\S]*?white-space:\s*nowrap/
    )
    expect(source).not.toMatch(/existing-course-status-pill[\s\S]{0,400}width:\s*\d+px/)
    expect(source).not.toMatch(
      /existing-course-status-pill[\s\S]{0,400}(locale|Pending Review|Taken Down)/
    )
  })
})
