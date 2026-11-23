<script setup lang="ts">
// SectionDetails — name / description (external_id is system-managed for order linkage).
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
import type { AdminServerDetailResponse } from '@/types/adminServer'

defineOptions({ name: 'SectionDetails' })

const { t } = useI18n({ useScope: 'global' })
const { raw } = useApiFetch()
const { toast } = useToast()

const detail = inject<Ref<AdminServerDetailResponse | null>>('adminServerDetail')!
const serverId = inject<Ref<number | null>>('adminServerId')!
const reload = inject<() => Promise<void>>('reloadAdminServer', async () => {})

interface Form { name: string; description: string }

const initial = ref<Form>({ name: '', description: '' })
const form = ref<Form>({ name: '', description: '' })
const syncing = ref(false)

function syncFromDetail() {
  const s = detail.value?.server
  if (!s) return
  syncing.value = true
  const f: Form = {
    name: s.name,
    description: s.description ?? '',
  }
  form.value = { ...f }
  initial.value = { ...f }
  syncing.value = false
}

const isDirty = computed(() => {
  if (syncing.value) return false
  const a = form.value, b = initial.value
  return a.name !== b.name || a.description !== b.description
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
  await raw(`/api/admin/servers/${serverId.value}/details`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
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
  <BaseCard variant="bg2" density="compact">
    <CollapsibleGroup :title="t('adminServer.settings.details.title')" :subtitle="t('adminServer.settings.details.desc')" icon="info" :defaultOpen="true">
      <div class="form">
        <FormField layout="horizontal" bordered>
          <template #label>{{ t('adminServer.settings.details.name') }}</template>
          <BaseInput v-model="form.name" />
        </FormField>
        <FormField layout="horizontal" bordered>
          <template #label>{{ t('adminServer.settings.details.description') }}</template>
          <BaseTextarea v-model="form.description" :rows="2" />
        </FormField>
      </div>
    </CollapsibleGroup>
  </BaseCard>
</template>

<style scoped>
.form > * + * { margin-top: var(--sp-2); }
</style>
