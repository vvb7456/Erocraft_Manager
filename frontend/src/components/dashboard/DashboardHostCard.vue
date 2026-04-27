<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import MsIcon from '@/components/ui/MsIcon.vue'
import UsageBar from '@/components/ui/UsageBar.vue'

defineOptions({ name: 'DashboardHostCard' })

export interface DashboardHostData {
  id: number
  name: string
  fqdn: string
  kind: string
  agentOnline: boolean
  wingsOnline: boolean
  publicReachable: boolean | null
  lastSeen: string | null
  wingsVersion: string | null
  cpuPct: number | null
  cpuCores: number | null
  loadAvg: number[] | null
  memUsedMb: number | null
  memTotalMb: number | null
  memPct: number | null
  uptimeSec: number | null
  diskUsedMb: number | null
  diskTotalMb: number | null
  diskPct: number | null
  netRxBps: number | null
  netTxBps: number | null
  containerTotal: number | null
  containerRunning: number | null
  activeAlerts: number
}

const props = defineProps<{ host: DashboardHostData; removable?: boolean }>()
const emit = defineEmits<{ (e: 'unpin', id: number): void }>()
const { t } = useI18n({ useScope: 'global' })
const router = useRouter()

/* ── Kind config ── */
const KIND_META: Record<string, { icon: string; color: string; labelKey: string }> = {
  wings_node: { icon: 'deployed_code', color: 'var(--ac)', labelKey: 'hosts.kind.wings_node' },
  generic_linux: { icon: 'terminal', color: 'var(--blue)', labelKey: 'hosts.kind.generic_linux' },
  synology_dsm: { icon: 'storage', color: 'var(--amber)', labelKey: 'hosts.kind.synology_dsm' },
}
const kindMeta = computed(() => KIND_META[props.host.kind] ?? KIND_META.generic_linux)
const isWings = computed(() => props.host.kind === 'wings_node')

/* ── Status ── */
type CardStatus = 'online' | 'stale' | 'offline'
const lastSeenInfo = computed(() => {
  const iso = props.host.lastSeen
  if (!iso) return { delta: Infinity, text: '--', stale: true }
  const hasTz = /Z|[+-]\d{2}:?\d{2}$/.test(iso)
  const ts = new Date(hasTz ? iso : iso + 'Z').getTime()
  if (Number.isNaN(ts)) return { delta: Infinity, text: '--', stale: true }
  const delta = Math.max(0, Math.floor((Date.now() - ts) / 1000))
  let text: string
  if (delta < 60) text = `${delta}s`
  else if (delta < 3600) text = `${Math.floor(delta / 60)}m`
  else if (delta < 86400) text = `${Math.floor(delta / 3600)}h`
  else text = `${Math.floor(delta / 86400)}d`
  return { delta, text, stale: delta > 90 }
})

const cardStatus = computed<CardStatus>(() => {
  if (!props.host.agentOnline) return 'offline'
  if (lastSeenInfo.value.stale) return 'stale'
  return 'online'
})

/* ── Formatters ── */
function fmtBytes(bps: number | null): string {
  if (bps == null) return '0 B/s'
  if (bps < 1024) return `${bps} B/s`
  if (bps < 1024 * 1024) return `${(bps / 1024).toFixed(1)} KB/s`
  return `${(bps / 1024 / 1024).toFixed(1)} MB/s`
}
function fmtMb(mb: number | null | undefined): string {
  if (mb == null) return '--'
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`
  return `${mb} MB`
}
function fmtUptime(sec: number | null): string {
  if (sec == null || sec <= 0) return '--'
  const d = Math.floor(sec / 86400)
  const h = Math.floor((sec % 86400) / 3600)
  const m = Math.floor((sec % 3600) / 60)
  if (d > 0) return `${d}d ${h}h`
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}

function navigate() {
  router.push(`/admin/hosts/${props.host.id}/overview`)
}
function onUnpin(e: Event) {
  e.stopPropagation()
  emit('unpin', props.host.id)
}
</script>

<template>
  <div
    class="d-host-card"
    :class="[`status-${cardStatus}`]"
    role="button"
    tabindex="0"
    @click="navigate"
    @keyup.enter="navigate"
  >
    <!-- Header -->
    <div class="head">
      <div class="head-l">
        <span class="kind" :style="{ color: kindMeta.color, borderColor: kindMeta.color }">
          <MsIcon :name="kindMeta.icon" size="sm" />
          <span class="kind-label">{{ t(kindMeta.labelKey) }}</span>
        </span>
        <span class="name">{{ host.name }}</span>
        <span class="fqdn">{{ host.fqdn }}</span>
      </div>
      <div class="head-r">
        <span v-if="host.activeAlerts > 0" class="alerts">
          <MsIcon name="warning" size="sm" />
          {{ host.activeAlerts }}
        </span>
        <span class="status-dot" :class="`s-${cardStatus}`" />
        <button
          v-if="removable"
          class="unpin"
          type="button"
          :title="t('dashboard.host.unpin')"
          @click="onUnpin"
          @keydown.stop
        >
          <MsIcon name="close" size="xs" />
        </button>
      </div>
    </div>

    <!-- Metrics -->
    <div v-if="host.agentOnline" class="metrics">
      <div class="m-block">
        <div class="m-head">
          <span class="m-key">
            CPU
            <span v-if="host.cpuCores" class="m-key-sub">×{{ host.cpuCores }}</span>
          </span>
          <span class="m-val">{{ host.cpuPct != null ? `${host.cpuPct.toFixed(0)}%` : '--' }}</span>
        </div>
        <UsageBar :percent="host.cpuPct ?? 0" :height="5" :danger="85" />
      </div>
      <div class="m-block">
        <div class="m-head">
          <span class="m-key">MEM</span>
          <span class="m-val">
            {{ fmtMb(host.memUsedMb) }} <span class="m-sep">/</span> {{ fmtMb(host.memTotalMb) }}
            <span class="m-pct">{{ host.memPct != null ? `${host.memPct.toFixed(0)}%` : '' }}</span>
          </span>
        </div>
        <UsageBar :percent="host.memPct ?? 0" :height="5" :danger="85" />
      </div>
      <div class="m-block">
        <div class="m-head">
          <span class="m-key">DSK</span>
          <span class="m-val">
            {{ fmtMb(host.diskUsedMb) }} <span class="m-sep">/</span> {{ fmtMb(host.diskTotalMb) }}
            <span class="m-pct">{{ host.diskPct != null ? `${host.diskPct.toFixed(0)}%` : '' }}</span>
          </span>
        </div>
        <UsageBar :percent="host.diskPct ?? 0" :height="5" :danger="85" />
      </div>
      <div class="m-block m-block--net">
        <div class="m-head">
          <span class="m-key">NET</span>
          <span class="m-net">
            <span class="m-net-cell"><MsIcon name="arrow_downward" size="xs" />{{ fmtBytes(host.netRxBps) }}</span>
            <span class="m-net-cell"><MsIcon name="arrow_upward" size="xs" />{{ fmtBytes(host.netTxBps) }}</span>
          </span>
        </div>
      </div>
    </div>
    <div v-else class="metrics-off">
      <MsIcon name="cloud_off" size="md" />
      <span>{{ t('monitoring.node.noAgent') }}</span>
    </div>

    <!-- Footer -->
    <div class="foot">
      <span v-if="isWings && host.wingsVersion" class="foot-cell" :title="host.wingsVersion">
        <span class="foot-label">Wings:</span>
        <span class="mono">{{ host.wingsVersion }}</span>
      </span>
      <span v-if="isWings && host.containerTotal != null" class="foot-cell">
        <MsIcon name="dns" size="xs" />
        <span class="mono">{{ host.containerRunning ?? 0 }}/{{ host.containerTotal }}</span>
        <span class="foot-label">{{ t('monitoring.node.containers') }}</span>
      </span>
      <span v-if="host.uptimeSec" class="foot-cell">
        <MsIcon name="schedule" size="xs" />
        <span class="mono">{{ fmtUptime(host.uptimeSec) }}</span>
      </span>
      <span class="foot-cell foot-cell--right" :class="{ stale: lastSeenInfo.stale }">
        <MsIcon name="sync" size="xs" />
        <span class="mono">{{ lastSeenInfo.text }}</span>
      </span>
    </div>
  </div>
</template>

<style scoped>
.d-host-card {
  background: var(--bg3);
  border: 1px solid var(--bd);
  border-radius: var(--r-lg);
  padding: var(--sp-4);
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  cursor: pointer;
  transition: transform .15s ease, border-color .15s ease, box-shadow .15s ease;
  outline: none;
}
.d-host-card:hover,
.d-host-card:focus-visible {
  transform: translateY(-2px);
  border-color: var(--bd-f);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);
}
.d-host-card.status-stale {
  border-color: color-mix(in srgb, var(--amber) 45%, var(--bd));
  border-style: dashed;
}
.d-host-card.status-offline {
  opacity: 0.72;
  border-color: color-mix(in srgb, var(--red) 35%, var(--bd));
}

/* ─ Header ─ */
.head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--sp-2);
}
.head-l {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  min-width: 0;
  flex: 1 1 auto;
}
.kind {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border: 1px solid;
  border-radius: var(--r-pill);
  font-size: var(--text-xs);
  font-weight: 600;
  background: color-mix(in srgb, currentColor 8%, transparent);
}
.kind-label { letter-spacing: 0.02em; }
.name {
  font-size: var(--text-md);
  font-weight: 600;
  color: var(--t1);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}
.fqdn {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--t3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
  flex-shrink: 1;
}
.head-r {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-shrink: 0;
}
.alerts {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 2px 6px;
  background: color-mix(in srgb, var(--amber) 18%, transparent);
  color: var(--amber);
  border-radius: var(--r-sm);
  font-size: var(--text-xs);
  font-weight: 700;
}
.status-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
  box-shadow: 0 0 0 3px color-mix(in srgb, currentColor 22%, transparent);
}
.s-online { background: var(--green); color: var(--green); }
.s-stale { background: var(--amber); color: var(--amber); }
.s-offline { background: var(--red); color: var(--red); }

.unpin {
  width: 22px;
  height: 22px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: transparent;
  color: var(--t3);
  border-radius: var(--r-sm);
  cursor: pointer;
  opacity: 0;
  transition: opacity .12s ease, background .12s ease, color .12s ease;
  padding: 0;
}
.d-host-card:hover .unpin,
.d-host-card:focus-within .unpin { opacity: 1; }
.unpin:hover { background: color-mix(in srgb, var(--red) 18%, transparent); color: var(--red); }

/* ─ Metrics ─ */
.metrics {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.m-block {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.m-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--sp-2);
  font-size: var(--text-xs);
  font-variant-numeric: tabular-nums;
  min-width: 0;
}
.m-key {
  color: var(--t3);
  font-weight: 600;
  letter-spacing: 0.04em;
  flex-shrink: 0;
}
.m-key-sub {
  color: var(--t3);
  font-weight: 400;
  font-size: 10px;
  margin-left: 2px;
  opacity: 0.7;
}
.m-val {
  color: var(--t1);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  text-align: right;
  min-width: 0;
}
.m-sep { color: var(--t3); }
.m-pct { color: var(--t3); margin-left: 4px; font-size: 10px; }

.m-block--net .m-head { align-items: center; }
.m-net {
  display: flex;
  gap: var(--sp-3);
  color: var(--t1);
}
.m-net-cell {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  font-family: var(--font-mono);
}
.m-net-cell :deep(.ms-icon) { color: var(--t3); }

.metrics-off {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--sp-1);
  padding: var(--sp-4) 0;
  color: var(--t3);
  font-size: var(--text-xs);
}

/* ─ Footer ─ */
.foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-3);
  font-size: var(--text-xs);
  color: var(--t3);
  padding-top: var(--sp-2);
  border-top: 1px dashed var(--bd);
}
.foot-cell {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.foot-cell--right { margin-left: auto; }
.foot-cell.stale { color: var(--amber); }
.mono { font-family: var(--font-mono); color: var(--t1); }
.foot-cell.stale .mono { color: var(--amber); }
.foot-label { color: var(--t3); }
</style>
