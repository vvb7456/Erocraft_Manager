<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { apiErrorMessage } from '@/composables/apiClient'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'
import {
  deleteNode,
  listNodes,
  type NodeOut,
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
import Badge from '@/components/ui/Badge.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import CardTap from '@/components/ui/CardTap.vue'
import CardKV from '@/components/ui/CardKV.vue'
import ActionSheet from '@/components/ui/ActionSheet.vue'
import NodeCreateModal from '@/components/hosts/NodeCreateModal.vue'
import NodeConfigModal from '@/components/hosts/NodeConfigModal.vue'
import LocationEditorModal from '@/components/hosts/LocationEditorModal.vue'

defineOptions({ name: 'HostsNodesTab' })

const emit = defineEmits<{
  bindNode: [node: NodeOut]
}>()

const { t } = useI18n({ useScope: 'global' })
const router = useRouter()
const { toast } = useToast()
const { confirm } = useConfirm()

const nodes = ref<NodeOut[]>([])
const loading = ref(true)
const searchTerm = ref('')
const mobileFilterOpen = ref(false)
const { sortBy, sortOrder, toggleSort, sortItems } = useTableSort({
  descColumns: ['servers_count'],
})
const sortColumns = computed(() => [
  { key: 'name', label: t('hosts.nodes.columns.name') },
  { key: 'location', label: t('hosts.nodes.columns.location') },
  { key: 'fqdn', label: t('hosts.nodes.columns.address') },
  { key: 'host_name', label: t('hosts.nodes.columns.host') },
  { key: 'servers_count', label: t('hosts.nodes.columns.usage') },
])

const createOpen = ref(false)
const nodeCreateRef = ref<InstanceType<typeof NodeCreateModal> | null>(null)
const locationCreateOpen = ref(false)

const configModalOpen = ref(false)
const configNodeId = ref<number | null>(null)
const configNodeName = ref('')

const mobileActionNode = ref<NodeOut | null>(null)
const mobileActionOpen = ref(false)

async function loadNodes() {
  loading.value = true
  try {
    const res = await listNodes()
    nodes.value = res.nodes
  } catch (err) {
    toast(apiErrorMessage(err), 'error')
  } finally {
    loading.value = false
  }
}

onMounted(loadNodes)

const filtered = computed(() => {
  const q = searchTerm.value.trim().toLowerCase()
  if (!q) return nodes.value
  return nodes.value.filter(n =>
    `${n.name} ${n.fqdn} ${n.location?.short ?? ''} ${n.host_name ?? ''}`.toLowerCase().includes(q),
  )
})

const sorted = computed(() =>
  sortItems(filtered.value, {
    name: (n) => n.name,
    location: (n) => n.location?.short ?? null,
    fqdn: (n) => n.fqdn,
    host_name: (n) => (n.host_id != null ? (n.host_name || `#${n.host_id}`) : null),
    servers_count: (n) => n.servers_count,
  }, {
    tieBreaker: (a, b) => a.id - b.id,
  }),
)

const { page, perPage, totalPages, paginated, setPerPage } = useClientPagination(sorted, {
  resetDeps: [searchTerm, sortBy, sortOrder],
})

function openNodeConfig(n: NodeOut) {
  configNodeId.value = n.id
  configNodeName.value = n.name
  configModalOpen.value = true
}

function openHost(hostId: number) {
  router.push({ name: 'host-detail', params: { id: hostId } })
}

function onNodeCreated(node: NodeOut) {
  void loadNodes()
  configNodeId.value = node.id
  configNodeName.value = node.name
  configModalOpen.value = true
}

function onLocationCreated() {
  void nodeCreateRef.value?.reloadLocations()
}

async function removeNode(n: NodeOut) {
  const ok = await confirm({
    title: t('hosts.nodes.deleteTitle'),
    message: t('hosts.nodes.deleteMsg', { name: n.name }),
    variant: 'danger',
    confirmText: t('common.btn.delete'),
  })
  if (!ok) return
  try {
    await deleteNode(n.id)
    toast(t('hosts.nodes.deleted', { name: n.name }), 'success')
    await loadNodes()
  } catch (err) {
    toast(apiErrorMessage(err), 'error')
  }
}

function openMobileAction(n: NodeOut) {
  mobileActionNode.value = n
  mobileActionOpen.value = true
}

defineExpose({ reload: loadNodes })
</script>

<template>
  <PageHeaderActions>
    <BaseButton size="sm" variant="primary" @click="createOpen = true">
      <MsIcon name="add" size="xs" />{{ t('hosts.nodes.createBtn') }}
    </BaseButton>
  </PageHeaderActions>

  <SectionToolbar>
    <template #start>
      <div class="tb-search-row">
        <FilterInput
          v-model="searchTerm"
          :placeholder="t('hosts.nodes.searchPlaceholder')"
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
        {{ t('hosts.nodes.totalCount', { n: filtered.length }) }}
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

  <div class="nodes-table-wrap">
  <DataTable
    :items="paginated"
    :page="page"
    :total-pages="totalPages"
    :per-page="perPage"
    :per-page-label="t('hosts.list.perPage')"
    :loading="loading"
    empty-icon="dns"
    :empty-text="t('hosts.nodes.empty')"
    row-key="id"
    @update:page="page = $event"
    @update:per-page="setPerPage"
  >
    <template #header>
      <SortTh class="col-name" col="name" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('hosts.nodes.columns.name') }}</SortTh>
      <SortTh class="col-loc" col="location" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('hosts.nodes.columns.location') }}</SortTh>
      <SortTh class="col-addr" col="fqdn" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('hosts.nodes.columns.address') }}</SortTh>
      <SortTh class="col-host" col="host_name" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('hosts.nodes.columns.host') }}</SortTh>
      <SortTh class="col-usage" col="servers_count" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('hosts.nodes.columns.usage') }}</SortTh>
      <th class="col-actions">{{ t('hosts.columns.actions') }}</th>
    </template>

    <template #row="{ item: n }">
      <td class="col-name">
        <div class="name-line">
          <span class="name-main">{{ n.name }}</span>
          <Badge v-if="n.maintenance_mode" size="sm" color="var(--amber)">
            {{ t('hosts.setting.wings.fields.maintenance') }}
          </Badge>
        </div>
        <div v-if="n.description" class="name-sub">{{ n.description }}</div>
      </td>
      <td class="col-loc">
        <code v-if="n.location?.short">{{ n.location.short }}</code>
        <span v-else class="muted-text">—</span>
      </td>
      <td class="col-addr mono">{{ n.scheme }}://{{ n.fqdn }}:{{ n.daemon_listen }}</td>
      <td class="col-host">
        <a
          v-if="n.host_id != null"
          href="#"
          class="host-link"
          @click.prevent="openHost(n.host_id)"
        >
          {{ n.host_name || `#${n.host_id}` }}
        </a>
        <span v-else class="muted-text">{{ t('hosts.nodes.unbound') }}</span>
      </td>
      <td class="col-usage tabular">
        {{ t('hosts.nodes.serversCount', { n: n.servers_count }) }} · {{ t('hosts.nodes.plansCount', { n: n.plans_count }) }}
      </td>
      <td class="col-actions">
        <div class="action-group">
          <BaseButton
            v-if="n.host_id == null"
            size="sm"
            variant="default"
            @click="emit('bindNode', n)"
          >
            <MsIcon name="add_circle" size="xs" /> {{ t('hosts.nodes.bindHost') }}
          </BaseButton>
          <BaseButton
            v-else
            size="sm"
            @click="openHost(n.host_id)"
          >
            <MsIcon name="edit" size="xs" /> {{ t('common.btn.edit') }}
          </BaseButton>
          <BaseButton size="sm" @click="openNodeConfig(n)">
            <MsIcon name="code" size="xs" /> {{ t('hosts.nodes.viewConfig') }}
          </BaseButton>
          <BaseButton
            size="sm"
            variant="danger"
            @click="removeNode(n)"
          >
            <MsIcon name="delete" size="xs" /> {{ t('common.btn.delete') }}
          </BaseButton>
        </div>
      </td>
    </template>

    <template #card="{ item: n }">
      <CardTap @tap="openMobileAction(n)">
        <div class="card-row--main">
          <span class="card-name">{{ n.name }}</span>
          <Badge v-if="n.maintenance_mode" size="sm" color="var(--amber)">
            {{ t('hosts.setting.wings.fields.maintenance') }}
          </Badge>
        </div>
        <div class="card-row--sub mono">{{ n.scheme }}://{{ n.fqdn }}:{{ n.daemon_listen }}</div>
        <div class="card-detail">
          <CardKV :label="t('hosts.nodes.columns.location')">
            <code v-if="n.location?.short">{{ n.location.short }}</code>
            <span v-else class="muted-text">—</span>
          </CardKV>
          <CardKV :label="t('hosts.nodes.columns.host')">
            <span v-if="n.host_id != null" class="host-link">{{ n.host_name || `#${n.host_id}` }}</span>
            <span v-else class="muted-text">{{ t('hosts.nodes.unbound') }}</span>
          </CardKV>
          <CardKV :label="t('hosts.nodes.columns.usage')">
            <span class="tabular">{{ n.servers_count }} / {{ n.plans_count }}</span>
          </CardKV>
        </div>
      </CardTap>
    </template>
  </DataTable>
  </div>

  <ActionSheet v-model="mobileActionOpen" :title="mobileActionNode?.name">
    <template v-if="mobileActionNode" #info>
      {{ mobileActionNode.scheme }}://{{ mobileActionNode.fqdn }}:{{ mobileActionNode.daemon_listen }}
    </template>
    <template v-if="mobileActionNode">
      <button
        v-if="mobileActionNode.host_id == null"
        @click="mobileActionOpen = false; emit('bindNode', mobileActionNode!)"
      >
        <MsIcon name="add_circle" size="sm" /> {{ t('hosts.nodes.bindHost') }}
      </button>
      <button
        v-else
        @click="mobileActionOpen = false; openHost(mobileActionNode!.host_id!)"
      >
        <MsIcon name="edit" size="sm" /> {{ t('common.btn.edit') }}
      </button>
      <button @click="mobileActionOpen = false; openNodeConfig(mobileActionNode!)">
        <MsIcon name="code" size="sm" /> {{ t('hosts.nodes.viewConfig') }}
      </button>
      <button
        class="action-sheet--danger"
        @click="mobileActionOpen = false; removeNode(mobileActionNode!)"
      >
        <MsIcon name="delete" size="sm" /> {{ t('common.btn.delete') }}
      </button>
    </template>
  </ActionSheet>

  <NodeCreateModal
    ref="nodeCreateRef"
    v-model="createOpen"
    @created="onNodeCreated"
    @createLocation="locationCreateOpen = true"
  />
  <LocationEditorModal
    v-model="locationCreateOpen"
    :z-index="1150"
    @saved="onLocationCreated"
  />
  <NodeConfigModal
    v-model="configModalOpen"
    :node-id="configNodeId"
    :node-name="configNodeName"
  />
</template>

<style scoped>
.nodes-table-wrap :deep(.col-loc)     { white-space: nowrap; }
.nodes-table-wrap :deep(.col-host)    { white-space: nowrap; }
.nodes-table-wrap :deep(.col-usage)   { white-space: nowrap; }

code {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  background: var(--bg-in);
  padding: 2px 6px;
  border-radius: var(--r-xs);
  color: var(--t1);
}

.name-line {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}
.name-main {
  color: var(--t1);
  font-weight: 500;
}
.name-sub {
  color: var(--t3);
  font-size: var(--text-xs);
  margin-top: 2px;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.mono {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  color: var(--t2);
}
.tabular {
  font-variant-numeric: tabular-nums;
  color: var(--t2);
  font-size: var(--text-sm);
}
.host-link {
  color: var(--ac);
  text-decoration: none;
  font-weight: 500;
}
.host-link:hover { color: var(--ac2); }
.muted-text { color: var(--t3); font-size: var(--text-sm); }

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
