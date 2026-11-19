<script setup lang="ts">
// C4 — Create Host modal.
// Minimal create flow; edit lives on the detail page's settings tab.
// Workflow: user fills form → POST /api/admin/hosts. Backend probes
// the agent BEFORE committing; failure returns 400 and we surface the
// detail. On success, if backend generated a token we forward it to
// HostTokenRevealModal (one-time disclosure). Parent is notified via
// `@created` so the list can refresh.
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import BaseModal from '@/components/ui/BaseModal.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import FormField from '@/components/form/FormField.vue'
import ToggleSwitch from '@/components/ui/ToggleSwitch.vue'
import HelpTip from '@/components/ui/HelpTip.vue'
import AlertBanner from '@/components/ui/AlertBanner.vue'
import SecretInput from '@/components/ui/SecretInput.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import HostTokenRevealModal from '@/components/hosts/HostTokenRevealModal.vue'

defineOptions({ name: 'HostCreateModal' })

export interface PresetNodeInfo {
  id: number
  name: string
  fqdn: string
}

const props = defineProps<{
  modelValue: boolean
  /** Pterodactyl node IDs already bound to an existing host — rendered
   *  as disabled options to prevent duplicate assignment. */
  usedNodeIds?: number[]
  presetNode?: PresetNodeInfo | null
}>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  'created': [hostId: number]
}>()

const { t } = useI18n({ useScope: 'global' })
const { get, post } = useApiFetch()
const { toast } = useToast()

interface FormState {
  name: string
  kind: string
  hostname: string
  agent_url: string
  agent_token: string
  pterodactyl_node_id: number | null
  enabled: boolean
}

function blankForm(): FormState {
  return {
    name: '',
    kind: 'wings_node',
    hostname: '',
    agent_url: '',
    agent_token: '',
    pterodactyl_node_id: null,
    enabled: true,
  }
}

const form = ref<FormState>(blankForm())
const submitting = ref(false)
const revealOpen = ref(false)
const revealToken = ref('')
const createdHostName = ref('')

// ── Panel nodes (only needed for wings_node kind) ──
interface NodeOption { id: number; name: string }
const nodes = ref<NodeOption[]>([])
const nodesLoaded = ref(false)
async function loadNodes() {
  const r = await get<{ nodes: NodeOption[] }>('/api/admin/resources/nodes')
  if (r) {
    nodes.value = r.nodes || []
    nodesLoaded.value = true
  }
}

// ── Kind options ──
const kindOptions = computed(() => [
  { value: 'wings_node', label: t('hosts.kind.wings_node') },
  { value: 'generic_linux', label: t('hosts.kind.generic_linux') },
])

const nodeOptions = computed(() => {
  const used = new Set(props.usedNodeIds || [])
  return nodes.value.map(n => ({
    value: n.id,
    label: `${n.name} (#${n.id})`,
    disabled: used.has(n.id),
  }))
})

const hasAvailableNodes = computed(() =>
  nodeOptions.value.some(opt => !opt.disabled),
)

const isWings = computed(() => form.value.kind === 'wings_node')

watch(isWings, (now) => {
  if (!now) form.value.pterodactyl_node_id = null
})

// ── Validation ──
const canSubmit = computed(() => {
  const f = form.value
  if (!f.name.trim()) return false
  if (!f.hostname.trim()) return false
  if (!f.agent_url.trim()) return false
  if (isWings.value && f.pterodactyl_node_id == null) return false
  return true
})

// ── Lifecycle ──
watch(() => props.modelValue, (open) => {
  if (open) {
    form.value = blankForm()
    if (props.presetNode) {
      form.value.kind = 'wings_node'
      form.value.pterodactyl_node_id = props.presetNode.id
      form.value.name = props.presetNode.name
      form.value.hostname = props.presetNode.fqdn
    }
    void loadNodes()
  }
})

// ── Actions ──
async function submit() {
  if (!canSubmit.value) return
  submitting.value = true
  try {
    const body: Record<string, unknown> = {
      name: form.value.name.trim(),
      kind: form.value.kind,
      hostname: form.value.hostname.trim(),
      agent_url: form.value.agent_url.trim(),
      enabled: form.value.enabled,
    }
    if (form.value.agent_token) body.agent_token = form.value.agent_token
    if (isWings.value) body.pterodactyl_node_id = form.value.pterodactyl_node_id

    const res = await post<{
      host: { id: number }
      generated_agent_token: string | null
    }>('/api/admin/hosts', body)

    if (!res) return

    toast(t('hosts.create.created'), 'success')
    if (res.generated_agent_token) {
      revealToken.value = res.generated_agent_token
      createdHostName.value = form.value.name
      revealOpen.value = true
    }
    emit('created', res.host.id)
    emit('update:modelValue', false)
  } catch (err: any) {
    toast(err?.message || t('hosts.create.createFailed'), 'error')
  } finally {
    submitting.value = false
  }
}

function cancel() {
  emit('update:modelValue', false)
}

function onTokenCopied() {
  toast(t('hosts.tokenReveal.copied'), 'success')
}
</script>

<template>
  <BaseModal
    :modelValue="modelValue"
    @update:modelValue="emit('update:modelValue', $event)"
    :title="t('hosts.create.title')"
    icon="add_circle"
    size="md"
  >
    <div class="form-grid">
      <FormField layout="horizontal" keep-horizontal control-fit bordered>
        <template #label>
          {{ t('hosts.create.fields.enabled') }}
          <HelpTip :text="t('hosts.create.fields.enabledHint')" />
        </template>
        <ToggleSwitch v-model="form.enabled" size="sm" />
      </FormField>

      <FormField layout="horizontal" bordered>
        <template #label>
          {{ t('hosts.create.fields.name') }}
          <HelpTip :text="t('hosts.create.fields.nameHint')" />
        </template>
        <BaseInput v-model="form.name" />
      </FormField>

      <FormField layout="horizontal" bordered>
        <template #label>
          {{ t('hosts.create.fields.kind') }}
          <HelpTip :text="t('hosts.create.fields.kindHint')" />
        </template>
        <BaseSelect
          teleport
          :options="kindOptions"
          v-model="form.kind"
        />
      </FormField>

      <FormField
        layout="horizontal"
        bordered
      >
        <template #label>
          {{ t('hosts.create.fields.pteroNode') }}
          <HelpTip :text="t('hosts.create.fields.pteroNodeHint')" />
        </template>
        <div class="node-select-row">
          <BaseSelect
            teleport
            :disabled="!isWings"
            :options="nodeOptions"
            :modelValue="form.pterodactyl_node_id ?? ''"
            @update:modelValue="(v: any) => form.pterodactyl_node_id = (v === '' || v == null) ? null : Number(v)"
          />
          <BaseButton
            size="sm"
            variant="ghost"
            square
            :disabled="!isWings"
            :title="t('hosts.create.refreshNodes')"
            @click="loadNodes()"
          >
            <MsIcon name="refresh" size="xs" />
          </BaseButton>
        </div>
      </FormField>

      <AlertBanner
        v-if="isWings && nodesLoaded && !hasAvailableNodes"
        tone="info"
        dense
      >
        {{ t('hosts.create.noUnboundNodesHint') }}
      </AlertBanner>

      <FormField layout="horizontal" bordered>
        <template #label>
          {{ t('hosts.create.fields.hostname') }}
          <HelpTip :text="t('hosts.create.fields.hostnameHint')" />
        </template>
        <BaseInput v-model="form.hostname" placeholder="10.0.0.22" />
      </FormField>

      <FormField layout="horizontal" bordered>
        <template #label>
          {{ t('hosts.create.fields.agentUrl') }}
          <HelpTip :text="t('hosts.create.fields.agentUrlHint')" />
        </template>
        <BaseInput v-model="form.agent_url" placeholder="http://10.0.0.22:48765" />
      </FormField>

      <FormField layout="horizontal" bordered>
        <template #label>
          {{ t('hosts.create.fields.agentToken') }}
          <HelpTip :text="t('hosts.create.fields.agentTokenHint')" />
        </template>
        <div class="token-row">
          <SecretInput
            :modelValue="form.agent_token"
            copyable
            :toggleable="false"
            :revealed="true"
            @copied="onTokenCopied"
            @update:modelValue="form.agent_token = $event"
          />
        </div>
      </FormField>
    </div>

    <template #footer>
      <BaseButton variant="default" @click="cancel" :disabled="submitting">
        {{ t('hosts.create.cancel') }}
      </BaseButton>
      <BaseButton
        variant="primary"
        :loading="submitting"
        :disabled="!canSubmit"
        @click="submit"
      >
        {{ submitting ? t('hosts.create.creating') : t('hosts.create.create') }}
      </BaseButton>
    </template>
  </BaseModal>

  <HostTokenRevealModal
    v-model="revealOpen"
    :token="revealToken"
    :info="createdHostName"
  />
</template>

<style scoped>
.form-grid {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}

.token-row {
  display: flex;
  align-items: stretch;
  gap: var(--sp-2);
  width: 100%;
  min-width: 0;
}

.token-row :deep(.secret-input) {
  flex: 1;
  min-width: 0;
}

.node-select-row {
  display: flex;
  align-items: center;
  gap: var(--sp-1);
  width: 100%;
  min-width: 0;
}

.node-select-row :deep(.base-select) {
  flex: 1;
  min-width: 0;
}
</style>
