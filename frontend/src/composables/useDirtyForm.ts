// useDirtyForm — share a single "unsaved changes" UX across a page that is
// composed of multiple sub-forms (sections).
//
// Pattern:
//   - The page calls `provideDirtyForm()` once, mounts <DirtyBar> bound to
//     the returned group state, and calls `attachLeaveGuard()` so the
//     ConfirmDialog (save / discard / stay) fires from a single place.
//   - Each section calls `useDirtyFormSection({ isDirty, save, discard })`
//     to register its local state. Sections never own DirtyBars themselves.
//
// `save` runs registered sections sequentially; if any returns false, the
// chain aborts and the bar stays open so the user can react. `discard`
// always runs every section unconditionally.
import { computed, getCurrentInstance, inject, onBeforeUnmount, provide, ref, shallowReactive, type ComputedRef, type Ref } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate, type RouteLocationNormalized } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useConfirm } from '@/composables/useConfirm'

export interface DirtyFormSection {
  busy?: Ref<boolean> | ComputedRef<boolean>
  // Reactive flag; the section is considered dirty whenever .value is true.
  isDirty: Ref<boolean> | ComputedRef<boolean>
  // Persist current edits. Resolve to true on success / no-op, false on
  // failure (so the parent can keep the bar open and abort leave-guard).
  save: () => Promise<boolean> | boolean
  // Roll local state back to the last saved snapshot. Should never throw.
  discard: () => void | Promise<void>
  // Optional debug label.
  name?: string
}

interface LeaveGuardOptions {
  update?: boolean | ((to: RouteLocationNormalized, from: RouteLocationNormalized) => boolean)
}

export interface DirtyFormGroup {
  isDirty: ComputedRef<boolean>
  saving: Ref<boolean>
  save: () => Promise<boolean>
  discard: () => Promise<void>
  register: (section: DirtyFormSection) => void
  unregister: (section: DirtyFormSection) => void
  attachLeaveGuard: (options?: LeaveGuardOptions) => void
  allowLeave: () => Promise<boolean>
  // Reusable three-outcome ConfirmDialog. Pages that intercept their own
  // navigation (e.g. SettingsPage's tab switcher) should call this to keep
  // the prompt UX identical to the route-leave guard.
  promptUnsaved: () => Promise<'save' | 'discard' | 'stay'>
}

export interface ProvideDirtyFormOptions {
  // Override the three-outcome prompt entirely (text or short-circuit
  // behaviour). Receives the live group so callers can inspect e.g. error
  // state. Returns 'save' | 'discard' | 'stay'.
  prompt?: (group: { isDirty: ComputedRef<boolean> }) => Promise<'save' | 'discard' | 'stay'>
}

const DIRTY_FORM_KEY = Symbol('DirtyFormGroup') as symbol
const activeGuards = new Set<DirtyFormGroup>()

export async function confirmPendingChanges(): Promise<boolean> {
  for (const group of activeGuards) if (!await group.allowLeave()) return false
  return true
}

export function useParentDirtyForm(): DirtyFormGroup {
  const group = inject<DirtyFormGroup>(DIRTY_FORM_KEY)
  if (!group) throw new Error('Missing dirty form provider')
  return group
}

export function provideDirtyForm(options: ProvideDirtyFormOptions = {}): DirtyFormGroup {
  // shallowReactive avoids unwrapping the inner Ref<boolean> on isDirty.
  const sections = shallowReactive<DirtyFormSection[]>([])
  const saving = ref(false)
  const { t } = useI18n({ useScope: 'global' })
  const { confirm } = useConfirm()

  const isDirty = computed(() => sections.some(s => !!s.isDirty.value))

  function register(section: DirtyFormSection) {
    sections.push(section)
  }
  function unregister(section: DirtyFormSection) {
    const i = sections.indexOf(section)
    if (i >= 0) sections.splice(i, 1)
  }

  async function save(): Promise<boolean> {
    if (saving.value || sections.some(section => section.busy?.value)) return false
    saving.value = true
    try {
      // Snapshot the array because a section's save may trigger a reload
      // that could in theory reorder registrations.
      const list = sections.slice()
      for (const s of list) {
        if (!s.isDirty.value) continue
        const ok = await s.save()
        if (ok === false) return false
      }
      return !isDirty.value
    } finally {
      saving.value = false
    }
  }

  async function discard(): Promise<void> {
    if (saving.value || sections.some(section => section.busy?.value)) return
    for (const s of sections.slice()) {
      if (!s.isDirty.value) continue
      await s.discard()
    }
  }

  // Three-outcome unsaved-changes prompt. Returns the user's choice rather
  // than a boolean so the leave-guard can distinguish "discard" from
  // "stay on page" without an extra round-trip. Pages can pass a custom
  // prompt() in options to swap text or short-circuit (e.g. when a form
  // has validation errors and "save" must be hidden).
  async function promptUnsaved(): Promise<'save' | 'discard' | 'stay'> {
    if (options.prompt) return options.prompt({ isDirty })
    const r = await confirm({
      title: t('settings.unsavedTitle'),
      message: t('settings.unsavedMessage'),
      confirmText: t('settings.unsavedSave'),
      cancelText: t('settings.unsavedStay'),
      altText: t('settings.unsavedDiscard'),
    })
    if (r === 'alt') return 'discard'
    return r === true ? 'save' : 'stay'
  }

  let deciding = false
  async function allowLeave(): Promise<boolean> {
    if (saving.value || deciding || sections.some(section => section.busy?.value)) return false
    if (!isDirty.value) return true
    deciding = true
    try {
      const choice = await promptUnsaved()
      if (choice === 'stay') return false
      if (choice === 'save') return await save()
      await discard()
      return !isDirty.value
    } catch {
      return false
    } finally { deciding = false }
  }

  let attached = false
  function attachLeaveGuard(options: LeaveGuardOptions = {}) {
    if (attached) return
    attached = true
    activeGuards.add(group)
    onBeforeRouteLeave(allowLeave)
    onBeforeRouteUpdate((to, from) => {
      const update = typeof options.update === 'function' ? options.update(to, from) : options.update
      return update || JSON.stringify(to.params) !== JSON.stringify(from.params) ? allowLeave() : true
    })
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (isDirty.value || saving.value || sections.some(section => section.busy?.value)) {
        event.preventDefault()
        event.returnValue = ''
      }
    }
    if (typeof window !== 'undefined') window.addEventListener('beforeunload', beforeUnload)
    onBeforeUnmount(() => {
      activeGuards.delete(group)
      if (typeof window !== 'undefined') window.removeEventListener('beforeunload', beforeUnload)
    })
  }

  const group: DirtyFormGroup = {
    isDirty, saving, save, discard, register, unregister, attachLeaveGuard, promptUnsaved, allowLeave,
  }
  provide(DIRTY_FORM_KEY, group)
  return group
}

// Section-side hook. Auto-registers on setup and auto-unregisters on
// unmount so sections behind v-if (e.g. wings_node-only panes) participate
// only while mounted.
//
// `group` is optional: when omitted we inject from the parent (the usual
// child-section case). When the page that called `provideDirtyForm()`
// also wants to register itself as a section, it MUST pass its own group
// — Vue's inject() does not see same-component provide().
export function useDirtyFormSection(section: DirtyFormSection, group?: DirtyFormGroup): void {
  const g = group ?? inject<DirtyFormGroup | null>(DIRTY_FORM_KEY, null)
  if (!g) {
    // Not fatal — running in a page without a provider just means the
    // section behaves standalone. Surface in dev to catch wiring mistakes.
    if (import.meta.env.DEV) {
      console.warn('[useDirtyFormSection] no DirtyFormGroup provided in parent')
    }
    return
  }
  g.register(section)
  // Use Vue's instance-bound unmount hook so this works inside child
  // components without leaking.
  if (getCurrentInstance()) {
    onBeforeUnmount(() => g.unregister(section))
  }
}
