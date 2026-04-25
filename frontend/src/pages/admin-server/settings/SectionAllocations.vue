<script setup lang="ts">
// SectionAllocations — chip-input editor for the server's port set.
// First chip = primary; deletions of existing allocations are treated as
// destructive (confirm gate). The ports list cannot be saved empty.
//
// Save order against backend (mirrors design doc):
//   1. POST /allocations  (so new ports exist before primary swap)
//   2. PUT  /allocations/primary  (only if primary id changed)
//   3. DELETE /allocations/{id}   (one-by-one; backend rejects deleting
//                                  the current primary, so we sequence
//                                  the swap first)
import { ref, computed, watch, inject, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'
import { useDirtyFormSection } from '@/composables/useDirtyForm'
import CollapsibleGroup from '@/components/ui/CollapsibleGroup.vue'
import BaseCard from '@/components/ui/BaseCard.vue'
import FormField from '@/components/form/FormField.vue'
import AllocationsChipInput from '@/components/admin-server/AllocationsChipInput.vue'
import type { AdminServerDetailResponse, ServerAllocationSummary } from '@/types/adminServer'

defineOptions({ name: 'SectionAllocations' })

const { t } = useI18n({ useScope: 'global' })
const { get, post, put, raw } = useApiFetch()
const { toast } = useToast()
const { confirm } = useConfirm()

const detail = inject<Ref<AdminServerDetailResponse | null>>('adminServerDetail')!
const serverId = inject<Ref<number | null>>('adminServerId')!
const reload = inject<() => Promise<void>>('reloadAdminServer', async () => {})

const initialChips = ref<ServerAllocationSummary[]>([])
const chips = ref<ServerAllocationSummary[]>([])
const available = ref<ServerAllocationSummary[]>([])
const syncing = ref(false)

function syncFromDetail() {
  syncing.value = true
  const all = detail.value?.allocations ?? []
  const primary = all.find(a => a.isPrimary)
  const extras = all.filter(a => !a.isPrimary).sort((a, b) => a.id - b.id)
  const ordered = primary ? [primary, ...extras] : [...extras]
  initialChips.value = ordered.map(a => ({ ...a }))
  chips.value = ordered.map(a => ({ ...a }))
  syncing.value = false
}

watch(serverId, async (id) => {
  if (!id) return
  const res = await get<{ allocations: ServerAllocationSummary[] }>(
    `/api/admin/servers/${id}/allocations/available`,
  )
  available.value = res?.allocations ?? []
}, { immediate: true })

const diff = computed(() => {
  const cur = chips.value
  const init = initialChips.value
  const curIds = new Set(cur.map(a => a.id))
  const initIds = new Set(init.map(a => a.id))
  const added = cur.filter(a => !initIds.has(a.id))
  const removed = init.filter(a => !curIds.has(a.id))
  const oldPrimary = init[0]?.id ?? 0
  const newPrimary = cur[0]?.id ?? 0
  const primaryChanged = oldPrimary !== newPrimary
  return { added, removed, primaryChanged, newPrimary, oldPrimary }
})

const isDirty = computed(() => {
  if (syncing.value) return false
  const d = diff.value
  return d.added.length > 0 || d.removed.length > 0 || d.primaryChanged
})

// Container polls detail every 30s; resetting the form mid-edit would
// stomp the user's pending changes (and make DirtyBar flash). Only
// re-sync when the section is *not* dirty. Declared after isDirty to
// avoid TDZ since the immediate callback fires synchronously.
watch(detail, () => { if (!isDirty.value) syncFromDetail() }, { immediate: true, deep: false })

const validationError = computed<string | null>(() => {
  if (chips.value.length === 0) {
    return t('adminServer.settings.allocations.errors.empty')
  }
  return null
})
defineExpose({ validationError })

function discard() { syncFromDetail() }

async function save(): Promise<boolean> {
  if (!isDirty.value || !serverId.value) return true
  if (validationError.value) {
    toast(validationError.value, 'error')
    return false
  }
  const sid = serverId.value
  const d = diff.value

  if (d.removed.length > 0 || d.primaryChanged) {
    const ok = await confirm({
      title: t('adminServer.settings.allocations.confirm.title'),
      message: t('adminServer.settings.allocations.confirm.message', {
        rm: d.removed.length, swap: d.primaryChanged ? 1 : 0,
      }),
      variant: 'danger',
      confirmText: t('adminServer.settings.allocations.confirm.confirmText'),
    })
    if (!ok) return false
  }

  if (d.added.length > 0) {
    const r = await post(`/api/admin/servers/${sid}/allocations`, {
      allocationIds: d.added.map(a => a.id),
    })
    if (r === null) return false
  }
  if (d.primaryChanged && d.newPrimary > 0) {
    const r = await put(`/api/admin/servers/${sid}/allocations/primary`, {
      allocationId: d.newPrimary,
    })
    if (r === null) return false
  }
  for (const a of d.removed) {
    const r = await raw(`/api/admin/servers/${sid}/allocations/${a.id}`, { method: 'DELETE' })
    if (!r) return false
  }
  toast(t('adminServer.settings.saved'), 'success')
  await reload()
  const ar = await get<{ allocations: ServerAllocationSummary[] }>(
    `/api/admin/servers/${sid}/allocations/available`,
  )
  available.value = ar?.allocations ?? []
  return true
}

useDirtyFormSection({ name: 'allocations', isDirty, save, discard })
</script>

<template>
  <BaseCard variant="bg2" class="settings-card">
    <CollapsibleGroup :title="t('adminServer.settings.allocations.title')" icon="lan" :defaultOpen="false">
      <div class="form">
        <FormField
          layout="vertical"
          bordered
          :hint="t('adminServer.settings.allocations.hint')"
          :error="isDirty ? (validationError || undefined) : undefined"
        >
          <template #label>{{ t('adminServer.settings.allocations.current') }}</template>
          <AllocationsChipInput v-model="chips" :available="available" />
        </FormField>
      </div>
    </CollapsibleGroup>
  </BaseCard>
</template>

<style scoped>
.form > * + * { margin-top: var(--sp-2); }
</style>
