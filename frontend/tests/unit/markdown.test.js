import { describe, it, expect } from 'vitest'
import { renderMarkdown } from '@/utils/markdown'

describe('markdown utility', () => {
  it('renders basic markdown text', () => {
    const result = renderMarkdown('Hello **world**')
    expect(result).toContain('<strong>world</strong>')
  })

  it('renders markdown links with target="_blank"', () => {
    const result = renderMarkdown('[GitHub](https://github.com)')
    expect(result).toContain('href="https://github.com"')
    expect(result).toContain('target="_blank"')
    expect(result).toContain('rel="noopener noreferrer"')
    expect(result).toContain('>GitHub</a>')
  })

  it('renders markdown with line breaks (GFM)', () => {
    const result = renderMarkdown('Line 1\nLine 2')
    expect(result).toContain('<br>')
  })

  it('renders markdown headers', () => {
    expect(renderMarkdown('# Heading 1')).toContain('<h1')
    expect(renderMarkdown('## Heading 2')).toContain('<h2')
    expect(renderMarkdown('### Heading 3')).toContain('<h3')
  })

  it('renders markdown lists', () => {
    const unordered = renderMarkdown('- Item 1\n- Item 2')
    expect(unordered).toContain('<ul>')
    expect(unordered).toContain('<li>Item 1</li>')

    const ordered = renderMarkdown('1. First\n2. Second')
    expect(ordered).toContain('<ol>')
    expect(ordered).toContain('<li>First</li>')
  })

  it('renders markdown code blocks', () => {
    const inline = renderMarkdown('Use `console.log()` function')
    expect(inline).toContain('<code>console.log()</code>')

    const block = renderMarkdown('```js\nconst x = 1\n```')
    expect(block).toContain('<pre>')
    expect(block).toContain('<code')
  })

  it('renders markdown blockquotes', () => {
    const result = renderMarkdown('> This is a quote')
    expect(result).toContain('<blockquote>')
    expect(result).toContain('This is a quote')
  })

  it('renders standard Markdown images with alt text and safe URLs', () => {
    const result = renderMarkdown('![NTHU Physics](https://example.com/physics.jpg)')
    expect(result).toContain('<img')
    expect(result).toContain('src="https://example.com/physics.jpg"')
    expect(result).toContain('alt="NTHU Physics"')
    expect(renderMarkdown('![unsafe](javascript:alert(1))')).not.toContain('javascript:')
  })

  it.each(['1', '20', '42', '58.5', '99.9', '100'])(
    'applies the validated %s%% image width',
    (width) => {
      const result = renderMarkdown(`![Campus](https://example.com/campus.jpg){width=${width}%}`)
      expect(result).toContain(`style="width: ${width}%;"`)
      expect(result).toContain('alt="Campus"')
    }
  )

  it.each(['left', 'center', 'right'])(
    'applies the allowed %s image alignment class',
    (alignment) => {
      const result = renderMarkdown(
        `![Campus](https://example.com/campus.jpg){width=50% align=${alignment}}`
      )
      expect(result).toContain('style="width: 50%;"')
      expect(result).toContain(`about-us-image--align-${alignment}`)
    }
  )

  it('ignores unsupported and malicious image options without emitting attributes', () => {
    const result = renderMarkdown(
      '![Campus](https://example.com/campus.jpg){width=150% align=fixed style="position:absolute" onclick=alert(1)}'
    )
    expect(result).toContain('<img')
    expect(result).not.toContain('style=')
    expect(result).not.toContain('about-us-image--align-fixed')
    expect(result).not.toContain('onclick=')
    expect(result).not.toContain('position:absolute')
  })

  it('keeps valid options while discarding unknown image options', () => {
    const result = renderMarkdown(
      '![Campus](https://example.com/campus.jpg){width=50% align=center data-test=unsafe}'
    )
    expect(result).toContain('style="width: 50%;"')
    expect(result).toContain('about-us-image--align-center')
    expect(result).not.toContain('data-test')
  })

  it.each(['left', 'right'])('enables wrapping for %s-aligned images', (alignment) => {
    const result = renderMarkdown(
      `![Campus](https://example.com/campus.jpg){width=33% align=${alignment} wrap=true}`
    )
    expect(result).toContain(`about-us-image--align-${alignment}`)
    expect(result).toContain('about-us-image--wrap')
  })

  it('does not wrap centered images even when wrap=true is requested', () => {
    const result = renderMarkdown(
      '![Campus](https://example.com/campus.jpg){width=50% align=center wrap=true}'
    )
    expect(result).toContain('about-us-image--align-center')
    expect(result).not.toContain('about-us-image--wrap')
  })

  it('ignores invalid wrap values and arbitrary class attributes', () => {
    const result = renderMarkdown(
      '![Campus](https://example.com/campus.jpg){width=33% align=right wrap=javascript class="anything"}'
    )
    expect(result).toContain('style="width: 33%;"')
    expect(result).toContain('about-us-image--align-right')
    expect(result).not.toContain('about-us-image--wrap')
    expect(result).not.toContain('anything')
  })

  it.each(['0%', '100.1%', '150%', '42px', '20rem', '10vw', 'calc(50%)', 'auto'])(
    'rejects invalid image width %s',
    (width) => {
      const result = renderMarkdown(`![Campus](https://example.com/campus.jpg){width=${width}}`)
      expect(result).toContain('<img')
      expect(result).not.toContain('style=')
    }
  )

  it.each(['left', 'right'])('combines a flexible width with %s text wrapping', (alignment) => {
    const result = renderMarkdown(
      `![Campus](https://example.com/campus.jpg){width=58.5% align=${alignment} wrap=true}`
    )
    expect(result).toContain('style="width: 58.5%;"')
    expect(result).toContain(`about-us-image--align-${alignment}`)
    expect(result).toContain('about-us-image--wrap')
  })

  it('sanitizes potentially dangerous HTML', () => {
    const result = renderMarkdown('<script>alert("xss")</script>')
    expect(result).not.toContain('<script>')
    expect(result).not.toContain('alert')
  })

  it('does not preserve user-supplied style or class attributes from raw HTML', () => {
    const result = renderMarkdown(
      '<img src="https://example.com/image.jpg" style="position:absolute" class="anything">'
    )
    expect(result).toContain('<img')
    expect(result).not.toContain('style=')
    expect(result).not.toContain('class=')
    expect(result).not.toContain('position:absolute')
    expect(result).not.toContain('anything')
  })

  it('handles empty or null input', () => {
    expect(renderMarkdown('')).toBe('')
    expect(renderMarkdown(null)).toBe('')
    expect(renderMarkdown(undefined)).toBe('')
  })

  it('renders complex markdown with multiple elements', () => {
    const result = renderMarkdown(
      'This is **bold** and *italic* text with a [link](https://example.com)'
    )

    expect(result).toContain('<strong>bold</strong>')
    expect(result).toContain('<em>italic</em>')
    expect(result).toContain('href="https://example.com"')
    expect(result).toContain('target="_blank"')
  })

  it('handles markdown with special characters', () => {
    const result = renderMarkdown('Text with & < > " characters')
    expect(result).toContain('&amp;')
    expect(result).toContain('&lt;')
    expect(result).toContain('&gt;')
  })

  it('preserves links with query parameters', () => {
    const result = renderMarkdown('[Link](https://example.com?foo=bar&baz=qux)')
    expect(result).toContain('href="https://example.com?foo=bar&amp;baz=qux"')
    expect(result).toContain('target="_blank"')
  })

  it('renders markdown tables', () => {
    const table = `| Header 1 | Header 2 |
| -------- | -------- |
| Cell 1   | Cell 2   |
| Cell 3   | Cell 4   |`
    const result = renderMarkdown(table)
    expect(result).toContain('<table>')
    expect(result).toContain('<thead>')
    expect(result).toContain('<th>')
    expect(result).toContain('<tbody>')
    expect(result).toContain('<td>')
    expect(result).toContain('Header 1')
    expect(result).toContain('Cell 1')
  })

  it('renders horizontal rules', () => {
    const result = renderMarkdown('Content above\n\n---\n\nContent below')
    expect(result).toContain('<hr')
    expect(result).toContain('Content above')
    expect(result).toContain('Content below')
  })
})
