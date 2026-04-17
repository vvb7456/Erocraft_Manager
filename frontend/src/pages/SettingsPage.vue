<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import PageHeader from '@/components/layout/PageHeader.vue'
import TabSwitcher, { type TabItem } from '@/components/ui/TabSwitcher.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import NumberInput from '@/components/form/NumberInput.vue'
import SecretInput from '@/components/ui/SecretInput.vue'
import ToggleSwitch from '@/components/ui/ToggleSwitch.vue'
import Spinner from '@/components/ui/Spinner.vue'
import FormField from '@/components/form/FormField.vue'
import { TIMEZONE_OPTIONS } from '@/config/timezones'

defineOptions({ name: 'SettingsPage' })

const { t } = useI18n({ useScope: 'global' })
const { get, post } = useApiFetch()
const { toast } = useToast()

// ── Tabs ──
const activeTab = ref('general')
const tabs = computed<TabItem[]>(() => [
  { key: 'general',    label: t('settings.ptero.title'),    icon: 'dns' },
  { key: 'smtp',       label: t('settings.smtp.title'),     icon: 'mail' },
  { key: 'branding',   label: t('settings.branding.title'), icon: 'palette' },
  { key: 'defaults',   label: t('settings.defaults.title'), icon: 'tune' },
  { key: 'automation', label: t('settings.automation.title'), icon: 'schedule' },
])

// ── State ──
const initialLoading = ref(true)
const settings = ref<Record<string, any>>({})
const automation = ref({
  AUTOMATION_RUN_HOUR: 2,
  AUTOMATION_RUN_MINUTE: 0,
  AUTOMATION_SUSPEND_ENABLED: false,
  AUTOMATION_DELETE_ENABLED: false,
  AUTOMATION_DELETE_DAYS: 14,
  AUTOMATION_EMAIL_ENABLED: false,
  AUTOMATION_EMAIL_RUN_HOUR: 10,
  AUTOMATION_EMAIL_RUN_MINUTE: 0,
  TIMEZONE: 'Asia/Shanghai',
})
const saveLoading = ref(false)

// ── Helpers ──
function getStr(key: string, def = ''): string { return settings.value[key] ?? def }
function setStr(key: string, val: string) { settings.value[key] = val }
function getNum(key: string, def = 0): number { return Number(settings.value[key]) || def }
function setNum(key: string, val: number) { settings.value[key] = val }
function getBool(key: string): boolean {
  const v = settings.value[key]
  return v === true || v === 'true' || v === '1'
}
function setBool(key: string, val: boolean) { settings.value[key] = val }

// ── Resources for selects ──
const nestList = ref<any[]>([])
const eggList = ref<any[]>([])
const nodeList = ref<any[]>([])
const nestOptions = computed(() => nestList.value.map((n: any) => ({ value: n.id, label: `${n.name} (#${n.id})` })))
const eggOptions = computed(() => eggList.value.map((e: any) => ({ value: e.id, label: `${e.name} (#${e.id})` })))
const nodeOptions = computed(() => nodeList.value.map((n: any) => ({ value: n.id, label: `${n.name} (#${n.id})` })))

watch(() => getNum('DEFAULT_NEST_ID'), async (nestId) => {
  if (!nestId) { eggList.value = []; return }
  const data = await get<{ eggs: any[] }>(`/api/nests/${nestId}/eggs`)
  eggList.value = data?.eggs || []
})

// ── Fetch ──
onMounted(async () => {
  const [settingsData, autoData, nestsRes, nodesRes] = await Promise.all([
    get<Record<string, any>>('/api/settings'),
    get<Record<string, any>>('/api/automation'),
    get<{ nests: any[] }>('/api/nests'),
    get<{ nodes: any[] }>('/api/nodes'),
  ])
  if (settingsData) settings.value = settingsData
  if (autoData) Object.assign(automation.value, autoData)
  if (nestsRes) nestList.value = nestsRes.nests
  if (nodesRes) nodeList.value = nodesRes.nodes
  const nestId = getNum('DEFAULT_NEST_ID')
  if (nestId) {
    const data = await get<{ eggs: any[] }>(`/api/nests/${nestId}/eggs`)
    eggList.value = data?.eggs || []
  }
  initialLoading.value = false
})

// ── Save ──
async function saveAll() {
  saveLoading.value = true
  const r1 = await post<{ message: string }>('/api/settings', settings.value)
  const r2 = await post<{ message: string }>('/api/automation', automation.value)
  saveLoading.value = false
  if (r1 && r2) toast(t('settings.saved'), 'success')
}
</script>

<template>
  <PageHeader icon="settings" :title="t('settings.title')" />

  <div class="page-body">
    <div v-if="initialLoading" class="center-loading"><Spinner size="lg" /></div>

    <template v-else>
      <TabSwitcher :tabs="tabs" v-model="activeTab" />

      <div class="st-panel">
        <!-- General / Pterodactyl -->
        <template v-if="activeTab === 'general'">
          <p class="st-desc">{{ t('settings.ptero.desc') }}</p>
          <FormField :label="t('settings.ptero.url')" layout="horizontal" bordered>
            <BaseInput :modelValue="getStr('PTERO_PANEL_URL')" :placeholder="t('settings.ptero.url_placeholder')" @update:modelValue="setStr('PTERO_PANEL_URL', $event)" />
          </FormField>
          <FormField :label="t('settings.ptero.apiKey')" layout="horizontal" bordered>
            <SecretInput :modelValue="getStr('PTERO_API_KEY')" :placeholder="t('settings.ptero.apiKey_placeholder')" @update:modelValue="setStr('PTERO_API_KEY', $event)" />
          </FormField>
          <FormField :label="t('settings.ptero.dbHost')" layout="horizontal" bordered>
            <BaseInput :modelValue="getStr('DB_HOST')" placeholder="127.0.0.1" @update:modelValue="setStr('DB_HOST', $event)" />
          </FormField>
          <FormField :label="t('settings.ptero.dbPort')" layout="horizontal" bordered>
            <NumberInput :modelValue="getNum('DB_PORT', 3306)" @update:modelValue="setNum('DB_PORT', $event)" :min="1" :max="65535" />
          </FormField>
          <FormField :label="t('settings.ptero.dbUser')" layout="horizontal" bordered>
            <BaseInput :modelValue="getStr('DB_USER')" @update:modelValue="setStr('DB_USER', $event)" />
          </FormField>
          <FormField :label="t('settings.ptero.dbPassword')" layout="horizontal" bordered>
            <SecretInput :modelValue="getStr('DB_PASSWORD')" @update:modelValue="setStr('DB_PASSWORD', $event)" />
          </FormField>
          <FormField :label="t('settings.ptero.dbName')" layout="horizontal" bordered>
            <BaseInput :modelValue="getStr('DB_NAME')" placeholder="panel" @update:modelValue="setStr('DB_NAME', $event)" />
          </FormField>
        </template>

        <!-- SMTP -->
        <template v-if="activeTab === 'smtp'">
          <p class="st-desc">{{ t('settings.smtp.desc') }}</p>
          <FormField :label="t('settings.smtp.host')" layout="horizontal" bordered>
            <BaseInput :modelValue="getStr('SMTP_HOST')" @update:modelValue="setStr('SMTP_HOST', $event)" />
          </FormField>
          <FormField :label="t('settings.smtp.port')" layout="horizontal" bordered>
            <NumberInput :modelValue="getNum('SMTP_PORT', 587)" @update:modelValue="setNum('SMTP_PORT', $event)" :min="1" :max="65535" />
          </FormField>
          <FormField :label="t('settings.smtp.sender')" layout="horizontal" bordered>
            <BaseInput :modelValue="getStr('SENDER_EMAIL')" type="email" @update:modelValue="setStr('SENDER_EMAIL', $event)" />
          </FormField>
          <FormField :label="t('settings.smtp.password')" layout="horizontal" bordered>
            <SecretInput :modelValue="getStr('SMTP_PASSWORD')" @update:modelValue="setStr('SMTP_PASSWORD', $event)" />
          </FormField>
          <FormField :label="t('settings.smtp.delay')" layout="horizontal" bordered>
            <NumberInput :modelValue="getNum('EMAIL_SEND_DELAY', 2)" @update:modelValue="setNum('EMAIL_SEND_DELAY', $event)" :min="0" :max="60" />
          </FormField>
          <FormField :label="t('settings.smtp.ssl')" layout="horizontal" bordered>
            <ToggleSwitch :modelValue="getBool('SMTP_USE_SSL')" @update:modelValue="setBool('SMTP_USE_SSL', $event)" size="sm" />
          </FormField>
        </template>

        <!-- Branding -->
        <template v-if="activeTab === 'branding'">
          <p class="st-desc">{{ t('settings.branding.desc') }}</p>
          <FormField :label="t('settings.branding.brandName')" layout="horizontal" bordered>
            <BaseInput :modelValue="getStr('BRAND_NAME')" @update:modelValue="setStr('BRAND_NAME', $event)" />
          </FormField>
          <FormField :label="t('settings.branding.systemName')" layout="horizontal" bordered>
            <BaseInput :modelValue="getStr('UI_SYSTEM_NAME')" @update:modelValue="setStr('UI_SYSTEM_NAME', $event)" />
          </FormField>
          <FormField :label="t('settings.branding.bannerUrl')" layout="horizontal" bordered>
            <BaseInput :modelValue="getStr('UI_BANNER_URL')" @update:modelValue="setStr('UI_BANNER_URL', $event)" />
          </FormField>
          <FormField :label="t('settings.branding.icpRecord')" layout="horizontal" bordered>
            <BaseInput :modelValue="getStr('UI_ICP_RECORD')" @update:modelValue="setStr('UI_ICP_RECORD', $event)" />
          </FormField>
        </template>

        <!-- Server Defaults -->
        <template v-if="activeTab === 'defaults'">
          <p class="st-desc">{{ t('settings.defaults.desc') }}</p>
          <FormField :label="t('settings.defaults.nest')" layout="horizontal" bordered>
            <BaseSelect :modelValue="getNum('DEFAULT_NEST_ID')" :options="nestOptions" :placeholder="t('settings.defaults.nest')" @update:modelValue="setNum('DEFAULT_NEST_ID', $event)" />
          </FormField>
          <FormField :label="t('settings.defaults.egg')" layout="horizontal" bordered>
            <BaseSelect :modelValue="getNum('DEFAULT_EGG_ID')" :options="eggOptions" :placeholder="t('settings.defaults.egg')" :disabled="!getNum('DEFAULT_NEST_ID')" @update:modelValue="setNum('DEFAULT_EGG_ID', $event)" />
          </FormField>
          <FormField :label="t('settings.defaults.node')" layout="horizontal" bordered>
            <BaseSelect :modelValue="getNum('DEFAULT_NODE_ID')" :options="nodeOptions" :placeholder="t('settings.defaults.node')" @update:modelValue="setNum('DEFAULT_NODE_ID', $event)" />
          </FormField>
          <FormField :label="t('settings.defaults.serverNamePrefix')" layout="horizontal" bordered>
            <BaseInput :modelValue="getStr('SERVER_NAME_PREFIX')" :placeholder="t('settings.defaults.serverNamePrefix_placeholder')" @update:modelValue="setStr('SERVER_NAME_PREFIX', $event)" />
          </FormField>
          <FormField :label="t('settings.defaults.dockerImage')" layout="horizontal" bordered>
            <BaseInput :modelValue="getStr('DOCKER_IMAGE')" @update:modelValue="setStr('DOCKER_IMAGE', $event)" />
          </FormField>
          <FormField :label="t('settings.defaults.cpu')" layout="horizontal" bordered>
            <NumberInput :modelValue="getNum('DEFAULT_CPU', 100)" @update:modelValue="setNum('DEFAULT_CPU', $event)" :min="0" />
          </FormField>
          <FormField :label="t('settings.defaults.memory')" layout="horizontal" bordered>
            <NumberInput :modelValue="getNum('DEFAULT_MEMORY', 1024)" @update:modelValue="setNum('DEFAULT_MEMORY', $event)" :min="0" />
          </FormField>
          <FormField :label="t('settings.defaults.disk')" layout="horizontal" bordered>
            <NumberInput :modelValue="getNum('DEFAULT_DISK', 5120)" @update:modelValue="setNum('DEFAULT_DISK', $event)" :min="0" />
          </FormField>
          <FormField :label="t('settings.defaults.databases')" layout="horizontal" bordered>
            <NumberInput :modelValue="getNum('DEFAULT_DATABASES')" @update:modelValue="setNum('DEFAULT_DATABASES', $event)" :min="0" />
          </FormField>
          <FormField :label="t('settings.defaults.backups')" layout="horizontal" bordered>
            <NumberInput :modelValue="getNum('DEFAULT_BACKUPS')" @update:modelValue="setNum('DEFAULT_BACKUPS', $event)" :min="0" />
          </FormField>
          <FormField :label="t('settings.defaults.allocations')" layout="horizontal" bordered>
            <NumberInput :modelValue="getNum('DEFAULT_ALLOCATIONS', 1)" @update:modelValue="setNum('DEFAULT_ALLOCATIONS', $event)" :min="0" />
          </FormField>
        </template>

        <!-- Automation -->
        <template v-if="activeTab === 'automation'">
          <p class="st-desc">{{ t('settings.automation.desc') }}</p>
          <FormField :label="t('settings.automation.timezone')" layout="horizontal" bordered>
            <BaseSelect :modelValue="automation.TIMEZONE" :options="TIMEZONE_OPTIONS" searchable @update:modelValue="automation.TIMEZONE = $event" />
          </FormField>

          <div class="st-sub">{{ t('settings.automation.suspend.title') }}</div>
          <p class="st-desc">{{ t('settings.automation.suspend.desc') }}</p>
          <FormField :label="t('settings.automation.suspend.enabled')" layout="horizontal" bordered>
            <ToggleSwitch v-model="automation.AUTOMATION_SUSPEND_ENABLED" size="sm" />
          </FormField>
          <FormField :label="t('settings.automation.suspend.runHour')" layout="horizontal" bordered>
            <NumberInput v-model="automation.AUTOMATION_RUN_HOUR" :min="0" :max="23" />
          </FormField>
          <FormField :label="t('settings.automation.suspend.runMinute')" layout="horizontal" bordered>
            <NumberInput v-model="automation.AUTOMATION_RUN_MINUTE" :min="0" :max="59" />
          </FormField>

          <div class="st-sub">{{ t('settings.automation.delete.title') }}</div>
          <p class="st-desc">{{ t('settings.automation.delete.desc') }}</p>
          <FormField :label="t('settings.automation.delete.enabled')" layout="horizontal" bordered>
            <ToggleSwitch v-model="automation.AUTOMATION_DELETE_ENABLED" size="sm" />
          </FormField>
          <FormField :label="t('settings.automation.delete.days')" layout="horizontal" bordered>
            <NumberInput v-model="automation.AUTOMATION_DELETE_DAYS" :min="0" :max="365" />
          </FormField>

          <div class="st-sub">{{ t('settings.automation.email.title') }}</div>
          <p class="st-desc">{{ t('settings.automation.email.desc') }}</p>
          <FormField :label="t('settings.automation.email.enabled')" layout="horizontal" bordered>
            <ToggleSwitch v-model="automation.AUTOMATION_EMAIL_ENABLED" size="sm" />
          </FormField>
          <FormField :label="t('settings.automation.email.runHour')" layout="horizontal" bordered>
            <NumberInput v-model="automation.AUTOMATION_EMAIL_RUN_HOUR" :min="0" :max="23" />
          </FormField>
          <FormField :label="t('settings.automation.email.runMinute')" layout="horizontal" bordered>
            <NumberInput v-model="automation.AUTOMATION_EMAIL_RUN_MINUTE" :min="0" :max="59" />
          </FormField>
        </template>
      </div>

      <!-- Save -->
      <div class="st-save">
        <BaseButton variant="primary" :loading="saveLoading" @click="saveAll">
          {{ t('settings.save') }}
        </BaseButton>
      </div>
    </template>
  </div>
</template>

<style scoped>
.center-loading { display: flex; justify-content: center; padding: var(--sp-8); }

.st-panel {
  margin-top: var(--sp-4);
  max-width: 640px;
  margin-left: auto;
  margin-right: auto;
}

/* Sub-heading / description */
.st-sub {
  font-size: .84rem;
  font-weight: 600;
  color: var(--t1);
  padding: var(--sp-3) 0 var(--sp-1);
}

.st-desc {
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--t1);
  margin: 0 0 var(--sp-4);
}

/* Save bar */
.st-save {
  display: flex;
  justify-content: flex-end;
  padding: var(--sp-4) 0;
  max-width: 640px;
  margin-left: auto;
  margin-right: auto;
}
</style>
