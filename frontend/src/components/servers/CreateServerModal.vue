<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import BaseModal from '@/components/ui/BaseModal.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import NumberInput from '@/components/form/NumberInput.vue'
import FormField from '@/components/form/FormField.vue'
import CollapsibleGroup from '@/components/ui/CollapsibleGroup.vue'

defineOptions({ name: 'CreateServerModal' })

const props = defineProps<{
  modelValue: boolean
  preSelectUsername?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [val: boolean]
  created: []
}>()

const { t } = useI18n({ useScope: 'global' })
const { get, post } = useApiFetch()
const { toast } = useToast()

const createLoading = ref(false)

const createForm = ref({
  user_id: '' as string | number,
  server_name: '',
  plan_id: '' as string | number,
  nest_id: '' as string | number,
  egg_id: '' as string | number,
  docker_image: '',
  startup_command: '',
  node_id: '' as string | number,
  allocation_id: '' as string | number,
  cpu: 100,
  memory: 1024,
  disk: 5120,
  databases: 0,
  backups: 0,
  allocations: 1,
  expiration_days: 30,
  environment: {} as Record<string, string>,
})

// Dropdown data
const userList = ref<{ id: number; username: string; email: string }[]>([])
const nestList = ref<{ id: number; name: string }[]>([])
const eggList = ref<{ id: number; name: string; docker_image: string; startup: string }[]>([])
const nodeList = ref<{ id: number; name: string }[]>([])
const allocationList = ref<{ id: number; ip: string; port: number }[]>([])
const eggVariables = ref<{ name: string; env_variable: string; default_value: string; description: string; rules: string }[]>([])
const serverNamePrefix = ref('')

interface PlanOption {
  id: number
  display_name: string
  is_active: boolean
  nest_id: number
  egg_id: number
  node_id: number
  cpu: number
  memory_mb: number
  disk_mb: number
  database_limit: number
  backup_limit: number
  allocation_limit: number
  docker_image: string
  startup_command: string
  env_defaults: Record<string, string>
}
const planList = ref<PlanOption[]>([])

const userOptions = computed(() => userList.value.map(u => ({ value: u.id, label: `${u.username} (${u.email})` })))
const planOptions = computed(() => planList.value.map(p => ({ value: p.id, label: p.display_name })))
const nestOptions = computed(() => nestList.value.map(n => ({ value: n.id, label: n.name })))
const eggOptions = computed(() => eggList.value.map(e => ({ value: e.id, label: e.name })))
const nodeOptions = computed(() => nodeList.value.map(n => ({ value: n.id, label: n.name })))
const allocationOptions = computed(() => allocationList.value.map(a => ({ value: a.id, label: `${a.ip}:${a.port}` })))

// Load eggs when nest changes.
// Increment a per-watcher request token before each load and only commit the
// result if the token still matches when the response arrives. This prevents
// a slow earlier request (eg. nest A) from clobbering a later one (nest B)
// when the user clicks rapidly. (Audit FM7.)
let eggReqSeq = 0
watch(() => createForm.value.nest_id, async (nestId) => {
  const seq = ++eggReqSeq
  eggList.value = []
  eggVariables.value = []
  createForm.value.egg_id = ''
  createForm.value.startup_command = ''
  if (!nestId) return
  const data = await get<{ eggs: any[] }>(`/api/admin/resources/nests/${nestId}/eggs`)
  if (seq !== eggReqSeq) return
  if (data) eggList.value = data.eggs
})

// Load egg details when egg changes (also guarded against stale responses).
let varReqSeq = 0
watch(() => createForm.value.egg_id, async (eggId) => {
  const seq = ++varReqSeq
  eggVariables.value = []
  if (!eggId || !createForm.value.nest_id) return
  const egg = eggList.value.find(e => e.id === eggId)
  if (egg) {
    if (egg.docker_image) createForm.value.docker_image = egg.docker_image
    if (egg.startup) createForm.value.startup_command = egg.startup
  }
  const data = await get<{ variables: any[] }>(`/api/admin/resources/nests/${createForm.value.nest_id}/eggs/${eggId}/variables`)
  if (seq !== varReqSeq) return
  if (data) {
    eggVariables.value = data.variables
    const env: Record<string, string> = {}
    for (const v of data.variables) {
      env[v.env_variable] = v.default_value || ''
    }
    createForm.value.environment = env
  }
})

// Load allocations when node changes (stale-response guard).
let allocReqSeq = 0
watch(() => createForm.value.node_id, async (nodeId) => {
  const seq = ++allocReqSeq
  allocationList.value = []
  createForm.value.allocation_id = ''
  if (!nodeId) return
  const data = await get<{ allocations: any[] }>(`/api/admin/resources/nodes/${nodeId}/allocations`)
  if (seq !== allocReqSeq) return
  if (data) {
    allocationList.value = data.allocations
    if (data.allocations.length > 0) {
      const sorted = [...data.allocations].sort((a: any, b: any) => a.port - b.port)
      createForm.value.allocation_id = sorted[0].id
    }
  }
})

// Auto-fill server name when user changes
watch(() => createForm.value.user_id, (userId) => {
  if (!userId) return
  const user = userList.value.find(u => u.id === userId)
  if (user) {
    const prefix = serverNamePrefix.value
    createForm.value.server_name = prefix ? `${prefix}-${user.username}` : user.username
  }
})

// Plan selection → cascade values into the form. egg_id needs the eggList
// to be loaded for the chosen nest first, so we wait for the nest watcher to
// finish and then assign egg_id (which itself triggers the egg watcher to
// load variables — we override env_defaults afterwards).
async function applyPlan(plan: PlanOption) {
  createForm.value.docker_image = plan.docker_image
  createForm.value.startup_command = plan.startup_command
  createForm.value.cpu = plan.cpu
  createForm.value.memory = plan.memory_mb
  createForm.value.disk = plan.disk_mb
  createForm.value.databases = plan.database_limit
  createForm.value.backups = plan.backup_limit
  createForm.value.allocations = plan.allocation_limit
  createForm.value.node_id = plan.node_id
  createForm.value.nest_id = plan.nest_id
  // Wait for egg list to populate, then pick egg.
  const seq = ++planEggWaitSeq
  const waitForEggs = (tries: number) => {
    if (seq !== planEggWaitSeq) return
    if (eggList.value.some(e => e.id === plan.egg_id)) {
      createForm.value.egg_id = plan.egg_id
      // Restore startup/docker/env after the egg watcher completes its own
      // overrides (it runs after egg_id assignment + variable fetch).
      const seq2 = ++planEnvWaitSeq
      const restore = (tries2: number) => {
        if (seq2 !== planEnvWaitSeq) return
        if (eggVariables.value.length > 0 || tries2 > 30) {
          createForm.value.docker_image = plan.docker_image
          createForm.value.startup_command = plan.startup_command
          const env: Record<string, string> = { ...createForm.value.environment }
          for (const [k, v] of Object.entries(plan.env_defaults || {})) {
            env[k] = String(v)
          }
          createForm.value.environment = env
          return
        }
        setTimeout(() => restore(tries2 + 1), 100)
      }
      setTimeout(() => restore(0), 150)
      return
    }
    if (tries > 50) return
    setTimeout(() => waitForEggs(tries + 1), 100)
  }
  setTimeout(() => waitForEggs(0), 50)
}

let planEggWaitSeq = 0
let planEnvWaitSeq = 0
watch(() => createForm.value.plan_id, (planId) => {
  if (!planId) return
  const plan = planList.value.find(p => p.id === planId)
  if (plan) applyPlan(plan)
})

// Open modal → reset & load dropdown data
watch(() => props.modelValue, async (open) => {
  if (!open) return
  // Reset form
  createForm.value = {
    user_id: '',
    server_name: '',
    plan_id: '',
    nest_id: '',
    egg_id: '',
    docker_image: '',
    startup_command: '',
    node_id: '',
    allocation_id: '',
    cpu: 100,
    memory: 1024,
    disk: 5120,
    databases: 0,
    backups: 0,
    allocations: 1,
    expiration_days: 30,
    environment: {},
  }
  eggList.value = []
  allocationList.value = []
  eggVariables.value = []

  // Load dropdown data in parallel
  const [usersData, nestsData, nodesData, defaultsData, plansData] = await Promise.all([
    get<{ users: any[] }>('/api/admin/resources/users'),
    get<{ nests: any[] }>('/api/admin/resources/nests'),
    get<{ nodes: any[] }>('/api/admin/resources/nodes'),
    get<Record<string, any>>('/api/admin/resources/server-defaults'),
    get<PlanOption[]>('/api/admin/billing/plans?include_inactive=false'),
  ])
  if (usersData) userList.value = usersData.users
  if (nestsData) nestList.value = nestsData.nests
  if (nodesData) nodeList.value = nodesData.nodes
  if (plansData) {
    planList.value = (plansData as PlanOption[]).filter(p => p.is_active !== false)
    // 默认选中第一个套餐（会触发 watcher 自动套用）
    if (planList.value.length > 0 && !createForm.value.plan_id) {
      createForm.value.plan_id = planList.value[0].id
    }
  }
  if (defaultsData) {
    createForm.value.cpu = defaultsData.cpu
    createForm.value.memory = defaultsData.memory
    createForm.value.disk = defaultsData.disk
    createForm.value.databases = defaultsData.databases
    createForm.value.backups = defaultsData.backups
    createForm.value.allocations = defaultsData.allocations
    createForm.value.docker_image = defaultsData.docker_image
    serverNamePrefix.value = defaultsData.server_name_prefix || ''
    if (defaultsData.nest_id) createForm.value.nest_id = defaultsData.nest_id
    if (defaultsData.node_id) createForm.value.node_id = defaultsData.node_id
    if (defaultsData.egg_id) {
      const waitEgg = () => {
        if (eggList.value.length > 0) {
          createForm.value.egg_id = defaultsData.egg_id
        } else {
          setTimeout(waitEgg, 100)
        }
      }
      setTimeout(waitEgg, 100)
    }
  }

  // Pre-select user if specified
  if (props.preSelectUsername) {
    const user = userList.value.find(u => u.username === props.preSelectUsername)
    if (user) createForm.value.user_id = user.id
  }
})

async function doCreateServer() {
  const f = createForm.value
  if (!f.user_id || !f.server_name || !f.egg_id || !f.startup_command || !f.node_id || !f.allocation_id) {
    toast(t('servers.create.validation.requiredFields'), 'error')
    return
  }
  createLoading.value = true
  const res = await post<{ message: string }>('/api/admin/servers', {
    user_id: Number(f.user_id),
    server_name: f.server_name,
    egg_id: Number(f.egg_id),
    docker_image: f.docker_image,
    startup_command: f.startup_command,
    node_id: Number(f.node_id),
    allocation_id: Number(f.allocation_id),
    environment: f.environment,
    cpu: f.cpu,
    memory: f.memory,
    disk: f.disk,
    databases: f.databases,
    backups: f.backups,
    allocations: f.allocations,
    expiration_days: f.expiration_days,
    plan_id: f.plan_id ? Number(f.plan_id) : null,
  })
  createLoading.value = false
  if (res) {
    toast(t('servers.create.success'), 'success')
    emit('update:modelValue', false)
    emit('created')
  }
}

function close() {
  emit('update:modelValue', false)
}
</script>

<template>
  <BaseModal :model-value="modelValue" @update:model-value="$emit('update:modelValue', $event)" :title="t('servers.create.title')" icon="add" size="xl" scroll="body">
    <div class="create-form">
      <!-- Plan + Owner -->
      <div class="create-row">
        <FormField :label="t('servers.create.plan')" density="compact" class="create-col">
          <BaseSelect
            v-model="createForm.plan_id"
            :options="planOptions"
            :placeholder="t('servers.create.plan_placeholder')"
            searchable
          />
        </FormField>
        <FormField :label="t('servers.create.user')" required density="compact" class="create-col">
          <BaseSelect v-model="createForm.user_id" :options="userOptions" :placeholder="t('servers.create.user_placeholder')" searchable />
        </FormField>
      </div>

      <!-- Name + Expiration -->
      <div class="create-row">
        <FormField :label="t('servers.create.server_name')" required density="compact" class="create-col">
          <BaseInput v-model="createForm.server_name" :placeholder="t('servers.create.server_name_placeholder')" />
        </FormField>
        <FormField :label="t('servers.create.expiration_days')" required density="compact" class="create-col">
          <NumberInput v-model="createForm.expiration_days" :min="1" :max="3650" />
        </FormField>
      </div>

      <!-- Node & Port -->
      <div class="create-row">
        <FormField :label="t('servers.create.node')" required density="compact" class="create-col">
          <BaseSelect v-model="createForm.node_id" :options="nodeOptions" :placeholder="t('servers.create.node_placeholder')" />
        </FormField>
        <FormField :label="t('servers.create.allocation')" required density="compact" class="create-col" :hint="!createForm.node_id ? t('servers.create.allocation_hint') : undefined">
          <BaseSelect v-model="createForm.allocation_id" :options="allocationOptions" :placeholder="allocationList.length === 0 && createForm.node_id ? t('servers.create.no_allocations') : t('servers.create.allocation_placeholder')" :disabled="!createForm.node_id" searchable />
        </FormField>
      </div>

      <!-- Preset & Image -->
      <CollapsibleGroup :title="t('servers.create.section_image')" icon="tune" :default-open="true">
        <div class="create-row">
          <FormField :label="t('servers.create.nest')" required density="compact" class="create-col">
            <BaseSelect v-model="createForm.nest_id" :options="nestOptions" :placeholder="t('servers.create.nest_placeholder')" />
          </FormField>
          <FormField :label="t('servers.create.egg')" required density="compact" class="create-col" :hint="!createForm.nest_id ? t('servers.create.egg_hint') : undefined">
            <BaseSelect v-model="createForm.egg_id" :options="eggOptions" :placeholder="t('servers.create.egg_placeholder')" :disabled="!createForm.nest_id" />
          </FormField>
        </div>
        <FormField :label="t('servers.create.docker_image')" density="compact">
          <BaseInput v-model="createForm.docker_image" mono />
        </FormField>
        <FormField :label="t('servers.create.startup_command')" required density="compact">
          <BaseInput v-model="createForm.startup_command" mono />
        </FormField>
      </CollapsibleGroup>

      <!-- Resources -->
      <CollapsibleGroup :title="t('servers.create.section_resources')" icon="memory" :default-open="false">
        <div class="create-row create-row--3">
          <FormField :label="t('servers.create.cpu')" density="compact" class="create-col">
            <NumberInput v-model="createForm.cpu" :min="0" :max="10000" :step="10" />
          </FormField>
          <FormField :label="t('servers.create.memory')" density="compact" class="create-col">
            <NumberInput v-model="createForm.memory" :min="0" :max="1048576" :step="128" />
          </FormField>
          <FormField :label="t('servers.create.disk')" density="compact" class="create-col">
            <NumberInput v-model="createForm.disk" :min="0" :max="1048576" :step="512" />
          </FormField>
        </div>
        <div class="create-row create-row--3">
          <FormField :label="t('servers.create.databases')" density="compact" class="create-col">
            <NumberInput v-model="createForm.databases" :min="0" :max="100" />
          </FormField>
          <FormField :label="t('servers.create.backups')" density="compact" class="create-col">
            <NumberInput v-model="createForm.backups" :min="0" :max="100" />
          </FormField>
          <FormField :label="t('servers.create.extra_allocations')" density="compact" class="create-col">
            <NumberInput v-model="createForm.allocations" :min="0" :max="100" />
          </FormField>
        </div>
      </CollapsibleGroup>

      <!-- Egg Environment Variables -->
      <CollapsibleGroup v-if="eggVariables.length > 0" :title="t('servers.create.section_env')" icon="terminal" :default-open="false" :count="eggVariables.length">
        <FormField v-for="v in eggVariables" :key="v.env_variable" :label="v.name" :hint="v.description" density="compact">
          <BaseInput v-model="createForm.environment[v.env_variable]" mono />
        </FormField>
      </CollapsibleGroup>
    </div>

    <template #footer>
      <BaseButton @click="close">{{ t('common.btn.cancel') }}</BaseButton>
      <BaseButton variant="primary" :loading="createLoading" @click="doCreateServer">
        {{ createLoading ? t('servers.create.creating') : t('common.btn.confirm') }}
      </BaseButton>
    </template>
  </BaseModal>
</template>

<style scoped>
.create-form {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  min-width: 0;
}
.create-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 var(--sp-3);
  min-width: 0;
}
.create-row--3 {
  grid-template-columns: 1fr 1fr 1fr;
}
/* Lock each grid cell to its track width — prevent intrinsic content (long
   select option labels) from pushing the sibling column. */
.create-row > .create-col,
.create-row--3 > .create-col {
  min-width: 0;
}
@media (max-width: 768px) {
  .create-row,
  .create-row--3 {
    grid-template-columns: 1fr;
  }
}
</style>
