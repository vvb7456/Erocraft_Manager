<script setup lang="ts">
import { ref, inject, onMounted, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import BaseCard from '@/components/ui/BaseCard.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import FormField from '@/components/form/FormField.vue'
import Badge from '@/components/ui/Badge.vue'
import LoadingCenter from '@/components/ui/LoadingCenter.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import MsIcon from '@/components/ui/MsIcon.vue'

defineOptions({ name: 'ServerSettingsPage' })

const { t } = useI18n({ useScope: 'global' })
const { get, loading } = useApiFetch()
const { toast } = useToast()

interface ServerDetail {
  id: number; uuid: string; nodeId: number
}

interface StartupVar {
  envVariable: string
  name: string
  description: string
  defaultValue: string
  value: string
  isEditable: boolean
  rules: string
}

const server = inject<Ref<ServerDetail | null>>('server')!
const variables = ref<StartupVar[]>([])
const editValues = ref<Record<string, string>>({})

async function loadVars() {
  if (!server.value) return
  const data = await get<StartupVar[]>(`/api/user/servers/${server.value.id}/startup`)
  if (data) {
    variables.value = data
    editValues.value = Object.fromEntries(data.map(v => [v.envVariable, v.value]))
  }
}

onMounted(loadVars)

function isBooleanVar(v: StartupVar): boolean {
  return v.rules.includes('in:true,false') || v.rules.includes('boolean')
}

function isSelectVar(v: StartupVar): { options: { value: string; label: string }[] } | false {
  const m = v.rules.match(/in:([^\|]+)/)
  if (!m) return false
  const opts = m[1].split(',').map(o => o.trim())
  if (opts.length <= 1) return false
  // Exclude boolean-like selects handled above
  if (opts.length === 2 && opts.includes('true') && opts.includes('false')) return false
  return { options: opts.map(o => ({ value: o, label: o })) }
}
</script>

<template>
  <LoadingCenter v-if="loading" />

  <EmptyState
    v-else-if="!variables.length"
    icon="tune"
    :title="t('userServers.startup.title')"
  />

  <div v-else class="settings-layout">
    <BaseCard v-for="v in variables" :key="v.envVariable" class="var-card">
      <div class="var-header">
        <span class="var-name">{{ v.name }}</span>
        <Badge v-if="!v.isEditable" color="var(--t3)">{{ t('userServers.startup.readonly') }}</Badge>
        <code class="var-env">{{ v.envVariable }}</code>
      </div>

      <p v-if="v.description" class="var-desc">{{ v.description }}</p>

      <div class="var-input">
        <template v-if="!v.isEditable">
          <code class="var-readonly-value">{{ editValues[v.envVariable] }}</code>
        </template>

        <template v-else-if="isBooleanVar(v)">
          <BaseSelect
            :modelValue="editValues[v.envVariable]"
            @update:modelValue="(val: string | number | boolean) => editValues[v.envVariable] = String(val)"
            :options="[{ value: 'true', label: 'True' }, { value: 'false', label: 'False' }]"
          />
        </template>

        <template v-else-if="isSelectVar(v)">
          <BaseSelect
            :modelValue="editValues[v.envVariable]"
            @update:modelValue="(val: string | number | boolean) => editValues[v.envVariable] = String(val)"
            :options="(isSelectVar(v) as any).options"
          />
        </template>

        <template v-else>
          <BaseInput
            :modelValue="editValues[v.envVariable]"
            @update:modelValue="editValues[v.envVariable] = $event"
          />
        </template>
      </div>

      <div v-if="v.defaultValue" class="var-default">
        {{ t('userServers.startup.default') }}: <code>{{ v.defaultValue }}</code>
      </div>
    </BaseCard>
  </div>
</template>

<style scoped>
.settings-layout {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}

.var-card {
  padding: var(--sp-4);
}

.var-header {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}

.var-name {
  font-weight: 600;
  color: var(--t1);
}

.var-env {
  margin-left: auto;
  font-size: var(--text-xs);
  color: var(--t3);
  background: var(--bg4);
  padding: 1px 6px;
  border-radius: var(--r-xs);
  font-family: 'IBM Plex Mono', monospace;
}

.var-desc {
  font-size: var(--text-sm);
  color: var(--t2);
  margin: var(--sp-2) 0;
  line-height: 1.5;
}

.var-input {
  margin-top: var(--sp-2);
}

.var-readonly-value {
  font-family: 'IBM Plex Mono', monospace;
  font-size: var(--text-sm);
  color: var(--t2);
  background: var(--bg4);
  padding: var(--sp-2) var(--sp-3);
  border-radius: var(--r-xs);
  display: block;
}

.var-default {
  margin-top: var(--sp-2);
  font-size: var(--text-xs);
  color: var(--t3);
}

.var-default code {
  font-family: 'IBM Plex Mono', monospace;
  background: var(--bg4);
  padding: 0 4px;
  border-radius: 2px;
}
</style>
