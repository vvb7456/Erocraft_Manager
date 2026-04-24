<script setup lang="ts">
// HostOverviewPane (C7) — read-only host overview tab.
//
// Three vertical sections:
//   1. Basic info <dl> grid (kind, hostname, agent_url, panel node, enabled,
//      created/updated, last seen)
//   2. <HostStatusPanel /> — composite ECharts panel (gauges + stats + 1h hero trends)
//   3. Active alerts list — pulled from /api/monitoring/alerts?active_only=true,
//      filtered to this host's panel node id
import { computed, inject, onBeforeUnmount, onMounted, type Ref, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import BaseCard from '@/components/ui/BaseCard.vue'
import AlertBanner from '@/components/ui/AlertBanner.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import HostStatusPanel from '@/components/hosts/HostStatusPanel.vue'
import type { HostDetail } from '@/types/host'

defineOptions({ name: 'HostOverviewPane' })

const { t, locale } = useI18n({ useScope: 'global' })
const host = inject<Ref<HostDetail | null>>('hostDetail')!
const { get } = useApiFetch()

interface AlertItem {
  id: number
  nodeId: number | null
  alertType: string
  severity: 'info' | 'warning' | 'critical'
  message: string | null
  createdAt: string
  resolvedAt: string | null
}

const alerts = ref<AlertItem[]>([])
let alertTimer: number | null = null

async function fetchAlerts() {
  const data = await get<{ items: AlertItem[] }>('/api/monitoring/alerts?active_only=true&limit=50')
  alerts.value = data?.items || []
}

onMounted(() => {
  fetchAlerts()
  // Same cadence as host status panel
  alertTimer = window.setInterval(fetchAlerts, 30_000)
})
onBeforeUnmount(() => { if (alertTimer !== null) clearInterval(alertTimer) })

const activeAlerts = computed(() => {
  const nid = host.value?.pterodactyl_node_id
  if (nid == null) return []
  return alerts.value.filter(a => a.nodeId === nid)
})

function severityTone(s: string): 'info' | 'warning' | 'danger' {
  if (s === 'critical') return 'danger'
  if (s === 'warning') return 'warning'
  return 'info'
}

function fmtDate(iso: string | null): string {
  if (!iso) return '—'
  try {
    const hasTz = /Z|[+-]\d{2}:?\d{2}$/.test(iso)
    return new Date(hasTz ? iso : iso + 'Z').toLocaleString(locale.value)
  } catch {
    return iso
  }
}

const enabledLabel = computed(() => {
  if (!host.value) return '—'
  return host.value.enabled ? t('hosts.overview.yes') : t('hosts.overview.no')
})
</script>

<template>
  <div v-if="!host" class="muted">{{ t('hosts.detail.loading') }}</div>

  <div v-else class="pane-stack">
    <BaseCard variant="bg2">
      <h3 class="section-title">{{ t('hosts.overview.basicInfo') }}</h3>
      <dl class="info-grid">
        <div class="row">
          <dt>{{ t('hosts.overview.fields.name') }}</dt>
          <dd>{{ host.name }}</dd>
        </div>
        <div class="row">
          <dt>{{ t('hosts.overview.fields.kind') }}</dt>
          <dd>{{ t(`hosts.kind.${host.kind}`) }}</dd>
        </div>
        <div class="row">
          <dt>{{ t('hosts.overview.fields.hostname') }}</dt>
          <dd class="mono">{{ host.hostname || '—' }}</dd>
        </div>
        <div class="row">
          <dt>{{ t('hosts.overview.fields.agentUrl') }}</dt>
          <dd class="mono trunc" :title="host.agent_url">{{ host.agent_url }}</dd>
        </div>
        <div class="row">
          <dt>{{ t('hosts.overview.fields.panelNode') }}</dt>
          <dd>{{ host.pterodactyl_node_id ?? '—' }}</dd>
        </div>
        <div class="row">
          <dt>{{ t('hosts.overview.fields.enabled') }}</dt>
          <dd>{{ enabledLabel }}</dd>
        </div>
        <div class="row">
          <dt>{{ t('hosts.overview.fields.createdAt') }}</dt>
          <dd>{{ fmtDate(host.created_at) }}</dd>
        </div>
        <div class="row">
          <dt>{{ t('hosts.overview.fields.lastSeenAt') }}</dt>
          <dd>{{ fmtDate(host.last_seen_at) }}</dd>
        </div>
      </dl>
    </BaseCard>

    <HostStatusPanel :hostId="host.id" :kind="host.kind" />

    <BaseCard variant="bg2">
      <h3 class="section-title">{{ t('hosts.overview.activeAlerts') }}</h3>
      <div v-if="activeAlerts.length" class="alert-stack">
        <AlertBanner
          v-for="a in activeAlerts"
          :key="a.id"
          :tone="severityTone(a.severity)"
          dense
        >
          <strong>{{ a.alertType }}</strong>
          <span v-if="a.message"> — {{ a.message }}</span>
          <span class="alert-ts"> · {{ fmtDate(a.createdAt) }}</span>
        </AlertBanner>
      </div>
      <EmptyState
        v-else
        icon="check_circle"
        :title="t('hosts.overview.noActiveAlerts')"
        density="compact"
      />
    </BaseCard>
  </div>
</template>

<style scoped>
.muted {
  color: var(--t3);
  font-size: var(--text-sm);
  padding: var(--sp-4);
}

.pane-stack {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}

.section-title {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--t2);
  letter-spacing: .04em;
  text-transform: uppercase;
  margin: 0 0 var(--sp-3) 0;
}

.info-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--sp-2) var(--sp-6);
  margin: 0;
}
.row {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.row dt {
  color: var(--t3);
  font-size: var(--text-xs);
  letter-spacing: .04em;
  text-transform: uppercase;
}
.row dd {
  color: var(--t1);
  font-size: var(--text-sm);
  margin: 0;
  min-width: 0;
}
.mono {
  font-family: var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace);
  font-variant-numeric: tabular-nums;
}
.trunc {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.alert-stack {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.alert-ts {
  color: var(--t3);
  font-size: var(--text-xs);
  margin-left: var(--sp-1);
}

@media (max-width: 720px) {
  .info-grid { grid-template-columns: 1fr; }
}
</style>
