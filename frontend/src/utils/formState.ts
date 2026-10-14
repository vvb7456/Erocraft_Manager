export function formSnapshot(value: unknown): string {
  return JSON.stringify(value, (_, entry) => {
    if (!entry || typeof entry !== 'object' || Array.isArray(entry)) return entry
    return Object.fromEntries(Object.keys(entry).sort().map(key => [key, entry[key]]))
  }) ?? ''
}

export function sameFormValue(left: unknown, right: unknown): boolean {
  return formSnapshot(left) === formSnapshot(right)
}

export function restoreScalarValue(value: string | number | boolean, original: unknown): unknown {
  const comparable = typeof value === 'boolean' ? original === true || original === 'true' || original === '1'
    : typeof value === 'number' ? Number(original ?? 0) : String(original ?? '')
  return value === comparable ? original : value
}
