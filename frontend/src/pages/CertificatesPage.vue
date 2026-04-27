<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useConfirm } from '@/composables/useConfirm'
import { useToast } from '@/composables/useToast'
import PageHeader from '@/components/layout/PageHeader.vue'
import StatCard from '@/components/ui/StatCard.vue'
import BaseCard from '@/components/ui/BaseCard.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseModal from '@/components/ui/BaseModal.vue'
import AddCard from '@/components/ui/AddCard.vue'
import Badge from '@/components/ui/Badge.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import StatusDot from '@/components/ui/StatusDot.vue'
import LoadingCenter from '@/components/ui/LoadingCenter.vue'
import DataTable from '@/components/ui/DataTable.vue'
import CardTap from '@/components/ui/CardTap.vue'
import CardKV from '@/components/ui/CardKV.vue'
import type { AcmeCertificate, AcmeStatus, CertificateDeployment, ManagedCertificate } from '@/types/certificate'
import type { HostDetail } from '@/types/host'

defineOptions({ name: 'CertificatesPage' })

const { t } = useI18n({ useScope: 'global' })
const { get, post } = useApiFetch()
const { confirm } = useConfirm()
const { toast } = useToast()

const certificates = ref<ManagedCertificate[]>([])
const acmeStatus = ref<AcmeStatus | null>(null)
const hosts = ref<HostDetail[]>([])
const loading = ref(true)
const addOpen = ref(false)
const renewingId = ref<number | null>(null)
const registeringKey = ref<string | null>(null)
const page = ref(1)
const perPage = ref(20)
const syncingId = ref<number | null>(null)

interface DeploymentRow {
  id: number
  cert: ManagedCertificate
  dep: CertificateDeployment
  host: HostDetail | null
}

function parseDate(value: string | null): Date | null {
  if (!value) return null
  const normalized = /Z|[+-]\d{2}:?\d{2}$/.test(value) ? value : `${value}Z`
  const dt = new Date(normalized)
  return Number.isNaN(dt.getTime()) ? null : dt
}

function formatDate(value: string | null): string {
  const dt = parseDate(value)
  if (!dt) return t('certificates.common.none')
  return dt.toLocaleString()
}

function daysLeft(value: string | null): number | null {
  const dt = parseDate(value)
  if (!dt) return null
  return Math.ceil((dt.getTime() - Date.now()) / 86400000)
}

function formatDays(value: string | null): string {
  const days = daysLeft(value)
  if (days === null) return t('certificates.common.unknown')
  if (days < 0) return t('certificates.days.expired', { n: Math.abs(days) })
  if (days === 0) return t('certificates.days.today')
  return t('certificates.days.left', { n: days })
}

function shortHash(value: string | null): string {
  if (!value) return t('certificates.common.none')
  return `${value.slice(0, 10)}...${value.slice(-6)}`
}

function certStatus(cert: ManagedCertificate): 'ok' | 'warning' | 'error' | 'disabled' | 'unknown' {
  if (!cert.enabled) return 'disabled'
  if (cert.source_last_error) return 'error'
  const days = daysLeft(cert.source_not_after)
  if (days === null || !cert.source_fingerprint_sha256) return 'unknown'
  if (days < 0) return 'error'
  if (days <= cert.alert_threshold_days) return 'warning'
  return 'ok'
}

function deploymentStatus(dep: CertificateDeployment): 'ok' | 'warning' | 'error' | 'unknown' {
  if (dep.status === 'synced') return 'ok'
  if (dep.status === 'outdated' || dep.status === 'unknown') return 'warning'
  if (dep.status === 'deploy_failed' || dep.status === 'unreachable') return 'error'
  return 'unknown'
}

function statStatus(kind: 'ok' | 'warning' | 'error' | 'disabled' | 'unknown'): 'running' | 'loading' | 'error' | 'stopped' {
  if (kind === 'ok') return 'running'
  if (kind === 'warning' || kind === 'unknown') return 'loading'
  if (kind === 'disabled') return 'stopped'
  return 'error'
}

function hostAgentStatus(host: HostDetail | null): 'running' | 'error' | 'stopped' {
  if (!host || !host.enabled) return 'stopped'
  return host.inbound_reachable ? 'running' : 'error'
}

function deploymentPath(dep: CertificateDeployment): string {
  return dep.target_cert_path || dep.target_name || t('certificates.common.unknown')
}

const hostsById = computed(() => new Map(hosts.value.map(h => [h.id, h])))

const acmeByCertId = computed(() => {
  const map = new Map<number, AcmeCertificate>()
  for (const cert of acmeStatus.value?.certificates ?? []) {
    if (cert.registered_certificate_id !== null) map.set(cert.registered_certificate_id, cert)
  }
  return map
})

const deploymentRows = computed<DeploymentRow[]>(() =>
  certificates.value.flatMap(cert =>
    cert.deployments.map(dep => ({
      id: dep.id,
      cert,
      dep,
      host: hostsById.value.get(dep.host_id) ?? null,
    })),
  ),
)

const totalPages = computed(() => Math.max(1, Math.ceil(deploymentRows.value.length / perPage.value)))
const paginatedRows = computed(() => {
  const start = (page.value - 1) * perPage.value
  return deploymentRows.value.slice(start, start + perPage.value)
})

const expiringCount = computed(() =>
  certificates.value.filter(c => {
    const st = certStatus(c)
    return st === 'warning' || st === 'error'
  }).length,
)

const deploymentProblems = computed(() =>
  deploymentRows.value.filter(row => deploymentStatus(row.dep) !== 'ok').length,
)

const syncedDeployments = computed(() =>
  deploymentRows.value.filter(row => row.dep.status === 'synced').length,
)

const acmeOk = computed(() =>
  !!acmeStatus.value?.home_exists && !!acmeStatus.value?.binary_exists && !!acmeStatus.value?.binary_executable,
)

const availableAcme = computed(() =>
  (acmeStatus.value?.certificates ?? []).filter(cert =>
    cert.registered_certificate_id === null && cert.source_compatible,
  ),
)

async function loadAll() {
  loading.value = true
  try {
    const [certData, acmeData, hostData] = await Promise.all([
      get<ManagedCertificate[]>('/api/admin/certificates', { silent: true }),
      get<AcmeStatus>('/api/admin/certificates/acme/status', { silent: true }),
      get<HostDetail[]>('/api/admin/hosts', { silent: true }),
    ])
    if (certData) certificates.value = certData
    if (acmeData) acmeStatus.value = acmeData
    if (hostData) hosts.value = hostData
  } finally {
    loading.value = false
  }
}

onMounted(loadAll)

async function renewForce(cert: ManagedCertificate) {
  const ok = await confirm({
    title: t('certificates.confirm.renewTitle'),
    message: t('certificates.confirm.renewMessage', { name: cert.name }),
    confirmText: t('certificates.actions.forceRenew'),
    variant: 'danger',
  })
  if (!ok) return
  renewingId.value = cert.id
  try {
    const res = await post<Record<string, unknown>>(`/api/admin/certificates/${cert.id}/renew-force`)
    if (res) {
      toast(t('certificates.toast.renewed'), 'success')
      await loadAll()
    }
  } finally {
    renewingId.value = null
  }
}

async function registerAcme(cert: AcmeCertificate) {
  registeringKey.value = `${cert.domain}-${cert.is_ecc}`
  try {
    const res = await post<ManagedCertificate>('/api/admin/certificates/acme/register', {
      domain: cert.domain,
      is_ecc: cert.is_ecc,
      name: cert.domain,
    })
    if (res) {
      toast(t('certificates.toast.registered'), 'success')
      addOpen.value = false
      await loadAll()
    }
  } finally {
    registeringKey.value = null
  }
}

async function syncDeployment(row: DeploymentRow) {
  const ok = await confirm({
    title: t('certificates.confirm.syncTitle'),
    message: t('certificates.confirm.syncMessage', { host: row.dep.host_name || row.host?.name || row.dep.host_id }),
    confirmText: t('certificates.actions.forceSync'),
    variant: 'default',
  })
  if (!ok) return
  syncingId.value = row.dep.id
  try {
    await post(`/api/admin/certificates/${row.cert.id}/deployments/${row.dep.id}/redeploy`)
    toast(t('certificates.toast.synced'), 'success')
    await loadAll()
  } finally {
    syncingId.value = null
  }
}

function cardTone(cert: ManagedCertificate): 'default' | 'danger' {
  return certStatus(cert) === 'error' ? 'danger' : 'default'
}
</script>

<template>
  <PageHeader icon="workspace_premium" :title="t('certificates.title')" />

  <LoadingCenter v-if="loading && certificates.length === 0" />

  <div v-else class="page-body cert-page">
    <section class="stat-grid" aria-label="certificate summary">
      <StatCard :label="t('certificates.stats.count')" status="info" variant="kpi">
        <template #value>{{ certificates.length }}</template>
        <template #sub>{{ t('certificates.stats.enabled', { n: certificates.filter(c => c.enabled).length }) }}</template>
      </StatCard>
      <StatCard
        :label="t('certificates.stats.certStatus')"
        :status="expiringCount > 0 ? 'loading' : 'running'"
        variant="kpi"
        :tone="expiringCount > 0 ? 'warn' : 'default'"
      >
        <template #value>{{ expiringCount > 0 ? expiringCount : t('certificates.stats.ok') }}</template>
        <template #sub>{{ expiringCount > 0 ? t('certificates.stats.expiring') : t('certificates.stats.noExpiring') }}</template>
      </StatCard>
      <StatCard
        :label="t('certificates.stats.acme')"
        :status="acmeOk ? 'running' : 'error'"
        variant="kpi"
      >
        <template #value>{{ acmeOk ? t('certificates.stats.ready') : t('certificates.stats.error') }}</template>
        <template #sub>{{ t('certificates.stats.acmeFound', { n: acmeStatus?.certificate_count ?? 0 }) }}</template>
      </StatCard>
      <StatCard
        :label="t('certificates.stats.deployments')"
        :status="deploymentProblems > 0 ? 'error' : 'running'"
        variant="kpi"
        :tone="deploymentProblems > 0 ? 'warn' : 'default'"
      >
        <template #value>{{ syncedDeployments }}/{{ deploymentRows.length }}</template>
        <template #sub>{{ deploymentProblems > 0 ? t('certificates.stats.deployProblems', { n: deploymentProblems }) : t('certificates.stats.deployOk') }}</template>
      </StatCard>
    </section>

    <section class="cert-card-grid" aria-label="certificates">
      <div class="section-title-row cert-section-title">
        <h2>{{ t('certificates.certificates.title') }}</h2>
      </div>

      <BaseCard
        v-for="cert in certificates"
        :key="cert.id"
        class="cert-card"
        :tone="cardTone(cert)"
        variant="bg3"
        radius="md"
        density="compact"
      >
        <div class="cert-card__top">
          <div class="cert-card__title-wrap">
            <div class="cert-title-row">
              <h3 class="cert-card__title">
                <span>{{ cert.name }}</span>
                <span class="cert-state" :class="`cert-state--${certStatus(cert)}`">
                  <StatusDot :status="statStatus(certStatus(cert))" size="sm" />
                  {{ t(`certificates.status.${certStatus(cert)}`) }}
                </span>
              </h3>
            </div>
          </div>
          <div class="cert-card__actions">
            <BaseButton
              size="sm"
              square
              variant="warning"
              :loading="renewingId === cert.id"
              :ariaLabel="t('certificates.actions.forceRenew')"
              :title="t('certificates.actions.forceRenew')"
              @click="renewForce(cert)"
            >
              <MsIcon name="sync" size="xs" />
            </BaseButton>
          </div>
        </div>

        <div class="domain-list">
          <Badge v-for="domain in cert.domains" :key="domain" size="sm" color="var(--blue)">
            {{ domain }}
          </Badge>
        </div>

        <div class="cert-kv">
          <span>{{ t('certificates.card.lastUpdated') }}</span>
          <strong>{{ formatDate(cert.source_not_before) }}</strong>
          <span>{{ t('certificates.card.expires') }}</span>
          <strong>{{ formatDate(cert.source_not_after) }}</strong>
          <span>{{ t('certificates.card.remaining') }}</span>
          <strong>{{ formatDays(cert.source_not_after) }}</strong>
          <span>{{ t('certificates.card.nextRenew') }}</span>
          <strong>{{ formatDate(acmeByCertId.get(cert.id)?.next_renew_time_iso ?? null) }}</strong>
          <span>{{ t('certificates.card.fingerprint') }}</span>
          <strong class="mono">{{ shortHash(cert.source_fingerprint_sha256) }}</strong>
          <span>{{ t('certificates.card.sourcePath') }}</span>
          <strong class="mono path-value" :title="cert.source_path">{{ cert.source_path }}</strong>
        </div>

        <p v-if="cert.source_last_error" class="cert-error">{{ cert.source_last_error }}</p>
      </BaseCard>

      <AddCard class="cert-add-card" :label="t('certificates.addCard')" @click="addOpen = true" />
    </section>

    <section class="deployment-section" aria-label="deployment statuses">
      <div class="section-title-row deploy-section-title">
        <h2>{{ t('certificates.nodes.title') }}</h2>
      </div>

      <DataTable
        :items="paginatedRows"
        :page="page"
        :total-pages="totalPages"
        :per-page="perPage"
        row-key="id"
        :per-page-label="t('certificates.nodes.perPage')"
        empty-icon="lan"
        :empty-text="t('certificates.nodes.empty')"
        @update:page="page = $event"
        @update:per-page="perPage = $event; page = 1"
      >
        <template #header>
          <th class="col-host">{{ t('certificates.nodes.host') }}</th>
          <th class="col-agent">{{ t('certificates.nodes.agent') }}</th>
          <th class="col-sync">{{ t('certificates.nodes.sync') }}</th>
          <th class="col-domains">{{ t('certificates.nodes.domains') }}</th>
          <th class="col-days">{{ t('certificates.nodes.days') }}</th>
          <th class="col-next">{{ t('certificates.nodes.nextRenew') }}</th>
          <th class="col-path">{{ t('certificates.nodes.path') }}</th>
          <th class="col-actions">{{ t('certificates.nodes.actions') }}</th>
        </template>

        <template #row="{ item: row }">
          <td class="col-host">
            <div class="host-cell">
              <span>{{ row.dep.host_name || row.host?.name || row.dep.host_id }}</span>
              <small>{{ row.dep.host_kind || row.host?.kind || '-' }}</small>
            </div>
          </td>
          <td class="col-agent">
            <span class="status-cell">
              <StatusDot :status="hostAgentStatus(row.host)" size="sm" />
              {{ row.host?.enabled === false ? t('certificates.agent.disabled') : row.host?.inbound_reachable ? t('certificates.agent.online') : t('certificates.agent.offline') }}
            </span>
          </td>
          <td class="col-sync">
            <Badge size="sm" :color="deploymentStatus(row.dep) === 'ok' ? 'var(--green)' : deploymentStatus(row.dep) === 'error' ? 'var(--red)' : 'var(--amber)'">
              {{ t(`certificates.deployment.${row.dep.status}`) }}
            </Badge>
          </td>
          <td class="col-domains">
            <div class="domain-lines">
              <span v-for="domain in row.cert.domains" :key="domain">{{ domain }}</span>
            </div>
          </td>
          <td class="col-days">{{ formatDays(row.cert.source_not_after) }}</td>
          <td class="col-next">{{ formatDate(acmeByCertId.get(row.cert.id)?.next_renew_time_iso ?? null) }}</td>
          <td
            class="col-path mono clip"
            :title="row.dep.target_path_error || deploymentPath(row.dep)"
          >
            {{ deploymentPath(row.dep) }}
          </td>
          <td class="col-actions">
            <BaseButton
              size="sm"
              variant="warning"
              :loading="syncingId === row.dep.id"
              @click="syncDeployment(row)"
            >
              <MsIcon name="sync" size="xs" />
              {{ t('certificates.actions.forceSync') }}
            </BaseButton>
          </td>
        </template>

        <template #card="{ item: row }">
          <CardTap>
            <div class="mobile-row-main">
              <span>{{ row.dep.host_name || row.host?.name || row.dep.host_id }}</span>
              <Badge size="sm" :color="deploymentStatus(row.dep) === 'ok' ? 'var(--green)' : deploymentStatus(row.dep) === 'error' ? 'var(--red)' : 'var(--amber)'">
                {{ t(`certificates.deployment.${row.dep.status}`) }}
              </Badge>
            </div>
            <div class="mobile-domains">
              <span v-for="domain in row.cert.domains" :key="domain">{{ domain }}</span>
            </div>
            <div class="mobile-kv">
              <CardKV :label="t('certificates.nodes.agent')">
                <StatusDot :status="hostAgentStatus(row.host)" size="sm" />
              </CardKV>
              <CardKV :label="t('certificates.nodes.days')">{{ formatDays(row.cert.source_not_after) }}</CardKV>
              <CardKV :label="t('certificates.nodes.nextRenew')">{{ formatDate(acmeByCertId.get(row.cert.id)?.next_renew_time_iso ?? null) }}</CardKV>
            </div>
            <div class="mobile-path mono" :title="row.dep.target_path_error || deploymentPath(row.dep)">
              {{ deploymentPath(row.dep) }}
            </div>
            <div class="mobile-actions">
              <BaseButton size="sm" variant="warning" :loading="syncingId === row.dep.id" @click.stop="syncDeployment(row)">
                <MsIcon name="sync" size="xs" />
                {{ t('certificates.actions.forceSync') }}
              </BaseButton>
            </div>
          </CardTap>
        </template>
      </DataTable>
    </section>

  </div>

  <BaseModal
    v-model="addOpen"
    :title="t('certificates.selector.title')"
    icon="add"
    size="lg"
  >
    <div class="selector-list">
      <div v-if="availableAcme.length === 0" class="selector-empty">
        {{ t('certificates.selector.empty') }}
      </div>
      <div
        v-for="cert in availableAcme"
        :key="`${cert.domain}-${cert.is_ecc}`"
        class="selector-row"
      >
        <div class="selector-main">
          <strong>{{ cert.domain }}</strong>
          <span>{{ [cert.domain, ...cert.alt_names].join(', ') }}</span>
          <small class="mono">{{ cert.source_path }}</small>
        </div>
        <div class="selector-meta">
          <Badge size="sm" color="var(--blue)">acme.sh</Badge>
          <span>{{ formatDays(cert.not_after) }}</span>
        </div>
        <BaseButton
          size="sm"
          variant="primary"
          :loading="registeringKey === `${cert.domain}-${cert.is_ecc}`"
          @click="registerAcme(cert)"
        >
          <MsIcon name="add" size="xs" />
          {{ t('certificates.selector.add') }}
        </BaseButton>
      </div>
    </div>
  </BaseModal>
</template>

<style scoped>
.cert-page {
  display: flex;
  flex-direction: column;
  gap: var(--sp-5);
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--sp-3);
}

.cert-card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(310px, 1fr));
  gap: var(--sp-3);
  align-items: stretch;
}

.cert-section-title {
  grid-column: 1 / -1;
  margin-bottom: 0;
}

.cert-card,
.cert-add-card {
  min-height: 260px;
}

.deployment-section {
  min-width: 0;
}

.deploy-section-title {
  grid-column: 1 / -1;
  margin-bottom: 0;
}

.cert-card__top {
  display: flex;
  justify-content: space-between;
  gap: var(--sp-2);
  align-items: flex-start;
}

.cert-card__title-wrap {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex: 1 1 auto;
}

.cert-title-row {
  min-width: 0;
}

.cert-card__title {
  margin: 0;
  min-width: 0;
  color: var(--t1);
  font-size: .98rem;
  font-weight: 650;
  line-height: 1.35;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  word-break: break-word;
}

.cert-state {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-left: 8px;
  vertical-align: baseline;
  color: var(--t2);
  font-size: var(--text-xs);
  line-height: 1.2;
  font-weight: 500;
  white-space: nowrap;
}

.cert-state--ok {
  color: var(--green);
}

.cert-state--warning,
.cert-state--unknown {
  color: var(--amber);
}

.cert-state--error {
  color: var(--red);
}

.cert-state--disabled {
  color: var(--t3);
}

.cert-card__actions {
  display: inline-flex;
  gap: var(--sp-1);
  flex-shrink: 0;
}

.domain-list {
  display: flex;
  gap: var(--sp-1);
  flex-wrap: wrap;
  margin-top: var(--sp-3);
}

.cert-kv {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  gap: 7px var(--sp-3);
  margin-top: var(--sp-4);
  font-size: var(--text-sm);
}

.cert-kv span {
  color: var(--t3);
}

.cert-kv strong {
  min-width: 0;
  color: var(--t1);
  font-weight: 500;
}

.cert-error {
  margin: var(--sp-3) 0 0;
  color: var(--red);
  font-size: var(--text-sm);
  line-height: 1.5;
}

.node-section {
  min-width: 0;
}

.section-title-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--sp-3);
  margin-bottom: var(--sp-2);
}

.section-title-row h2 {
  margin: 0;
  font-size: 1rem;
  color: var(--t1);
}

.col-host { width: 16%; }
.col-agent { width: 10%; }
.col-sync { width: 10%; }
.col-domains { width: 18%; }
.col-days { width: 10%; }
.col-next { width: 14%; }
.col-path { width: 16%; }
.col-actions { width: 12%; text-align: right; }

.host-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.host-cell small {
  color: var(--t3);
}

.status-cell {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-1);
}

.domain-lines {
  display: flex;
  flex-direction: column;
  gap: 2px;
  white-space: normal;
}

.mono {
  font-family: 'IBM Plex Mono', ui-monospace, SFMono-Regular, monospace;
  font-size: var(--text-sm);
}

.clip {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.path-value {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mobile-row-main {
  display: flex;
  justify-content: space-between;
  gap: var(--sp-2);
  color: var(--t1);
  font-weight: 600;
}

.mobile-domains {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-top: var(--sp-2);
  color: var(--t2);
}

.mobile-kv {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--sp-3);
  margin-top: var(--sp-3);
}

.mobile-path {
  margin-top: var(--sp-2);
  color: var(--t3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mobile-actions {
  margin-top: var(--sp-3);
  display: flex;
  justify-content: flex-end;
}

.selector-list {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.selector-empty {
  color: var(--t3);
  padding: var(--sp-4);
  text-align: center;
}

.selector-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  gap: var(--sp-3);
  align-items: center;
  padding: var(--sp-3);
  border: 1px solid var(--bd);
  border-radius: var(--r-sm);
  background: var(--bg2);
}

.selector-main {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.selector-main span,
.selector-main small,
.selector-meta {
  color: var(--t3);
  font-size: var(--text-sm);
}

.selector-meta {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}

@media (max-width: 980px) {
  .stat-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 768px) {
  .stat-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .cert-card-grid {
    grid-template-columns: 1fr;
  }

  .cert-card,
  .cert-add-card {
    min-height: 0;
  }

  .selector-row {
    grid-template-columns: 1fr;
  }

  .selector-meta {
    justify-content: space-between;
  }
}
</style>
