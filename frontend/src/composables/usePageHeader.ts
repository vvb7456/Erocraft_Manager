import { inject, provide, shallowRef, type InjectionKey, type ShallowRef } from 'vue'

const actionsKey: InjectionKey<ShallowRef<HTMLElement | null>> = Symbol('page-header-actions')

export function providePageHeader() {
  provide(actionsKey, shallowRef<HTMLElement | null>(null))
}

export function usePageHeaderActions() {
  const target = inject(actionsKey)
  if (!target) throw new Error('Missing page header provider')
  return target
}
