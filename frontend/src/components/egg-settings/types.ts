/**
 * Shared interface for all egg settings components.
 * Both EggSettingsSillyTavern and EggSettingsGeneric implement this contract.
 */

export interface StartupVar {
  envVariable: string
  name: string
  description: string
  defaultValue: string
  value: string
  isEditable: boolean
  rules: string | null
}

/** Props passed to every egg settings component */
export interface EggSettingsProps {
  serverId: number
  serverUuid: string
  eggName: string
  variables: StartupVar[]
}

/** Methods exposed by egg settings components via defineExpose */
export interface EggSettingsExpose {
  /** Save changes. Returns true on success. */
  save(): Promise<boolean>
  /** Discard unsaved changes, revert to last-saved state. */
  discard(): void
  /**
   * Optional list of short, already-localised validation error labels.
   * The parent feeds this directly into the DirtyBar `errors` prop, which
   * (a) disables the Save button and (b) renders the strings as chips.
   * Vue template refs auto-unwrap the underlying ComputedRef/Ref, so the
   * declared type here is plain `string[]`.
   */
  validationErrors?: string[]
}
