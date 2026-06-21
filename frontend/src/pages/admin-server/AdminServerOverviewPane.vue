<script setup lang="ts">
// AdminServerOverviewPane v5 — operator dashboard, presentation-only.
// Runtime polling lives in the container (AdminServerDetailPage). This pane
// injects runtime + buffers and renders three sections.
//
// Status conventions follow the user-side console:
//   - Expiration color: ≤0 → red, ≤7 → amber, else → green; null → t2 (permanent)
//   - Header badge lives on the container (mirrors ServerDetailPage.statusBadge())
import { computed, inject, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useClipboard } from '@/composables/useClipboard'
import BaseCard from '@/components/ui/BaseCard.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import ServerStatTile from '@/components/admin-server/ServerStatTile.vue'
import ServerSparkline from '@/components/admin-server/ServerSparkline.vue'
import type {
  AdminServerDetailResponse,
  ServerRuntimeResponse,
  ServerRuntimeResources,
} from '@/types/adminServer'

defineOptions({ name: 'AdminServerOverviewPane' })

const { t, locale } = useI18n({ useScope: 'global' })
const router = useRouter()
const { copy: copyToClipboard } = useClipboard()

const detail = inject<Ref<AdminServerDetailResponse | null>>('adminServerDetail')!
const runtime = inject<Ref<ServerRuntimeResponse | null>>('adminServerRuntime')!
const runtimeStale = inject<Ref<boolean>>('adminServerRuntimeStale')!
const cpuBuffer = inject<Ref<number[]>>('adminServerCpuBuffer')!
const memBuffer = inject<Ref<number[]>>('adminServerMemBuffer')!

// ── formatters ─────────────────────────────────────────────────────────
function fmtBytesMb(mib: number | null | undefined): string {
  if (mib == null) return '—'
  if (mib >= 1024) return `${(mib / 1024).toFixed(2)} GiB`
  return `${Math.round(mib)} MiB`
}
function fmtBytesB(bytes: number | null | undefined): string {
  if (bytes == null) return '—'
  return fmtBytesMb(bytes / (1024 * 1024))
}
function fmtBytesRate(bytes: number | null | undefined): string {
  if (bytes == null) return '—'
  if (bytes >= 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${bytes} B`
}
function fmtUptimeMs(ms: number | null | undefined): string {
  if (!ms) return '—'
  const s = Math.floor(ms / 1000)
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  const m = Math.floor((s % 3600) / 60)
  if (d > 0) return `${d}d ${h}h`
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}
function fmtDate(iso: string | null): string {
  if (!iso) return '—'
  try {
    const hasTz = /Z|[+-]\d{2}:?\d{2}$/.test(iso)
    return new Date(hasTz ? iso : iso + 'Z').toLocaleDateString(locale.value)
  } catch { return iso }
}

// ── derived ────────────────────────────────────────────────────────────
const res = computed<ServerRuntimeResources>(() => runtime.value?.resources ?? {})

const primary = computed(() => detail.value?.allocations.find(a => a.isPrimary) ?? null)
const extras = computed(() => detail.value?.allocations.filter(a => !a.isPrimary) ?? [])
const primaryString = computed(() => {
  const a = primary.value
  if (!a) return ''
  return `${a.ipAlias || a.ip}:${a.port}`
})
const sftpString = computed(() => {
  const d = detail.value
  if (!d) return ''
  return `sftp://${d.owner.username}.${d.server.uuidShort}@${d.node.fqdn}:${d.node.daemonSftp}`
})

// expiration — mirrors user-side ServerConsolePage.expirationColor / text.
const daysLeft = computed<number | null>(() => {
  const exp = detail.value?.server.expirationDate
  if (!exp) return null
  const expDate = new Date(exp + 'T00:00:00')
  if (Number.isNaN(expDate.getTime())) return null
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  return Math.floor((expDate.getTime() - today.getTime()) / 86_400_000)
})
const expirationColor = computed(() => {
  if (!detail.value || detail.value.server.expirationDate === null) return 'var(--t2)'
  if (daysLeft.value === null) return 'var(--t2)'
  if (daysLeft.value < 0) return 'var(--red)'
  if (daysLeft.value <= 7) return 'var(--amber)'
  return 'var(--green)'
})
const expirationText = computed(() => {
  if (!detail.value) return ''
  if (detail.value.server.expirationDate === null) return t('adminServer.overview.values.permanent')
  if (daysLeft.value === null) return ''
  if (daysLeft.value < 0) return t('adminServer.overview.expired')
  return t('adminServer.overview.daysLeft', { n: daysLeft.value })
})

// resource tiles
const cpuPercent = computed(() => {
  const used = res.value.cpu_absolute as number | undefined
  const limit = detail.value?.server.cpu ?? 0
  if (used == null || !limit) return null
  return Math.min(100, (used / limit) * 100)
})
const memPercent = computed(() => {
  const used = res.value.memory_bytes as number | undefined
  const limitMib = detail.value?.server.memory ?? 0
  if (used == null || !limitMib) return null
  return Math.min(100, (used / (limitMib * 1024 * 1024)) * 100)
})
const diskPercent = computed(() => {
  const used = res.value.disk_bytes as number | undefined
  const limitMib = detail.value?.server.disk ?? 0
  if (used == null || !limitMib) return null
  return Math.min(100, (used / (limitMib * 1024 * 1024)) * 100)
})

const cpuValue = computed(() => {
  const v = res.value.cpu_absolute as number | undefined
  return v != null ? `${v.toFixed(1)}%` : '—'
})
const memValue = computed(() => fmtBytesB(res.value.memory_bytes as number | undefined))
const diskValue = computed(() => fmtBytesB(res.value.disk_bytes as number | undefined))
const cpuSub = computed(() => {
  const limit = detail.value?.server.cpu ?? 0
  return limit ? `/ ${limit}%` : t('adminServer.overview.values.unlimited')
})
const memSub = computed(() => {
  const limit = detail.value?.server.memory ?? 0
  return limit ? `/ ${fmtBytesMb(limit)}` : t('adminServer.overview.values.unlimited')
})
const diskSub = computed(() => {
  const limit = detail.value?.server.disk ?? 0
  return limit ? `/ ${fmtBytesMb(limit)}` : t('adminServer.overview.values.unlimited')
})
const netRx = computed(() => (res.value.network as { rx_bytes?: number } | undefined)?.rx_bytes)
const netTx = computed(() => (res.value.network as { tx_bytes?: number } | undefined)?.tx_bytes)
const netValue = computed(() => {
  if (netRx.value == null && netTx.value == null) return '—'
  return `↓${fmtBytesRate(netRx.value)} ↑${fmtBytesRate(netTx.value)}`
})
const netSub = computed(() => {
  const up = res.value.uptime as number | undefined
  return up ? `uptime ${fmtUptimeMs(up)}` : ''
})

// ── actions ────────────────────────────────────────────────────────────
function jumpUser() {
  if (!detail.value) return
  router.push({ name: 'users', query: { q: detail.value.owner.username } })
}
function jumpHost() {
  if (!detail.value?.managerHost) return
  router.push({ name: 'host-overview', params: { id: detail.value.managerHost.id } })
}
async function copy(text: string) {
  await copyToClipboard(text, {
    successMessage: t('adminServer.overview.copied'),
    failureMessage: t('adminServer.overview.copyFailed'),
  })
}
</script>

<template>
  <div v-if="!detail" class="muted">{{ t('adminServer.loading') }}</div>

  <div v-else class="pane">
    <!-- 1) Identity bar — 5 equal stat-cards -->
    <section class="ident-row">
      <div class="ident-card">
        <div class="ident-card__label">{{ t('adminServer.overview.fields.serverName') }}</div>
        <div class="ident-card__value trunc" :title="detail.server.name">{{ detail.server.name }}</div>
        <div class="ident-card__sub mono">#{{ detail.server.id }}</div>
      </div>

      <div class="ident-card">
        <div class="ident-card__label">{{ t('adminServer.overview.fields.owner') }}</div>
        <button class="ident-card__value link trunc" :title="detail.owner.username" @click="jumpUser">
          @{{ detail.owner.username }}
        </button>
        <div class="ident-card__sub mono trunc" :title="detail.owner.email">{{ detail.owner.email }}</div>
      </div>

      <div class="ident-card">
        <div class="ident-card__label">{{ t('adminServer.overview.fields.node') }}</div>
        <template v-if="detail.managerHost">
          <button class="ident-card__value link trunc" :title="detail.node.name" @click="jumpHost">
            {{ detail.node.name }}
          </button>
        </template>
        <template v-else>
          <div class="ident-card__value trunc" :title="detail.node.name">{{ detail.node.name }}</div>
        </template>
        <div class="ident-card__sub mono trunc" :title="detail.node.fqdn">{{ detail.node.fqdn }}</div>
      </div>

      <div class="ident-card">
        <div class="ident-card__label">{{ t('adminServer.overview.fields.address') }}</div>
        <div class="ident-card__value mono trunc" :title="primaryString">
          {{ primaryString || '—' }}
        </div>
        <div class="ident-card__sub">
          <button v-if="primaryString" class="mini-btn" @click="copy(primaryString)">
            <MsIcon name="content_copy" size="xxs" />{{ t('adminServer.overview.copy') }}
          </button>
          <span v-else>—</span>
        </div>
      </div>

      <div class="ident-card">
        <div class="ident-card__label">{{ t('adminServer.overview.fields.expirationDate') }}</div>
        <div class="ident-card__value" :style="{ color: expirationColor }">
          <template v-if="!detail.server.expirationDate">
            {{ t('adminServer.overview.values.permanent') }}
          </template>
          <template v-else>{{ detail.server.expirationDate }}</template>
        </div>
        <div class="ident-card__sub" :style="{ color: expirationColor }">
          {{ expirationText || '—' }}
        </div>
      </div>
    </section>

    <!-- 2) Realtime panel — tiles + 2 separate sparkline cards -->
    <BaseCard variant="bg2" class="rt">
      <header class="rt__head">
        <span class="rt__title">{{ t('adminServer.overview.sections.runtime') }}</span>
        <span v-if="runtimeStale" class="rt__stale">
          <MsIcon name="warning" size="xxs" />{{ t('adminServer.overview.values.stale') }}
        </span>
      </header>

      <div class="rt__tiles">
        <ServerStatTile
          :label="t('adminServer.overview.fields.cpuUsage')"
          :value="cpuValue"
          :sub="cpuSub"
          :percent="cpuPercent"
          :stale="runtimeStale"
        />
        <ServerStatTile
          :label="t('adminServer.overview.fields.memoryUsage')"
          :value="memValue"
          :sub="memSub"
          :percent="memPercent"
          :stale="runtimeStale"
        />
        <ServerStatTile
          :label="t('adminServer.overview.fields.diskUsage')"
          :value="diskValue"
          :sub="diskSub"
          :percent="diskPercent"
          :stale="runtimeStale"
        />
        <ServerStatTile
          :label="t('adminServer.overview.fields.network')"
          :value="netValue"
          :sub="netSub"
          :stale="runtimeStale"
        />
      </div>

      <div class="rt__sparks">
        <div class="spark-card">
          <ServerSparkline
            :label="t('adminServer.overview.spark.cpu')"
            :values="cpuBuffer"
            :unit-formatter="(v) => `${v.toFixed(1)}%`"
            color="var(--ac)"
          />
        </div>
        <div class="spark-card">
          <ServerSparkline
            :label="t('adminServer.overview.spark.mem')"
            :values="memBuffer"
            :unit-formatter="(v) => fmtBytesMb(v)"
            color="var(--blue)"
          />
        </div>
      </div>
    </BaseCard>

    <!-- 3) Extra info card — 3-col -->
    <BaseCard variant="bg2" class="extra">
      <div class="extra__cols">
        <section class="extra__col">
          <h3 class="extra__h">{{ t('adminServer.overview.sections.config') }}</h3>
          <dl class="kv">
            <div class="kv-row">
              <dt>{{ t('adminServer.overview.fields.egg') }}</dt>
              <dd>{{ detail.nest?.name || '—' }} / {{ detail.egg.name }}</dd>
            </div>
            <div class="kv-row">
              <dt>{{ t('adminServer.overview.fields.image') }}</dt>
              <dd class="mono trunc" :title="detail.server.image">{{ detail.server.image }}</dd>
            </div>
            <div class="kv-row">
              <dt>{{ t('adminServer.overview.fields.quota') }}</dt>
              <dd class="mono">
                {{ detail.server.cpu || '∞' }}% CPU<br>
                {{ detail.server.memory ? fmtBytesMb(detail.server.memory) : '∞' }} MEM<br>
                {{ detail.server.disk ? fmtBytesMb(detail.server.disk) : '∞' }} DISK
              </dd>
            </div>
          </dl>
        </section>

        <section class="extra__col">
          <h3 class="extra__h">{{ t('adminServer.overview.sections.network') }}</h3>
          <dl class="kv">
            <div class="kv-row">
              <dt>{{ t('adminServer.overview.fields.address') }}</dt>
              <dd class="mono">{{ primaryString || '—' }}</dd>
            </div>
            <div class="kv-row">
              <dt>{{ t('adminServer.overview.fields.extraAllocations') }}</dt>
              <dd class="mono">
                <template v-if="extras.length">
                  <span v-for="a in extras" :key="a.id" class="alloc-chip">{{ a.port }}</span>
                </template>
                <span v-else class="hint">{{ t('adminServer.overview.values.noExtra') }}</span>
              </dd>
            </div>
            <div class="kv-row">
              <dt>{{ t('adminServer.overview.fields.sftp') }}</dt>
              <dd class="mono trunc-with-action">
                <span class="trunc" :title="sftpString">{{ sftpString }}</span>
                <button class="copy-btn" :title="t('adminServer.overview.copy')" @click="copy(sftpString)">
                  <MsIcon name="content_copy" size="xs" />
                </button>
              </dd>
            </div>
          </dl>
        </section>

        <section class="extra__col">
          <h3 class="extra__h">{{ t('adminServer.overview.sections.meta') }}</h3>
          <dl class="kv">
            <div v-if="detail.server.description" class="kv-row">
              <dt>{{ t('adminServer.overview.fields.description') }}</dt>
              <dd class="desc">{{ detail.server.description }}</dd>
            </div>
            <div class="kv-row">
              <dt>UUID</dt>
              <dd class="mono uuid">{{ detail.server.uuid }}</dd>
            </div>
            <div v-if="detail.server.externalId" class="kv-row">
              <dt>{{ t('adminServer.overview.fields.externalId') }}</dt>
              <dd class="mono">{{ detail.server.externalId }}</dd>
            </div>
            <div class="kv-row">
              <dt>{{ t('adminServer.overview.fields.createdAt') }}</dt>
              <dd>{{ fmtDate(detail.server.createdAt) }}</dd>
            </div>
            <div class="kv-row">
              <dt>{{ t('adminServer.overview.fields.installedAt') }}</dt>
              <dd>{{ fmtDate(detail.server.installedAt) }}</dd>
            </div>
            <div class="kv-row">
              <dt>{{ t('adminServer.overview.fields.updatedAt') }}</dt>
              <dd>{{ fmtDate(detail.server.updatedAt) }}</dd>
            </div>
          </dl>
        </section>
      </div>
    </BaseCard>
  </div>
</template>

<style scoped>
.muted {
  color: var(--t3);
  font-size: var(--text-sm);
  padding: var(--sp-4);
}

.pane {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}

/* ── 1) Identity bar ────────────────────────────────────────────── */
.ident-row {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: var(--sp-2);
}
@media (max-width: 1100px) { .ident-row { grid-template-columns: repeat(3, 1fr); } }
@media (max-width: 720px)  { .ident-row { grid-template-columns: repeat(2, 1fr); } }

.ident-card {
  background: var(--bg2);
  border: 1px solid var(--bd);
  border-radius: var(--r-md);
  padding: var(--sp-3) var(--sp-4);
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.ident-card__label {
  color: var(--t3);
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: .04em;
}
.ident-card__value {
  color: var(--t1);
  font-size: var(--text-md);
  font-weight: 600;
  line-height: 1.3;
  margin-top: 2px;
  min-width: 0;
}
.ident-card__value.mono {
  font-family: 'IBM Plex Mono', ui-monospace, monospace;
  font-size: var(--text-base);
  font-weight: 500;
}
.ident-card__value.link {
  appearance: none;
  background: transparent;
  border: 0;
  padding: 0;
  font: inherit;
  font-weight: 600;
  color: var(--ac2);
  cursor: pointer;
  text-align: left;
}
.ident-card__value.link:hover { text-decoration: underline; }
.ident-card__sub {
  color: var(--t3);
  font-size: var(--text-xs);
  margin-top: 2px;
  min-width: 0;
}
.ident-card__sub.mono {
  font-family: 'IBM Plex Mono', ui-monospace, monospace;
}

.mini-btn {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  background: transparent;
  border: 0;
  padding: 0;
  color: var(--t3);
  font: inherit;
  font-size: var(--text-xs);
  cursor: pointer;
}
.mini-btn:hover { color: var(--ac2); }

/* ── 2) Realtime panel ──────────────────────────────────────────── */
.rt__head {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin-bottom: var(--sp-3);
}
.rt__title {
  color: var(--t2);
  font-size: var(--text-sm);
  font-weight: 600;
  letter-spacing: .04em;
  text-transform: uppercase;
}
.rt__stale {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 1px 6px;
  background: color-mix(in srgb, var(--amber) 14%, transparent);
  color: var(--amber);
  border-radius: 3px;
  font-size: var(--text-xs);
}
.rt__tiles {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--sp-2);
  margin-bottom: var(--sp-3);
}
.rt__sparks {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--sp-2);
}
@media (max-width: 720px) {
  .rt__tiles { grid-template-columns: repeat(2, 1fr); }
  .rt__sparks { grid-template-columns: 1fr; }
}
.spark-card {
  background: var(--bg3);
  border: 1px solid var(--bd);
  border-radius: var(--r-sm);
  padding: var(--sp-2) var(--sp-3);
  min-width: 0;
  overflow: hidden;
}

/* ── 3) Extra info ─────────────────────────────────────────────── */
.extra__cols {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--sp-5);
}
@media (max-width: 1024px) {
  .extra__cols { grid-template-columns: 1fr; gap: var(--sp-4); }
}
.extra__col { min-width: 0; }
.extra__h {
  margin: 0 0 var(--sp-2);
  color: var(--t2);
  font-size: var(--text-xs);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: .04em;
  padding-bottom: var(--sp-1);
  border-bottom: 1px solid var(--bd);
}

.kv {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  margin: 0;
}
.kv-row {
  display: grid;
  grid-template-columns: 6rem 1fr;
  gap: var(--sp-3);
  align-items: baseline;
  font-size: var(--text-sm);
  min-width: 0;
}
.kv-row dt {
  margin: 0;
  color: var(--t3);
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: .04em;
}
.kv-row dd {
  margin: 0;
  color: var(--t1);
  min-width: 0;
}

.alloc-chip {
  display: inline-block;
  padding: 1px 6px;
  margin-right: 4px;
  background: var(--bg3);
  border: 1px solid var(--bd);
  border-radius: 3px;
  font-size: var(--text-xs);
}
.trunc {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
}
.trunc-with-action {
  display: flex;
  align-items: center;
  gap: var(--sp-1);
  min-width: 0;
}
.trunc-with-action .trunc { flex: 1; }

.copy-btn {
  display: inline-flex;
  align-items: center;
  background: transparent;
  border: 0;
  color: var(--t3);
  cursor: pointer;
  padding: 0 4px;
  border-radius: 3px;
}
.copy-btn:hover { color: var(--ac2); background: var(--bg3); }

.link {
  appearance: none;
  background: transparent;
  border: 0;
  padding: 0;
  font: inherit;
  color: var(--ac2);
  cursor: pointer;
}
.link:hover { text-decoration: underline; }

.hint { color: var(--t3); font-size: var(--text-xs); }
.mono {
  font-family: 'IBM Plex Mono', ui-monospace, monospace;
  font-size: var(--text-xs);
}
.uuid {
  word-break: break-all;
  line-height: 1.4;
}
.desc {
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--t1);
  font-size: var(--text-sm);
  line-height: 1.5;
}
</style>
