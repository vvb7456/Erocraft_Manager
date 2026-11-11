<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useConfirm } from '@/composables/useConfirm'
import { useToast } from '@/composables/useToast'
import { useFormatDate } from '@/composables/useFormatDate'
import BaseModal from '@/components/ui/BaseModal.vue'
import BaseCard from '@/components/ui/BaseCard.vue'
import SectionToolbar from '@/components/ui/SectionToolbar.vue'
import DataTable from '@/components/ui/DataTable.vue'
import FilterInput from '@/components/ui/FilterInput.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import Badge from '@/components/ui/Badge.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import CardTap from '@/components/ui/CardTap.vue'
import CardKV from '@/components/ui/CardKV.vue'
import ActionSheet from '@/components/ui/ActionSheet.vue'

defineOptions({ name: 'RedemptionBatchDetailModal' })

export interface RedemptionExportItem {
  id: number
  batch_id: number
  quantity: number
  created_by: number | null
  created_by_username: string | null
  created_at: string
}

export interface RedemptionBatchSummary {
  id: number
  name: string
  source: string
  spec_key: string | null
  plan_id: number | null
  plan_name: string | null
  plan_code: string | null
  days: number
  amount_fen: number
  channel: string
  quantity: number
  unused_count: number
  redeemed_count: number
  void_count: number
  expired_count: number
  exported_count: number
  exportable_count: number
  expires_at: string | null
  created_by: number | null
  created_by_username: string | null
  created_at: string
  exports?: RedemptionExportItem[]
}

export interface RedemptionCodeItem {
  id: number
  code: string
  batch_id: number
  batch_name: string | null
  source: string
  plan_id: number | null
  plan_name: string | null
  days: number
  amount_fen: number
  channel: string
  status: string
  export_id: number | null
  external_order_id: string | null
  redeemed_by: number | null
  redeemed_by_username: string | null
  redeemed_at: string | null
  order_id: number | null
  order_no: string | null
  target_server_id: number | null
  target_server_name: string | null
  expires_at: string | null
  voided_at: string | null
  void_reason: string | null
  created_at: string
}

const props = defineProps<{
  modelValue: boolean
  batchId: number | null
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  updated: []
}>()

const { t, te } = useI18n({ useScope: 'global' })
const { get, raw, handleError } = useApiFetch()
const { confirm } = useConfirm()
const { toast } = useToast()
const { formatDateTime: fmtDate } = useFormatDate()

const batch = ref<RedemptionBatchSummary | null>(null)
const items = ref<RedemptionCodeItem[]>([])
const total = ref(0)
const loading = ref(false)
const exporting = ref(false)

const searchQuery = ref('')
const statusFilter = ref('all')
const limit = ref(20)
const offset = ref(0)

const page = computed({
  get: () => Math.floor(offset.value / limit.value) + 1,
  set: (p: number) => { offset.value = Math.max(0, (p - 1) * limit.value) },
})
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / limit.value)))

const statusOptions = computed(() => [
  { value: 'all', label: t('billing.admin.redemption.detail.filterAllStatus') },
  { value: 'unused', label: t('billing.admin.redemption.detail.status.unused') },
  { value: 'redeemed', label: t('billing.admin.redemption.detail.status.redeemed') },
  { value: 'expired', label: t('billing.admin.redemption.detail.status.expired') },
  { value: 'void', label: t('billing.admin.redemption.detail.status.void') },
])

function statusColor(s: string): string {
  switch (s) {
    case 'unused': return 'var(--green)'
    case 'redeeming': return 'var(--amber)'
    case 'redeemed': return 'var(--blue)'
    case 'expired': return 'var(--t3)'
    case 'void': return 'var(--red)'
    default: return 'var(--t3)'
  }
}

function statusLabel(s: string): string {
  const key = `billing.admin.redemption.detail.status.${s}`
  return te(key) ? t(key) : s
}

function fenToYuan(fen: number): string {
  return (fen / 100).toFixed(2)
}

async function loadDetail() {
  if (!props.batchId) return
  const data = await get<RedemptionBatchSummary>(
    `/api/admin/billing/redemption/batches/${props.batchId}`,
    { silent: true },
  )
  if (data) batch.value = data
}

async function loadCodes() {
  if (!props.batchId) return
  loading.value = true
  const qs = new URLSearchParams({
    batch_id: String(props.batchId),
    limit: String(limit.value),
    offset: String(offset.value),
  })
  if (statusFilter.value !== 'all') qs.set('status', statusFilter.value)
  if (searchQuery.value.trim()) qs.set('q', searchQuery.value.trim())
  try {
    const data = await get<{ items: RedemptionCodeItem[]; total: number }>(
      `/api/admin/billing/redemption/codes?${qs.toString()}`,
      { silent: true },
    )
    if (data) {
      items.value = data.items
      total.value = data.total
    }
  } finally {
    loading.value = false
  }
}

watch(
  () => [props.modelValue, props.batchId] as const,
  async ([open, id]) => {
    if (open && id) {
      searchQuery.value = ''
      statusFilter.value = 'all'
      offset.value = 0
      await Promise.all([loadDetail(), loadCodes()]).catch(handleError)
    }
  },
  { immediate: true },
)

watch([searchQuery, statusFilter], () => {
  if (!props.modelValue || !props.batchId) return
  offset.value = 0
  void loadCodes().catch(handleError)
})

watch(page, () => {
  if (!props.modelValue || !props.batchId) return
  void loadCodes().catch(handleError)
})

async function copyCode(code: string) {
  try {
    await navigator.clipboard.writeText(code)
    toast(t('billing.admin.redemption.copiedCode'), 'success')
  } catch {
    toast(t('billing.pay.copyFailed'), 'error')
  }
}

function triggerBlobDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

async function doExportRemaining() {
  if (!batch.value || batch.value.exportable_count <= 0) return
  exporting.value = true
  try {
    const res = await raw(`/api/admin/billing/redemption/batches/${batch.value.id}/export`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    })
    const blob = await res.blob()
    triggerBlobDownload(blob, `redemption_batch_${batch.value.id}.txt`)
    toast(t('billing.admin.redemption.exportAllOk'), 'success')
    await Promise.all([loadDetail(), loadCodes()])
    emit('updated')
  } catch (err) {
    handleError(err)
  } finally {
    exporting.value = false
  }
}

async function doDownloadExport(exp: RedemptionExportItem) {
  try {
    const res = await raw(`/api/admin/billing/redemption/exports/${exp.id}/download`, {
      method: 'GET',
    })
    const blob = await res.blob()
    triggerBlobDownload(blob, `redemption_batch_${exp.batch_id}_export_${exp.id}.txt`)
  } catch (err) {
    handleError(err)
  }
}

async function doVoidCode(c: RedemptionCodeItem) {
  const ok = await confirm({
    title: t('billing.admin.redemption.detail.voidCode'),
    message: t('billing.admin.redemption.detail.voidCodeConfirm', { code: c.code }),
    variant: 'danger',
    confirmText: t('billing.admin.redemption.detail.voidCode'),
  })
  if (!ok) return
  try {
    const res = await raw(`/api/admin/billing/redemption/codes/${c.id}/void`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason: t('billing.admin.redemption.detail.voidReasonDefault') }),
    })
    const updated = (await res.json()) as RedemptionCodeItem
    const idx = items.value.findIndex((x) => x.id === updated.id)
    if (idx >= 0) items.value.splice(idx, 1, updated)
    toast(t('billing.admin.redemption.detail.voidCodeOk'), 'success')
    await loadDetail()
    emit('updated')
  } catch (err) {
    handleError(err)
  }
}

const mobileTarget = ref<RedemptionCodeItem | null>(null)
const mobileOpen = ref(false)
function openMobile(c: RedemptionCodeItem) {
  mobileTarget.value = c
  mobileOpen.value = true
}
</script>

<template>
  <BaseModal
    :model-value="modelValue"
    :title="batch ? t('billing.admin.redemption.detail.title', { name: batch.name }) : ''"
    icon="redeem"
    size="xl"
    :close-on-overlay="true"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div v-if="batch" class="batch-detail">
      <BaseCard variant="bg3" density="compact" class="export-card">
        <div class="export-bar">
          <div class="export-meta">
            <span class="meta-chip">{{ batch.plan_name || `#${batch.plan_id}` }}</span>
            <span class="meta-sep">·</span>
            <span class="meta-chip">{{ t('billing.admin.redemption.daysValue', { days: batch.days }) }}</span>
            <span class="meta-sep">·</span>
            <span class="meta-chip mono">¥{{ fenToYuan(batch.amount_fen) }}</span>
            <span class="meta-sep">·</span>
            <span class="meta-chip">{{ t(`billing.channel.${batch.channel}`) }}</span>
            <span class="meta-sep">·</span>
            <span class="meta-chip">
              {{ t('billing.admin.redemption.progressText', { redeemed: batch.redeemed_count, unused: batch.unused_count, total: batch.quantity }) }}
            </span>
          </div>
          <BaseButton
            v-if="batch.source === 'manual'"
            size="sm"
            variant="primary"
            :loading="exporting"
            :disabled="batch.exportable_count <= 0"
            @click="doExportRemaining"
          >
            <MsIcon name="download" size="xs" />
            {{ t('billing.admin.redemption.detail.exportRemaining', { count: batch.exportable_count }) }}
          </BaseButton>
        </div>

        <div v-if="batch.exports && batch.exports.length > 0" class="export-history">
          <div class="export-history__label">{{ t('billing.admin.redemption.detail.exportHistory') }}</div>
          <div class="export-history__list">
            <button
              v-for="exp in batch.exports"
              :key="exp.id"
              type="button"
              class="export-pill"
              @click="doDownloadExport(exp)"
            >
              <MsIcon name="download" size="xs" />
              <span>{{ t('billing.admin.redemption.detail.exportItem', { id: exp.id, count: exp.quantity, time: fmtDate(exp.created_at) }) }}</span>
            </button>
          </div>
        </div>
      </BaseCard>

      <SectionToolbar>
        <template #start>
          <FilterInput
            v-model="searchQuery"
            :placeholder="t('billing.admin.redemption.detail.searchCodePlaceholder')"
            class="tb-search"
          />
          <span class="toolbar-status tb-status">
            {{ t('billing.admin.redemption.detail.totalCodes', { n: total }) }}
          </span>
        </template>
        <template #end>
          <BaseSelect
            v-model="statusFilter"
            :options="statusOptions"
            :prefix="t('billing.admin.redemption.detail.statusFilterLabel') + ': '"
            size="sm"
            fit
          />
        </template>
      </SectionToolbar>

      <DataTable
        :items="items"
        :page="page"
        :total-pages="totalPages"
        :per-page="limit"
        :loading="loading"
        empty-icon="redeem"
        :empty-text="t('billing.admin.redemption.detail.emptyCodes')"
        row-key="id"
        @update:page="page = $event"
        @update:per-page="limit = $event; offset = 0"
      >
        <template #header>
          <th class="col-code">{{ t('billing.admin.redemption.detail.codeCol.code') }}</th>
          <th class="col-status">{{ t('billing.admin.redemption.detail.codeCol.status') }}</th>
          <th class="col-ext">{{ t('billing.admin.redemption.detail.codeCol.externalOrder') }}</th>
          <th class="col-redeemed">{{ t('billing.admin.redemption.detail.codeCol.redeemedInfo') }}</th>
          <th class="col-expires">{{ t('billing.admin.redemption.detail.codeCol.expiresAt') }}</th>
          <th class="col-actions">{{ t('billing.admin.redemption.detail.codeCol.actions') }}</th>
        </template>
        <template #row="{ item: c }">
          <td class="col-code">
            <div class="code-cell">
              <code>{{ c.code }}</code>
              <BaseButton size="sm" variant="ghost" square :title="t('billing.pay.copy')" @click="copyCode(c.code)">
                <MsIcon name="content_copy" size="xs" />
              </BaseButton>
            </div>
          </td>
          <td class="col-status">
            <Badge :color="statusColor(c.status)">{{ statusLabel(c.status) }}</Badge>
          </td>
          <td class="col-ext mono">{{ c.external_order_id || '—' }}</td>
          <td class="col-redeemed">
            <template v-if="c.redeemed_by">
              <div>{{ c.redeemed_by_username || `#${c.redeemed_by}` }}</div>
              <div class="name-sub mono">{{ c.order_no || '' }} {{ c.target_server_name ? `· ${c.target_server_name}` : '' }}</div>
            </template>
            <span v-else class="text-muted">—</span>
          </td>
          <td class="col-expires">
            {{ c.expires_at ? fmtDate(c.expires_at) : t('billing.admin.redemption.neverExpire') }}
          </td>
          <td class="col-actions">
            <BaseButton
              size="sm"
              variant="danger"
              :disabled="c.status !== 'unused'"
              @click="doVoidCode(c)"
            >
              <MsIcon name="block" size="xs" /> {{ t('billing.admin.redemption.detail.voidCode') }}
            </BaseButton>
          </td>
        </template>
        <template #card="{ item: c }">
          <CardTap @tap="openMobile(c)">
            <div class="card-row--main">
              <span class="card-name"><code>{{ c.code }}</code></span>
              <Badge :color="statusColor(c.status)" size="sm">{{ statusLabel(c.status) }}</Badge>
            </div>
            <div class="card-detail">
              <CardKV :label="t('billing.admin.redemption.detail.codeCol.externalOrder')">
                <span class="mono">{{ c.external_order_id || '—' }}</span>
              </CardKV>
              <CardKV :label="t('billing.admin.redemption.detail.codeCol.redeemedInfo')">
                {{ c.redeemed_by_username || (c.redeemed_by ? `#${c.redeemed_by}` : '—') }}
              </CardKV>
            </div>
          </CardTap>
        </template>
      </DataTable>
    </div>

    <ActionSheet v-model="mobileOpen" :title="mobileTarget?.code">
      <template v-if="mobileTarget">
        <button @click="mobileOpen = false; copyCode(mobileTarget!.code)">
          <MsIcon name="content_copy" size="sm" /> {{ t('billing.pay.copy') }}
        </button>
        <button
          class="action-sheet--danger"
          :disabled="mobileTarget.status !== 'unused'"
          @click="mobileOpen = false; doVoidCode(mobileTarget!)"
        >
          <MsIcon name="block" size="sm" /> {{ t('billing.admin.redemption.detail.voidCode') }}
        </button>
      </template>
    </ActionSheet>
  </BaseModal>
</template>

<style scoped>
.batch-detail { display: flex; flex-direction: column; gap: var(--sp-3); }
.export-card { margin-bottom: var(--sp-1); }
.export-bar { display: flex; align-items: center; justify-content: space-between; gap: var(--sp-3); flex-wrap: wrap; }
.export-meta { display: flex; align-items: center; gap: var(--sp-2); flex-wrap: wrap; font-size: var(--text-sm); color: var(--t2); }
.meta-chip { color: var(--t1); font-weight: 500; }
.meta-sep { color: var(--t3); }
.export-history { margin-top: var(--sp-3); padding-top: var(--sp-2); border-top: 1px solid var(--bd); }
.export-history__label { font-size: var(--text-xs); color: var(--t3); margin-bottom: var(--sp-2); }
.export-history__list { display: flex; flex-wrap: wrap; gap: var(--sp-2); }
.export-pill {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 4px 10px; border: 1px solid var(--bd); border-radius: var(--r-sm);
  background: var(--bg2); color: var(--t2); font: inherit; font-size: var(--text-xs); cursor: pointer;
}
.export-pill:hover { border-color: var(--ac); color: var(--ac); }

:deep(.col-code)     { width: 28%; }
:deep(.col-status)   { width: 10%; white-space: nowrap; }
:deep(.col-ext)      { width: 16%; font-size: var(--text-xs); color: var(--t2); }
:deep(.col-redeemed) { width: 20%; }
:deep(.col-expires)  { width: 14%; color: var(--t2); font-size: var(--text-sm); }
:deep(.col-actions)  { width: 12%; }

.code-cell { display: inline-flex; align-items: center; gap: var(--sp-1); }
.mono { font-family: var(--font-mono); }
.text-muted { color: var(--t3); }
code {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  background: var(--bg-in);
  padding: 2px 6px;
  border-radius: var(--r-xs);
  color: var(--t1);
}
.name-sub { color: var(--t3); font-size: var(--text-xs); margin-top: 2px; }
.card-name { font-weight: 600; font-size: .9rem; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
