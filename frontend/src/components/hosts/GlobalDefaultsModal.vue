<script setup lang="ts">
// C3 — Global defaults modal for host management.
// Edits the three cross-host settings that survive PR-B's per-host alert
// refactor: collection interval, retention window, default email
// recipients. Backed by GET/PUT /api/admin/global-defaults.
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import BaseModal from '@/components/ui/BaseModal.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import NumberInput from '@/components/form/NumberInput.vue'
import FormField from '@/components/form/FormField.vue'
import HelpTip from '@/components/ui/HelpTip.vue'
import Spinner from '@/components/ui/Spinner.vue'

defineOptions({ name: 'GlobalDefaultsModal' })

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()

const { t } = useI18n({ useScope: 'global' })
const { get, put } = useApiFetch()
const { toast } = useToast()

interface Defaults {
  monitor_interval_sec: number
  monitor_retention_days: number
  alert_default_recipients: number[]
}

interface AdminOption { id: number; username: string; email: string }

const loading = ref(false)
const saving = ref(false)
const values = ref<Defaults>({
  monitor_interval_sec: 60,
  monitor_retention_days: 30,
  alert_default_recipients: [],
})
const baseline = ref('')
const admins = ref<AdminOption[]>([])

const adminOptions = computed(() =>
  admins.value.map(a => ({
    value: String(a.id),
    label: `${a.username} (${a.email || '—'})`,
  }))
)

const recipientsSelected = computed<string[]>({
  get: () => values.value.alert_default_recipients.map(String),
  set: (v) => {
    values.value.alert_default_recipients = (v || [])
      .map(x => Number(x))
      .filter(n => Number.isFinite(n))
  },
})

const dirty = computed(() => JSON.stringify(values.value) !== baseline.value)

async function loadAll() {
  loading.value = true
  try {
    const [d, u] = await Promise.all([
      get<Defaults>('/api/admin/global-defaults'),
      get<{ users: AdminOption[] }>('/api/admin/users?page=1&perPage=200'),
    ])
    if (d) {
      values.value = {
        monitor_interval_sec: d.monitor_interval_sec,
        monitor_retention_days: d.monitor_retention_days,
        alert_default_recipients: [...(d.alert_default_recipients || [])],
      }
      baseline.value = JSON.stringify(values.value)
    }
    if (u) {
      admins.value = (u.users || [])
        .filter((x: any) => x.root_admin || x.rootAdmin)
        .map((x: any) => ({ id: x.id, username: x.username, email: x.email || '' }))
    }
  } finally {
    loading.value = false
  }
}

watch(() => props.modelValue, (open) => {
  if (open) loadAll()
})

async function save() {
  saving.value = true
  try {
    const res = await put<Defaults>('/api/admin/global-defaults', { ...values.value })
    if (res) {
      toast(t('hosts.globalDefaults.saved'), 'success')
      emit('update:modelValue', false)
    }
  } catch (err: any) {
    toast(err?.message || t('hosts.globalDefaults.saveFailed'), 'error')
  } finally {
    saving.value = false
  }
}

function cancel() {
  emit('update:modelValue', false)
}
</script>

<template>
  <BaseModal
    :modelValue="modelValue"
    @update:modelValue="emit('update:modelValue', $event)"
    :title="t('hosts.globalDefaults.title')"
    icon="tune"
    size="md"
  >
    <div v-if="loading" class="loading-row">
      <Spinner size="sm" />
      <span>{{ t('hosts.globalDefaults.loading') }}</span>
    </div>

    <div v-else class="form-grid">
      <FormField layout="horizontal" bordered>
        <template #label>
          {{ t('hosts.globalDefaults.fields.interval') }}
          <HelpTip :text="t('hosts.globalDefaults.fields.intervalHint')" />
        </template>
        <NumberInput
          v-model="values.monitor_interval_sec"
          :min="30"
          :max="3600"
          :step="10"
        />
      </FormField>

      <FormField layout="horizontal" bordered>
        <template #label>
          {{ t('hosts.globalDefaults.fields.retention') }}
          <HelpTip :text="t('hosts.globalDefaults.fields.retentionHint')" />
        </template>
        <NumberInput
          v-model="values.monitor_retention_days"
          :min="1"
          :max="365"
          :step="1"
        />
      </FormField>

      <FormField layout="horizontal" bordered>
        <template #label>
          {{ t('hosts.globalDefaults.fields.recipients') }}
          <HelpTip :text="t('hosts.globalDefaults.fields.recipientsHint')" />
        </template>
        <BaseSelect
          v-if="adminOptions.length"
          multiple
          teleport
          :options="adminOptions"
          v-model="recipientsSelected"
          :placeholder="t('hosts.globalDefaults.fields.recipientsEmpty')"
        />
        <div v-else class="chip-empty">
          {{ t('hosts.globalDefaults.fields.recipientsEmpty') }}
        </div>
      </FormField>
    </div>

    <template #footer>
      <BaseButton variant="default" @click="cancel" :disabled="saving">
        {{ t('hosts.globalDefaults.cancel') }}
      </BaseButton>
      <BaseButton
        variant="primary"
        :loading="saving"
        :disabled="loading || !dirty"
        @click="save"
      >
        {{ t('hosts.globalDefaults.save') }}
      </BaseButton>
    </template>
  </BaseModal>
</template>

<style scoped>
.loading-row {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  color: var(--t3);
  padding: var(--sp-4) 0;
}

.form-grid {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}

.chip-empty {
  color: var(--t3);
  font-size: var(--text-sm);
  padding: var(--sp-1) 0;
}
</style>
