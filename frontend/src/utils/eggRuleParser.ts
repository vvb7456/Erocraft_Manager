/**
 * Parse Pterodactyl egg_variables `rules` field into form control metadata.
 *
 * Supported rule patterns:
 *   - `required`        → field is required
 *   - `in:true,false`   → boolean toggle
 *   - `in:v1,v2,...`    → select dropdown
 *   - env var matching /password|secret|token/i → password input
 *   - everything else   → text input
 */

export type FieldType = 'toggle' | 'select' | 'text' | 'password'

export interface SelectOption {
  value: string
  label: string
}

export interface ParsedRule {
  required: boolean
  type: FieldType
  options?: SelectOption[]
}

/**
 * Parse a Pterodactyl `rules` string + env variable name into a form field descriptor.
 *
 * @param rules - The `rules` field from egg_variables (e.g. "required|string|in:true,false")
 * @param envVar - The `env_variable` name (used for type heuristics, e.g. PASSWORD → password input)
 */
export function parseRules(rules: string | null | undefined, envVar: string): ParsedRule {
  const parts = (rules ?? '').split('|').map(p => p.trim()).filter(Boolean)
  const required = parts.includes('required')

  // Check for `in:...` rule
  const inPart = parts.find(p => p.startsWith('in:'))
  if (inPart) {
    const values = inPart.slice(3).split(',').map(v => v.trim())
    // Boolean toggle: exactly {true, false}
    if (
      values.length === 2
      && values.includes('true')
      && values.includes('false')
    ) {
      return { required, type: 'toggle' }
    }
    // Select dropdown for other enum values
    return {
      required,
      type: 'select',
      options: values.map(v => ({ value: v, label: v })),
    }
  }

  // Heuristic: env var name suggests a secret
  if (/password|secret|token/i.test(envVar)) {
    return { required, type: 'password' }
  }

  return { required, type: 'text' }
}
