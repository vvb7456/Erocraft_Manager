<script setup lang="ts">
// SectionBuild — limits / threads / oom / quotas via PATCH /build.
// Backend rolls back if Wings sync fails. We send all fields every save
// (the backend treats any provided field as authoritative).
import { ref, computed, watch, inject, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import { useDirtyFormSection } from '@/composables/useDirtyForm'
import CollapsibleGroup from '@/components/ui/CollapsibleGroup.vue'
import BaseCard from '@/components/ui/BaseCard.vue'
import FormField from '@/components/form/FormField.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import NumberInput from '@/components/form/NumberInput.vue'
import ToggleSwitch from '@/components/ui/ToggleSwitch.vue'
import HelpTip from '@/components/ui/HelpTip.vue'
import type { AdminServerDetailResponse } from '@/types/adminServer'

defineOptions({ name: 'SectionBuild' })

const { t } = useI18n({ useScope: 'global' })
const { raw } = useApiFetch()
const { toast } = useToast()

const detail = inject<Ref<AdminServerDetailResponse | null>>('adminServerDetail')!
const serverId = inject<Ref<number | null>>('adminServerId')!
const reload = inject<() => Promise<void>>('reloadAdminServer', async () => {})

interface Form {
  cpu: number
  memory: number
  swap: number
  disk: number
  io: number
  threads: string
  oomDisabled: boolean
  allocationLimit: number
  databaseLimit: number
  backupLimit: number
}

function emptyForm(): Form {
  return {
    cpu: 0, memory: 0, swap: 0, disk: 0, io: 500,
    threads: '', oomDisabled: false,
    allocationLimit: 0, databaseLimit: 0, backupLimit: 0,
  }
}

const initial = ref<Form>(emptyForm())
const form = ref<Form>(emptyForm())
const syncing = ref(false)

function syncFromDetail() {
  const s = detail.value?.server
  if (!s) return
  syncing.value = true
  const f: Form = {
    cpu: s.cpu,
    memory: s.memory,
    swap: s.swap,
    disk: s.disk,
    io: s.io,
    threads: s.threads ?? '',
    oomDisabled: s.oomDisabled,
    allocationLimit: s.allocationLimit ?? 0,
    databaseLimit: s.databaseLimit ?? 0,
    backupLimit: s.backupLimit,
  }
  form.value = { ...f }
  initial.value = { ...f }
  syncing.value = false
}

const isDirty = computed(() => {
  if (syncing.value) return false
  const a = form.value, b = initial.value
  return (a.cpu !== b.cpu || a.memory !== b.memory || a.swap !== b.swap
    || a.disk !== b.disk || a.io !== b.io || a.threads !== b.threads
    || a.oomDisabled !== b.oomDisabled || a.allocationLimit !== b.allocationLimit
    || a.databaseLimit !== b.databaseLimit || a.backupLimit !== b.backupLimit)
})

// Container polls detail every 30s; gate sync so an in-flight poll
// doesn't stomp pending edits and flash DirtyBar.
watch(detail, () => { if (!isDirty.value) syncFromDetail() }, { immediate: true, deep: false })

function discard() { form.value = { ...initial.value } }

async function save(): Promise<boolean> {
  if (!isDirty.value || !serverId.value) return true
  if (form.value.io < 10 || form.value.io > 1000) {
    toast(t('adminServer.settings.build.ioHint'), 'error')
    return false
  }
  const body: Record<string, unknown> = {
    memory: form.value.memory,
    swap: form.value.swap,
    disk: form.value.disk,
    io: form.value.io,
    cpu: form.value.cpu,
    threads: form.value.threads.trim() === '' ? null : form.value.threads.trim(),
    oomDisabled: form.value.oomDisabled,
    allocationLimit: form.value.allocationLimit,
    databaseLimit: form.value.databaseLimit,
    backupLimit: form.value.backupLimit,
  }
  const res = await raw(`/api/admin/servers/${serverId.value}/build`, {
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

useDirtyFormSection({ name: 'build', isDirty, save, discard })
</script>

<template>
  <BaseCard variant="bg2" class="settings-card">
    <CollapsibleGroup :title="t('adminServer.settings.build.title')" icon="memory" :defaultOpen="false">
      <div class="form">
        <FormField layout="horizontal" bordered>
          <template #label>
            {{ t('adminServer.settings.build.cpu') }}
            <HelpTip :text="t('adminServer.settings.build.cpuHint')" />
          </template>
          <NumberInput v-model="form.cpu" :min="0" :step="50" />
        </FormField>
        <FormField layout="horizontal" bordered>
          <template #label>{{ t('adminServer.settings.build.memory') }}</template>
          <NumberInput v-model="form.memory" :min="0" :step="128" />
        </FormField>
        <FormField layout="horizontal" bordered>
          <template #label>
            {{ t('adminServer.settings.build.swap') }}
            <HelpTip :text="t('adminServer.settings.build.swapHint')" />
          </template>
          <NumberInput v-model="form.swap" :min="-1" :step="128" />
        </FormField>
        <FormField layout="horizontal" bordered>
          <template #label>{{ t('adminServer.settings.build.disk') }}</template>
          <NumberInput v-model="form.disk" :min="0" :step="512" />
        </FormField>
        <FormField layout="horizontal" bordered>
          <template #label>
            {{ t('adminServer.settings.build.io') }}
            <HelpTip :text="t('adminServer.settings.build.ioHint')" />
          </template>
          <NumberInput v-model="form.io" :min="10" :max="1000" :step="10" />
        </FormField>
        <FormField layout="horizontal" bordered>
          <template #label>
            {{ t('adminServer.settings.build.threads') }}
            <HelpTip :text="t('adminServer.settings.build.threadsHint')" />
          </template>
          <BaseInput v-model="form.threads" placeholder="0-3,8" />
        </FormField>
        <FormField layout="horizontal" bordered>
          <template #label>{{ t('adminServer.settings.build.oomDisabled') }}</template>
          <ToggleSwitch v-model="form.oomDisabled" size="sm" />
        </FormField>
        <FormField layout="horizontal" bordered>
          <template #label>{{ t('adminServer.settings.build.allocationLimit') }}</template>
          <NumberInput v-model="form.allocationLimit" :min="0" :step="1" />
        </FormField>
        <FormField layout="horizontal" bordered>
          <template #label>{{ t('adminServer.settings.build.databaseLimit') }}</template>
          <NumberInput v-model="form.databaseLimit" :min="0" :step="1" />
        </FormField>
        <FormField layout="horizontal" bordered>
          <template #label>{{ t('adminServer.settings.build.backupLimit') }}</template>
          <NumberInput v-model="form.backupLimit" :min="0" :step="1" />
        </FormField>
      </div>
    </CollapsibleGroup>
  </BaseCard>
</template>

<style scoped>
.form > * + * { margin-top: var(--sp-2); }
</style>
