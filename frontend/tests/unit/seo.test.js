import { afterEach, describe, expect, it } from 'vitest'

import { setSeo } from '@/utils/seo'

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
      title: '公開課程｜PhysArchive',
      description: '公開課程說明',
      canonicalPath: '/courses',
      robots: 'index, follow',
      jsonLd: [{ '@type': 'CollectionPage', name: '公開課程' }],
    })

    expect(document.title).toBe('公開課程｜PhysArchive')
    expect(meta('meta[name="description"]')).toBe('公開課程說明')
    expect(meta('meta[name="robots"]')).toBe('index, follow')
    expect(meta('meta[property="og:title"]')).toBe('公開課程｜PhysArchive')
    expect(meta('meta[name="twitter:card"]')).toBe('summary_large_image')
    expect(meta('meta[name="twitter:url"]')).toMatch(/\/courses$/)
    expect(document.head.querySelector('link[rel="canonical"]')?.href).toMatch(/\/courses$/)

    const graph = JSON.parse(
      document.head.querySelector('script[type="application/ld+json"]').textContent
    )
    expect(graph['@context']).toBe('https://schema.org')
    expect(graph['@graph'][0]['@type']).toBe('CollectionPage')
  })

  it('removes stale structured data and applies protected-route defaults', () => {
    setSeo({ jsonLd: [{ '@type': 'WebSite' }] })
    setSeo({
      title: '管理後台｜PhysArchive',
      canonicalPath: '/admin',
      robots: 'noindex, nofollow',
      jsonLd: [],
    })

    expect(meta('meta[name="robots"]')).toBe('noindex, nofollow')
    expect(document.getElementById('seo-jsonld')).toBeNull()
  })

  it('keeps a self-canonical public detail page followable while excluding it from indexing', () => {
    setSeo({
      title: '普通物理(一)｜PhysArchive',
      canonicalPath: '/courses/42',
      robots: 'noindex, follow',
    })

    expect(meta('meta[name="robots"]')).toBe('noindex, follow')
    expect(document.head.querySelector('link[rel="canonical"]')?.href).toMatch(/\/courses\/42$/)
  })
})
