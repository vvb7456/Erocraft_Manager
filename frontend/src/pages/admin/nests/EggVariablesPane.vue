<script setup lang="ts">
import { computed, inject, ref, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { apiErrorMessage } from '@/composables/apiClient'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'
import {
  createEggVariable,
  deleteEggVariable,
  ENV_VAR_PATTERN,
  RESERVED_ENV_NAMES,
  updateEggVariable,
  type AffectedPlanWarning,
  type EggDetailOut,
  type EggVariableOut,
} from '@/api/adminNestsEggs'
import PageHeaderActions from '@/components/layout/PageHeaderActions.vue'
import SectionToolbar from '@/components/ui/SectionToolbar.vue'
import FilterInput from '@/components/ui/FilterInput.vue'
import DataTable from '@/components/ui/DataTable.vue'
import SortTh from '@/components/ui/SortTh.vue'
import MobileFilterSheet from '@/components/ui/MobileFilterSheet.vue'
import { useTableSort } from '@/composables/useTableSort'
import { useClientPagination } from '@/composables/useTablePagination'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseModal from '@/components/ui/BaseModal.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import BaseTextarea from '@/components/form/BaseTextarea.vue'
import FormField from '@/components/form/FormField.vue'
import ToggleSwitch from '@/components/ui/ToggleSwitch.vue'
import HelpTip from '@/components/ui/HelpTip.vue'
import Badge from '@/components/ui/Badge.vue'
import CardTap from '@/components/ui/CardTap.vue'
import CardKV from '@/components/ui/CardKV.vue'
import ActionSheet from '@/components/ui/ActionSheet.vue'
import MsIcon from '@/components/ui/MsIcon.vue'

defineOptions({ name: 'EggVariablesPane' })

const { t } = useI18n({ useScope: 'global' })
const { toast } = useToast()
const { confirm } = useConfirm()

const egg = inject<Ref<EggDetailOut | null>>('eggDetail')!
const reloadEgg = inject<() => Promise<void>>('reloadEgg')!
const setAffectedPlans = inject<(plans: AffectedPlanWarning[]) => void>('setAffectedPlans')!

const searchTerm = ref('')
const mobileFilterOpen = ref(false)
const { sortBy, sortOrder, toggleSort, sortItems } = useTableSort({
  descColumns: ['permissions'],
})
const sortColumns = computed(() => [
  { key: 'name', label: t('nests.variables.columns.name') },
  { key: 'env_variable', label: t('nests.variables.columns.envVariable') },
  { key: 'default_value', label: t('nests.variables.columns.defaultValue') },
  { key: 'permissions', label: t('nests.variables.columns.permissions') },
])

const modalOpen = ref(false)
const editingVar = ref<EggVariableOut | null>(null)
const saving = ref(false)

const mobileActionVar = ref<EggVariableOut | null>(null)
const mobileActionOpen = ref(false)

const form = ref({
  name: '',
  description: '',
  env_variable: '',
  default_value: '',
  user_viewable: true,
  user_editable: true,
  rules: 'required|string|max:191',
})

const variables = computed(() => egg.value?.variables || [])
const reservedListStr = Array.from(RESERVED_ENV_NAMES).join(', ')

const filteredVariables = computed(() => {
  const q = searchTerm.value.trim().toLowerCase()
  if (!q) return variables.value
  return variables.value.filter(v =>
    `${v.name} ${v.env_variable} ${v.description ?? ''} ${v.rules}`.toLowerCase().includes(q),
  )
})

const sortedVariables = computed(() =>
  sortItems(filteredVariables.value, {
    name: (v) => v.name,
    env_variable: (v) => v.env_variable,
    default_value: (v) => v.default_value,
    permissions: (v) => (v.user_viewable ? 2 : 0) + (v.user_editable ? 1 : 0),
  }, {
    tieBreaker: (a, b) => a.id - b.id,
  }),
)

const { page, perPage, totalPages, paginated, setPerPage } = useClientPagination(sortedVariables, {
  resetDeps: [searchTerm, sortBy, sortOrder],
})

const envVarError = computed(() => {
  const s = form.value.env_variable.trim()
  if (!s) return ''
  if (!ENV_VAR_PATTERN.test(s)) return t('nests.variables.errors.envFormat')
  if (RESERVED_ENV_NAMES.has(s.toUpperCase())) {
    return t('nests.variables.errors.envReserved', { name: s })
  }
  const dup = variables.value.find(
    v => v.env_variable.toUpperCase() === s.toUpperCase() && v.id !== editingVar.value?.id,
  )
  if (dup) return t('nests.variables.errors.envDuplicate', { name: s })
  return ''
})

const canSubmit = computed(() =>
  !!form.value.name.trim() &&
  !!form.value.env_variable.trim() &&
  !!form.value.rules.trim() &&
  !envVarError.value,
)

function openCreate() {
  editingVar.value = null
  form.value = {
    name: '',
    description: '',
    env_variable: '',
    default_value: '',
    user_viewable: true,
    user_editable: true,
    rules: 'required|string|max:191',
  }
  modalOpen.value = true
}

function openEdit(v: EggVariableOut) {
  editingVar.value = v
  form.value = {
    name: v.name,
    description: v.description || '',
    env_variable: v.env_variable,
    default_value: v.default_value || '',
    user_viewable: !!v.user_viewable,
    user_editable: !!v.user_editable,
    rules: v.rules,
  }
  modalOpen.value = true
}

function openMobileAction(v: EggVariableOut) {
  mobileActionVar.value = v
  mobileActionOpen.value = true
}

async function submit() {
  if (!egg.value || !canSubmit.value) return
  saving.value = true
  try {
    const payload = {
      name: form.value.name.trim(),
      description: form.value.description,
      env_variable: form.value.env_variable.trim(),
      default_value: form.value.default_value,
      user_viewable: form.value.user_viewable,
      user_editable: form.value.user_editable,
      rules: form.value.rules.trim(),
    }
    const res = editingVar.value
      ? await updateEggVariable(egg.value.id, editingVar.value.id, payload)
      : await createEggVariable(egg.value.id, payload)

    setAffectedPlans(res.affected_plans)
    if (res.affected_plans.length > 0) {
      toast(t('nests.egg.savedWithPlanWarnings', { n: res.affected_plans.length }), 'warning')
    } else {
      toast(
        editingVar.value ? t('nests.variables.updated') : t('nests.variables.created'),
        'success',
      )
    }
    modalOpen.value = false
    await reloadEgg()
  } catch (err) {
    toast(apiErrorMessage(err), 'error')
  } finally {
    saving.value = false
  }
}

async function removeVar(v: EggVariableOut) {
  if (!egg.value) return
  const ok = await confirm({
    title: t('nests.variables.deleteTitle'),
    message: t('nests.variables.deleteMsg', { name: v.name, env: v.env_variable }),
    variant: 'danger',
    confirmText: t('common.btn.delete'),
  })
  if (!ok) return
  try {
    const res = await deleteEggVariable(egg.value.id, v.id)
    setAffectedPlans(res.affected_plans)
    if (res.affected_plans.length > 0) {
      toast(t('nests.egg.savedWithPlanWarnings', { n: res.affected_plans.length }), 'warning')
    } else {
      toast(t('nests.variables.deleted', { env: v.env_variable }), 'success')
    }
    await reloadEgg()
  } catch (err) {
    toast(apiErrorMessage(err), 'error')
  }
}
</script>

<template>
  <div v-if="egg" class="vars-pane">
    <PageHeaderActions>
      <BaseButton size="sm" variant="primary" @click="openCreate">
        <MsIcon name="add" size="xs" />{{ t('nests.variables.addBtn') }}
      </BaseButton>
    </PageHeaderActions>

    <SectionToolbar>
      <template #start>
        <div class="tb-search-row">
          <FilterInput
            v-model="searchTerm"
            :placeholder="t('nests.variables.searchPlaceholder')"
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
          {{ t('nests.variables.totalCount', { n: filteredVariables.length }) }}
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

    <DataTable
      :items="paginated"
      :page="page"
      :total-pages="totalPages"
      :per-page="perPage"
      :per-page-label="t('nests.perPage')"
      empty-icon="tune"
      :empty-text="t('nests.variables.empty')"
      row-key="id"
      @update:page="page = $event"
      @update:per-page="setPerPage"
    >
      <template #header>
        <SortTh class="col-name" col="name" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('nests.variables.columns.name') }}</SortTh>
        <SortTh class="col-env" col="env_variable" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('nests.variables.columns.envVariable') }}</SortTh>
        <SortTh class="col-default" col="default_value" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('nests.variables.columns.defaultValue') }}</SortTh>
        <th class="col-rules">{{ t('nests.variables.columns.rules') }}</th>
        <SortTh class="col-perms" col="permissions" :sort-by="sortBy" :sort-order="sortOrder" @sort="toggleSort">{{ t('nests.variables.columns.permissions') }}</SortTh>
        <th class="col-actions">{{ t('nests.variables.columns.actions') }}</th>
      </template>

      <template #row="{ item: v }">
        <td class="col-name">
          <div class="name-main">{{ v.name }}</div>
          <div v-if="v.description" class="name-sub" :title="v.description">{{ v.description }}</div>
        </td>
        <td class="col-env"><code>{{ v.env_variable }}</code></td>
        <td class="col-default">
          <code v-if="v.default_value !== ''" class="code-ellipsis" :title="v.default_value">{{ v.default_value }}</code>
          <span v-else class="muted-text">—</span>
        </td>
        <td class="col-rules">
          <code class="code-ellipsis" :title="v.rules">{{ v.rules }}</code>
        </td>
        <td class="col-perms">
          <div class="perm-badges">
            <Badge size="sm" :color="v.user_viewable ? 'var(--ac)' : 'var(--t3)'">
              {{ v.user_viewable ? t('nests.variables.badges.viewable') : t('nests.variables.badges.hidden') }}
            </Badge>
            <Badge size="sm" :color="v.user_editable ? 'var(--green)' : 'var(--t3)'">
              {{ v.user_editable ? t('nests.variables.badges.editable') : t('nests.variables.badges.readOnly') }}
            </Badge>
          </div>
        </td>
        <td class="col-actions">
          <div class="action-group">
            <BaseButton size="sm" @click="openEdit(v)">
              <MsIcon name="edit" size="xs" /> {{ t('common.btn.edit') }}
            </BaseButton>
            <BaseButton size="sm" variant="danger" @click="removeVar(v)">
              <MsIcon name="delete" size="xs" /> {{ t('common.btn.delete') }}
            </BaseButton>
          </div>
        </td>
      </template>

      <template #card="{ item: v }">
        <CardTap @tap="openMobileAction(v)">
          <div class="card-row--main">
            <span class="card-name">{{ v.name }}</span>
            <div class="perm-badges">
              <Badge size="sm" :color="v.user_viewable ? 'var(--ac)' : 'var(--t3)'">
                {{ v.user_viewable ? t('nests.variables.badges.viewable') : t('nests.variables.badges.hidden') }}
              </Badge>
              <Badge size="sm" :color="v.user_editable ? 'var(--green)' : 'var(--t3)'">
                {{ v.user_editable ? t('nests.variables.badges.editable') : t('nests.variables.badges.readOnly') }}
              </Badge>
            </div>
          </div>
          <div v-if="v.description" class="card-row--sub">{{ v.description }}</div>
          <div class="card-detail">
            <CardKV :label="t('nests.variables.columns.envVariable')">
              <code>{{ v.env_variable }}</code>
            </CardKV>
            <CardKV :label="t('nests.variables.columns.defaultValue')">
              <code v-if="v.default_value !== ''">{{ v.default_value }}</code>
              <span v-else class="muted-text">—</span>
            </CardKV>
            <CardKV :label="t('nests.variables.columns.rules')">
              <code>{{ v.rules }}</code>
            </CardKV>
          </div>
        </CardTap>
      </template>
    </DataTable>

    <ActionSheet v-model="mobileActionOpen" :title="mobileActionVar?.name">
      <template v-if="mobileActionVar" #info>
        <code>{{ mobileActionVar.env_variable }}</code>
      </template>
      <template v-if="mobileActionVar">
        <button @click="mobileActionOpen = false; openEdit(mobileActionVar!)">
          <MsIcon name="edit" size="sm" /> {{ t('common.btn.edit') }}
        </button>
        <button
          class="action-sheet--danger"
          @click="mobileActionOpen = false; removeVar(mobileActionVar!)"
        >
          <MsIcon name="delete" size="sm" /> {{ t('common.btn.delete') }}
        </button>
      </template>
    </ActionSheet>

    <BaseModal
      v-model="modalOpen"
      :title="editingVar ? t('nests.variables.editTitle') : t('nests.variables.createTitle')"
      icon="tune"
      size="md"
    >
      <div class="var-form">
        <div class="grid-2">
          <FormField :label="t('nests.variables.fields.name')" required density="compact">
            <BaseInput v-model="form.name" maxlength="191" />
          </FormField>

          <FormField
            :error="envVarError || undefined"
            required
            density="compact"
          >
            <template #label>
              {{ t('nests.variables.fields.envVariable') }}
              <HelpTip :text="t('nests.variables.tips.reserved', { list: reservedListStr })" />
            </template>
            <BaseInput v-model="form.env_variable" placeholder="SERVER_JARFILE" maxlength="191" />
          </FormField>
        </div>

        <FormField :label="t('nests.variables.fields.description')" density="compact">
          <BaseTextarea v-model="form.description" :rows="2" />
        </FormField>

        <div class="grid-2">
          <FormField :label="t('nests.variables.fields.defaultValue')" density="compact">
            <BaseInput v-model="form.default_value" />
          </FormField>

          <FormField required density="compact">
            <template #label>
              {{ t('nests.variables.fields.rules') }}
              <HelpTip :text="t('nests.variables.tips.rules')" />
            </template>
            <BaseInput v-model="form.rules" placeholder="required|string|max:191" />
          </FormField>
        </div>

        <div class="toggle-stack">
          <FormField
            :label="t('nests.variables.fields.userViewable')"
            layout="horizontal"
            keep-horizontal
            control-fit
            bordered
            density="compact"
          >
            <ToggleSwitch v-model="form.user_viewable" size="sm" />
          </FormField>

          <FormField
            :label="t('nests.variables.fields.userEditable')"
            layout="horizontal"
            keep-horizontal
            control-fit
            bordered
            density="compact"
          >
            <ToggleSwitch v-model="form.user_editable" size="sm" />
          </FormField>
        </div>
      </div>

      <template #footer>
        <BaseButton variant="default" :disabled="saving" @click="modalOpen = false">
          {{ t('common.btn.cancel') }}
        </BaseButton>
        <BaseButton variant="primary" :loading="saving" :disabled="!canSubmit" @click="submit">
          {{ editingVar ? t('common.btn.save') : t('common.btn.confirm') }}
        </BaseButton>
      </template>
    </BaseModal>
  </div>
</template>

<style scoped>
:deep(.dt-table)    { min-width: 960px; }
:deep(.col-name)    { width: 22%; }
:deep(.col-env)     { width: 14%; white-space: nowrap; }
:deep(.col-default) { width: 14%; }
:deep(.col-rules)   { width: 18%; }
:deep(.col-perms)   { width: 16%; white-space: nowrap; }
:deep(.col-actions) { width: 16%; }

code {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  background: var(--bg-in);
  padding: 2px 6px;
  border-radius: var(--r-xs);
  color: var(--t1);
}
.code-ellipsis {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
}
.name-main {
  color: var(--t1);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
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
.muted-text {
  color: var(--t3);
}
.perm-badges {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-1);
  flex-wrap: wrap;
}
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
.card-row--main .perm-badges {
  flex-shrink: 0;
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
  font-size: var(--text-xs);
  color: var(--t3);
}
.card-detail {
  display: flex;
  gap: var(--sp-4);
  margin-top: var(--sp-2);
  flex-wrap: wrap;
}

.var-form {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.toggle-stack {
  display: flex;
  flex-direction: column;
}
.grid-2 {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: var(--sp-3);
}
@media (max-width: 680px) {
  .grid-2 {
    grid-template-columns: 1fr;
  }
}
</style>
