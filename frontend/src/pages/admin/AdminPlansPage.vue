<script setup lang="ts">
/**
 * AdminPlansPage — `/admin/billing/plans`
 *
 * When ``standalone`` (default) renders its own PageHeader + .page-body.
 * Set ``standalone=false`` when embedding as a tab inside AdminBillingPage.
 *
 * Mirrors the visual conventions of ServersPage / UsersPage:
 *   - Plain PageHeader (icon + title only)
 *   - `.page-body` flex-column container
 *   - SectionToolbar:
 *       #start = FilterInput + total-count
 *       #end   = "新建套餐" + status BaseSelect (with prefix)
 *   - DataTable with percentage-based column widths
 *   - Row actions are individual BaseButtons (no SplitButton)
 *   - StatusDot rendered BEFORE the status label
 */
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useConfirm } from '@/composables/useConfirm'
import { useToast } from '@/composables/useToast'
import PageHeader from '@/components/layout/PageHeader.vue'
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
import MobileFilterSheet from '@/components/ui/MobileFilterSheet.vue'
import PlanEditorModal, { type AdminPlan, type EditorMode } from '@/components/billing/PlanEditorModal.vue'

defineOptions({ name: 'AdminPlansPage' })

const props = withDefaults(defineProps<{ standalone?: boolean }>(), { standalone: true })

const { t } = useI18n({ useScope: 'global' })
const { get, raw } = useApiFetch()
const { confirm } = useConfirm()
const { toast } = useToast()

interface NodeRef { id: number; name: string }
interface NestRef { id: number; name: string }
interface EggRef  { id: number; name: string; nest_id: number }

const plans = ref<AdminPlan[]>([])
const nodes = ref<Map<number, NodeRef>>(new Map())
const nests = ref<Map<number, NestRef>>(new Map())
const eggs  = ref<Map<number, EggRef>>(new Map())

const tableLoading = ref(true)

const searchTerm = ref('')
const statusFilter = ref<'all' | 'active' | 'inactive'>('all')

const statusOptions = computed(() => [
  { value: 'all',      label: t('billing.admin.plans.filterAll') },
  { value: 'active',   label: t('billing.admin.plans.filterActive') },
  { value: 'inactive', label: t('billing.admin.plans.filterInactive') },
])

// ── Mobile filter sheet ──
const mobileFilterOpen = ref(false)
const filterGroups = computed(() => [
  {
    key: 'status',
    label: t('billing.admin.plans.statusFilterLabel'),
    modelValue: statusFilter.value,
    options: statusOptions.value,
  },
])
function onMobileFilter(groupKey: string, value: string | number | boolean) {
  if (groupKey === 'status') {
    statusFilter.value = String(value) as 'all' | 'active' | 'inactive'
    page.value = 1
  }
}

const editorOpen = ref(false)
const editorMode = ref<EditorMode>('create')
const editorPlan = ref<AdminPlan | null>(null)

const page = ref(1)
const perPage = ref(20)

const mobileActionPlan = ref<AdminPlan | null>(null)
const mobileActionOpen = ref(false)

const filteredPlans = computed(() => {
  const q = searchTerm.value.trim().toLowerCase()
  return plans.value.filter((p) => {
    if (statusFilter.value === 'active' && !p.is_active) return false
    if (statusFilter.value === 'inactive' && p.is_active) return false
    if (q) {
      const haystack = [p.code, p.display_name, p.category_label ?? ''].join(' ').toLowerCase()
      if (!haystack.includes(q)) return false
    }
    return true
  })
})

const totalPages = computed(() => Math.max(1, Math.ceil(filteredPlans.value.length / perPage.value)))
const paginated = computed(() => {
  const start = (page.value - 1) * perPage.value
  return filteredPlans.value.slice(start, start + perPage.value)
})

function fenToYuan(fen: number): string { return (fen / 100).toFixed(2) }
function nodeName(id: number): string { return nodes.value.get(id)?.name ?? `#${id}` }
function eggName(id: number): string { return eggs.value.get(id)?.name ?? `#${id}` }

async function loadPlans() {
  const data = await get<AdminPlan[]>('/api/admin/billing/plans?include_inactive=true', { silent: true })
  if (data !== null) plans.value = data
}

async function loadNodes() {
  const data = await get<{ nodes: NodeRef[] }>('/api/admin/resources/nodes', { silent: true })
  if (data?.nodes) nodes.value = new Map(data.nodes.map((n) => [n.id, n]))
}

async function loadNestsAndEggs() {
  const data = await get<{ nests: NestRef[] }>('/api/admin/resources/nests', { silent: true })
  if (!data?.nests) return
  nests.value = new Map(data.nests.map((n) => [n.id, n]))
  const eggLists = await Promise.all(
    data.nests.map((n) =>
      get<{ eggs: EggRef[] }>(`/api/admin/resources/nests/${n.id}/eggs`, { silent: true }).then((r) =>
        (r?.eggs ?? []).map((e) => ({ ...e, nest_id: n.id })),
      ),
    ),
  )
  eggs.value = new Map(eggLists.flat().map((e) => [e.id, e]))
}

async function loadAll() {
  tableLoading.value = true
  await Promise.all([loadPlans(), loadNodes(), loadNestsAndEggs()])
  tableLoading.value = false
}

onMounted(loadAll)

function openCreate() {
  editorMode.value = 'create'
  editorPlan.value = null
  editorOpen.value = true
}
function openEdit(plan: AdminPlan) {
  editorMode.value = 'edit'
  editorPlan.value = plan
  editorOpen.value = true
}
function openDuplicate(plan: AdminPlan) {
  editorMode.value = 'duplicate'
  editorPlan.value = plan
  editorOpen.value = true
}

function onSaved(saved: AdminPlan) {
  const idx = plans.value.findIndex((p) => p.id === saved.id)
  if (idx >= 0) plans.value.splice(idx, 1, saved)
  else plans.value.push(saved)
  plans.value.sort((a, b) => (a.display_order - b.display_order) || (a.id - b.id))
}

async function toggleActive(plan: AdminPlan) {
  const payload = buildPutPayload(plan, { is_active: !plan.is_active })
  const res = await raw(`/api/admin/billing/plans/${plan.id}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
    headers: { 'Content-Type': 'application/json' },
    silent: true,
  })
  if (res && res.ok) {
    const updated = await res.json() as AdminPlan
    onSaved(updated)
    toast(plan.is_active
      ? t('billing.admin.plans.deactivateSuccess')
      : t('billing.admin.plans.activateSuccess'), 'success')
  } else if (res) {
    let msg = `HTTP ${res.status}`
    try { const body = await res.json(); msg = body.detail || body.message || msg } catch { /* ignore */ }
    toast(msg, 'error')
  }
}

async function doDelete(plan: AdminPlan) {
  const ok = await confirm({
    title: t('billing.admin.plans.delete'),
    message: t('billing.admin.plans.deleteConfirm', { code: plan.code }),
    variant: 'danger',
    confirmText: t('billing.admin.plans.delete'),
  })
  if (!ok) return

  const res = await raw(`/api/admin/billing/plans/${plan.id}`, { method: 'DELETE', silent: true })
  if (res && res.ok) {
    plans.value = plans.value.filter((p) => p.id !== plan.id)
    toast(t('billing.admin.plans.deleteSuccess'), 'success')
  } else if (res?.status === 409) {
    toast(t('billing.admin.plans.deleteFailedReferenced'), 'error')
  } else if (res) {
    let msg = `HTTP ${res.status}`
    try { const body = await res.json(); msg = body.detail || body.message || msg } catch { /* ignore */ }
    toast(msg, 'error')
  }
}

function buildPutPayload(plan: AdminPlan, overrides: Partial<AdminPlan> = {}): Record<string, unknown> {
  const merged = { ...plan, ...overrides }
  return {
    code: merged.code,
    display_name: merged.display_name,
    price_fen: merged.price_fen,
    days: merged.days,
    currency_code: merged.currency_code,
    period_options: merged.period_options,
    node_id: merged.node_id,
    egg_id: merged.egg_id,
    nest_id: merged.nest_id,
    cpu: merged.cpu,
    memory_mb: merged.memory_mb,
    disk_mb: merged.disk_mb,
    swap_mb: merged.swap_mb,
    io: merged.io,
    database_limit: merged.database_limit,
    backup_limit: merged.backup_limit,
    allocation_limit: merged.allocation_limit,
    oom_disabled: merged.oom_disabled,
    docker_image: merged.docker_image,
    startup_command: merged.startup_command,
    env_defaults: merged.env_defaults,
    is_active: merged.is_active,
    display_order: merged.display_order,
    description_md: merged.description_md,
    category_label: merged.category_label,
  }
}

function openMobileAction(plan: AdminPlan) {
  mobileActionPlan.value = plan
  mobileActionOpen.value = true
}
</script>

<template>
  <PageHeader v-if="props.standalone" icon="local_offer" :title="t('billing.admin.plans.pageTitle')" />

  <div :class="props.standalone ? 'page-body' : ''">
    <SectionToolbar>
      <template #start>
        <div class="tb-search-row">
          <FilterInput
            v-model="searchTerm"
            :placeholder="t('billing.admin.plans.searchPlaceholder')"
            class="tb-search"
            @update:modelValue="page = 1"
          />
          <button
            class="tb-filter-btn"
            :title="t('common.filterSort.title')"
            @click="mobileFilterOpen = true"
          >
            <MsIcon name="tune" size="sm" />
          </button>
        </div>
        <span class="toolbar-status tb-status">
          {{ t('billing.admin.plans.totalCount', { n: filteredPlans.length }) }}
        </span>
      </template>
      <template #end>
        <div class="tb-select-group tb-desktop-only">
          <BaseSelect
            v-model="statusFilter"
            :options="statusOptions"
            :prefix="t('billing.admin.plans.statusFilterLabel') + ': '"
            size="sm"
            fit
            @update:modelValue="page = 1"
          />
        </div>
        <div class="tb-btn-group">
          <BaseButton size="sm" variant="primary" @click="openCreate">
            <MsIcon name="add" size="xs" /> {{ t('billing.admin.plans.create') }}
          </BaseButton>
        </div>
      </template>
    </SectionToolbar>

    <MobileFilterSheet
      v-model:open="mobileFilterOpen"
      :sort-columns="[]"
      :sort-by="''"
      :sort-order="'asc'"
      :filters="filterGroups"
      @update:filter="onMobileFilter"
    />

    <DataTable
      :items="paginated"
      :page="page"
      :total-pages="totalPages"
      :per-page="perPage"
      :loading="tableLoading"
      :per-page-label="t('billing.admin.plans.perPageLabel')"
      empty-icon="local_offer"
      :empty-text="searchTerm
        ? t('billing.admin.plans.emptySearch', { q: searchTerm })
        : t('billing.admin.plans.empty')"
      row-key="id"
      @update:page="page = $event"
      @update:per-page="perPage = $event; page = 1"
    >
      <template #header>
        <th class="col-id">#</th>
        <th class="col-status">{{ t('billing.admin.plans.col.status') }}</th>
        <th class="col-code">{{ t('billing.admin.plans.col.code') }}</th>
        <th class="col-name">{{ t('billing.admin.plans.col.name') }}</th>
        <th class="col-price">{{ t('billing.admin.plans.col.price') }}</th>
        <th class="col-node">{{ t('billing.admin.plans.col.node') }}</th>
        <th class="col-egg">{{ t('billing.admin.plans.col.egg') }}</th>
        <th class="col-actions">{{ t('billing.admin.plans.col.actions') }}</th>
      </template>
      <template #row="{ item: p }">
        <td class="col-id">{{ p.id }}</td>
        <td class="col-status">
          <Badge :color="p.is_active ? 'var(--green)' : 'var(--red)'">
            {{ p.is_active ? t('billing.admin.plans.statusActive') : t('billing.admin.plans.statusInactive') }}
          </Badge>
        </td>
        <td class="col-code"><code>{{ p.code }}</code></td>
        <td class="col-name">
          <div class="name-main">{{ p.display_name }}</div>
          <div v-if="p.category_label" class="name-sub">{{ p.category_label }}</div>
        </td>
        <td class="col-price mono">¥{{ fenToYuan(p.price_fen) }} / {{ p.days }}{{ t('billing.admin.plans.dayUnit') }}</td>
        <td class="col-node"><Badge color="var(--blue)">{{ nodeName(p.node_id) }}</Badge></td>
        <td class="col-egg"><Badge color="var(--ac)">{{ eggName(p.egg_id) }}</Badge></td>
        <td class="col-actions">
          <div class="action-group">
            <BaseButton size="sm" @click="openEdit(p)">
              <MsIcon name="edit" size="xs" /> {{ t('billing.admin.plans.edit') }}
            </BaseButton>
            <BaseButton size="sm" @click="openDuplicate(p)">
              <MsIcon name="content_copy" size="xs" /> {{ t('billing.admin.plans.duplicate') }}
            </BaseButton>
            <BaseButton
              size="sm"
              :variant="p.is_active ? 'warning' : 'success'"
              @click="toggleActive(p)"
            >
              <MsIcon :name="p.is_active ? 'pause_circle' : 'play_circle'" size="xs" />
              {{ p.is_active ? t('billing.admin.plans.deactivate') : t('billing.admin.plans.activate') }}
            </BaseButton>
            <BaseButton size="sm" variant="danger" @click="doDelete(p)">
              <MsIcon name="delete" size="xs" /> {{ t('billing.admin.plans.delete') }}
            </BaseButton>
          </div>
        </td>
      </template>

      <template #card="{ item: p }">
        <CardTap @tap="openMobileAction(p)">
          <div class="card-row--main">
            <span class="card-name">{{ p.display_name }} <span class="card-id-inline">#{{ p.id }}</span></span>
            <Badge :color="p.is_active ? 'var(--green)' : 'var(--red)'" size="sm">
              {{ p.is_active ? t('billing.admin.plans.statusActive') : t('billing.admin.plans.statusInactive') }}
            </Badge>
          </div>
          <div class="card-detail">
            <CardKV :label="t('billing.admin.plans.col.code')"><code>{{ p.code }}</code></CardKV>
            <CardKV :label="t('billing.admin.plans.col.price')">
              <span class="mono">¥{{ fenToYuan(p.price_fen) }} / {{ p.days }}{{ t('billing.admin.plans.dayUnit') }}</span>
            </CardKV>
            <CardKV :label="t('billing.admin.plans.col.node')">{{ nodeName(p.node_id) }}</CardKV>
            <CardKV :label="t('billing.admin.plans.col.egg')">{{ eggName(p.egg_id) }}</CardKV>
          </div>
        </CardTap>
      </template>
    </DataTable>

    <ActionSheet v-model="mobileActionOpen" :title="mobileActionPlan?.display_name">
      <template v-if="mobileActionPlan" #info>
        <code>{{ mobileActionPlan.code }}</code>
        ·
        <span class="mono">¥{{ fenToYuan(mobileActionPlan.price_fen) }} / {{ mobileActionPlan.days }}{{ t('billing.admin.plans.dayUnit') }}</span>
      </template>
      <template v-if="mobileActionPlan">
        <button @click="mobileActionOpen = false; openEdit(mobileActionPlan!)">
          <MsIcon name="edit" size="sm" /> {{ t('billing.admin.plans.edit') }}
        </button>
        <button @click="mobileActionOpen = false; openDuplicate(mobileActionPlan!)">
          <MsIcon name="content_copy" size="sm" /> {{ t('billing.admin.plans.duplicate') }}
        </button>
        <button @click="mobileActionOpen = false; toggleActive(mobileActionPlan!)">
          <MsIcon :name="mobileActionPlan.is_active ? 'pause_circle' : 'play_circle'" size="sm" />
          {{ mobileActionPlan.is_active ? t('billing.admin.plans.deactivate') : t('billing.admin.plans.activate') }}
        </button>
        <button class="action-sheet--danger" @click="mobileActionOpen = false; doDelete(mobileActionPlan!)">
          <MsIcon name="delete" size="sm" /> {{ t('billing.admin.plans.delete') }}
        </button>
      </template>
    </ActionSheet>

    <PlanEditorModal
      v-model="editorOpen"
      :mode="editorMode"
      :plan="editorPlan"
      :nodes-map="nodes"
      :nests-map="nests"
      :eggs-map="eggs"
      :all-plans="plans"
      @saved="onSaved"
    />
  </div>
</template>

<style scoped>
/* Column widths use percentages (total 100%). */
:deep(.col-id)      { width: 4%;  color: var(--t3); }
:deep(.col-code)    { width: 11%; }
:deep(.col-name)    { width: 20%; }
:deep(.col-status)  { width: 8%;  white-space: nowrap; }
:deep(.col-price)   { width: 13%; white-space: nowrap; }
:deep(.col-node)    { width: 9%; }
:deep(.col-egg)     { width: 9%; }
:deep(.col-actions) { width: 26%; }

.mono {
  font-family: var(--font-mono, 'IBM Plex Mono', monospace);
}

code {
  font-family: var(--font-mono, 'IBM Plex Mono', monospace);
  font-size: var(--text-xs);
  background: var(--bg-in);
  padding: 2px 6px;
  border-radius: var(--r-xs);
  color: var(--t1);
}

.name-main {
  color: var(--t1);
  font-weight: 500;
}

.name-sub {
  color: var(--t3);
  font-size: var(--text-xs);
  margin-top: 2px;
}

.action-group {
  display: flex;
  gap: var(--sp-2);
  align-items: center;
  flex-wrap: wrap;
}

.card-name {
  font-weight: 600;
  font-size: .92rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.card-id-inline {
  font-size: .78rem;
  font-weight: 400;
  color: var(--t3);
  margin-left: var(--sp-1);
}

@media (max-width: 768px) {
  .toolbar-half {
    flex: 1;
    min-width: 0;
  }
}
</style>
