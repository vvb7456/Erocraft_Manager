<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { apiErrorMessage } from '@/composables/apiClient'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'
import {
  createNest,
  deleteEgg,
  deleteNest,
  exportEggDownload,
  listEggs,
  listNests,
  updateNest,
  type EggDetailOut,
  type EggSummaryOut,
  type NestOut,
} from '@/api/adminNestsEggs'
import PageHeader from '@/components/layout/PageHeader.vue'
import PageHeaderActions from '@/components/layout/PageHeaderActions.vue'
import TabSwitcher from '@/components/ui/TabSwitcher.vue'
import SectionToolbar from '@/components/ui/SectionToolbar.vue'
import FilterInput from '@/components/ui/FilterInput.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import DataTable from '@/components/ui/DataTable.vue'
import SortTh from '@/components/ui/SortTh.vue'
import { useTableSort } from '@/composables/useTableSort'
import { useClientPagination } from '@/composables/useTablePagination'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseModal from '@/components/ui/BaseModal.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import BaseTextarea from '@/components/form/BaseTextarea.vue'
import FormField from '@/components/form/FormField.vue'
import CardTap from '@/components/ui/CardTap.vue'
import CardKV from '@/components/ui/CardKV.vue'
import ActionSheet from '@/components/ui/ActionSheet.vue'
import MobileFilterSheet from '@/components/ui/MobileFilterSheet.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import EggCreateModal from '@/components/nests/EggCreateModal.vue'

defineOptions({ name: 'NestsPage' })

const { t } = useI18n({ useScope: 'global' })
const route = useRoute()
const router = useRouter()
const { toast } = useToast()
const { confirm } = useConfirm()

// ── Top-level tabs (?tab=eggs|nests) ──
type TabKey = 'eggs' | 'nests'
const VALID_TABS: TabKey[] = ['eggs', 'nests']

function pickInitialTab(): TabKey {
  const q = route.query.tab
  const raw = Array.isArray(q) ? q[0] : q
  if (raw && (VALID_TABS as string[]).includes(raw)) return raw as TabKey
  return 'eggs'
}

const activeTab = computed<TabKey>({
  get: pickInitialTab,
  set: (tab) => {
    void router.push({
      query: {
        ...route.query,
        tab,
        ...(tab === 'nests' ? { nest: undefined } : {}),
      },
    })
  },
})

const tabs = computed(() => [
  { key: 'eggs', icon: 'extension', label: t('nests.tabs.eggs') },
  { key: 'nests', icon: 'folder', label: t('nests.tabs.nests') },
])

// ── Data state ──
const nests = ref<NestOut[]>([])
const eggs = ref<EggSummaryOut[]>([])
const loadingNests = ref(true)
const loadingEggs = ref(true)

async function loadNests() {
  loadingNests.value = true
  try {
    const res = await listNests()
    nests.value = res.nests
  } catch (err) {
    toast(apiErrorMessage(err), 'error')
  } finally {
    loadingNests.value = false
  }
}

async function loadEggs() {
  loadingEggs.value = true
  try {
    const res = await listEggs()
    eggs.value = res.eggs
  } catch (err) {
    toast(apiErrorMessage(err), 'error')
  } finally {
    loadingEggs.value = false
  }
}

async function loadAll() {
  await Promise.all([loadNests(), loadEggs()])
}

onMounted(loadAll)

// ── Eggs Tab state ──
const eggSearch = ref('')
const nestFilter = ref<string>('all')
const mobileFilterOpen = ref(false)
const {
  sortBy: eggSortBy,
  sortOrder: eggSortOrder,
  toggleSort: toggleEggSort,
  sortItems: sortEggItems,
} = useTableSort({
  descColumns: ['variables_count', 'servers_count', 'plans_count'],
})
const eggSortColumns = computed(() => [
  { key: 'name', label: t('nests.egg.columns.name') },
  { key: 'nest_name', label: t('nests.eggs.filterNest') },
  { key: 'variables_count', label: t('nests.egg.columns.variables') },
  { key: 'servers_count', label: t('nests.egg.columns.servers') },
  { key: 'plans_count', label: t('nests.egg.columns.plans') },
])

function syncNestFilterFromRoute() {
  const q = route.query.nest
  const raw = Array.isArray(q) ? q[0] : q
  if (raw && /^\d+$/.test(raw)) {
    nestFilter.value = raw
  } else {
    nestFilter.value = 'all'
  }
}

watch(() => route.query.nest, syncNestFilterFromRoute, { immediate: true })

function setNestFilter(val: string | number | boolean) {
  const next = String(val)
  nestFilter.value = next
  void router.replace({
    query: {
      ...route.query,
      tab: 'eggs',
      nest: next === 'all' ? undefined : next,
    },
  })
}

const nestFilterOptions = computed(() => [
  { value: 'all', label: t('nests.eggs.allNests') },
  ...nests.value.map(n => ({ value: String(n.id), label: n.name })),
])

const eggFilterGroups = computed(() => [
  {
    key: 'nest',
    label: t('nests.eggs.filterNest'),
    modelValue: nestFilter.value,
    options: nestFilterOptions.value,
  },
])

function onMobileFilter(groupKey: string, value: string | number | boolean) {
  if (groupKey === 'nest') setNestFilter(value)
}

const filteredEggs = computed(() => {
  const q = eggSearch.value.trim().toLowerCase()
  const targetNestId = nestFilter.value === 'all' ? null : Number(nestFilter.value)
  return eggs.value.filter(e => {
    if (targetNestId != null && e.nest_id !== targetNestId) return false
    if (q) {
      const images = Object.values(e.docker_images || {}).join(' ')
      const hay = `${e.name} ${e.nest_name} ${e.description ?? ''} ${images}`.toLowerCase()
      if (!hay.includes(q)) return false
    }
    return true
  })
})

const sortedEggs = computed(() =>
  sortEggItems(filteredEggs.value, {
    name: (e) => e.name,
    nest_name: (e) => e.nest_name,
    variables_count: (e) => e.variables_count,
    servers_count: (e) => e.servers_count,
    plans_count: (e) => e.plans_count,
  }, {
    tieBreaker: (a, b) => a.id - b.id,
  }),
)

const {
  page: eggPage,
  perPage: eggPerPage,
  totalPages: eggTotalPages,
  paginated: paginatedEggs,
  setPerPage: setEggPerPage,
} = useClientPagination(sortedEggs, {
  resetDeps: [eggSearch, nestFilter, eggSortBy, eggSortOrder],
})

function primaryImage(e: EggSummaryOut): { first: string; extra: number } {
  const vals = Object.values(e.docker_images || {})
  return { first: vals[0] || '', extra: Math.max(0, vals.length - 1) }
}

const defaultCreateNestId = computed(() =>
  nestFilter.value !== 'all' ? Number(nestFilter.value) : (nests.value[0]?.id ?? null),
)

// ── Egg actions ──
const eggCreateOpen = ref(false)
const mobileActionEgg = ref<EggSummaryOut | null>(null)
const mobileEggSheetOpen = ref(false)

function openEggDetail(e: EggSummaryOut) {
  void router.push({ name: 'egg-detail', params: { eggId: e.id } })
}

async function handleExportEgg(e: EggSummaryOut) {
  try {
    await exportEggDownload(e.id, `egg-${e.id}`)
    toast(t('nests.egg.exported'), 'success')
  } catch (err) {
    toast(apiErrorMessage(err), 'error')
  }
}

async function removeEgg(e: EggSummaryOut) {
  const ok = await confirm({
    title: t('nests.egg.deleteTitle'),
    message: t('nests.egg.deleteMsg', { name: e.name }),
    variant: 'danger',
    confirmText: t('common.btn.delete'),
  })
  if (!ok) return
  try {
    await deleteEgg(e.id)
    toast(t('nests.egg.deleted', { name: e.name }), 'success')
    await loadAll()
  } catch (err) {
    toast(apiErrorMessage(err), 'error')
  }
}

function onEggCreatedOrImported(egg: EggDetailOut) {
  void router.push({ name: 'egg-detail', params: { eggId: egg.id } })
}

function openMobileEggAction(e: EggSummaryOut) {
  mobileActionEgg.value = e
  mobileEggSheetOpen.value = true
}

// ── Nests Tab state ──
const nestSearch = ref('')
const mobileNestFilterOpen = ref(false)
const {
  sortBy: nestSortBy,
  sortOrder: nestSortOrder,
  toggleSort: toggleNestSort,
  sortItems: sortNestItems,
} = useTableSort({
  descColumns: ['eggs_count', 'servers_count'],
})
const nestSortColumns = computed(() => [
  { key: 'name', label: t('nests.columns.name') },
  { key: 'eggs_count', label: t('nests.columns.eggs') },
  { key: 'servers_count', label: t('nests.columns.servers') },
])

const nestModalOpen = ref(false)
const editingNest = ref<NestOut | null>(null)
const formName = ref('')
const formDesc = ref('')
const savingNest = ref(false)

const mobileActionNest = ref<NestOut | null>(null)
const mobileNestSheetOpen = ref(false)

const filteredNests = computed(() => {
  const q = nestSearch.value.trim().toLowerCase()
  if (!q) return nests.value
  return nests.value.filter(n =>
    n.name.toLowerCase().includes(q) ||
    (n.description || '').toLowerCase().includes(q) ||
    n.author.toLowerCase().includes(q),
  )
})

const sortedNests = computed(() =>
  sortNestItems(filteredNests.value, {
    name: (n) => n.name,
    eggs_count: (n) => n.eggs_count,
    servers_count: (n) => n.servers_count,
  }, {
    tieBreaker: (a, b) => a.id - b.id,
  }),
)

const {
  page: nestPage,
  perPage: nestPerPage,
  totalPages: nestTotalPages,
  paginated: paginatedNests,
  setPerPage: setNestPerPage,
} = useClientPagination(sortedNests, {
  resetDeps: [nestSearch, nestSortBy, nestSortOrder],
})

function filterEggsByNest(n: NestOut) {
  void router.push({ query: { tab: 'eggs', nest: String(n.id) } })
}

function openCreateNest() {
  editingNest.value = null
  formName.value = ''
  formDesc.value = ''
  nestModalOpen.value = true
}

function openEditNest(n: NestOut) {
  editingNest.value = n
  formName.value = n.name
  formDesc.value = n.description || ''
  nestModalOpen.value = true
}

async function saveNest() {
  const name = formName.value.trim()
  if (!name) {
    toast(t('nests.validation.nameRequired'), 'error')
    return
  }
  savingNest.value = true
  try {
    if (editingNest.value) {
      await updateNest(editingNest.value.id, {
        name,
        description: formDesc.value.trim() || null,
      })
      toast(t('nests.nest.updated'), 'success')
    } else {
      await createNest({
        name,
        description: formDesc.value.trim() || null,
      })
      toast(t('nests.nest.created'), 'success')
    }
    nestModalOpen.value = false
    await loadAll()
  } catch (err) {
    toast(apiErrorMessage(err), 'error')
  } finally {
    savingNest.value = false
  }
}

async function removeNest(n: NestOut) {
  const ok = await confirm({
    title: t('nests.nest.deleteTitle'),
    message: t('nests.nest.deleteMsg', { name: n.name }),
    variant: 'danger',
    confirmText: t('common.btn.delete'),
  })
  if (!ok) return
  try {
    await deleteNest(n.id)
    toast(t('nests.nest.deleted', { name: n.name }), 'success')
    await loadAll()
  } catch (err) {
    toast(apiErrorMessage(err), 'error')
  }
}

function openMobileNestAction(n: NestOut) {
  mobileActionNest.value = n
  mobileNestSheetOpen.value = true
}
</script>

<template>
  <PageHeader icon="deployed_code" :title="t('nests.title')">
    <TabSwitcher v-model="activeTab" :tabs="tabs" />
  </PageHeader>

  <div class="page-body">
    <!-- ═══ Tab 1: Eggs (default) ═══ -->
    <div v-if="activeTab === 'eggs'" class="tab-content">
      <PageHeaderActions>
        <BaseButton
          size="sm"
          variant="primary"
          :disabled="nests.length === 0"
          @click="eggCreateOpen = true"
        >
          <MsIcon name="add" size="xs" />{{ t('nests.actions.createEgg') }}
        </BaseButton>
      </PageHeaderActions>

      <SectionToolbar>
        <template #start>
          <div class="tb-search-row">
            <FilterInput
              v-model="eggSearch"
              :placeholder="t('nests.eggs.searchPlaceholder')"
              class="tb-search"
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
            {{ t('nests.eggs.totalCount', { n: filteredEggs.length }) }}
          </span>
        </template>
        <template #end>
          <div class="tb-select-group tb-desktop-only">
            <BaseSelect
              :model-value="nestFilter"
              :options="nestFilterOptions"
              :prefix="t('nests.eggs.filterNest') + ': '"
              size="sm"
              fit
              @update:model-value="setNestFilter($event as string)"
            />
          </div>
        </template>
      </SectionToolbar>

      <MobileFilterSheet
        v-model:open="mobileFilterOpen"
        :sort-columns="eggSortColumns"
        :sort-by="eggSortBy"
        :sort-order="eggSortOrder"
        :filters="eggFilterGroups"
        @sort="toggleEggSort"
        @update:filter="onMobileFilter"
      />

      <DataTable
        :items="paginatedEggs"
        :page="eggPage"
        :total-pages="eggTotalPages"
        :per-page="eggPerPage"
        :per-page-label="t('nests.perPage')"
        :loading="loadingEggs"
        empty-icon="extension"
        :empty-text="t('nests.egg.empty')"
        row-key="id"
        @update:page="eggPage = $event"
        @update:per-page="setEggPerPage"
      >
        <template #header>
          <SortTh class="col-egg-name" col="name" :sort-by="eggSortBy" :sort-order="eggSortOrder" @sort="toggleEggSort">{{ t('nests.egg.columns.name') }}</SortTh>
          <SortTh class="col-egg-nest" col="nest_name" :sort-by="eggSortBy" :sort-order="eggSortOrder" @sort="toggleEggSort">{{ t('nests.eggs.filterNest') }}</SortTh>
          <th class="col-egg-image">{{ t('nests.egg.columns.dockerImage') }}</th>
          <SortTh class="col-egg-num" col="variables_count" :sort-by="eggSortBy" :sort-order="eggSortOrder" @sort="toggleEggSort">{{ t('nests.egg.columns.variables') }}</SortTh>
          <SortTh class="col-egg-num" col="servers_count" :sort-by="eggSortBy" :sort-order="eggSortOrder" @sort="toggleEggSort">{{ t('nests.egg.columns.servers') }}</SortTh>
          <SortTh class="col-egg-num" col="plans_count" :sort-by="eggSortBy" :sort-order="eggSortOrder" @sort="toggleEggSort">{{ t('nests.egg.columns.plans') }}</SortTh>
          <th class="col-egg-actions">{{ t('nests.columns.actions') }}</th>
        </template>

        <template #row="{ item: e }">
          <td class="col-egg-name clickable" @click="openEggDetail(e)">
            <div class="name-main name-link">{{ e.name }}</div>
            <div v-if="e.description" class="name-sub" :title="e.description">{{ e.description }}</div>
          </td>
          <td class="col-egg-nest clickable" @click="openEggDetail(e)">{{ e.nest_name || '—' }}</td>
          <td class="col-egg-image clickable" @click="openEggDetail(e)">
            <span v-if="primaryImage(e).first" class="image-cell">
              <code class="image-code" :title="primaryImage(e).first">{{ primaryImage(e).first }}</code>
              <span v-if="primaryImage(e).extra > 0" class="image-more">+{{ primaryImage(e).extra }}</span>
            </span>
            <span v-else class="muted-text">—</span>
          </td>
          <td class="col-egg-num tabular clickable" @click="openEggDetail(e)">{{ e.variables_count }}</td>
          <td class="col-egg-num tabular clickable" @click="openEggDetail(e)">{{ e.servers_count }}</td>
          <td class="col-egg-num tabular clickable" @click="openEggDetail(e)">{{ e.plans_count }}</td>
          <td class="col-egg-actions">
            <div class="action-group">
              <BaseButton size="sm" @click.stop="openEggDetail(e)">
                <MsIcon name="edit" size="xs" /> {{ t('common.btn.edit') }}
              </BaseButton>
              <BaseButton size="sm" @click.stop="handleExportEgg(e)">
                <MsIcon name="download" size="xs" /> {{ t('nests.actions.export') }}
              </BaseButton>
              <BaseButton size="sm" variant="danger" @click.stop="removeEgg(e)">
                <MsIcon name="delete" size="xs" /> {{ t('common.btn.delete') }}
              </BaseButton>
            </div>
          </td>
        </template>

        <template #card="{ item: e }">
          <CardTap @tap="openMobileEggAction(e)">
            <div class="card-row--main">
              <span class="card-name">{{ e.name }}</span>
              <span class="card-nest-label">{{ e.nest_name }}</span>
            </div>
            <div class="card-row--sub mono">{{ primaryImage(e).first || '—' }}</div>
            <div class="card-detail">
              <CardKV :label="t('nests.egg.columns.variables')">
                <span class="tabular">{{ e.variables_count }}</span>
              </CardKV>
              <CardKV :label="t('nests.egg.columns.servers')">
                <span class="tabular">{{ e.servers_count }}</span>
              </CardKV>
              <CardKV :label="t('nests.egg.columns.plans')">
                <span class="tabular">{{ e.plans_count }}</span>
              </CardKV>
            </div>
          </CardTap>
        </template>
      </DataTable>

      <ActionSheet v-model="mobileEggSheetOpen" :title="mobileActionEgg?.name">
        <template v-if="mobileActionEgg" #info>
          {{ mobileActionEgg.nest_name }}
        </template>
        <template v-if="mobileActionEgg">
          <button @click="mobileEggSheetOpen = false; openEggDetail(mobileActionEgg!)">
            <MsIcon name="edit" size="sm" /> {{ t('common.btn.edit') }}
          </button>
          <button @click="mobileEggSheetOpen = false; handleExportEgg(mobileActionEgg!)">
            <MsIcon name="download" size="sm" /> {{ t('nests.actions.exportJson') }}
          </button>
          <button
            class="action-sheet--danger"
            @click="mobileEggSheetOpen = false; removeEgg(mobileActionEgg!)"
          >
            <MsIcon name="delete" size="sm" /> {{ t('common.btn.delete') }}
          </button>
        </template>
      </ActionSheet>
    </div>

    <!-- ═══ Tab 2: Nests ═══ -->
    <div v-else-if="activeTab === 'nests'" class="tab-content">
      <PageHeaderActions>
        <BaseButton size="sm" variant="primary" @click="openCreateNest">
          <MsIcon name="add" size="xs" />{{ t('nests.actions.createNest') }}
        </BaseButton>
      </PageHeaderActions>

      <SectionToolbar>
        <template #start>
          <div class="tb-search-row">
            <FilterInput
              v-model="nestSearch"
              :placeholder="t('nests.searchPlaceholder')"
              class="tb-search"
            />
            <button
              class="tb-filter-btn"
              :title="t('common.filterSort.title')"
              @click="mobileNestFilterOpen = true"
            >
              <MsIcon name="tune" size="sm" />
            </button>
          </div>
          <span class="toolbar-status tb-status">{{ t('nests.totalNests', { n: filteredNests.length }) }}</span>
        </template>
      </SectionToolbar>

      <MobileFilterSheet
        v-model:open="mobileNestFilterOpen"
        :sort-columns="nestSortColumns"
        :sort-by="nestSortBy"
        :sort-order="nestSortOrder"
        :filters="[]"
        @sort="toggleNestSort"
      />

      <DataTable
        :items="paginatedNests"
        :page="nestPage"
        :total-pages="nestTotalPages"
        :per-page="nestPerPage"
        :per-page-label="t('nests.perPage')"
        :loading="loadingNests"
        empty-icon="folder"
        :empty-text="t('nests.empty')"
        row-key="id"
        @update:page="nestPage = $event"
        @update:per-page="setNestPerPage"
      >
        <template #header>
          <SortTh class="col-nest-name" col="name" :sort-by="nestSortBy" :sort-order="nestSortOrder" @sort="toggleNestSort">{{ t('nests.columns.name') }}</SortTh>
          <th class="col-nest-desc">{{ t('nests.columns.description') }}</th>
          <SortTh class="col-nest-num" col="eggs_count" :sort-by="nestSortBy" :sort-order="nestSortOrder" @sort="toggleNestSort">{{ t('nests.columns.eggs') }}</SortTh>
          <SortTh class="col-nest-num" col="servers_count" :sort-by="nestSortBy" :sort-order="nestSortOrder" @sort="toggleNestSort">{{ t('nests.columns.servers') }}</SortTh>
          <th class="col-nest-actions">{{ t('nests.columns.actions') }}</th>
        </template>

        <template #row="{ item: n }">
          <td class="col-nest-name clickable" @click="filterEggsByNest(n)">
            <div class="name-main name-link">{{ n.name }}</div>
            <div v-if="n.author" class="name-sub mono">{{ n.author }}</div>
          </td>
          <td class="col-nest-desc clickable" @click="filterEggsByNest(n)">
            <span class="desc-text" :title="n.description || undefined">{{ n.description || '—' }}</span>
          </td>
          <td class="col-nest-num tabular clickable" @click="filterEggsByNest(n)">{{ n.eggs_count }}</td>
          <td class="col-nest-num tabular clickable" @click="filterEggsByNest(n)">{{ n.servers_count }}</td>
          <td class="col-nest-actions">
            <div class="action-group">
              <BaseButton size="sm" @click.stop="openEditNest(n)">
                <MsIcon name="edit" size="xs" /> {{ t('common.btn.edit') }}
              </BaseButton>
              <BaseButton
                size="sm"
                variant="danger"
                @click.stop="removeNest(n)"
              >
                <MsIcon name="delete" size="xs" /> {{ t('common.btn.delete') }}
              </BaseButton>
            </div>
          </td>
        </template>

        <template #card="{ item: n }">
          <CardTap @tap="openMobileNestAction(n)">
            <div class="card-row--main">
              <span class="card-name">{{ n.name }}</span>
            </div>
            <div v-if="n.description" class="card-row--sub">{{ n.description }}</div>
            <div class="card-detail">
              <CardKV :label="t('nests.columns.eggs')">
                <span class="tabular">{{ n.eggs_count }}</span>
              </CardKV>
              <CardKV :label="t('nests.columns.servers')">
                <span class="tabular">{{ n.servers_count }}</span>
              </CardKV>
              <CardKV :label="t('nests.columns.author')">
                <span class="mono">{{ n.author || '—' }}</span>
              </CardKV>
            </div>
          </CardTap>
        </template>
      </DataTable>

      <ActionSheet v-model="mobileNestSheetOpen" :title="mobileActionNest?.name">
        <template v-if="mobileActionNest" #info>
          {{ mobileActionNest.author }}
        </template>
        <template v-if="mobileActionNest">
          <button @click="mobileNestSheetOpen = false; filterEggsByNest(mobileActionNest!)">
            <MsIcon name="extension" size="sm" /> {{ t('nests.actions.viewEggs') }}
          </button>
          <button @click="mobileNestSheetOpen = false; openEditNest(mobileActionNest!)">
            <MsIcon name="edit" size="sm" /> {{ t('common.btn.edit') }}
          </button>
          <button
            class="action-sheet--danger"
            @click="mobileNestSheetOpen = false; removeNest(mobileActionNest!)"
          >
            <MsIcon name="delete" size="sm" /> {{ t('common.btn.delete') }}
          </button>
        </template>
      </ActionSheet>
    </div>
  </div>

  <!-- Create / Edit Nest Modal -->
  <BaseModal
    v-model="nestModalOpen"
    :title="editingNest ? t('nests.nest.editTitle') : t('nests.nest.createTitle')"
    icon="folder"
    size="sm"
  >
    <div class="modal-form">
      <FormField :label="t('nests.nest.fields.name')" required density="compact">
        <BaseInput v-model="formName" :placeholder="t('nests.nest.fields.namePlaceholder')" maxlength="191" />
      </FormField>
      <FormField :label="t('nests.nest.fields.description')" density="compact">
        <BaseTextarea v-model="formDesc" :rows="3" :placeholder="t('nests.nest.fields.descPlaceholder')" />
      </FormField>
    </div>
    <template #footer>
      <BaseButton variant="default" :disabled="savingNest" @click="nestModalOpen = false">
        {{ t('common.btn.cancel') }}
      </BaseButton>
      <BaseButton variant="primary" :loading="savingNest" @click="saveNest">
        {{ editingNest ? t('common.btn.save') : t('common.btn.confirm') }}
      </BaseButton>
    </template>
  </BaseModal>

  <!-- Create / Import Egg Modal -->
  <EggCreateModal
    v-model="eggCreateOpen"
    :nests="nests"
    :default-nest-id="defaultCreateNestId"
    :all-eggs="eggs"
    @created="onEggCreatedOrImported"
  />
</template>

<style scoped>
.modal-form {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.clickable { cursor: pointer; }

/* Eggs table */
:deep(.col-egg-nest)    { color: var(--t2); white-space: nowrap; }
:deep(.col-egg-num)     { white-space: nowrap; }

/* Nests table */
:deep(.col-nest-desc)    { color: var(--t2); }
:deep(.col-nest-num)     { white-space: nowrap; }

code {
  font-family: var(--font-mono);
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
.name-link {
  transition: color .15s;
}
.clickable:hover .name-link {
  color: var(--ac);
}
.name-sub {
  color: var(--t3);
  font-size: var(--text-xs);
  margin-top: 2px;
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.desc-text {
  display: inline-block;
  max-width: 340px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
}
.image-cell {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-1);
  max-width: 280px;
}
.image-code {
  display: inline-block;
  min-width: 0;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
}
.image-more {
  color: var(--t3);
  font-size: var(--text-xs);
  flex-shrink: 0;
}
.mono {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--t3);
}
.tabular {
  font-variant-numeric: tabular-nums;
  color: var(--t2);
}
.muted-text {
  color: var(--t3);
}
.action-group {
  display: flex;
  gap: var(--sp-2);
  align-items: center;
  flex-wrap: wrap;
}

/* Mobile cards */
.card-row--main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-2);
}
.card-name {
  font-weight: 600;
  color: var(--t1);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.card-nest-label {
  font-size: var(--text-xs);
  color: var(--t3);
  flex-shrink: 0;
}
.card-row--sub {
  margin-top: 2px;
  font-size: var(--text-sm);
  color: var(--t3);
  word-break: break-all;
}
.card-detail {
  display: flex;
  gap: var(--sp-4);
  margin-top: var(--sp-2);
  flex-wrap: wrap;
}
</style>
