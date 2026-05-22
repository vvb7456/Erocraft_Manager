<script setup lang="ts">
// Server-level network page (custom domain / Cloudflare Tunnel).
//
// UX model: dirty-bar, no per-control auto-save.
//   * draft   = user edits in local state (switch + subdomain input)
//   * baseline = last known server state
//   * isDirty = draft != baseline → DirtyBar appears
//   * Save: derive the API call from (baseline → draft):
//       false→true  : POST   /api/user/servers/{id}/tunnel { customSubdomain }
//       true→false  : DELETE /api/user/servers/{id}/tunnel
//       true→true   : PUT    /api/user/servers/{id}/tunnel { customSubdomain }
//                     (only when subdomain actually changed)
//   * Discard: draft = clone(baseline)
//   * Routing/closing while dirty triggers the standard three-outcome prompt.
//
// We never call the API on switch toggle / input change. The switch only
// updates draft state — the user must hit "Save" in the DirtyBar.
import { ref, inject, computed, watch, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import { useClipboard } from '@/composables/useClipboard'
import { provideDirtyForm, useDirtyFormSection } from '@/composables/useDirtyForm'
import BaseCard from '@/components/ui/BaseCard.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import FormField from '@/components/form/FormField.vue'
import HelpTip from '@/components/ui/HelpTip.vue'
import Badge from '@/components/ui/Badge.vue'
import AlertBanner from '@/components/ui/AlertBanner.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import LoadingCenter from '@/components/ui/LoadingCenter.vue'
import SectionHeader from '@/components/ui/SectionHeader.vue'
import ToggleSwitch from '@/components/ui/ToggleSwitch.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import DirtyBar from '@/components/ui/DirtyBar.vue'

defineOptions({ name: 'ServerNetworkPage' })

interface ServerDetail {
  id: number
  eggName: string
  address: string | null
  tunnel: { status: string; hostname: string; customSubdomain: string | null; lastError: string | null } | null
  hostTunnelReady: boolean
}

interface TunnelState {
  tunnel: { status: string; hostname: string; customSubdomain: string | null; lastError: string | null } | null
  hostTunnelReady: boolean
  zoneName: string | null
}

const { t } = useI18n({ useScope: 'global' })
const server = inject<Ref<ServerDetail | null>>('server')!
const reloadServer = inject<() => Promise<void>>('reloadServer')
const { get, post, put, del, error: apiError } = useApiFetch()
const { toast } = useToast()
const { copy: copyToClipboard } = useClipboard()

const SUBDOMAIN_RE = /^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$/

// ─── Server state (baseline) ─────────────────────────────────────────────
const loading = ref(true)
const state = ref<TunnelState | null>(null)
const baselineEnabled = ref(false)
const baselineSubdomain = ref('')

// ─── Local edit state (draft) ────────────────────────────────────────────
const draftEnabled = ref(false)
const draftSubdomain = ref('')
const subdomainTouched = ref(false)
const copiedKey = ref<string | null>(null)

// ─── Derived ─────────────────────────────────────────────────────────────
const tunnel = computed(() => state.value?.tunnel ?? null)
const hostReady = computed(() => state.value?.hostTunnelReady ?? false)
const zoneName = computed(() => state.value?.zoneName ?? '')

const subdomainNorm = computed(() => draftSubdomain.value.trim().toLowerCase())
const subdomainValid = computed(() => SUBDOMAIN_RE.test(subdomainNorm.value))
const showSubdomainError = computed(() =>
  subdomainTouched.value && draftEnabled.value
  && draftSubdomain.value.length > 0 && !subdomainValid.value,
)
// Empty subdomain is also invalid when enabling — must be set before save.
const subdomainEmpty = computed(() => draftEnabled.value && !subdomainNorm.value)

const subdomainChanged = computed(() => subdomainNorm.value !== baselineSubdomain.value)
const enabledChanged = computed(() => draftEnabled.value !== baselineEnabled.value)
const isDirty = computed(() => {
  if (enabledChanged.value) return true
  if (draftEnabled.value && subdomainChanged.value) return true
  return false
})

// Save is only allowed when dirty AND, if enabling/keeping enabled, a valid
// non-empty subdomain has been entered.
const canSave = computed(() => {
  if (!isDirty.value) return false
  if (draftEnabled.value && (subdomainEmpty.value || !subdomainValid.value)) return false
  return true
})

// Localised validation error labels surfaced through the DirtyBar. Empty
// when dirty=false so the bar is hidden anyway.
const validationErrors = computed<string[]>(() => {
  if (!isDirty.value) return []
  const list: string[] = []
  if (draftEnabled.value && subdomainEmpty.value) {
    list.push(t('userServers.network.subdomainRequired'))
  } else if (draftEnabled.value && !subdomainValid.value) {
    list.push(t('userServers.network.subdomainInvalid'))
  }
  return list
})

const statusBadge = computed(() => {
  const s = tunnel.value?.status
  if (!s) return null
  if (s === 'active') return { color: 'var(--green)', label: t('userServers.network.statusActive') }
  if (s === 'failed') return { color: 'var(--red)', label: t('userServers.network.statusFailed') }
  return null
})

// ─── Load + sync baseline → draft ────────────────────────────────────────
function applyState(s: TunnelState) {
  state.value = s
  const enabled = !!s.tunnel
  const sub = s.tunnel?.customSubdomain ?? ''
  baselineEnabled.value = enabled
  baselineSubdomain.value = sub
  draftEnabled.value = enabled
  draftSubdomain.value = sub
  subdomainTouched.value = false
}

async function load() {
  if (!server.value) return
  loading.value = true
  try {
    const data = await get<TunnelState>(
      `/api/user/servers/${server.value.id}/tunnel`,
      { silent: true },
    )
    if (data) applyState(data)
  } finally {
    loading.value = false
  }
}

watch(server, (s) => { if (s) void load() }, { immediate: true })

// ─── Clipboard ───────────────────────────────────────────────────────────
async function copyAddr(text: string, key: string) {
  const ok = await copyToClipboard(text, { silent: true })
  if (ok) {
    copiedKey.value = key
    setTimeout(() => { if (copiedKey.value === key) copiedKey.value = null }, 1500)
  }
}

// ─── Dirty-bar wiring ────────────────────────────────────────────────────
const dirtyForm = provideDirtyForm()
dirtyForm.attachLeaveGuard()

async function saveSection(): Promise<boolean> {
  if (!server.value) return false
  if (!canSave.value) {
    // Should not happen because DirtyBar disables Save when invalid, but
    // belt-and-suspenders.
    toast(t('userServers.network.subdomainInvalid'), 'error')
    return false
  }

  // Derive transition.
  const from = baselineEnabled.value
  const to = draftEnabled.value
  const sub = subdomainNorm.value

  let res: TunnelState | null = null
  if (!from && to) {
    // Enable
    res = await post<TunnelState>(
      `/api/user/servers/${server.value.id}/tunnel`,
      { customSubdomain: sub },
    )
  } else if (from && !to) {
    // Disable
    await del(`/api/user/servers/${server.value.id}/tunnel`)
    if (apiError.value) return false
    // Re-fetch full state since DELETE returns 204.
    res = await get<TunnelState>(
      `/api/user/servers/${server.value.id}/tunnel`,
      { silent: true },
    )
  } else if (from && to && subdomainChanged.value) {
    // Rename
    res = await put<TunnelState>(
      `/api/user/servers/${server.value.id}/tunnel`,
      { customSubdomain: sub },
    )
  } else {
    // Nothing to do (shouldn't reach here with isDirty guard)
    return true
  }

  if (!res) return false
  applyState(res)
  toast(t('userServers.network.toast.saved'), 'success')
  if (reloadServer) await reloadServer()
  return true
}

function discardSection(): void {
  draftEnabled.value = baselineEnabled.value
  draftSubdomain.value = baselineSubdomain.value
  subdomainTouched.value = false
}

// Save button on DirtyBar — gate on canSave so an invalid draft surfaces
// the inline error instead of attempting an API call.
async function handleSaveClick() {
  if (!canSave.value) {
    subdomainTouched.value = true
    if (subdomainEmpty.value) {
      toast(t('userServers.network.subdomainRequired'), 'error')
    } else if (!subdomainValid.value) {
      toast(t('userServers.network.subdomainInvalid'), 'error')
    }
    return
  }
  await dirtyForm.save()
}

useDirtyFormSection(
  { isDirty, save: saveSection, discard: discardSection, name: 'ServerNetwork' },
  dirtyForm,
)
</script>

<template>
  <LoadingCenter v-if="loading && !state" />

  <div v-else-if="!state" class="net-page">
    <BaseCard variant="bg2">
      <EmptyState
        icon="error"
        :title="t('userServers.network.loadFailed')"
      >
        <BaseButton variant="primary" size="sm" @click="load">
          {{ t('userServers.network.retry') }}
        </BaseButton>
      </EmptyState>
    </BaseCard>
  </div>

  <div v-else class="net-page">
    <!-- ─── Card 1: Addresses ─── -->
    <BaseCard variant="bg2" class="net-card">
      <SectionHeader icon="dns" flush>{{ t('userServers.network.addressSection') }}</SectionHeader>

      <FormField layout="horizontal">
        <template #label>
          {{ t('userServers.network.rawAddress') }}
          <HelpTip :text="t('userServers.network.rawAddressHint')" />
        </template>
        <div class="addr-row">
          <input class="form-input form-input--mono" readonly :value="server?.address ?? ''" />
          <button
            class="copy-btn"
            :title="t('userServers.network.copyAddress')"
            @click="copyAddr(server?.address ?? '', 'raw')"
          >
            <MsIcon :name="copiedKey === 'raw' ? 'check' : 'content_copy'" />
          </button>
        </div>
      </FormField>

      <FormField v-if="tunnel?.status === 'active'" layout="horizontal">
        <template #label>
          {{ t('userServers.network.customDomain') }}
          <HelpTip :text="t('userServers.network.customDomainHint')" />
        </template>
        <div class="addr-row">
          <input class="form-input form-input--mono" readonly :value="tunnel.hostname" />
          <button
            class="copy-btn"
            :title="t('userServers.network.copyAddress')"
            @click="copyAddr(tunnel!.hostname, 'tunnel')"
          >
            <MsIcon :name="copiedKey === 'tunnel' ? 'check' : 'content_copy'" />
          </button>
        </div>
      </FormField>
    </BaseCard>

    <!-- ─── Card 2: Custom domain control ─── -->
    <BaseCard variant="bg2" class="net-card">
      <SectionHeader icon="public" flush>{{ t('userServers.network.section') }}</SectionHeader>

      <!-- Host not ready -->
      <EmptyState
        v-if="!hostReady"
        icon="cloud_off"
        :title="t('userServers.network.hostNotReady.title')"
        :message="t('userServers.network.hostNotReady.message')"
        density="compact"
      />

      <template v-else>
        <!-- Toggle row: pure local state, NOT auto-saved. -->
        <div class="toggle-row">
          <div class="toggle-meta">
            <div class="toggle-label">{{ t('userServers.network.enableLabel') }}</div>
            <div class="toggle-hint">{{ t('userServers.network.enableHint') }}</div>
          </div>
          <div class="toggle-state">
            <Badge v-if="statusBadge" :color="statusBadge.color">
              {{ statusBadge.label }}
            </Badge>
            <ToggleSwitch v-model="draftEnabled" />
          </div>
        </div>

        <!-- Failed banner -->
        <AlertBanner
          v-if="tunnel?.status === 'failed'"
          tone="danger"
          class="mt-12"
        >
          <strong>{{ t('userServers.network.statusFailed') }}</strong>
          <div>{{ tunnel.lastError || t('userServers.network.statusFailedHint') }}</div>
        </AlertBanner>

        <!-- Subdomain editor: visible whenever draft is "enabled" (even
             before the change is saved), so the user can pick a name and
             enable + name in one save. -->
        <div v-if="draftEnabled" class="subdomain-block">
          <FormField
            layout="horizontal"
            :error="showSubdomainError ? t('userServers.network.subdomainInvalid')
                  : (subdomainEmpty && subdomainTouched ? t('userServers.network.subdomainRequired') : '')"
          >
            <template #label>
              {{ t('userServers.network.subdomainLabel') }}
              <HelpTip :text="t('userServers.network.subdomainHint')" />
            </template>
            <div class="sub-row">
              <BaseInput
                v-model="draftSubdomain"
                :placeholder="t('userServers.network.subdomainPlaceholder')"
                mono
                @blur="subdomainTouched = true"
              />
              <span class="sub-suffix">.{{ zoneName }}</span>
            </div>
          </FormField>
        </div>

        <!-- Warning banner -->
        <AlertBanner tone="warning" class="mt-12">
          <strong>{{ t('userServers.network.warning.title') }}</strong>
          <div class="warn-body">{{ t('userServers.network.warning.body') }}</div>
        </AlertBanner>
      </template>
    </BaseCard>

    <DirtyBar
      :dirty="dirtyForm.isDirty.value"
      :saving="dirtyForm.saving.value"
      :errors="validationErrors"
      @save="handleSaveClick"
      @discard="dirtyForm.discard"
    />
  </div>
</template>

<style scoped>
.net-page {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
  max-width: 760px;
  margin: 0 auto;
  width: 100%;
}

.net-card {
  padding: var(--sp-4);
}

.section-note {
  font-size: var(--text-sm);
  color: var(--t3);
  margin: var(--sp-2) 0 var(--sp-3);
}

.addr-row {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex: 1;
}

.copy-btn {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: 1px solid var(--bd);
  border-radius: var(--r-sm);
  background: var(--bg-in);
  color: var(--t3);
  cursor: pointer;
  transition: color .15s, background .15s, border-color .15s;
}
.copy-btn:hover { color: var(--ac); border-color: var(--bd-f); }

.toggle-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--sp-3);
  padding: var(--sp-2) 0;
}
.toggle-meta { flex: 1; min-width: 0; }
.toggle-label { color: var(--t1); font-size: var(--text-md); font-weight: 500; }
.toggle-hint { color: var(--t3); font-size: var(--text-sm); margin-top: var(--sp-1); }
.toggle-state { display: flex; align-items: center; gap: var(--sp-2); flex-shrink: 0; }

.subdomain-block { margin-top: var(--sp-3); }

.sub-row {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex: 1;
}
.sub-row :deep(.form-input) { flex: 1; min-width: 0; }
.sub-suffix {
  font-family: 'IBM Plex Mono', monospace;
  font-size: var(--text-sm);
  color: var(--t2);
  white-space: nowrap;
}

.mt-12 { margin-top: var(--sp-3); }
.warn-body { margin-top: var(--sp-1); }
.addr-row .form-input { flex: 1; min-width: 0; }
</style>
