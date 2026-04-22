/** Mapping helpers between backend locale codes and frontend i18n keys.
 *
 * The Pterodactyl panel stores locale as a short code without a region
 * (`'en'` or `'zh'`) — that's also what its own LanguageMiddleware
 * consumes. Our vue-i18n setup uses BCP-47 keys with a region (`'en'` or
 * `'zh-CN'`). Centralise the conversion so adding ``zh-TW`` or ``ja`` later
 * only touches one file.
 */

export type BackendLocale = 'en' | 'zh'
export type FrontendLocale = 'en' | 'zh-CN'

/** Convert a backend locale (`users.language`) to the vue-i18n key. */
export function backendToFrontendLocale(value: unknown): FrontendLocale {
  return value === 'zh' ? 'zh-CN' : 'en'
}

/** Convert a vue-i18n key to the backend `users.language` value. */
export function frontendToBackendLocale(value: string): BackendLocale {
  return value === 'zh-CN' ? 'zh' : 'en'
}
