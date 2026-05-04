<script setup lang="ts">
// HostTunnelPane — Cloudflare Tunnel admin tab.
//
// Per docs/ADMIN_HOST_TUNNEL_DESIGN.md:
//   • Top section: tunnel binding state + control buttons
//     (Bind/Change · Install · Sync · Restart · Uninstall)
//   • Bottom section: per-server tunnel ingress DataTable (Phase 2 data;
//     Phase 1 shows EmptyState)
//
// Bind/change uses a two-step modal:
//   step 1 → enter account_id + token, click "Verify" → POST /admin/cf/zones
//   step 2 → choose zone from list, click "Save" → PUT /admin/hosts/{id}/tunnel
//
// Uninstall uses a name-typing confirmation (BaseModal with text input).

import { computed, inject, ref, watch, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'
import BaseCard from '@/components/ui/BaseCard.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import BaseModal from '@/components/ui/BaseModal.vue'
import SecretInput from '@/components/ui/SecretInput.vue'
import FormField from '@/components/form/FormField.vue'
import HelpTip from '@/components/ui/HelpTip.vue'
import Badge from '@/components/ui/Badge.vue'
import AlertBanner from '@/components/ui/AlertBanner.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import Spinner from '@/components/ui/Spinner.vue'
import DataTable from '@/components/ui/DataTable.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import type { HostDetail } from '@/types/host'

defineOptions({ name: 'HostTunnelPane' })

interface TunnelDetail {
  host_id: number
  cf_account_id: string
  cf_zone_id: string
  cf_zone_name: string
  cf_tunnel_id: string | null
  cf_tunnel_name: string | null
  cloudflared_version: string | null
  cf_config_version: number | null
  last_synced_at: string | null
  last_error: string | null
  cloudflared_live_active: boolean | null
  cloudflared_live_unit_present: boolean | null
  cloudflared_live_version: string | null
  cloudflared_live_error: string | null
  server_tunnel_count: number
  created_at: string
  updated_at: string
}
interface CFZone { id: string; name: string; status: string | null }
interface ServerTunnelRow {
  id: number
  server_id: number
  server_name: string | null
  server_uuid_short: string | null
  hostname: string
  upstream: string
  status: string
}

const host = inject<Ref<HostDetail | null>>('hostDetail')!
const { t } = useI18n({ useScope: 'global' })
const { get, post, put, del } = useApiFetch()
const { toast } = useToast()
const { confirm } = useConfirm()

// ---------------------------------------------------------------
// Top-section state
// ---------------------------------------------------------------
const loading = ref(true)
const detail = ref<TunnelDetail | null>(null)

const installing = ref(false)
const syncing = ref(false)
const restarting = ref(false)
const uninstalling = ref(false)

const isBound = computed(() => detail.value !== null)
const isInstalled = computed(() => isBound.value && detail.value!.cf_tunnel_id !== null)
// Live status derived from agent probe (cloudflared_live_*).
// 'unbound'    — no row at all
// 'uninstalled'— row exists but no CF tunnel created yet
// 'probing'    — detail loaded but live probe still null + no error (race)
// 'unreachable'— live probe failed (cloudflared_live_error set)
// 'inactive'   — cloudflared service not running
// 'no_unit'    — systemd unit missing on node
// 'active'     — cloudflared running and unit present
const status = computed(() => {
  const d = detail.value
  if (!d) return 'unbound'
  if (!d.cf_tunnel_id) return 'uninstalled'
  if (d.cloudflared_live_error) return 'unreachable'
  if (d.cloudflared_live_active === null) return 'probing'
  if (!d.cloudflared_live_unit_present) return 'no_unit'
  if (!d.cloudflared_live_active) return 'inactive'
  return 'active'
})

const statusColor = computed(() => {
  switch (status.value) {
    case 'active': return 'var(--green)'
    case 'probing': return 'var(--blue)'
    case 'unreachable':
    case 'inactive':
    case 'no_unit': return 'var(--red)'
    case 'uninstalled': return 'var(--amber)'
    default: return 'var(--t3)'
  }
})

const busy = computed(() =>
  installing.value || syncing.value || restarting.value || uninstalling.value,
)

function shortId(id: string | null | undefined): string {
  if (!id) return '—'
  return id.length > 16 ? `${id.slice(0, 8)}…${id.slice(-4)}` : id
}
function formatTime(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString()
}

async function loadDetail() {
  if (!host.value) return
  loading.value = true
  try {
    const data = await get<TunnelDetail | null>(
      `/api/admin/hosts/${host.value.id}/tunnel`, { silent: true },
    )
    detail.value = data
  } finally {
    loading.value = false
  }
  await loadServers()
}

watch(host, (h) => {
  if (h) void loadDetail()
}, { immediate: true })

// ---------------------------------------------------------------
// Bind modal (two-step)
// ---------------------------------------------------------------
const bindOpen = ref(false)
const bindStep = ref<1 | 2>(1)
const bindAccount = ref('')
const bindToken = ref('')
const bindZoneId = ref('')
const bindZones = ref<CFZone[]>([])
const verifying = ref(false)
const binding = ref(false)

const bindZoneOptions = computed(() => bindZones.value.map(z => ({
  value: z.id,
  label: z.name + (z.status && z.status !== 'active' ? ` (${z.status})` : ''),
})))

const canVerify = computed(() =>
  bindAccount.value.trim().length > 0 && bindToken.value.trim().length >= 20,
)

function openBind() {
  bindStep.value = 1
  bindAccount.value = detail.value?.cf_account_id ?? ''
  bindToken.value = ''
  bindZoneId.value = detail.value?.cf_zone_id ?? ''
  bindZones.value = []
  bindOpen.value = true
}

async function verifyToken() {
  if (!canVerify.value) return
  verifying.value = true
  try {
    const r = await post<{ zones: CFZone[] }>('/api/admin/cf/zones', {
      cf_account_id: bindAccount.value.trim(),
      cf_api_token: bindToken.value.trim(),
    })
    if (r) {
      bindZones.value = r.zones
      if (bindZones.value.length === 0) {
        toast(t('hosts.tunnel.noZones'), 'warning')
        return
      }
      if (!bindZones.value.some(z => z.id === bindZoneId.value)) {
        bindZoneId.value = bindZones.value[0].id
      }
      bindStep.value = 2
    }
  } finally {
    verifying.value = false
  }
}

async function submitBind() {
  if (!host.value || !bindZoneId.value) return
  const selected = bindZones.value.find(z => z.id === bindZoneId.value)
  if (!selected) return
  binding.value = true
  try {
    const r = await put<TunnelDetail>(
      `/api/admin/hosts/${host.value.id}/tunnel`,
      {
        cf_account_id: bindAccount.value.trim(),
        cf_api_token: bindToken.value.trim(),
        cf_zone_id: selected.id,
        cf_zone_name: selected.name,
      },
    )
    if (r) {
      detail.value = r
      bindToken.value = ''
      bindOpen.value = false
      toast(t('hosts.tunnel.bindOk'), 'success')
    }
  } finally {
    binding.value = false
  }
}

// ---------------------------------------------------------------
// Install / Sync / Restart
// ---------------------------------------------------------------
async function install() {
  if (!host.value) return
  installing.value = true
  try {
    const r = await post<TunnelDetail>(
      `/api/admin/hosts/${host.value.id}/tunnel/install`, {},
    )
    if (r) {
      detail.value = r
      await loadServers()
      toast(t('hosts.tunnel.installOk'), 'success')
    }
  } finally {
    installing.value = false
  }
}

async function sync() {
  if (!host.value) return
  syncing.value = true
  try {
    const r = await post<TunnelDetail>(
      `/api/admin/hosts/${host.value.id}/tunnel/sync`, {},
    )
    if (r) {
      detail.value = r
      await loadServers()
      toast(t('hosts.tunnel.syncOk'), 'success')
    }
  } finally {
    syncing.value = false
  }
}

async function restart() {
  if (!host.value) return
  const ok = await confirm({
    title: t('hosts.tunnel.confirm.restartTitle'),
    message: t('hosts.tunnel.confirm.restartMsg'),
    variant: 'default',
  })
  if (!ok) return
  restarting.value = true
  try {
    const r = await post(`/api/admin/hosts/${host.value.id}/tunnel/restart`, {})
    if (r) toast(t('hosts.tunnel.restartOk'), 'success')
  } finally {
    restarting.value = false
  }
}

// ---------------------------------------------------------------
// Uninstall (typed-name confirmation)
// ---------------------------------------------------------------
const uninstallOpen = ref(false)
const uninstallTyped = ref('')

const expectedName = computed(() => host.value?.name ?? '')
const canUninstall = computed(() => uninstallTyped.value.trim() === expectedName.value)

function openUninstall() {
  uninstallTyped.value = ''
  uninstallOpen.value = true
}

async function submitUninstall() {
  if (!host.value || !canUninstall.value) return
  uninstalling.value = true
  try {
    const r = await del<{ ok: boolean; agent_ok: boolean; agent_error: string | null }>(
      `/api/admin/hosts/${host.value.id}/tunnel`,
    )
    if (r) {
      detail.value = null
      serverRows.value = []
      serverTotalPages.value = 1
      uninstallOpen.value = false
      if (r.agent_ok === false) {
        toast(t('hosts.tunnel.uninstallPartial', { err: r.agent_error || '?' }), 'warning')
      } else {
        toast(t('hosts.tunnel.uninstallOk'), 'success')
      }
    }
  } finally {
    uninstalling.value = false
  }
}

// ---------------------------------------------------------------
// Bottom section: server tunnels (live load from backend)
// ---------------------------------------------------------------
const serverRows = ref<ServerTunnelRow[]>([])
const serverLoading = ref(false)
const serverPage = ref(1)
const serverPerPage = ref(20)
const serverTotalPages = ref(1)

async function loadServers() {
  if (!host.value) return
  serverLoading.value = true
  try {
    const r = await get<{ items: ServerTunnelRow[] }>(
      `/api/admin/hosts/${host.value.id}/tunnel/servers`,
      { silent: true },
    )
    serverRows.value = r?.items ?? []
    serverTotalPages.value = Math.max(1, Math.ceil(serverRows.value.length / serverPerPage.value))
  } finally {
    serverLoading.value = false
  }
}

function statusBadgeColor(s: string): string {
  if (s === 'active') return 'var(--green)'
  if (s === 'failed') return 'var(--red)'
  return 'var(--t3)'
}
</script>

<template>
  <div v-if="!host" class="muted">{{ t('hosts.detail.loading') }}</div>

  <div v-else class="tunnel-pane">
    <!-- ── Section 1: tunnel state + controls ── -->
    <BaseCard variant="bg2" class="settings-card">
      <Spinner v-if="loading" />

      <template v-else>
        <!-- Unbound -->
        <div v-if="!isBound" class="empty-bind">
          <EmptyState
            icon="cloud_off"
            :title="t('hosts.tunnel.empty.title')"
            :message="t('hosts.tunnel.empty.desc')"
          >
            <BaseButton variant="primary" @click="openBind">
              <MsIcon name="link" size="xs" />
              {{ t('hosts.tunnel.actions.bind') }}
            </BaseButton>
          </EmptyState>
        </div>

        <!-- Bound -->
        <div v-else class="state-block">
          <div class="state-head">
            <div class="state-head__title">
              <MsIcon name="cloud" />
              <span>{{ t('hosts.tunnel.runtimeTitle') }}</span>
            </div>
            <Badge :color="statusColor" size="sm">
              {{ t(`hosts.tunnel.status.${status}`, status) }}
            </Badge>
            <span v-if="detail!.cloudflared_live_version || detail!.cloudflared_version" class="meta-text">
              cloudflared v{{ detail!.cloudflared_live_version || detail!.cloudflared_version }}
            </span>
          </div>

          <AlertBanner v-if="detail!.cloudflared_live_error" tone="warning" dense>
            {{ t('hosts.tunnel.liveProbeFailed') }}: {{ detail!.cloudflared_live_error }}
          </AlertBanner>
          <AlertBanner v-if="detail!.last_error" tone="danger" dense>
            {{ detail!.last_error }}
          </AlertBanner>

          <div class="kv-grid">
            <div class="kv">
              <span class="k">{{ t('hosts.tunnel.fields.account') }}</span>
              <code class="v">{{ shortId(detail!.cf_account_id) }}</code>
            </div>
            <div class="kv">
              <span class="k">{{ t('hosts.tunnel.fields.zone') }}</span>
              <span class="v">{{ detail!.cf_zone_name }}</span>
            </div>
            <div class="kv">
              <span class="k">{{ t('hosts.tunnel.fields.tunnelName') }}</span>
              <span class="v">{{ detail!.cf_tunnel_name || '—' }}</span>
            </div>
            <div class="kv">
              <span class="k">{{ t('hosts.tunnel.fields.tunnelId') }}</span>
              <code class="v">{{ shortId(detail!.cf_tunnel_id) }}</code>
            </div>
            <div class="kv">
              <span class="k">{{ t('hosts.tunnel.fields.configVersion') }}</span>
              <code class="v">{{ detail!.cf_config_version != null ? `v${detail!.cf_config_version}` : '—' }}</code>
            </div>
            <div class="kv">
              <span class="k">{{ t('hosts.tunnel.fields.lastSyncedAt') }}</span>
              <span class="v">{{ formatTime(detail!.last_synced_at) }}</span>
            </div>
          </div>

          <div class="actions">
            <BaseButton size="sm" variant="default" :disabled="busy" @click="openBind">
              <MsIcon name="edit" size="xs" />
              {{ t('hosts.tunnel.actions.rebind') }}
            </BaseButton>
            <BaseButton
              v-if="!isInstalled"
              size="sm"
              variant="primary"
              :loading="installing"
              :disabled="busy"
              @click="install"
            >
              <MsIcon name="download" size="xs" />
              {{ t('hosts.tunnel.actions.install') }}
            </BaseButton>
            <template v-else>
              <BaseButton size="sm" variant="default" :loading="syncing" :disabled="busy" @click="sync">
                <MsIcon name="sync" size="xs" />
                {{ t('hosts.tunnel.actions.sync') }}
              </BaseButton>
              <BaseButton size="sm" variant="default" :loading="restarting" :disabled="busy" @click="restart">
                <MsIcon name="restart_alt" size="xs" />
                {{ t('hosts.tunnel.actions.restart') }}
              </BaseButton>
            </template>
            <span class="spacer" />
            <BaseButton size="sm" variant="danger" :loading="uninstalling" :disabled="busy" @click="openUninstall">
              <MsIcon name="link_off" size="xs" />
              {{ t('hosts.tunnel.actions.uninstall') }}
            </BaseButton>
          </div>
        </div>
      </template>
    </BaseCard>

    <!-- ── Section 2: server tunnels (Phase 2 data; placeholder for now) ── -->
    <BaseCard variant="bg2" class="settings-card">
      <div class="section-head">
        <div class="section-head__title">
          <MsIcon name="dns" />
          <span>{{ t('hosts.tunnel.serversTitle') }}</span>
        </div>
        <span class="meta-text">{{ t('hosts.tunnel.serversHint') }}</span>
      </div>

      <DataTable
        :items="serverRows"
        :page="serverPage"
        :totalPages="serverTotalPages"
        :perPage="serverPerPage"
        :loading="serverLoading"
        :emptyText="isInstalled ? t('hosts.tunnel.serversEmptyReady') : t('hosts.tunnel.serversEmptyNoTunnel')"
        emptyIcon="link"
        rowKey="id"
      >
        <template #header>
          <th>{{ t('hosts.tunnel.cols.serverId') }}</th>
          <th>{{ t('hosts.tunnel.cols.hostname') }}</th>
          <th>{{ t('hosts.tunnel.cols.upstream') }}</th>
          <th>{{ t('hosts.tunnel.cols.status') }}</th>
        </template>
        <template #row="{ item }">
          <td>
            <RouterLink :to="{ name: 'admin-server-overview', params: { id: item.server_id } }" class="server-link">
              {{ item.server_name || `#${item.server_id}` }}
            </RouterLink>
            <div class="meta-text"><code>{{ item.server_uuid_short || item.server_id }}</code></div>
          </td>
          <td><code>{{ item.hostname }}</code></td>
          <td><code>{{ item.upstream }}</code></td>
          <td><Badge size="sm" :color="statusBadgeColor(item.status)">{{ item.status }}</Badge></td>
        </template>
        <template #card="{ item }">
          <div>
            <RouterLink :to="{ name: 'admin-server-overview', params: { id: item.server_id } }" class="server-link">
              <strong>{{ item.server_name || `#${item.server_id}` }}</strong>
            </RouterLink>
          </div>
          <div class="meta-text">{{ item.hostname }} → {{ item.upstream }}</div>
          <Badge size="sm" :color="statusBadgeColor(item.status)">{{ item.status }}</Badge>
        </template>
      </DataTable>
    </BaseCard>

    <!-- ── Bind modal (two-step) ── -->
    <BaseModal v-model="bindOpen" :title="t('hosts.tunnel.bind.title')" icon="link" size="sm">
      <!-- Step 1: account + token -->
      <div v-if="bindStep === 1" class="bind-body">
        <FormField>
          <template #label>
            {{ t('hosts.tunnel.fields.account') }}
            <HelpTip :text="t('hosts.tunnel.tips.account')" />
          </template>
          <BaseInput v-model="bindAccount" placeholder="5fc506669316893b…" />
        </FormField>
        <FormField>
          <template #label>
            {{ t('hosts.tunnel.fields.token') }}
            <HelpTip :text="t('hosts.tunnel.tips.token')" />
          </template>
          <SecretInput v-model="bindToken" />
        </FormField>
      </div>

      <!-- Step 2: zone select -->
      <div v-else class="bind-body">
        <FormField :label="t('hosts.tunnel.fields.zone')">
          <BaseSelect
            v-model="bindZoneId"
            :options="bindZoneOptions"
            valueKey="value"
            labelKey="label"
            teleport
          />
        </FormField>
      </div>

      <template #footer>
        <BaseButton variant="ghost" :disabled="verifying || binding" @click="bindOpen = false">
          {{ t('common.btn.cancel') }}
        </BaseButton>
        <BaseButton
          v-if="bindStep === 1"
          variant="primary"
          :loading="verifying"
          :disabled="!canVerify"
          @click="verifyToken"
        >
          {{ t('hosts.tunnel.bind.verify') }}
        </BaseButton>
        <template v-else>
          <BaseButton variant="default" :disabled="binding" @click="bindStep = 1">
            {{ t('hosts.tunnel.bind.back') }}
          </BaseButton>
          <BaseButton variant="primary" :loading="binding" :disabled="!bindZoneId" @click="submitBind">
            {{ t('hosts.tunnel.bind.save') }}
          </BaseButton>
        </template>
      </template>
    </BaseModal>

    <!-- ── Uninstall modal (typed-name confirmation) ── -->
    <BaseModal v-model="uninstallOpen" :title="t('hosts.tunnel.confirm.uninstallTitle')" icon="warning" size="sm">
      <div class="uninstall-body">
        <AlertBanner tone="danger" dense>
          {{ detail && detail.server_tunnel_count > 0
            ? t('hosts.tunnel.confirm.uninstallBusyMsg', { n: detail.server_tunnel_count })
            : t('hosts.tunnel.confirm.uninstallMsg') }}
        </AlertBanner>
        <BaseInput v-model="uninstallTyped" :placeholder="expectedName" />
      </div>
      <template #footer>
        <BaseButton variant="ghost" :disabled="uninstalling" @click="uninstallOpen = false">
          {{ t('common.btn.cancel') }}
        </BaseButton>
        <BaseButton
          variant="danger"
          :loading="uninstalling"
          :disabled="!canUninstall"
          @click="submitUninstall"
        >
          {{ t('hosts.tunnel.actions.uninstall') }}
        </BaseButton>
      </template>
    </BaseModal>
  </div>
</template>

<style scoped>
.muted {
  color: var(--t3);
  font-size: var(--text-sm);
  padding: var(--sp-4);
}

.tunnel-pane {
  margin-top: var(--sp-4);
  display: flex;
  flex-direction: column;
  gap: var(--sp-5);
}

.empty-bind {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  align-items: center;
}

.empty-actions {
  display: flex;
  justify-content: center;
}

.state-block {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}

.state-head {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}

.state-head__title {
  display: flex;
  align-items: center;
  gap: var(--sp-1);
  color: var(--t1);
  font-weight: 600;
  font-size: var(--text-md);
}

.section-head {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
  margin-bottom: var(--sp-3);
}

.section-head__title {
  display: flex;
  align-items: center;
  gap: var(--sp-1);
  color: var(--t1);
  font-weight: 600;
  font-size: var(--text-md);
}

.meta-text {
  color: var(--t3);
  font-size: var(--text-xs);
  font-family: var(--font-mono);
}

.server-link {
  color: var(--ac);
  text-decoration: none;
}
.server-link:hover { text-decoration: underline; }

.kv-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--sp-2) var(--sp-4);
  padding: var(--sp-3);
  border: 1px solid var(--bd);
  border-radius: var(--r-sm);
  background: var(--bg3);
}

.kv {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.kv .k {
  color: var(--t3);
  font-size: var(--text-xs);
}

.kv .v {
  color: var(--t1);
  font-size: var(--text-sm);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

code.v,
.section-head code,
td code {
  font-family: var(--font-mono);
}

.actions {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
  margin-top: var(--sp-2);
}

.spacer { flex: 1; }

.bind-body {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}

.uninstall-body {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}

@media (max-width: 640px) {
  .kv-grid {
    grid-template-columns: 1fr;
  }
}
</style>
