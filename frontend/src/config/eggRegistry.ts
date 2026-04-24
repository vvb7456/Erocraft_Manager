/**
 * Egg preset registry — maps egg names to custom settings components and metadata.
 * Uses egg name (not egg_id) as the key since IDs may change on re-import.
 */
import { defineAsyncComponent, type Component } from 'vue'

// ── Per-egg settings component registry ──

const registry: Record<string, () => Promise<Component>> = {
  SillyTavern: () => import('@/components/egg-settings/EggSettingsSillyTavern.vue'),
  // Future:
  // 'Paper': () => import('@/components/egg-settings/EggSettingsMinecraft.vue'),
}

// ── Per-egg metadata ──

export interface EggMeta {
  /** Show "Open App" button for servers with this egg */
  hasWebUi?: boolean
  /** Env vars hidden from the generic settings form */
  hiddenVars?: string[]
  /** Env vars whose values should be masked in activity logs */
  secretVars?: string[]
  /** Label shown on the Settings tab and "Open" button (e.g. "SillyTavern"). Fallback: undefined → generic */
  label?: string
}

const EGG_META: Record<string, EggMeta> = {
  SillyTavern: {
    hasWebUi: true,
    hiddenVars: ['FORCE_REINSTALL'],
    secretVars: ['PASSWORD'],
    label: 'SillyTavern',
  },
}

// ── Public API ──

/**
 * Get the settings component for a given egg name.
 * Returns the custom preset component if registered, otherwise the generic auto-form.
 */
export function getEggSettingsComponent(eggName: string): Component {
  const loader = registry[eggName]
  if (loader) {
    return defineAsyncComponent(loader as () => Promise<{ default: Component }>)
  }
  return defineAsyncComponent(
    () => import('@/components/egg-settings/EggSettingsGeneric.vue') as Promise<{ default: Component }>,
  )
}

/** Check if this egg has a custom preset (not using generic fallback). */
export function hasPreset(eggName: string): boolean {
  return eggName in registry
}

/** Get metadata for an egg. Returns empty object for unknown eggs. */
export function getEggMeta(eggName: string): EggMeta {
  return EGG_META[eggName] ?? {}
}

/** Check if servers with this egg expose a web UI. */
export function hasWebUi(eggName: string): boolean {
  return EGG_META[eggName]?.hasWebUi ?? false
}
