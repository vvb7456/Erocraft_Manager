export interface ChatTextPart { text: string; href?: string; route?: string }

function trimPunctuation(value: string) {
  let result = value.replace(/[.,!?;:，。！？；：、]+$/u, '')
  const pairs: Record<string, string> = { ')': '(', ']': '[', '}': '{', '）': '（' }
  while (result) {
    const close = result[result.length - 1]!
    const open = pairs[close]
    if (!open || result.split(close).length <= result.split(open).length) break
    result = result.slice(0, -1).replace(/[.,!?;:，。！？；：、]+$/u, '')
  }
  return result
}

export function chatTextParts(text: string, origin: string, isRoute: (path: string) => boolean): ChatTextPart[] {
  const pattern = /https?:\/\/[^\s<>"'，。！？；、（）【】「」“”‘’\u200b-\u200f\u202a-\u202e]+|www\.[^\s<>"'，。！？；、（）【】「」“”‘’\u200b-\u200f\u202a-\u202e]+|(?:\/#\/|#\/|\/[a-zA-Z])[^\s<>"'，。！？；、（）【】「」“”‘’]*|[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}/gi
  const parts: ChatTextPart[] = []
  let cursor = 0
  for (const match of text.matchAll(pattern)) {
    const start = match.index!
    const value = trimPunctuation(match[0])
    if (start > cursor) parts.push({ text: text.slice(cursor, start) })
    const part: ChatTextPart = { text: value }
    if (/^(\/|#\/|www\.)/i.test(value) && start > 0 && /[\w/:]/.test(text[start - 1]!)) {
      parts.push(part)
      cursor = start + value.length
      continue
    }
    if (/^[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}$/.test(value)) {
      part.href = `mailto:${value}`
    } else {
      try {
        const url = new URL(value.startsWith('www.') ? `https://${value}` : value, `${origin}/`)
        if (['https:', 'http:'].includes(url.protocol) && !url.username && !url.password) {
          const route = url.hash.startsWith('#/') && url.pathname === '/' ? url.hash.slice(1) : `${url.pathname}${url.search}${url.hash}`
          if (url.origin === origin && route.startsWith('/') && !route.startsWith('//') && !route.includes('\\') && isRoute(route)) {
            part.href = url.href
            part.route = route
          } else if (/^(https?:\/\/|www\.)/i.test(value)) part.href = url.href
        }
      } catch { /* Invalid addresses remain plain text. */ }
    }
    parts.push(part)
    cursor = start + value.length
  }
  if (cursor < text.length) parts.push({ text: text.slice(cursor) })
  return parts
}
