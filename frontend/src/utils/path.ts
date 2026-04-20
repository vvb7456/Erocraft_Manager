/**
 * File name / path validation utilities.
 */

const INVALID_FILENAME_CHARS = /[/\\:*?"<>|\0]/

/**
 * Validate a file or folder name (single segment, no path separators).
 * Returns an i18n error key suffix if invalid, or null if valid.
 */
export function validateFileName(name: string): string | null {
  const trimmed = name.trim()
  if (!trimmed) return 'emptyName'
  if (INVALID_FILENAME_CHARS.test(trimmed)) return 'invalidChars'
  if (trimmed === '.' || trimmed === '..') return 'reservedName'
  if (trimmed.length > 255) return 'nameTooLong'
  return null
}

/**
 * Sanitize a move target path — strip `.` and `..` segments, ensure leading `/`.
 */
export function sanitizeMovePath(path: string): string {
  return '/' + path.split('/').filter(s => s && s !== '..' && s !== '.').join('/')
}
