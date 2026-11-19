<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { apiErrorMessage } from '@/composables/apiClient'
import { useToast } from '@/composables/useToast'
import {
  createNode,
  listLocations,
  type LocationOut,
  type NodeCreateIn,
  type NodeOut,
} from '@/api/adminNodesLocations'
import BaseModal from '@/components/ui/BaseModal.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import TabSwitcher from '@/components/ui/TabSwitcher.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import NumberInput from '@/components/form/NumberInput.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import FormField from '@/components/form/FormField.vue'
import ToggleSwitch from '@/components/ui/ToggleSwitch.vue'
import HelpTip from '@/components/ui/HelpTip.vue'
import AlertBanner from '@/components/ui/AlertBanner.vue'
import MsIcon from '@/components/ui/MsIcon.vue'

defineOptions({ name: 'NodeCreateModal' })

const props = defineProps<{
  modelValue: boolean
  zIndex?: number
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  created: [node: NodeOut]
  createLocation: []
}>()

const { t } = useI18n({ useScope: 'global' })
const { toast } = useToast()

const locations = ref<LocationOut[]>([])
const loadingLocations = ref(false)
const submitting = ref(false)
const activeTab = ref<'basic' | 'resources'>('basic')

const tabs = computed(() => [
  { key: 'basic', icon: 'dns', label: t('hosts.nodes.create.tabBasic') },
  { key: 'resources', icon: 'tune', label: t('hosts.nodes.create.tabResources') },
])

interface FormState {
  name: string
  description: string
  location_id: number | null
  fqdn: string
  scheme: 'http' | 'https'
  public: boolean
  behind_proxy: boolean
  maintenance_mode: boolean
  memory: number
  memory_overallocate: number
  disk: number
  disk_overallocate: number
  upload_size: number
  daemon_listen: number
  daemon_sftp: number
  daemon_base: string
}

function defaultForm(): FormState {
  return {
    name: '',
    description: '',
    location_id: null,
    fqdn: '',
    scheme: 'https',
    public: true,
    behind_proxy: false,
    maintenance_mode: false,
    memory: 8192,
    memory_overallocate: 0,
    disk: 51200,
    disk_overallocate: 0,
    upload_size: 100,
    daemon_listen: 8080,
    daemon_sftp: 2022,
    daemon_base: '/var/lib/pterodactyl/volumes',
  }
}

const form = ref<FormState>(defaultForm())

async function loadLocations() {
  loadingLocations.value = true
  try {
    const res = await listLocations()
    locations.value = res.locations
    if (form.value.location_id == null && locations.value.length > 0) {
      form.value.location_id = locations.value[0]!.id
    }
  } catch (err) {
    toast(apiErrorMessage(err), 'error')
  } finally {
    loadingLocations.value = false
  }
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      activeTab.value = 'basic'
      form.value = defaultForm()
      void loadLocations()
    }
  },
)

const locationOptions = computed(() =>
  locations.value.map(loc => ({
    value: loc.id,
    label: loc.long ? `${loc.short} — ${loc.long}` : loc.short,
  })),
)

const schemeOptions = [
  { value: 'https', label: 'https' },
  { value: 'http', label: 'http' },
]

const IPV4_RE = /^\d{1,3}(\.\d{1,3}){3}$/
const looksLikeBareIp = computed(() => {
  const s = form.value.fqdn.trim().replace(/^\[|\]$/g, '')
  return IPV4_RE.test(s) || (s.includes(':') && /^[0-9a-fA-F:]+$/.test(s))
})

const httpsBareIpError = computed(() =>
  form.value.scheme === 'https' && !form.value.behind_proxy && looksLikeBareIp.value
    ? t('hosts.nodes.create.httpsBareIpError')
    : '',
)

const canSubmit = computed(() => {
  const f = form.value
  if (!f.name.trim()) return false
  if (!f.location_id) return false
  if (!f.fqdn.trim()) return false
  if (httpsBareIpError.value) return false
  if (f.memory < 1 || f.disk < 1 || f.upload_size < 1) return false
  if (f.daemon_listen < 1 || f.daemon_listen > 65535) return false
  if (f.daemon_sftp < 1 || f.daemon_sftp > 65535) return false
  if (!f.daemon_base.trim().startsWith('/')) return false
  return true
})

async function submit() {
  if (!canSubmit.value || !form.value.location_id) return
  submitting.value = true
  try {
    const payload: NodeCreateIn = {
      name: form.value.name.trim(),
      description: form.value.description.trim() || null,
      location_id: form.value.location_id,
      fqdn: form.value.fqdn.trim(),
      scheme: form.value.scheme,
      public: form.value.public,
      behind_proxy: form.value.behind_proxy,
      maintenance_mode: form.value.maintenance_mode,
      memory: form.value.memory,
      memory_overallocate: form.value.memory_overallocate,
      disk: form.value.disk,
      disk_overallocate: form.value.disk_overallocate,
      upload_size: form.value.upload_size,
      daemon_listen: form.value.daemon_listen,
      daemon_sftp: form.value.daemon_sftp,
      daemon_base: form.value.daemon_base.trim(),
    }
    const created = await createNode(payload)
    toast(t('hosts.nodes.create.created', { name: created.name }), 'success')
    emit('created', created)
    emit('update:modelValue', false)
  } catch (err) {
    toast(apiErrorMessage(err), 'error')
  } finally {
    submitting.value = false
  }
}

defineExpose({ reloadLocations: loadLocations })
</script>

<template>
  <BaseModal
    :model-value="modelValue"
    @update:model-value="emit('update:modelValue', $event)"
    :title="t('hosts.nodes.create.title')"
    icon="dns"
    size="lg"
    :z-index="zIndex"
  >
    <div class="node-editor">
      <TabSwitcher v-model="activeTab" :tabs="tabs" />

      <AlertBanner v-if="!loadingLocations && locations.length === 0" tone="warning" dense>
        <div class="no-loc-row">
          <span>{{ t('hosts.nodes.create.noLocations') }}</span>
          <BaseButton size="sm" variant="primary" @click="emit('createLocation')">
            <MsIcon name="add" size="xs" />{{ t('hosts.locations.addBtn') }}
          </BaseButton>
        </div>
      </AlertBanner>

      <div v-show="activeTab === 'basic'" class="tab-pane">
        <div class="grid-2">
          <FormField :label="t('hosts.setting.wings.fields.name')" required density="compact">
            <BaseInput v-model="form.name" :placeholder="t('hosts.nodes.create.namePlaceholder')" />
          </FormField>

          <FormField :label="t('hosts.nodes.fields.location')" required density="compact">
            <div class="inline-control">
              <BaseSelect
                teleport
                :options="locationOptions"
                :placeholder="t('hosts.nodes.create.selectLocation')"
                :model-value="form.location_id ?? ''"
                @update:model-value="(v: any) => form.location_id = v === '' || v == null ? null : Number(v)"
              />
              <BaseButton
                size="sm"
                variant="ghost"
                square
                :title="t('hosts.locations.addBtn')"
                @click="emit('createLocation')"
              >
                <MsIcon name="add" size="xs" />
              </BaseButton>
            </div>
          </FormField>
        </div>

        <FormField :label="t('hosts.setting.wings.fields.description')" density="compact">
          <BaseInput v-model="form.description" :placeholder="t('hosts.nodes.create.descPlaceholder')" />
        </FormField>

        <div class="grid-2">
          <FormField
            :label="t('hosts.setting.wings.fields.fqdn')"
            :error="httpsBareIpError || undefined"
            required
            density="compact"
          >
            <BaseInput v-model="form.fqdn" placeholder="node1.example.com" />
          </FormField>

          <FormField :label="t('hosts.setting.wings.fields.scheme')" density="compact">
            <BaseSelect
              teleport
              :options="schemeOptions"
              :model-value="form.scheme"
              @update:model-value="(v: any) => form.scheme = v"
            />
          </FormField>
        </div>

        <div class="toggle-stack">
          <FormField layout="horizontal" keep-horizontal control-fit bordered density="compact">
            <template #label>
              {{ t('hosts.nodes.fields.public') }}
              <HelpTip :text="t('hosts.nodes.tips.public')" />
            </template>
            <ToggleSwitch v-model="form.public" size="sm" />
          </FormField>

          <FormField layout="horizontal" keep-horizontal control-fit bordered density="compact">
            <template #label>
              {{ t('hosts.setting.wings.fields.behindProxy') }}
              <HelpTip :text="t('hosts.setting.wings.tips.behindProxy')" />
            </template>
            <ToggleSwitch v-model="form.behind_proxy" size="sm" />
          </FormField>

          <FormField layout="horizontal" keep-horizontal control-fit bordered density="compact">
            <template #label>
              {{ t('hosts.setting.wings.fields.maintenance') }}
            </template>
            <ToggleSwitch v-model="form.maintenance_mode" size="sm" />
          </FormField>
        </div>
      </div>

      <div v-show="activeTab === 'resources'" class="tab-pane">
        <div class="grid-2">
          <FormField :label="t('hosts.setting.wings.fields.memory')" required density="compact">
            <NumberInput v-model="form.memory" :min="1" />
          </FormField>
          <FormField density="compact">
            <template #label>
              {{ t('hosts.setting.wings.fields.memoryOver') }}
              <HelpTip :text="t('hosts.setting.wings.tips.overallocate')" />
            </template>
            <NumberInput v-model="form.memory_overallocate" :min="-1" />
          </FormField>
        </div>

        <div class="grid-2">
          <FormField :label="t('hosts.setting.wings.fields.disk')" required density="compact">
            <NumberInput v-model="form.disk" :min="1" />
          </FormField>
          <FormField density="compact">
            <template #label>
              {{ t('hosts.setting.wings.fields.diskOver') }}
              <HelpTip :text="t('hosts.setting.wings.tips.overallocate')" />
            </template>
            <NumberInput v-model="form.disk_overallocate" :min="-1" />
          </FormField>
        </div>

        <div class="grid-3">
          <FormField :label="t('hosts.setting.wings.fields.uploadSize')" required density="compact">
            <NumberInput v-model="form.upload_size" :min="1" :max="1048576" />
          </FormField>
          <FormField :label="t('hosts.setting.wings.fields.daemonListen')" required density="compact">
            <NumberInput v-model="form.daemon_listen" :min="1" :max="65535" />
          </FormField>
          <FormField :label="t('hosts.setting.wings.fields.daemonSftp')" required density="compact">
            <NumberInput v-model="form.daemon_sftp" :min="1" :max="65535" />
          </FormField>
        </div>

        <FormField :label="t('hosts.setting.wings.fields.daemonBase')" required density="compact">
          <BaseInput v-model="form.daemon_base" placeholder="/var/lib/pterodactyl/volumes" />
        </FormField>
      </div>
    </div>

    <template #footer>
      <BaseButton variant="default" :disabled="submitting" @click="emit('update:modelValue', false)">
        {{ t('common.btn.cancel') }}
      </BaseButton>
      <BaseButton variant="primary" :loading="submitting" :disabled="!canSubmit" @click="submit">
        <MsIcon name="add" size="xs" />
        {{ t('hosts.nodes.create.submit') }}
      </BaseButton>
    </template>
  </BaseModal>
</template>

<style scoped>
.node-editor {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.tab-pane {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.toggle-stack {
  display: flex;
  flex-direction: column;
}
.no-loc-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  flex-wrap: wrap;
}
.inline-control {
  display: flex;
  align-items: center;
  gap: var(--sp-1);
  width: 100%;
  min-width: 0;
}
.inline-control :deep(.base-select) {
  flex: 1;
  min-width: 0;
}
.grid-2 {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: var(--sp-3);
}
.grid-3 {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--sp-3);
}
@media (max-width: 700px) {
  .grid-2,
  .grid-3 {
    grid-template-columns: 1fr;
  }
}
</style>
