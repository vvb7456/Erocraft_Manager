<script setup lang="ts">
// HostSettingPane (C8) — write-side companion to the overview tab.
//
// Sections (CollapsibleGroup, top-down):
//   1. Agent connection (name / hostname / agent_url / enabled / token reset)
//      → PATCH /api/admin/hosts/{id} on save; agent_token included only when
//        operator clicked "reset" so the backend re-encrypts a fresh value.
//   2. Wings service — placeholder until PR-A wings-config endpoint lands.
//   3. Alerting — placeholder until PR-B′-ii host-alerts endpoint lands.
//   4. Danger zone — DELETE /api/admin/hosts/{id} → back to list.
//
// Token policy: client generates with Web Crypto (32 random bytes →
// 43-char URL-safe base64), backend only encrypts. Plaintext is shown
// once via SecretInput so the operator can paste it into the agent's
// config.yaml.
import { computed, inject, ref, watch, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'
import { provideDirtyForm, useDirtyFormSection } from '@/composables/useDirtyForm'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseCard from '@/components/ui/BaseCard.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import CollapsibleGroup from '@/components/ui/CollapsibleGroup.vue'
import FormField from '@/components/form/FormField.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import ToggleSwitch from '@/components/ui/ToggleSwitch.vue'
import SecretInput from '@/components/ui/SecretInput.vue'
import AlertBanner from '@/components/ui/AlertBanner.vue'
import HelpTip from '@/components/ui/HelpTip.vue'
import DirtyBar from '@/components/ui/DirtyBar.vue'
import HostAlertingSection from './sections/HostAlertingSection.vue'
import HostCertSection from './sections/HostCertSection.vue'
import type { HostDetail } from '@/types/host'

defineOptions({ name: 'HostSettingPane' })

const { t } = useI18n({ useScope: 'global' })
const host = inject<Ref<HostDetail | null>>('hostDetail')!
const reloadHost = inject<() => Promise<void> | void>('reloadHost', () => {})
const router = useRouter()
const { post, del, raw } = useApiFetch()
const { toast } = useToast()
const { confirm } = useConfirm()

// Unified dirty-form orchestration for this page (basic form +
// HostAlertingSection child). The page renders ONE DirtyBar and ONE
// leave-guard; child sections register themselves via useDirtyFormSection.
const dirtyForm = provideDirtyForm()
dirtyForm.attachLeaveGuard()

// ---------------------------------------------------------------
// Token generator (matches backend secrets.token_urlsafe(32) — 43 chars)
// ---------------------------------------------------------------
function generateToken(): string {
  const buf = new Uint8Array(32)
  crypto.getRandomValues(buf)
  let bin = ''
  for (const b of buf) bin += String.fromCharCode(b)
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

// ---------------------------------------------------------------
// Form state (mirrors host fields; reset on host change)
// ---------------------------------------------------------------
interface FormState {
  name: string
  hostname: string
  agent_url: string
  enabled: boolean
}
const initial = ref<FormState>({ name: '', hostname: '', agent_url: '', enabled: true })
const form = ref<FormState>({ name: '', hostname: '', agent_url: '', enabled: true })
const newToken = ref<string | null>(null)  // null = not rotated; string = pending save
const syncing = ref(false)
const submitting = ref(false)
const probing = ref(false)
const deleting = ref(false)

function syncFromHost() {
  if (!host.value) return
  syncing.value = true
  const f: FormState = {
    name: host.value.name,
    hostname: host.value.hostname,
    agent_url: host.value.agent_url,
    enabled: host.value.enabled,
  }
  form.value = { ...f }
  initial.value = { ...f }
  newToken.value = null
  syncing.value = false
}

const isDirty = computed(() => {
  if (syncing.value) return false
  const a = form.value, b = initial.value
  return (
    a.name !== b.name
    || a.hostname !== b.hostname
    || a.agent_url !== b.agent_url
    || a.enabled !== b.enabled
    || newToken.value !== null
  )
})

// Host detail is refreshed on tab-enter and after explicit operations.
// Guard against stomping pending edits when upstream host data changes.
watch(host, () => {
  if (!isDirty.value) syncFromHost()
}, { immediate: true })

const canSubmit = computed(() => {
  if (!isDirty.value) return false
  const f = form.value
  return f.name.trim().length > 0 && f.hostname.trim().length > 0 && f.agent_url.trim().length > 0
})

async function save(): Promise<boolean> {
  if (!host.value || !canSubmit.value) return true
  submitting.value = true
  try {
    const body: Record<string, unknown> = {}
    if (form.value.name !== initial.value.name) body.name = form.value.name.trim()
    if (form.value.hostname !== initial.value.hostname) body.hostname = form.value.hostname.trim()
    if (form.value.agent_url !== initial.value.agent_url) body.agent_url = form.value.agent_url.trim()
    if (form.value.enabled !== initial.value.enabled) body.enabled = form.value.enabled
    if (newToken.value) body.agent_token = newToken.value

    const res = await raw(`/api/admin/hosts/${host.value.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!res) return false
    toast(t('hosts.setting.saved'), 'success')
    await reloadHost()
    return true
  } finally {
    submitting.value = false
  }
}

function discard() {
  form.value = { ...initial.value }
  newToken.value = null
}

// Register this pane's own basic-info form as a section in the page-wide
// DirtyBar / leave-guard. HostAlertingSection registers itself.
useDirtyFormSection({ name: 'host-basic', isDirty, save, discard }, dirtyForm)

function resetToken() {
  newToken.value = generateToken()
}

function clearTokenReset() {
  newToken.value = null
}

async function probe() {
  if (!host.value) return
  probing.value = true
  try {
    const r = await post<{ ok: boolean; error?: string; latency_ms?: number }>(
      `/api/admin/hosts/${host.value.id}/probe`, {},
    )
    if (!r) return
    if (r.ok) {
      toast(t('hosts.setting.probeOk', { ms: r.latency_ms ?? '?' }), 'success')
    } else {
      toast(t('hosts.setting.probeFail', { err: r.error || '?' }), 'error')
    }
  } finally {
    probing.value = false
  }
}

async function destroy() {
  if (!host.value) return
  const ok = await confirm({
    title: t('hosts.confirm.delete_title'),
    message: t('hosts.confirm.delete_msg', { name: host.value.name }),
    variant: 'danger',
  })
  if (!ok) return
  deleting.value = true
  try {
    await del(`/api/admin/hosts/${host.value.id}`)
    toast(t('hosts.actions.deleted', { name: host.value.name }), 'success')
    router.push({ name: 'hosts' })
  } finally {
    deleting.value = false
  }
}

const isWings = computed(() => host.value?.kind === 'wings_node')
</script>

<template>
  <div v-if="!host" class="muted">{{ t('hosts.detail.loading') }}</div>

  <div v-else class="setting-panel">
    <!-- ── Agent connection ── -->
    <BaseCard variant="bg2" class="settings-card">
      <CollapsibleGroup :title="t('hosts.setting.agent.title')" icon="cable" :defaultOpen="true">
        <div class="form">
          <FormField layout="horizontal" bordered>
            <template #label>
              {{ t('hosts.overview.fields.enabled') }}
              <HelpTip :text="t('hosts.setting.agent.enabledHint')" />
            </template>
            <ToggleSwitch v-model="form.enabled" size="sm" />
          </FormField>

          <FormField layout="horizontal" bordered>
            <template #label>{{ t('hosts.overview.fields.name') }}</template>
            <BaseInput v-model="form.name" />
          </FormField>

          <FormField layout="horizontal" bordered>
            <template #label>
              {{ t('hosts.overview.fields.kind') }}
              <HelpTip :text="t('hosts.setting.agent.kindLocked')" />
            </template>
            <BaseInput :modelValue="t(`hosts.kind.${host.kind}`)" disabled />
          </FormField>

          <FormField layout="horizontal" bordered>
            <template #label>{{ t('hosts.overview.fields.hostname') }}</template>
            <BaseInput v-model="form.hostname" />
          </FormField>

          <FormField layout="horizontal" bordered>
            <template #label>{{ t('hosts.overview.fields.agentUrl') }}</template>
            <BaseInput v-model="form.agent_url" placeholder="http://10.0.0.22:48765" />
          </FormField>

          <FormField v-if="isWings" layout="horizontal" bordered>
            <template #label>
              {{ t('hosts.overview.fields.panelNode') }}
              <HelpTip :text="t('hosts.setting.agent.panelNodeLocked')" />
            </template>
            <BaseInput :modelValue="String(host.pterodactyl_node_id ?? '')" disabled />
          </FormField>

          <FormField layout="horizontal" bordered>
            <template #label>
              {{ t('hosts.setting.agent.tokenLabel') }}
              <HelpTip :text="newToken ? t('hosts.setting.agent.tokenPendingHint') : t('hosts.setting.agent.tokenHint')" />
            </template>
            <div class="token-row">
              <SecretInput
                v-if="newToken"
                :modelValue="newToken"
                readonly
                class="token-input"
              />
              <BaseInput
                v-else
                :modelValue="'••••••••••••••••••••••••••••••••••••••••••'"
                disabled
                class="token-input"
              />
              <BaseButton v-if="!newToken" size="sm" variant="default" @click="resetToken">
                <MsIcon name="autorenew" size="xs" />
                {{ t('hosts.setting.agent.tokenReset') }}
              </BaseButton>
              <BaseButton v-else size="sm" variant="ghost" @click="clearTokenReset">
                {{ t('hosts.setting.agent.tokenCancelReset') }}
              </BaseButton>
            </div>
          </FormField>

          <AlertBanner v-if="newToken" tone="warning" dense>
            {{ t('hosts.setting.agent.tokenWarning') }}
          </AlertBanner>

          <div class="actions">
            <BaseButton size="sm" variant="default" :loading="probing" @click="probe">
              <MsIcon name="network_check" size="xs" />
              {{ t('hosts.setting.agent.probe') }}
            </BaseButton>
          </div>
        </div>
      </CollapsibleGroup>
    </BaseCard>

    <!-- ── Alerting ── -->
    <HostAlertingSection :hostId="host.id" :hostKind="host.kind" />

    <!-- ── Certificates ── -->
    <HostCertSection v-if="host" :hostId="host.id" :hostKind="host.kind" />

    <!-- ── Danger zone ── -->
    <BaseCard variant="bg2" class="settings-card">
      <CollapsibleGroup :title="t('hosts.setting.danger.title')" icon="warning" :defaultOpen="false">
        <div class="danger-row">
          <div class="danger-title">
            {{ t('hosts.setting.danger.deleteTitle') }}
            <HelpTip :text="t('hosts.setting.danger.deleteMsg')" />
          </div>
          <BaseButton size="sm" variant="danger" :loading="deleting" @click="destroy">
            <MsIcon name="delete" size="xs" />
            {{ t('hosts.actions.delete') }}
          </BaseButton>
        </div>
      </CollapsibleGroup>
    </BaseCard>

    <DirtyBar :dirty="dirtyForm.isDirty.value" :saving="dirtyForm.saving.value" @save="dirtyForm.save" @discard="dirtyForm.discard" />
  </div>
</template>

<style scoped>
.muted {
  color: var(--t3);
  font-size: var(--text-sm);
  padding: var(--sp-4);
}

.setting-panel {
  margin-top: var(--sp-4);
  max-width: 640px;
  margin-left: auto;
  margin-right: auto;
}

.setting-panel > * + * {
  margin-top: var(--sp-5);
}

.form {
  padding-top: var(--sp-2);
}

.token-row {
  display: flex;
  gap: var(--sp-2);
  align-items: center;
  width: 100%;
}
.token-input {
  flex: 1;
  min-width: 0;
}

.actions {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin-top: var(--sp-3);
}
.spacer { flex: 1; }

.hint {
  color: var(--t2);
  font-size: var(--text-sm);
  margin: var(--sp-2) 0 var(--sp-1);
}

.danger-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  padding-top: var(--sp-2);
}
.danger-title {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--t1);
  font-size: var(--text-sm);
  font-weight: 600;
}
</style>
