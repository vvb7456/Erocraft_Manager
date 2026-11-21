export const USERNAME_RE = /^[A-Za-z0-9_.\-]{3,32}$/

export function isValidUsername(raw: string): boolean {
  return USERNAME_RE.test(raw.trim())
}

export function isValidEmail(raw: string): boolean {
  return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(raw.trim())
}

export function isValidVerificationCode(raw: string): boolean {
  return /^\d{6}$/.test(raw.trim())
}

export type PasswordErrorKind = '' | 'whitespace' | 'length'

export function passwordErrorKey(raw: string): PasswordErrorKind {
  if (!raw) return ''
  if (/\s/.test(raw)) return 'whitespace'
  const bytes = new TextEncoder().encode(raw).length
  if (raw.length < 8 || bytes > 72) return 'length'
  return ''
}
