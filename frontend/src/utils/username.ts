export const USERNAME_RE = /^[A-Za-z0-9_.\-]{3,32}$/

export function isValidUsername(raw: string): boolean {
  return USERNAME_RE.test(raw.trim())
}
