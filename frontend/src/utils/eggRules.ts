// eggRules — minimal Laravel-style rule parser + validator for Pterodactyl
// egg variable rules (e.g. "required|string|max:128|in:server.jar,minecraft_server.jar").
//
// Returns null when the value passes; otherwise an i18n key path inside
// adminServer.settings.startup.varErrors.* so UI can surface a friendly
// message. Unknown rules are silently ignored — backend remains the source
// of truth and will reject anything we let slip.
//
// We treat empty string as "absent" for required/nullable arbitration —
// matches Laravel semantics and lets users blank optional fields.

export type RuleError = { key: string; params?: Record<string, string | number> }

function parseRules(rules: string | null | undefined): string[] {
  if (!rules) return []
  return rules.split('|').map(r => r.trim()).filter(Boolean)
}

function isEmpty(v: string): boolean {
  return v === ''
}

export function validateVariable(value: string, rulesStr: string | null | undefined): RuleError | null {
  const rules = parseRules(rulesStr)
  const required = rules.includes('required')
  const nullable = rules.includes('nullable') || rules.includes('sometimes')

  if (isEmpty(value)) {
    if (required) return { key: 'required' }
    if (nullable) return null
    // No required, no nullable → empty is OK
    return null
  }

  for (const rule of rules) {
    if (rule === 'required' || rule === 'nullable' || rule === 'sometimes') continue

    if (rule === 'string') {
      // strings are always strings here; nothing to check
      continue
    }
    if (rule === 'integer') {
      if (!/^-?\d+$/.test(value)) return { key: 'integer' }
      continue
    }
    if (rule === 'numeric') {
      if (Number.isNaN(Number(value))) return { key: 'numeric' }
      continue
    }
    if (rule === 'boolean') {
      if (!['0', '1', 'true', 'false'].includes(value.toLowerCase())) return { key: 'boolean' }
      continue
    }
    if (rule === 'alpha_num') {
      if (!/^[a-zA-Z0-9]+$/.test(value)) return { key: 'alpha_num' }
      continue
    }
    if (rule === 'alpha_dash') {
      if (!/^[a-zA-Z0-9_-]+$/.test(value)) return { key: 'alpha_dash' }
      continue
    }
    if (rule === 'url') {
      try { new URL(value) } catch { return { key: 'url' } }
      continue
    }
    if (rule.startsWith('in:')) {
      const allowed = rule.slice(3).split(',').map(s => s.trim())
      if (!allowed.includes(value)) return { key: 'in', params: { allowed: allowed.join(', ') } }
      continue
    }
    if (rule.startsWith('not_in:')) {
      const banned = rule.slice(7).split(',').map(s => s.trim())
      if (banned.includes(value)) return { key: 'not_in' }
      continue
    }
    const sizeMatch = rule.match(/^(min|max|size):(\d+)$/)
    if (sizeMatch) {
      const op = sizeMatch[1]
      const n = Number(sizeMatch[2])
      // Pterodactyl egg variables are strings so size = length
      const len = value.length
      if (op === 'min' && len < n) return { key: 'min', params: { n } }
      if (op === 'max' && len > n) return { key: 'max', params: { n } }
      if (op === 'size' && len !== n) return { key: 'size', params: { n } }
      continue
    }
    const between = rule.match(/^between:(\d+),(\d+)$/)
    if (between) {
      const lo = Number(between[1]), hi = Number(between[2])
      const len = value.length
      if (len < lo || len > hi) return { key: 'between', params: { lo, hi } }
      continue
    }
    if (rule.startsWith('regex:')) {
      // Laravel regex: /pattern/flags. We accept the pattern as-is.
      const body = rule.slice(6)
      // Strip leading/trailing slash + flags
      const m = body.match(/^\/(.*)\/([a-z]*)$/)
      try {
        const re = m ? new RegExp(m[1], m[2]) : new RegExp(body)
        if (!re.test(value)) return { key: 'regex' }
      } catch {
        // Invalid regex on our side — defer to backend
      }
      continue
    }
    // Unknown rule — silently skip
  }
  return null
}
