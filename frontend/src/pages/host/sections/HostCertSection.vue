<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'
import { useDirtyFormSection } from '@/composables/useDirtyForm'
import CollapsibleGroup from '@/components/ui/CollapsibleGroup.vue'
import BaseCard from '@/components/ui/BaseCard.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseModal from '@/components/ui/BaseModal.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import Badge from '@/components/ui/Badge.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import Spinner from '@/components/ui/Spinner.vue'
import type { CertTarget, CertTargetsResponse, ManagedCertificate } from '@/types/certificate'

defineOptions({ name: 'HostCertSection' })

const props = defineProps<{ hostId: number; hostKind: string }>()
const { t } = useI18n({ useScope: 'global' })
const { get, post, del } = useApiFetch()
const { toast } = useToast()
const { confirm } = useConfirm()

const isWings = computed(() => props.hostKind === 'wings_node')

// ---- data ----
const loading = ref(true)
const certificates = ref<ManagedCertificate[]>([])

const certTargets = ref<CertTarget[]>([])
const targetsLoading = ref(false)

// Add modal
const addOpen = ref(false)
const selectedCertId = ref<string>('')
const selectedTargetName = ref<string>('')

// Action loading
const syncingDepId = ref<number | null>(null)
const removingDepId = ref<number | null>(null)
const adding = ref(false)

// ---- computed ----
interface DeploymentRow {
  id: number
  certId: number
  certName: string
  certDomains: string
  targetName: string
  targetType: string
  targetPath: string | null
  status: string
}

const deployments = computed<DeploymentRow[]>(() => {
  const rows: DeploymentRow[] = []
  for (const cert of certificates.value) {
    for (const dep of cert.deployments ?? []) {
      if (dep.host_id !== props.hostId) continue
      let targetType = 'wings'
      let targetPath: string | null = dep.target_cert_path ?? null
      if (dep.target_name) {
        const t = certTargets.value.find(ct => ct.name === dep.target_name)
        targetType = t?.type ?? 'file'
        targetPath = targetPath || (t?.paths?.cert ?? null)
        if (!targetPath && t?.type === 'synology_dsm') {
          targetPath = t.dsm_cert_id ? `DSM ${t.dsm_cert_id}` : (t.certificate_desc ?? null)
        }
      }
      rows.push({
        id: dep.id,
        certId: cert.id,
        certName: cert.name,
        certDomains: (cert.domains ?? []).join(', '),
        targetName: dep.target_name || t('hosts.certs.wingsDefault'),
        targetType,
        targetPath,
        status: dep.status ?? 'unknown',
      })
    }
  }
  return rows
})

const certOptions = computed(() =>
  certificates.value.map(c => ({
    value: String(c.id),
    label: `${c.name} (${(c.domains ?? []).join(', ')})`,
  })),
)

const targetOptions = computed(() => {
  const opts: { value: string; label: string }[] = []
  if (isWings.value) {
    opts.push({ value: '', label: t('hosts.certs.wingsDefaultOption') })
  }
  for (const ct of certTargets.value) {
    const typeLabel = ct.type === 'synology_dsm' ? 'DSM' : 'file'
    opts.push({ value: ct.name, label: `${ct.name} (${typeLabel})` })
  }
  return opts
})

const canAdd = computed(() => {
  if (selectedCertId.value === '') return false
  if (certOptions.value.length === 0 || targetOptions.value.length === 0) return false
  if (!isWings.value && selectedTargetName.value === '') return false
  const cert = certificates.value.find(c => String(c.id) === selectedCertId.value)
  const alreadyBound = cert?.deployments?.some(
    d => d.host_id === props.hostId && d.target_name === selectedTargetName.value,
  )
  if (alreadyBound) return false
  return true
})

// ---- dirty bar integration (cert ops are immediate, no form state) ----
const isDirty = computed(() => false)
async function save(): Promise<boolean> { return true }
function discard() {}
useDirtyFormSection({ name: 'host-cert', isDirty, save, discard })

// ---- load ----
async function load() {
  loading.value = true
  const data = await get<ManagedCertificate[]>('/api/admin/certificates', { silent: true })
  certificates.value = data ?? []
  loading.value = false
}

async function loadTargets() {
  if (targetsLoading.value) return
  targetsLoading.value = true
  const data = await get<CertTargetsResponse>(`/api/admin/hosts/${props.hostId}/cert-targets`, { silent: true })
  certTargets.value = data?.targets ?? []
  if (!isWings.value && selectedTargetName.value === '' && certTargets.value.length > 0) {
    selectedTargetName.value = certTargets.value[0].name
  }
  targetsLoading.value = false
}

onMounted(() => { load(); loadTargets() })

// ---- actions ----
function openAdd() {
  selectedCertId.value = certOptions.value[0] ? String(certOptions.value[0].value) : ''
  selectedTargetName.value = targetOptions.value[0]?.value ?? ''
  loadTargets()
  addOpen.value = true
}

async function addDeployment() {
  if (!selectedCertId.value) return
  const certId = Number(selectedCertId.value)
  adding.value = true
  try {
    const res = await post(`/api/admin/certificates/${certId}/deployments`, {
      host_id: props.hostId,
      target_name: selectedTargetName.value,
    })
    if (res) {
      toast(t('hosts.certs.toastBound'), 'success')
      addOpen.value = false
      await load()
    }
  } finally {
    adding.value = false
  }
}

async function syncDeployment(row: DeploymentRow) {
  const ok = await confirm({
    title: t('hosts.certs.confirmSyncTitle'),
    message: t('hosts.certs.confirmSyncMessage', { name: row.certName }),
    confirmText: t('hosts.certs.sync'),
    variant: 'default',
  })
  if (!ok) return
  syncingDepId.value = row.id
  try {
    await post(`/api/admin/certificates/${row.certId}/deployments/${row.id}/redeploy`)
    toast(t('hosts.certs.toastSynced'), 'success')
    await load()
  } finally {
    syncingDepId.value = null
  }
}

async function removeDeployment(row: DeploymentRow) {
  const ok = await confirm({
    title: t('hosts.certs.confirmRemoveTitle'),
    message: t('hosts.certs.confirmRemoveMessage', { name: row.certName }),
    confirmText: t('hosts.certs.remove'),
    variant: 'danger',
  })
  if (!ok) return
  removingDepId.value = row.id
  try {
    await del(`/api/admin/certificates/${row.certId}/deployments/${row.id}`)
    toast(t('hosts.certs.toastRemoved'), 'success')
    await load()
  } finally {
    removingDepId.value = null
  }
}

function statusColor(s: string): string {
  if (s === 'synced') return 'var(--green)'
  if (s === 'outdated' || s === 'deploy_failed') return 'var(--amber)'
  if (s === 'unreachable') return 'var(--red)'
  return 'var(--t3)'
}
</script>

<template>
  <BaseCard variant="bg2" class="settings-card">
    <CollapsibleGroup :title="t('hosts.certs.title')" icon="verified_user" :defaultOpen="false">
      <Spinner v-if="loading" />

      <template v-else>
        <!-- Deployment list -->
        <div v-if="deployments.length" class="cert-rows">
          <div v-for="row in deployments" :key="row.id" class="cert-row">
            <div class="cert-row__top">
              <div class="cert-row__info">
                <strong>{{ row.certName }}</strong>
                <span class="field-row">{{ t('hosts.certs.labelDomains') }}{{ row.certDomains }}</span>
              </div>
              <Badge size="sm" :color="statusColor(row.status)">
                {{ row.status }}
              </Badge>
            </div>
            <div class="cert-row__bottom">
              <small class="field-row">
                {{ t('hosts.certs.labelTarget') }}{{ row.targetName }}
                <template v-if="row.targetPath"> · {{ row.targetPath }}</template>
              </small>
              <div class="cert-row__actions">
                <BaseButton size="sm" variant="default" :loading="syncingDepId === row.id" @click="syncDeployment(row)">
                  <MsIcon name="sync" size="xs" />
                  {{ t('hosts.certs.sync') }}
                </BaseButton>
                <BaseButton size="sm" variant="danger" :loading="removingDepId === row.id" @click="removeDeployment(row)">
                  <MsIcon name="link_off" size="xs" />
                  {{ t('hosts.certs.remove') }}
                </BaseButton>
              </div>
            </div>
          </div>
        </div>
        <div v-else class="muted">
          {{ t('hosts.certs.empty') }}
        </div>

        <div class="cert-section-actions">
          <BaseButton size="sm" variant="primary" @click="openAdd">
            <MsIcon name="add" size="xs" />
            {{ t('hosts.certs.addDeployment') }}
          </BaseButton>
        </div>
      </template>
    </CollapsibleGroup>
  </BaseCard>

  <!-- Add modal -->
  <BaseModal v-model="addOpen" :title="t('hosts.certs.addDeployment')" icon="verified_user" size="sm">
    <div class="add-modal-body">
      <label class="field-label">{{ t('hosts.certs.selectCert') }}</label>
      <BaseSelect v-model="selectedCertId" :options="certOptions" valueKey="value" labelKey="label" teleport />
      <label class="field-label">{{ t('hosts.certs.selectTarget') }}</label>
      <BaseSelect v-model="selectedTargetName" :options="targetOptions" valueKey="value" labelKey="label" teleport />
      <BaseButton variant="primary" :loading="adding" :disabled="!canAdd" @click="addDeployment">
        <MsIcon name="add" size="xs" />
        {{ t('hosts.certs.confirmAdd') }}
      </BaseButton>
    </div>
  </BaseModal>
</template>

<style scoped>
.cert-rows {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.cert-row {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  padding: var(--sp-2) var(--sp-3);
  border: 1px solid var(--bd);
  border-radius: var(--r-sm);
  background: var(--bg3);
}

.cert-row__top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--sp-2);
}

.cert-row__info {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.cert-row__info strong {
  color: var(--t1);
  font-size: var(--text-sm);
}

.cert-row__info span {
  color: var(--t3);
  font-size: var(--text-xs);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cert-row__bottom {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.cert-row__bottom small {
  color: var(--t3);
  font-size: var(--text-xs);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cert-row__actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--sp-2);
}

.field-row {
  color: var(--t3);
  font-size: var(--text-xs);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cert-section-actions {
  margin-top: var(--sp-3);
  display: flex;
  justify-content: flex-end;
}

.add-modal-body {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}

.target-note {
  font-size: var(--text-sm);
  color: var(--t3);
}

.muted {
  color: var(--t3);
  font-size: var(--text-sm);
}
</style>
