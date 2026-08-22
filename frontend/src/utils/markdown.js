import { marked } from 'marked'
import DOMPurify from 'dompurify'

const ALLOWED_IMAGE_ALIGNMENTS = new Set(['left', 'center', 'right'])
const IMAGE_OPTIONS_PATTERN = /(<img\b[^>]*>)[ \t]*\{([^{}\r\n<>]*)\}/gi
const IMAGE_WIDTH_PATTERN = /^(?:[1-9]\d?(?:\.\d)?|100(?:\.0)?)%$/
const SANITIZED_IMAGE_PATTERN = /<img\b[^>]*>/gi
const IMAGE_WIDTH_ATTRIBUTE = 'data-about-us-image-width'
const IMAGE_ALIGNMENT_ATTRIBUTE = 'data-about-us-image-alignment'
const IMAGE_WRAP_ATTRIBUTE = 'data-about-us-image-wrap'

const validatedImageWidth = (value) => {
  if (!IMAGE_WIDTH_PATTERN.test(value)) return null
  const numericWidth = Number.parseFloat(value)
  return numericWidth >= 1 && numericWidth <= 100 ? value : null
}

const imageOptions = (options) => {
  let width = null
  let alignment = null
  let wrap = false
  for (const option of options.trim().split(/\s+/)) {
    const [name, value, extra] = option.split('=')
    if (extra !== undefined || !name || !value) continue
    if (name === 'width') width = validatedImageWidth(value)
    if (name === 'align' && ALLOWED_IMAGE_ALIGNMENTS.has(value)) {
      alignment = value
    }
    if (name === 'wrap' && value === 'true') wrap = true
  }
  return { alignment, width, wrap: wrap && (alignment === 'left' || alignment === 'right') }
}

const applyImageOptions = (html) =>
  html.replace(IMAGE_OPTIONS_PATTERN, (_, imageHtml, options) => {
    const { alignment, width, wrap } = imageOptions(options)
    if (!alignment && !width) return imageHtml
    const widthAttribute = width ? ` ${IMAGE_WIDTH_ATTRIBUTE}="${width}"` : ''
    const alignmentAttribute = alignment ? ` ${IMAGE_ALIGNMENT_ATTRIBUTE}="${alignment}"` : ''
    const wrapAttribute = wrap ? ` ${IMAGE_WRAP_ATTRIBUTE}="true"` : ''
    return imageHtml.replace(/>$/, `${widthAttribute}${alignmentAttribute}${wrapAttribute}>`)
  })

const sanitizedAttributeValue = (imageHtml, attribute) => {
  const match = imageHtml.match(new RegExp(`\\s${attribute}="([^"]*)"`, 'i'))
  return match?.[1] ?? null
}

const applySanitizedImageOptions = (html) =>
  html.replace(SANITIZED_IMAGE_PATTERN, (imageHtml) => {
    const width = validatedImageWidth(
      sanitizedAttributeValue(imageHtml, IMAGE_WIDTH_ATTRIBUTE) ?? ''
    )
    const rawAlignment = sanitizedAttributeValue(imageHtml, IMAGE_ALIGNMENT_ATTRIBUTE)
    const alignment = ALLOWED_IMAGE_ALIGNMENTS.has(rawAlignment) ? rawAlignment : null
    const wrap =
      sanitizedAttributeValue(imageHtml, IMAGE_WRAP_ATTRIBUTE) === 'true' &&
      (alignment === 'left' || alignment === 'right')
    const cleanImageHtml = imageHtml
      .replace(new RegExp(`\\s${IMAGE_WIDTH_ATTRIBUTE}="[^"]*"`, 'gi'), '')
      .replace(new RegExp(`\\s${IMAGE_ALIGNMENT_ATTRIBUTE}="[^"]*"`, 'gi'), '')
      .replace(new RegExp(`\\s${IMAGE_WRAP_ATTRIBUTE}="[^"]*"`, 'gi'), '')
    const classes = []
    if (alignment) classes.push(`about-us-image--align-${alignment}`)
    if (wrap) classes.push('about-us-image--wrap')
    const classAttribute = classes.length > 0 ? ` class="${classes.join(' ')}"` : ''
    const widthStyle = width ? ` style="width: ${width};"` : ''
    return cleanImageHtml.replace(/>$/, `${classAttribute}${widthStyle}>`)
  })

const sanitizeMarkdownHtml = (html) =>
  DOMPurify.sanitize(html, {
    ADD_ATTR: ['target', IMAGE_WIDTH_ATTRIBUTE, IMAGE_ALIGNMENT_ATTRIBUTE, IMAGE_WRAP_ATTRIBUTE],
    FORBID_ATTR: ['class', 'style'],
  })

// Configure marked options
marked.use({
  breaks: true,
  gfm: true,
  renderer: {
    link({ href, title, text }) {
      const safeHref = href ?? ''
      const titleAttr = title ? ` title="${title}"` : ''
      return `<a href="${safeHref}"${titleAttr} target="_blank" rel="noopener noreferrer">${text}</a>`
    },
  },
})

export const renderMarkdown = (markdown) => {
  if (!markdown) return ''
  try {
    const rawHtml = applyImageOptions(marked.parse(markdown))
    // Configure DOMPurify to allow target attribute when sanitizing
    return applySanitizedImageOptions(sanitizeMarkdownHtml(rawHtml))
  } catch (error) {
    console.error('Markdown render error:', error)
    return sanitizeMarkdownHtml(markdown)
  }
}
