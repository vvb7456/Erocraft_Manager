<script setup lang="ts">
// SectionDetails — name / description / external_id.
// Saves via PATCH /api/admin/servers/{id}/details. Sends only the fields
// that actually changed so the backend's "no fields" guard doesn't fire.
import { ref, computed, watch, inject, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import { useDirtyFormSection } from '@/composables/useDirtyForm'
import CollapsibleGroup from '@/components/ui/CollapsibleGroup.vue'
import BaseCard from '@/components/ui/BaseCard.vue'
import FormField from '@/components/form/FormField.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import BaseTextarea from '@/components/form/BaseTextarea.vue'
import HelpTip from '@/components/ui/HelpTip.vue'
import type { AdminServerDetailResponse } from '@/types/adminServer'

defineOptions({ name: 'SectionDetails' })

const { t } = useI18n({ useScope: 'global' })
const { raw } = useApiFetch()
const { toast } = useToast()

const detail = inject<Ref<AdminServerDetailResponse | null>>('adminServerDetail')!
const serverId = inject<Ref<number | null>>('adminServerId')!
const reload = inject<() => Promise<void>>('reloadAdminServer', async () => {})

interface Form { name: string; description: string; externalId: string }

const initial = ref<Form>({ name: '', description: '', externalId: '' })
const form = ref<Form>({ name: '', description: '', externalId: '' })
const syncing = ref(false)

function syncFromDetail() {
  const s = detail.value?.server
  if (!s) return
  syncing.value = true
  const f: Form = {
    name: s.name,
    description: s.description ?? '',
    externalId: s.externalId ?? '',
  }
  form.value = { ...f }
  initial.value = { ...f }
  syncing.value = false
}

const isDirty = computed(() => {
  if (syncing.value) return false
  const a = form.value, b = initial.value
  return a.name !== b.name || a.description !== b.description || a.externalId !== b.externalId
})

// Container polls detail every 30s; gate sync on !isDirty so a poll
// arriving mid-edit doesn't stomp the form (DirtyBar would flash).
watch(detail, () => { if (!isDirty.value) syncFromDetail() }, { immediate: true, deep: false })

function discard() {
  form.value = { ...initial.value }
}

async function save(): Promise<boolean> {
  if (!isDirty.value || !serverId.value) return true
  if (form.value.name.trim().length === 0) {
    toast(t('adminServer.settings.saveFailed'), 'error')
    return false
  }
  const body: Record<string, unknown> = {}
  if (form.value.name !== initial.value.name) body.name = form.value.name.trim()
  if (form.value.description !== initial.value.description) body.description = form.value.description
  if (form.value.externalId !== initial.value.externalId) {
    body.externalId = form.value.externalId.trim() === '' ? null : form.value.externalId.trim()
  }
  const res = await raw(`/api/admin/servers/${serverId.value}/details`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res) return false
  toast(t('adminServer.settings.saved'), 'success')
  await reload()
  // The detail watcher skips re-sync while isDirty is true to avoid
  // stomping unsaved edits, so we must reset the baseline explicitly
  // after a successful save — otherwise DirtyBar stays visible and the
  // leave-guard prompt fires.
  syncFromDetail()
  return true
}

useDirtyFormSection({ name: 'details', isDirty, save, discard })
</script>

<template>
  <BaseCard variant="bg2" class="settings-card">
    <CollapsibleGroup :title="t('adminServer.settings.details.title')" icon="info" :defaultOpen="true">
      <div class="form">
        <FormField layout="horizontal" bordered>
          <template #label>{{ t('adminServer.settings.details.name') }}</template>
          <BaseInput v-model="form.name" />
        </FormField>
        <FormField layout="horizontal" bordered>
          <template #label>{{ t('adminServer.settings.details.description') }}</template>
          <BaseTextarea v-model="form.description" :rows="2" />
        </FormField>
        <FormField layout="horizontal" bordered>
          <template #label>
            {{ t('adminServer.settings.details.externalId') }}
            <HelpTip :text="t('adminServer.settings.details.externalIdHint')" />
          </template>
          <BaseInput v-model="form.externalId" />
        </FormField>
      </div>
    </CollapsibleGroup>
  </BaseCard>
</template>

<style scoped>
.form > * + * { margin-top: var(--sp-2); }
</style>
