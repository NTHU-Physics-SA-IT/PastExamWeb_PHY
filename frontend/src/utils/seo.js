export const SITE_URL = (
  import.meta.env.VITE_SITE_HOSTNAME ||
  (typeof window !== 'undefined'
    ? window.location.origin
    : 'https://physarchive.com')
).replace(/\/+$/, '')

export const DEFAULT_TITLE =
  '清大考古題｜清大物理系歷屆考題與解答｜PhysArchive'

export const DEFAULT_DESCRIPTION =
  '清大物理考古題整理平台，收錄普通物理、電磁學、理論力學、量子物理等課程的歷屆考題、解答與課程資料。'

function absoluteUrl(value = '/') {
  if (/^https?:\/\//i.test(value)) {
    return value
  }

  const path = value.startsWith('/') ? value : `/${value}`
  return `${SITE_URL}${path}`
}

function upsertMeta(attribute, key, content) {
  if (!content || typeof document === 'undefined') return

  let element = document.head.querySelector(
    `meta[${attribute}="${key}"]`
  )

  if (!element) {
    element = document.createElement('meta')
    element.setAttribute(attribute, key)
    document.head.appendChild(element)
  }

  element.setAttribute('content', content)
}

function setCanonical(url) {
  if (typeof document === 'undefined') return

  let canonical = document.head.querySelector(
    'link[rel="canonical"]'
  )

  if (!canonical) {
    canonical = document.createElement('link')
    canonical.setAttribute('rel', 'canonical')
    document.head.appendChild(canonical)
  }

  canonical.setAttribute('href', url)
}

function setJsonLd(items) {
  if (typeof document === 'undefined') return

  const existing = document.getElementById('seo-jsonld')

  if (!Array.isArray(items) || items.length === 0) {
    existing?.remove()
    return
  }

  const script = existing || document.createElement('script')
  script.id = 'seo-jsonld'
  script.type = 'application/ld+json'
  script.textContent = JSON.stringify({
    '@context': 'https://schema.org',
    '@graph': items,
  })

  if (!existing) {
    document.head.appendChild(script)
  }
}

export function setSeo({
  title = DEFAULT_TITLE,
  description = DEFAULT_DESCRIPTION,
  canonicalPath = '/',
  robots = 'index, follow',
  image = '/og-image.png',
  jsonLd = [],
} = {}) {
  if (typeof document === 'undefined') return

  const canonicalUrl = absoluteUrl(canonicalPath)
  const imageUrl = absoluteUrl(image)

  document.title = title

  upsertMeta('name', 'title', title)
  upsertMeta('name', 'description', description)
  upsertMeta('name', 'robots', robots)

  upsertMeta('property', 'og:type', 'website')
  upsertMeta('property', 'og:site_name', 'PhysArchive')
  upsertMeta('property', 'og:title', title)
  upsertMeta('property', 'og:description', description)
  upsertMeta('property', 'og:url', canonicalUrl)
  upsertMeta('property', 'og:image', imageUrl)

  upsertMeta('name', 'twitter:card', 'summary_large_image')
  upsertMeta('name', 'twitter:title', title)
  upsertMeta('name', 'twitter:description', description)
  upsertMeta('name', 'twitter:image', imageUrl)

  setCanonical(canonicalUrl)
  setJsonLd(jsonLd)
}

export function applyRouteSeo(route) {
  const routeSeo = route.meta?.seo || {}
  const protectedRoute = Boolean(
    route.meta?.requiresAuth || route.meta?.requiresAdmin
  )

  setSeo({
    title: routeSeo.title || DEFAULT_TITLE,
    description:
      routeSeo.description || DEFAULT_DESCRIPTION,
    canonicalPath:
      routeSeo.canonicalPath || route.path || '/',
    robots:
      routeSeo.robots ||
      (protectedRoute
        ? 'noindex, nofollow'
        : 'index, follow'),
    image: routeSeo.image || '/og-image.png',
    jsonLd: routeSeo.jsonLd || [],
  })
}