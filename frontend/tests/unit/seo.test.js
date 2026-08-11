import { afterEach, describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

import { DEFAULT_DESCRIPTION, DEFAULT_TITLE, setSeo } from '@/utils/seo'

function meta(selector) {
  return document.head.querySelector(selector)?.getAttribute('content')
}

describe('SEO metadata helper', () => {
  afterEach(() => {
    document.head
      .querySelectorAll('meta, link[rel="canonical"], script[type="application/ld+json"]')
      .forEach((element) => element.remove())
  })

  it('updates canonical, robots, Open Graph, Twitter, and JSON-LD metadata', () => {
    setSeo({
      title: '公開課程',
      description: '公開課程說明',
      canonicalPath: '/courses',
      robots: 'index, follow',
      jsonLd: [{ '@type': 'CollectionPage', name: '公開課程' }],
    })

    expect(document.title).toBe('公開課程')
    expect(meta('meta[name="title"]')).toBe('公開課程')
    expect(meta('meta[name="description"]')).toBe('公開課程說明')
    expect(meta('meta[name="robots"]')).toBe('index, follow')
    expect(meta('meta[property="og:title"]')).toBe('公開課程')
    expect(meta('meta[name="twitter:title"]')).toBe('公開課程')
    expect(meta('meta[property="og:site_name"]')).toBe('PhysArchive')
    expect(meta('meta[name="twitter:card"]')).toBe('summary_large_image')
    expect(meta('meta[name="twitter:url"]')).toMatch(/\/courses$/)
    expect(document.head.querySelector('link[rel="canonical"]')?.href).toMatch(/\/courses$/)

    const graph = JSON.parse(
      document.head.querySelector('script[type="application/ld+json"]').textContent
    )
    expect(graph['@context']).toBe('https://schema.org')
    expect(graph['@graph'][0]['@type']).toBe('CollectionPage')
  })

  it('keeps static fallback and page-title sources free of the PhysArchive suffix', () => {
    const indexSource = readFileSync('index.html', 'utf8')
    const routerSource = readFileSync('src/router/index.js', 'utf8')
    const seoSource = readFileSync('src/utils/seo.js', 'utf8')

    expect(indexSource).toContain('<title>清大物理考古系統</title>')
    expect(seoSource).toContain("upsertMeta('property', 'og:site_name', 'PhysArchive')")
    expect(`${indexSource}\n${routerSource}`).not.toMatch(/(?:\|\s*|｜)PhysArchive/)
  })

  it('uses the canonical site description across default social metadata', () => {
    setSeo()

    expect(DEFAULT_TITLE).toBe('清大物理考古系統')
    expect(document.title).toBe('清大物理考古系統')
    expect(DEFAULT_DESCRIPTION).toBe(
      '整理清華大學物理系歷年考試題目、解答、課程資料與討論，讓找清大考古題、準備考試與複習課程變得更簡單。'
    )
    expect(meta('meta[name="description"]')).toBe(DEFAULT_DESCRIPTION)
    expect(meta('meta[property="og:description"]')).toBe(DEFAULT_DESCRIPTION)
    expect(meta('meta[name="twitter:description"]')).toBe(DEFAULT_DESCRIPTION)
  })

  it('removes stale structured data and applies protected-route defaults', () => {
    setSeo({ jsonLd: [{ '@type': 'WebSite' }] })
    setSeo({
      title: '管理後台',
      canonicalPath: '/admin',
      robots: 'noindex, nofollow',
      jsonLd: [],
    })

    expect(meta('meta[name="robots"]')).toBe('noindex, nofollow')
    expect(document.getElementById('seo-jsonld')).toBeNull()
  })

  it('keeps a self-canonical public detail page followable while excluding it from indexing', () => {
    setSeo({
      title: '普通物理(一)',
      canonicalPath: '/courses/42',
      robots: 'noindex, follow',
    })

    expect(meta('meta[name="robots"]')).toBe('noindex, follow')
    expect(document.head.querySelector('link[rel="canonical"]')?.href).toMatch(/\/courses\/42$/)
  })
})
