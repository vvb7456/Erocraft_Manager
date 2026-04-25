<script setup lang="ts">
// SectionOwner — change server owner via PATCH /owner. Backend may return
// a "warning" field (Wings deauthorize failure); we surface that as a
// warning toast but still treat the save as successful since the panel
// owner change has committed.
import { ref, computed, watch, inject, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'
import { useDirtyFormSection } from '@/composables/useDirtyForm'
import CollapsibleGroup from '@/components/ui/CollapsibleGroup.vue'
import BaseCard from '@/components/ui/BaseCard.vue'
import FormField from '@/components/form/FormField.vue'
import UserSearchSelect from '@/components/admin-server/UserSearchSelect.vue'
import type { AdminServerDetailResponse } from '@/types/adminServer'

defineOptions({ name: 'SectionOwner' })

const { t } = useI18n({ useScope: 'global' })
const { raw } = useApiFetch()
const { toast } = useToast()
const { confirm } = useConfirm()

const detail = inject<Ref<AdminServerDetailResponse | null>>('adminServerDetail')!
const serverId = inject<Ref<number | null>>('adminServerId')!
const reload = inject<() => Promise<void>>('reloadAdminServer', async () => {})

const initialOwnerId = ref<number>(0)
const ownerId = ref<number>(0)
const syncing = ref(false)

function syncFromDetail() {
  syncing.value = true
  const id = detail.value?.owner.id ?? 0
  initialOwnerId.value = id
  ownerId.value = id
  syncing.value = false
}

const isDirty = computed(() => !syncing.value && ownerId.value !== initialOwnerId.value && ownerId.value > 0)

// Container polls detail every 30s; gate sync so an in-flight poll
// doesn't stomp pending edits and flash DirtyBar.
watch(detail, () => { if (!isDirty.value) syncFromDetail() }, { immediate: true, deep: false })

function discard() {
  ownerId.value = initialOwnerId.value
}

async function save(): Promise<boolean> {
  if (!isDirty.value || !serverId.value) return true
  // Destructive: switching owner invalidates the previous owner's Wings
  // tokens and force-logs them off any active console session.
  const ok = await confirm({
    title: t('adminServer.settings.owner.confirm.title'),
    message: t('adminServer.settings.owner.confirm.message'),
    variant: 'danger',
    confirmText: t('adminServer.settings.owner.confirm.confirmText'),
  })
  if (!ok) return false
  const res = await raw(`/api/admin/servers/${serverId.value}/owner`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ownerId: ownerId.value }),
  })
  if (!res) return false
  let body: { message?: string; warning?: string } = {}
  try { body = await res.json() } catch { /* ignore */ }
  toast(body.message || t('adminServer.settings.saved'), 'success')
  if (body.warning) {
    toast(t('adminServer.settings.owner.warning', { msg: body.warning }), 'warning')
  }
  await reload()
  return true
}

useDirtyFormSection({ name: 'owner', isDirty, save, discard })
</script>

<template>
  <BaseCard variant="bg2" class="settings-card">
    <CollapsibleGroup :title="t('adminServer.settings.owner.title')" icon="person" :defaultOpen="false">
      <div class="form">
        <FormField layout="horizontal" bordered>
          <template #label>{{ t('adminServer.settings.owner.current') }}</template>
          <span class="muted">
            {{ detail?.owner.username }} · {{ detail?.owner.email }}
          </span>
        </FormField>
        <FormField layout="horizontal" bordered>
          <template #label>{{ t('adminServer.settings.owner.select') }}</template>
          <UserSearchSelect v-model="ownerId" />
        </FormField>
      </div>
    </CollapsibleGroup>
  </BaseCard>
</template>

<style scoped>
.form > * + * { margin-top: var(--sp-2); }
.muted {
  color: var(--t2);
  font-size: var(--text-sm);
}
</style>
