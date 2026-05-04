/**
 * Shared markdown renderer for short admin-authored copy (plan descriptions,
 * etc.). Uses ``marked`` for parsing and ``DOMPurify`` for sanitisation so
 * untrusted HTML in the source can't escape into the page.
 *
 * Keep usage minimal: only rendered for fields documented as markdown in the
 * data model (e.g. ``description_md``).
 */
import { marked } from 'marked'
import DOMPurify from 'dompurify'

marked.setOptions({
  gfm: true,
  breaks: true,
})

export function renderMarkdown(source: string | null | undefined): string {
  if (!source) return ''
  const raw = marked.parse(source, { async: false }) as string
  return DOMPurify.sanitize(raw, {
    ALLOWED_TAGS: [
      'p', 'br', 'strong', 'em', 'u', 'code', 'pre',
      'ul', 'ol', 'li',
      'a', 'blockquote',
      'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
      'hr',
    ],
    ALLOWED_ATTR: ['href', 'title', 'target', 'rel'],
    ADD_ATTR: ['target'],
  })
}
