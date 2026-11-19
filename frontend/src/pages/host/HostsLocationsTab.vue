<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { apiErrorMessage } from '@/composables/apiClient'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'
import {
  deleteLocation,
  listLocations,
  type LocationOut,
} from '@/api/adminNodesLocations'
import PageHeaderActions from '@/components/layout/PageHeaderActions.vue'
import SectionToolbar from '@/components/ui/SectionToolbar.vue'
import FilterInput from '@/components/ui/FilterInput.vue'
import DataTable from '@/components/ui/DataTable.vue'
import SortTh from '@/components/ui/SortTh.vue'
import MobileFilterSheet from '@/components/ui/MobileFilterSheet.vue'
import { useTableSort } from '@/composables/useTableSort'
import { useClientPagination } from '@/composables/useTablePagination'
import BaseButton from '@/components/ui/BaseButton.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import CardTap from '@/components/ui/CardTap.vue'
import CardKV from '@/components/ui/CardKV.vue'
import ActionSheet from '@/components/ui/ActionSheet.vue'
import LocationEditorModal from '@/components/hosts/LocationEditorModal.vue'

defineOptions({ name: 'HostsLocationsTab' })

const { t } = useI18n({ useScope: 'global' })
const { toast } = useToast()
const { confirm } = useConfirm()

const locations = ref<LocationOut[]>([])
const loading = ref(true)
const searchTerm = ref('')
const mobileFilterOpen = ref(false)
const { sortBy, sortOrder, toggleSort, sortItems } = useTableSort({
  descColumns: ['nodes_count', 'servers_count'],
})
const sortColumns = computed(() => [
  { key: 'short', label: t('hosts.locations.columns.short') },
  { key: 'long', label: t('hosts.locations.columns.long') },
  { key: 'nodes_count', label: t('hosts.locations.columns.nodes') },
  { key: 'servers_count', label: t('hosts.locations.columns.servers') },
])

const editorOpen = ref(false)
const editingLocation = ref<LocationOut | null>(null)

const mobileActionLoc = ref<LocationOut | null>(null)
const mobileActionOpen = ref(false)

async function loadLocations() {
  loading.value = true
  try {
    const res = await listLocations()
    locations.value = res.locations
  } catch (err) {
    toast(apiErrorMessage(err), 'error')
  } finally {
    loading.value = false
  }
}

onMounted(loadLocations)

const filtered = computed(() => {
  const q = searchTerm.value.trim().toLowerCase()
  if (!q) return locations.value
  return locations.value.filter(loc =>
    `${loc.short} ${loc.long ?? ''}`.toLowerCase().includes(q),
  )
})

const sorted = computed(() =>
  sortItems(filtered.value, {
    short: (loc) => loc.short,
    long: (loc) => loc.long,
    nodes_count: (loc) => loc.nodes_count,
    servers_count: (loc) => loc.servers_count,
  }, {
    tieBreaker: (a, b) => a.id - b.id,
  }),
)

const { page, perPage, totalPages, paginated, setPerPage } = useClientPagination(sorted, {
  resetDeps: [searchTerm, sortBy, sortOrder],
})

function openCreate() {
  editingLocation.value = null
  editorOpen.value = true
}

function openEdit(loc: LocationOut) {
  editingLocation.value = loc
  editorOpen.value = true
}

function onSaved() {
  void loadLocations()
}

async function removeLocation(loc: LocationOut) {
  const ok = await confirm({
    title: t('hosts.locations.deleteTitle'),
    message: t('hosts.locations.deleteMsg', { short: loc.short }),
    variant: 'danger',
    confirmText: t('common.btn.delete'),
  })
  if (!ok) return
  try {
    await deleteLocation(loc.id)
    toast(t('hosts.locations.deleted', { short: loc.short }), 'success')
    await loadLocations()
  } catch (err) {
    toast(apiErrorMessage(err), 'error')
  }
}

function openMobileAction(loc: LocationOut) {
  mobileActionLoc.value = loc
  mobileActionOpen.value = true
}

defineExpose({ reload: loadLocations })
</script>

<template>
  <PageHeaderActions>
    <BaseButton size="sm" variant="primary" @click="openCreate">
      <MsIcon name="add" size="xs" />{{ t('hosts.locations.addBtn') }}
    </BaseButton>
  </PageHeaderActions>

  <SectionToolbar>
    <template #start>
      <div class="tb-search-row">
        <FilterInput
          v-model="searchTerm"
          :placeholder="t('hosts.locations.searchPlaceholder')"
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
        {{ t('hosts.locations.totalCount', { n: filtered.length }) }}
      </span>
    </template>
  </SectionToolbar>

  <MobileFilterSheet
    v-model:open="mobileFilterOpen"
    :sort-columns="sortColumns"
    :sort-by="sortBy"
    :sort-order="sortOrder"
    :filters="[]"
    @sort="toggleSort"
  />

  <div class="locations-table-wrap">
  <DataTable
    :items="paginated"
    :page="page"
    :total-pages="totalPages"
    :per-page="perPage"
    :per-page-label="t('hosts.list.perPage')"
    :loading="loading"
    empty-icon="public"
    :empty-text="t('hosts.locations.empty')"
    row-key="id"
    @update:page="page = $event"
    @update:per-page="setPerPage"
  >
    <template #header>
      <SortTh class="col-short" col="short" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('hosts.locations.columns.short') }}</SortTh>
      <SortTh class="col-long" col="long" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('hosts.locations.columns.long') }}</SortTh>
      <SortTh class="col-num" col="nodes_count" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('hosts.locations.columns.nodes') }}</SortTh>
      <SortTh class="col-num" col="servers_count" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('hosts.locations.columns.servers') }}</SortTh>
      <th class="col-actions">{{ t('hosts.locations.columns.actions') }}</th>
    </template>

    <template #row="{ item: loc }">
      <td class="col-short"><code>{{ loc.short }}</code></td>
      <td class="col-long">
        <span class="long-text">{{ loc.long || '—' }}</span>
      </td>
      <td class="col-num tabular">{{ loc.nodes_count }}</td>
      <td class="col-num tabular">{{ loc.servers_count }}</td>
      <td class="col-actions">
        <div class="action-group">
          <BaseButton size="sm" @click="openEdit(loc)">
            <MsIcon name="edit" size="xs" /> {{ t('common.btn.edit') }}
          </BaseButton>
          <BaseButton
            size="sm"
            variant="danger"
            :disabled="loc.nodes_count > 0"
            :title="loc.nodes_count > 0 ? t('hosts.locations.deleteBlocked') : undefined"
            @click="removeLocation(loc)"
          >
            <MsIcon name="delete" size="xs" /> {{ t('common.btn.delete') }}
          </BaseButton>
        </div>
      </td>
    </template>

    <template #card="{ item: loc }">
      <CardTap @tap="openMobileAction(loc)">
        <div class="card-row--main">
          <span class="card-name"><code>{{ loc.short }}</code></span>
        </div>
        <div v-if="loc.long" class="card-row--sub">{{ loc.long }}</div>
        <div class="card-detail">
          <CardKV :label="t('hosts.locations.columns.nodes')">
            <span class="tabular">{{ loc.nodes_count }}</span>
          </CardKV>
          <CardKV :label="t('hosts.locations.columns.servers')">
            <span class="tabular">{{ loc.servers_count }}</span>
          </CardKV>
        </div>
      </CardTap>
    </template>
  </DataTable>
  </div>

  <ActionSheet v-model="mobileActionOpen" :title="mobileActionLoc?.short">
    <template v-if="mobileActionLoc?.long" #info>
      {{ mobileActionLoc.long }}
    </template>
    <template v-if="mobileActionLoc">
      <button @click="mobileActionOpen = false; openEdit(mobileActionLoc!)">
        <MsIcon name="edit" size="sm" /> {{ t('common.btn.edit') }}
      </button>
      <button
        class="action-sheet--danger"
        :disabled="mobileActionLoc.nodes_count > 0"
        @click="mobileActionOpen = false; removeLocation(mobileActionLoc!)"
      >
        <MsIcon name="delete" size="sm" /> {{ t('common.btn.delete') }}
      </button>
    </template>
  </ActionSheet>

  <LocationEditorModal
    v-model="editorOpen"
    :location="editingLocation"
    @saved="onSaved"
  />
</template>

<style scoped>
.locations-table-wrap :deep(.dt-table)    { min-width: 720px; }
.locations-table-wrap :deep(.col-short)   { width: 20%; white-space: nowrap; }
.locations-table-wrap :deep(.col-long)    { width: 40%; color: var(--t2); }
.locations-table-wrap :deep(.col-num)     { width: 10%; white-space: nowrap; }
.locations-table-wrap :deep(.col-actions) { width: 20%; }

code {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  background: var(--bg-in);
  padding: 2px 6px;
  border-radius: var(--r-xs);
  color: var(--t1);
}
.long-text {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
}
.tabular { font-variant-numeric: tabular-nums; color: var(--t2); }

.action-group {
  display: flex;
  gap: var(--sp-2);
  align-items: center;
  flex-wrap: wrap;
}

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
.card-row--sub {
  margin-top: 2px;
  font-size: var(--text-sm);
  color: var(--t2);
}
.card-detail {
  display: flex;
  gap: var(--sp-4);
  margin-top: var(--sp-2);
}
</style>
