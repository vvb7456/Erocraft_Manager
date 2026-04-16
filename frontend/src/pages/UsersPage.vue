<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'
import PageHeader from '@/components/layout/PageHeader.vue'
import SectionToolbar from '@/components/ui/SectionToolbar.vue'
import FilterInput from '@/components/ui/FilterInput.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseModal from '@/components/ui/BaseModal.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import Badge from '@/components/ui/Badge.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import DataTable from '@/components/ui/DataTable.vue'
import SecretInput from '@/components/ui/SecretInput.vue'
import BottomSheet from '@/components/ui/BottomSheet.vue'

defineOptions({ name: 'UsersPage' })

const { t } = useI18n({ useScope: 'global' })
const route = useRoute()
const router = useRouter()
const { get, post, put, del, loading } = useApiFetch()
const { toast } = useToast()
const { confirm } = useConfirm()

// ── Types ──
interface UserItem {
  id: number
  username: string
  email: string
  first_name: string
  last_name: string
  root_admin: boolean
  server_count: number
  created_at: string | null
}

// ── Raw data ──
const rawUsers = ref<UserItem[]>([])

// ── Client-side state ──
const filterServer = ref('all')
const sortBy = ref('id')
const sortOrder = ref<'asc' | 'desc'>('desc')
const searchTerm = ref((route.query.q as string) || '')
const selectedIds = ref<Set<number>>(new Set())
const page = ref(1)
const perPage = ref(20)

// Batch operations
const batchActionType = ref('')
const batchActionOptions = computed(() => [
  { value: 'email', label: t('users.batch.email') },
  { value: 'delete', label: t('users.batch.delete') },
])

// Create modal
const createModalOpen = ref(false)
const createEmail = ref('')
const createUsername = ref('')
const createSendWelcome = ref(true)
const createLoading = ref(false)

// Edit modal
const editModalOpen = ref(false)
const editUser = ref<UserItem | null>(null)
const editForm = ref({ username: '', email: '', firstName: '', lastName: '', password: '' })
const editLoading = ref(false)

// ── Options ──
const serverFilterOptions = computed(() => [
  { value: 'all', label: t('users.filter.all') },
  { value: 'has_servers', label: t('users.filter.has_servers') },
  { value: 'no_servers', label: t('users.filter.no_servers') },
])

// ── Fetch (no server-side sort/filter) ──
async function loadUsers() {
  const data = await get<{ users: UserItem[] }>('/api/users')
  if (data) {
    rawUsers.value = data.users
  }
}

onMounted(loadUsers)

// ── Client-side filter → sort → paginate ──
const filtered = computed(() => {
  let list = rawUsers.value

  const q = searchTerm.value.toLowerCase().trim()
  if (q) {
    list = list.filter(u =>
      u.username.toLowerCase().includes(q) ||
      u.email.toLowerCase().includes(q) ||
      String(u.id).includes(q),
    )
  }

  if (filterServer.value === 'has_servers') {
    list = list.filter(u => u.server_count > 0)
  } else if (filterServer.value === 'no_servers') {
    list = list.filter(u => u.server_count === 0)
  }

  return list
})

const sorted = computed(() => {
  const list = [...filtered.value]
  const col = sortBy.value
  const asc = sortOrder.value === 'asc'

  list.sort((a, b) => {
    let va: string | number
    let vb: string | number

    if (col === 'username') {
      va = a.username.toLowerCase()
      vb = b.username.toLowerCase()
    } else if (col === 'server_count') {
      va = a.server_count
      vb = b.server_count
    } else if (col === 'created_at') {
      va = a.created_at || ''
      vb = b.created_at || ''
    } else {
      va = a.id
      vb = b.id
    }

    if (va < vb) return asc ? -1 : 1
    if (va > vb) return asc ? 1 : -1
    return 0
  })

  return list
})

const totalPages = computed(() => Math.max(1, Math.ceil(sorted.value.length / perPage.value)))

const paginated = computed(() => {
  const start = (page.value - 1) * perPage.value
  return sorted.value.slice(start, start + perPage.value)
})

// ── Selection ──
const allSelected = computed({
  get: () => paginated.value.length > 0 && paginated.value.every(u => selectedIds.value.has(u.id)),
  set: (v: boolean) => {
    const s = new Set(selectedIds.value)
    if (v) {
      paginated.value.forEach(u => s.add(u.id))
    } else {
      paginated.value.forEach(u => s.delete(u.id))
    }
    selectedIds.value = s
  },
})

function toggleSelect(id: number) {
  const s = new Set(selectedIds.value)
  if (s.has(id)) s.delete(id)
  else s.add(id)
  selectedIds.value = s
}

// ── Batch ──
async function executeBatchAction() {
  const action = batchActionType.value
  if (!action) return
  const ids = [...selectedIds.value]
  if (!ids.length) return

  if (action === 'delete') {
    const ok = await confirm({
      title: t('users.confirm.batch_delete_title'),
      message: t('users.confirm.batch_delete_msg', { n: ids.length }),
      variant: 'danger',
      confirmText: t('common.btn.delete'),
    })
    if (!ok) return
  }

  if (action === 'email') {
    const ok = await confirm({
      title: t('users.confirm.batch_email_title'),
      message: t('users.confirm.batch_email_msg', { n: ids.length }),
      confirmText: t('common.btn.confirm'),
    })
    if (!ok) return
  }

  const res = await post<{ message: string }>('/api/users/batch', { action, userIds: ids })
  if (res) {
    toast(res.message, 'success')
    selectedIds.value = new Set()
    batchActionType.value = ''
    await loadUsers()
  }
}

// ── Sort toggle (client-side, no reload) ──
function toggleSort(col: string) {
  if (sortBy.value === col) {
    sortOrder.value = sortOrder.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortBy.value = col
    sortOrder.value = col === 'id' ? 'desc' : 'asc'
  }
  page.value = 1
}

// ── Create ──
function openCreate() {
  createEmail.value = ''
  createUsername.value = ''
  createSendWelcome.value = true
  createModalOpen.value = true
}

function onEmailInput(email: string) {
  createEmail.value = email
  // Auto-fill username from email prefix
  const at = email.indexOf('@')
  if (at > 0 && !createUsername.value) {
    createUsername.value = email.substring(0, at)
  }
}

async function doCreate(andCreateServer = false) {
  createLoading.value = true
  const res = await post<{ message: string; emailSent?: boolean; user?: { id: number; username: string } }>('/api/users', {
    email: createEmail.value,
    username: createUsername.value,
    sendWelcome: createSendWelcome.value,
  })
  createLoading.value = false
  if (res) {
    let msg = res.message
    if (createSendWelcome.value) {
      msg += res.emailSent ? ` (${t('users.create.email_sent')})` : ` (${t('users.create.email_failed')})`
    }
    toast(msg, 'success')
    createModalOpen.value = false

    if (andCreateServer && res.user) {
      router.push({ name: 'servers', query: { new_for_user: res.user.username } })
    } else {
      await loadUsers()
    }
  }
}

// ── Edit ──
function openEdit(u: UserItem) {
  editUser.value = u
  editForm.value = {
    username: u.username,
    email: u.email,
    firstName: u.first_name || '',
    lastName: u.last_name || '',
    password: '',
  }
  editModalOpen.value = true
}

async function doEdit() {
  if (!editUser.value) return
  editLoading.value = true
  const res = await put<{ message: string }>(`/api/users/${editUser.value.id}`, {
    username: editForm.value.username,
    email: editForm.value.email,
    firstName: editForm.value.firstName,
    lastName: editForm.value.lastName,
    password: editForm.value.password || undefined,
  })
  editLoading.value = false
  if (res) {
    toast(t('users.edit.success'), 'success')
    editModalOpen.value = false
    await loadUsers()
  }
}

// ── Delete ──
async function deleteUser(u: UserItem) {
  const ok = await confirm({
    title: t('users.confirm.delete_title'),
    message: t('users.confirm.delete_msg', { name: u.username }),
    variant: 'danger',
    confirmText: t('common.btn.delete'),
  })
  if (!ok) return
  const res = await del<{ message: string }>(`/api/users/${u.id}`)
  if (res) {
    toast(res.message, 'success')
    await loadUsers()
  }
}

// ── Mobile action sheet ──
const mobileActionUser = ref<UserItem | null>(null)
const mobileActionOpen = ref(false)
function openMobileAction(u: UserItem) {
  mobileActionUser.value = u
  mobileActionOpen.value = true
}

// ── Mobile sort sheet ──
const mobileSortOpen = ref(false)
</script>

<template>
  <PageHeader icon="group" :title="t('users.title')" />

  <div class="page-body">
    <!-- Toolbar -->
    <SectionToolbar>
      <template #start>
        <FilterInput
          v-model="searchTerm"
          :placeholder="t('users.search_placeholder')"
          class="users-filter-input"
        />
        <div class="batch-controls">
          <BaseSelect v-model="batchActionType" :options="batchActionOptions" :placeholder="t('users.batch.select_action')" size="sm" fit :disabled="selectedIds.size === 0" />
          <BaseButton size="sm" :disabled="selectedIds.size === 0 || !batchActionType" @click="executeBatchAction">
            <MsIcon name="play_arrow" size="xs" /> {{ t('users.batch.execute') }}
          </BaseButton>
          <span v-if="selectedIds.size > 0" class="toolbar-status">{{ t('users.batch.selected', { n: selectedIds.size }) }}</span>
        </div>
      </template>
      <template #end>
        <div class="toolbar-end-row">
          <BaseButton size="sm" variant="primary" class="toolbar-half" @click="openCreate">
            <MsIcon name="person_add" size="xs" /> {{ t('users.action.create') }}
          </BaseButton>
          <BaseSelect v-model="filterServer" :options="serverFilterOptions" size="sm" fit class="toolbar-half" />
        </div>
      </template>
    </SectionToolbar>

    <!-- Table -->
    <DataTable
      :items="paginated"
      :page="page"
      :total-pages="totalPages"
      :per-page="perPage"
      :per-page-label="t('users.pagination.per_page')"
      :loading="loading"
      empty-icon="group"
      :empty-text="t('users.empty')"
      @update:page="page = $event"
      @update:per-page="perPage = $event; page = 1"
    >
      <template #header>
        <th class="col-check"><input type="checkbox" v-model="allSelected" /></th>
        <th class="col-id sortable" @click="toggleSort('id')">
          {{ t('users.table.id') }}
          <MsIcon v-if="sortBy === 'id'" :name="sortOrder === 'asc' ? 'arrow_upward' : 'arrow_downward'" size="xs" />
        </th>
        <th class="col-username sortable" @click="toggleSort('username')">
          {{ t('users.table.username') }}
          <MsIcon v-if="sortBy === 'username'" :name="sortOrder === 'asc' ? 'arrow_upward' : 'arrow_downward'" size="xs" />
        </th>
        <th class="col-email">{{ t('users.table.email') }}</th>
        <th class="col-count sortable" @click="toggleSort('server_count')">
          {{ t('users.table.server_count') }}
          <MsIcon v-if="sortBy === 'server_count'" :name="sortOrder === 'asc' ? 'arrow_upward' : 'arrow_downward'" size="xs" />
        </th>
        <th class="col-created sortable" @click="toggleSort('created_at')">
          {{ t('users.table.created_at') }}
          <MsIcon v-if="sortBy === 'created_at'" :name="sortOrder === 'asc' ? 'arrow_upward' : 'arrow_downward'" size="xs" />
        </th>
        <th class="col-role">{{ t('users.table.role') }}</th>
        <th class="col-actions">{{ t('users.table.actions') }}</th>
      </template>
      <template #row="{ item: u }">
        <td class="col-check"><input type="checkbox" :checked="selectedIds.has(u.id)" @change="toggleSelect(u.id)" /></td>
        <td class="col-id">{{ u.id }}</td>
        <td class="col-username">{{ u.username }}</td>
        <td class="col-email">{{ u.email }}</td>
        <td class="col-count">
          <router-link v-if="u.server_count > 0" :to="{ name: 'servers', query: { q: u.username } }" class="count-link">
            {{ u.server_count }}
          </router-link>
          <span v-else class="count-zero">0</span>
        </td>
        <td class="col-created">{{ u.created_at ? new Date(u.created_at).toLocaleDateString() : '-' }}</td>
        <td class="col-role">
          <Badge :color="u.root_admin ? 'var(--amber)' : undefined">
            {{ u.root_admin ? t('users.role.admin') : t('users.role.user') }}
          </Badge>
        </td>
        <td class="col-actions">
          <div class="action-group">
            <BaseButton size="sm" @click="openEdit(u)">
              <MsIcon name="edit" size="xs" /> {{ t('users.action.edit') }}
            </BaseButton>
            <BaseButton size="sm" variant="danger" @click="deleteUser(u)">
              <MsIcon name="delete" size="xs" /> {{ t('users.action.delete') }}
            </BaseButton>
          </div>
        </td>
      </template>

      <!-- Mobile card -->
      <template #card="{ item: u }">
        <div class="dt-card-tap" @click="openMobileAction(u)">
          <div class="card-row card-row--main">
            <span class="card-username">{{ u.username }} <span class="card-id-inline">#{{ u.id }}</span></span>
            <Badge :color="u.root_admin ? 'var(--amber)' : undefined" size="sm">
              {{ u.root_admin ? t('users.role.admin') : t('users.role.user') }}
            </Badge>
          </div>
          <div class="card-row card-row--sub">{{ u.email }}</div>
          <div class="card-row card-row--tags">
            <Badge :color="u.server_count > 0 ? 'var(--ac)' : 'var(--t3)'" size="sm">
              {{ t('users.table.server_count') }} {{ u.server_count }}
            </Badge>
            <span class="card-tag">{{ u.created_at ? new Date(u.created_at).toLocaleDateString() : '-' }}</span>
          </div>
        </div>
      </template>
    </DataTable>
  </div>

  <!-- Mobile Action Sheet -->
  <BottomSheet v-model="mobileActionOpen" :title="mobileActionUser?.username">
    <div v-if="mobileActionUser" class="action-sheet">
      <div class="action-sheet__info">
        {{ mobileActionUser.email }}
      </div>
      <button class="action-sheet__item" @click="mobileActionOpen = false; openEdit(mobileActionUser!)">
        <MsIcon name="edit" size="sm" /> {{ t('users.action.edit') }}
      </button>
      <button v-if="mobileActionUser.server_count > 0" class="action-sheet__item" @click="mobileActionOpen = false; router.push({ name: 'servers', query: { q: mobileActionUser!.username } })">
        <MsIcon name="dns" size="sm" /> {{ t('users.table.server_count') }} ({{ mobileActionUser.server_count }})
      </button>
      <button class="action-sheet__item action-sheet__item--danger" @click="mobileActionOpen = false; deleteUser(mobileActionUser!)">
        <MsIcon name="delete" size="sm" /> {{ t('users.action.delete') }}
      </button>
    </div>
  </BottomSheet>

  <!-- Create User Modal -->
  <BaseModal v-model="createModalOpen" :title="t('users.create.title')" icon="person_add" size="sm">
    <div class="form-stack">
      <div class="form-field">
        <label class="modal-label">{{ t('users.create.email') }}</label>
        <BaseInput :modelValue="createEmail" type="email" @update:modelValue="onEmailInput" />
      </div>
      <div class="form-field">
        <label class="modal-label">{{ t('users.create.username') }}</label>
        <BaseInput v-model="createUsername" />
      </div>
      <div class="form-field">
        <label class="checkbox-label">
          {{ t('users.create.send_welcome') }}
          <input type="checkbox" v-model="createSendWelcome" />
        </label>
      </div>
    </div>
    <template #footer>
      <BaseButton @click="createModalOpen = false">{{ t('common.btn.cancel') }}</BaseButton>
      <BaseButton variant="primary" :loading="createLoading" @click="doCreate(true)">
        <MsIcon name="dns" size="xs" /> {{ t('users.create.create_and_server') }}
      </BaseButton>
      <BaseButton variant="primary" :loading="createLoading" @click="doCreate(false)">{{ t('common.btn.confirm') }}</BaseButton>
    </template>
  </BaseModal>

  <!-- Edit User Modal -->
  <BaseModal v-model="editModalOpen" :title="t('users.edit.title')" icon="edit" size="md">
    <div class="form-stack">
      <div class="form-row">
        <div class="form-field">
          <label class="modal-label">{{ t('users.edit.username') }}</label>
          <BaseInput v-model="editForm.username" />
        </div>
        <div class="form-field">
          <label class="modal-label">{{ t('users.edit.email') }}</label>
          <BaseInput v-model="editForm.email" type="email" />
        </div>
      </div>
      <div class="form-row">
        <div class="form-field">
          <label class="modal-label">{{ t('users.edit.first_name') }}</label>
          <BaseInput v-model="editForm.firstName" />
        </div>
        <div class="form-field">
          <label class="modal-label">{{ t('users.edit.last_name') }}</label>
          <BaseInput v-model="editForm.lastName" />
        </div>
      </div>
      <div class="form-field">
        <label class="modal-label">{{ t('users.edit.password') }}</label>
        <SecretInput v-model="editForm.password" :placeholder="t('users.edit.password_hint')" />
      </div>
    </div>
    <template #footer>
      <BaseButton @click="editModalOpen = false">{{ t('common.btn.cancel') }}</BaseButton>
      <BaseButton variant="primary" :loading="editLoading" @click="doEdit">{{ t('common.btn.save') }}</BaseButton>
    </template>
  </BaseModal>
</template>

<style scoped>
.checkbox-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: .82rem;
  color: var(--t2);
  cursor: pointer;
}
.checkbox-label input { margin: 0; }

.users-filter-input {
  flex: 1;
  max-width: 280px;
}

@media (max-width: 768px) {
  .users-filter-input {
    max-width: none;
    width: 100%;
  }
}

.col-check { width: 36px; text-align: center !important; }
.col-id { width: 56px; }
.col-username { width: 14%; }
.col-email { width: 22%; }
.col-count { width: 64px; text-align: center !important; }
.col-created { width: 12%; }
.col-role { width: 80px; }
.col-actions { width: 160px; }

.count-link {
  color: var(--ac);
  text-decoration: none;
  font-weight: 600;
}
.count-link:hover {
  text-decoration: underline;
}
.count-zero {
  color: var(--t3);
}

/* Modal form styles */
.form-stack {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}

.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--sp-3);
}

.form-field {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}

.field-hint {
  font-size: .75rem;
  color: var(--t3);
  margin: 0;
}

/* Mobile card styles */
.card-username {
  font-weight: 600;
  font-size: .92rem;
}
.card-tag {
  font-size: .75rem;
  color: var(--t3);
}
</style>
