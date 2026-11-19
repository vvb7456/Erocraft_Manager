<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { apiErrorMessage } from '@/composables/apiClient'
import { useToast } from '@/composables/useToast'
import {
  createEgg,
  importEggFile,
  type EggDetailOut,
  type EggSummaryOut,
  type NestOut,
} from '@/api/adminNestsEggs'
import BaseModal from '@/components/ui/BaseModal.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import TabSwitcher from '@/components/ui/TabSwitcher.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import BaseTextarea from '@/components/form/BaseTextarea.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import FormField from '@/components/form/FormField.vue'
import ToggleSwitch from '@/components/ui/ToggleSwitch.vue'
import HelpTip from '@/components/ui/HelpTip.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import EggImagesEditor, {
  eggImageRowsToMap,
  validateEggImageRows,
  type EggImageRow,
} from '@/components/nests/EggImagesEditor.vue'

defineOptions({ name: 'EggCreateModal' })

const props = defineProps<{
  modelValue: boolean
  nests: NestOut[]
  defaultNestId?: number | null
  allEggs?: EggSummaryOut[]
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  created: [egg: EggDetailOut]
}>()

const { t } = useI18n({ useScope: 'global' })
const { toast } = useToast()

const activeTab = ref<'basic' | 'process'>('basic')
const tabs = computed(() => [
  { key: 'basic', icon: 'inventory_2', label: t('nests.egg.createTabs.basic') },
  { key: 'process', icon: 'data_object', label: t('nests.egg.createTabs.process') },
])

const nestId = ref<number | null>(null)
const name = ref('')
const description = ref('')
const startup = ref('')
const dockerImages = ref<EggImageRow[]>([{ label: 'Default', image: '' }])
const forceOutgoingIp = ref(false)
const configFrom = ref<number | null>(null)
const configStop = ref('^C')
const configStartup = ref('{"done": ""}')
const configFiles = ref('{}')
const configLogs = ref('{}')
const submitting = ref(false)
const importing = ref(false)
const fileInputRef = ref<HTMLInputElement | null>(null)
const imagesEditorRef = ref<InstanceType<typeof EggImagesEditor> | null>(null)

function reset() {
  activeTab.value = 'basic'
  nestId.value = props.defaultNestId ?? props.nests[0]?.id ?? null
  name.value = ''
  description.value = ''
  startup.value = ''
  dockerImages.value = [{ label: 'Default', image: '' }]
  imagesEditorRef.value?.resetTouched()
  forceOutgoingIp.value = false
  configFrom.value = null
  configStop.value = '^C'
  configStartup.value = '{"done": ""}'
  configFiles.value = '{}'
  configLogs.value = '{}'
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) reset()
  },
)

watch(nestId, () => {
  configFrom.value = null
})

const nestOptions = computed(() =>
  props.nests.map(n => ({
    value: n.id,
    label: `${n.name} (#${n.id})`,
  })),
)

const configFromOptions = computed(() => {
  const candidates = (props.allEggs || []).filter(e => e.nest_id === nestId.value)
  return [
    { value: '', label: t('nests.egg.configFromNone') },
    ...candidates.map(c => ({ value: c.id, label: `${c.name} (#${c.id})` })),
  ]
})

function checkJsonObj(raw: string): boolean {
  const s = raw.trim()
  if (!s) return configFrom.value != null
  try {
    const parsed = JSON.parse(s)
    return !!parsed && typeof parsed === 'object' && !Array.isArray(parsed)
  } catch {
    return false
  }
}

const startupJsonErr = computed(() =>
  checkJsonObj(configStartup.value) ? '' : t('nests.egg.jsonObjectRequired'),
)
const filesJsonErr = computed(() =>
  checkJsonObj(configFiles.value) ? '' : t('nests.egg.jsonObjectRequired'),
)
const logsJsonErr = computed(() =>
  checkJsonObj(configLogs.value) ? '' : t('nests.egg.jsonObjectRequired'),
)

const imageErrors = computed(() => validateEggImageRows(dockerImages.value))

const busy = computed(() => submitting.value || importing.value)

const canSubmit = computed(() => {
  if (!nestId.value) return false
  if (!name.value.trim() || !startup.value.trim()) return false
  if (imageErrors.value.length > 0) return false
  if (startupJsonErr.value || filesJsonErr.value || logsJsonErr.value) return false
  if (configFrom.value == null && !configStop.value.trim()) return false
  return true
})

function triggerFileImport() {
  if (busy.value || !nestId.value) return
  fileInputRef.value?.click()
}

async function onImportFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || !nestId.value) return

  importing.value = true
  try {
    const imported = await importEggFile(nestId.value, file)
    toast(t('nests.import.importedOk', { name: imported.name }), 'success')
    emit('created', imported)
    emit('update:modelValue', false)
  } catch (err) {
    toast(apiErrorMessage(err), 'error')
  } finally {
    importing.value = false
  }
}

async function submit() {
  if (!canSubmit.value || !nestId.value || busy.value) return
  submitting.value = true
  try {
    const created = await createEgg({
      nest_id: nestId.value,
      name: name.value.trim(),
      description: description.value.trim() || null,
      startup: startup.value.trim(),
      docker_images: eggImageRowsToMap(dockerImages.value),
      force_outgoing_ip: forceOutgoingIp.value,
      config_from: configFrom.value,
      config_stop: configStop.value.trim() || null,
      config_startup: configStartup.value.trim() || null,
      config_files: configFiles.value.trim() || null,
      config_logs: configLogs.value.trim() || null,
    })
    toast(t('nests.egg.created', { name: created.name }), 'success')
    emit('created', created)
    emit('update:modelValue', false)
  } catch (err) {
    toast(apiErrorMessage(err), 'error')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <BaseModal
    :model-value="modelValue"
    @update:model-value="emit('update:modelValue', $event)"
    :title="t('nests.egg.createTitle')"
    icon="add_circle"
    size="lg"
    footer-align="between"
  >
    <div class="egg-create">
      <input
        ref="fileInputRef"
        type="file"
        accept=".json,application/json"
        hidden
        @change="onImportFileChange"
      />
      <TabSwitcher v-model="activeTab" :tabs="tabs" />

      <div v-show="activeTab === 'basic'" class="tab-pane">
        <div class="grid-2">
          <FormField :label="t('nests.import.targetNest')" required density="compact">
            <BaseSelect
              teleport
              :options="nestOptions"
              :placeholder="t('nests.import.selectNest')"
              :model-value="nestId ?? ''"
              @update:model-value="(v: any) => nestId = v === '' || v == null ? null : Number(v)"
            />
          </FormField>

          <FormField :label="t('nests.egg.fields.name')" required density="compact">
            <BaseInput v-model="name" :placeholder="t('nests.egg.fields.namePlaceholder')" />
          </FormField>
        </div>

        <FormField :label="t('nests.egg.fields.description')" density="compact">
          <BaseTextarea v-model="description" :rows="2" />
        </FormField>

        <FormField required density="compact">
          <template #label>
            {{ t('nests.egg.fields.startup') }}
            <HelpTip :text="t('nests.egg.tips.startup')" />
          </template>
          <BaseTextarea
            v-model="startup"
            mono
            :rows="2"
            :spellcheck="false"
            :placeholder="t('nests.egg.fields.startupPlaceholder')"
          />
        </FormField>

        <EggImagesEditor ref="imagesEditorRef" v-model="dockerImages" />

        <FormField
          layout="horizontal"
          keep-horizontal
          control-fit
          bordered
          density="compact"
        >
          <template #label>
            {{ t('nests.egg.fields.forceOutgoingIp') }}
            <HelpTip :text="t('nests.egg.tips.forceOutgoingIp')" />
          </template>
          <ToggleSwitch v-model="forceOutgoingIp" size="sm" />
        </FormField>
      </div>

      <div v-show="activeTab === 'process'" class="tab-pane">
        <div class="grid-2">
          <FormField density="compact">
            <template #label>
              {{ t('nests.egg.fields.configFrom') }}
              <HelpTip :text="t('nests.egg.tips.configFrom')" />
            </template>
            <BaseSelect
              teleport
              :options="configFromOptions"
              :model-value="configFrom ?? ''"
              @update:model-value="(v: any) => configFrom = v === '' || v == null ? null : Number(v)"
            />
          </FormField>

          <FormField :label="t('nests.egg.fields.configStop')" :required="configFrom == null" density="compact">
            <BaseInput v-model="configStop" placeholder="^C" />
          </FormField>
        </div>

        <FormField
          :label="t('nests.egg.fields.configStartup')"
          :required="configFrom == null"
          :error="startupJsonErr || undefined"
          density="compact"
        >
          <BaseTextarea v-model="configStartup" mono :rows="3" :spellcheck="false" />
        </FormField>

        <FormField
          :label="t('nests.egg.fields.configFiles')"
          :required="configFrom == null"
          :error="filesJsonErr || undefined"
          density="compact"
        >
          <BaseTextarea v-model="configFiles" mono :rows="4" :spellcheck="false" />
        </FormField>

        <FormField
          :label="t('nests.egg.fields.configLogs')"
          :required="configFrom == null"
          :error="logsJsonErr || undefined"
          density="compact"
        >
          <BaseTextarea v-model="configLogs" mono :rows="3" :spellcheck="false" />
        </FormField>
      </div>

    </div>

    <template #footer>
      <BaseButton
        variant="default"
        :loading="importing"
        :disabled="busy || !nestId"
        @click="triggerFileImport"
      >
        <MsIcon name="upload_file" size="xs" /> {{ t('nests.actions.importEgg') }}
      </BaseButton>
      <div class="footer-actions">
        <BaseButton variant="default" :disabled="busy" @click="emit('update:modelValue', false)">
          {{ t('common.btn.cancel') }}
        </BaseButton>
        <BaseButton variant="primary" :loading="submitting" :disabled="busy || !canSubmit" @click="submit">
          <MsIcon name="add" size="xs" /> {{ t('nests.egg.createBtn') }}
        </BaseButton>
      </div>
    </template>
  </BaseModal>
</template>

<style scoped>
.egg-create {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.tab-pane {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.grid-2 {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: var(--sp-3);
}
.footer-actions {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}
@media (max-width: 768px) {
  .footer-actions {
    flex-direction: column-reverse;
    width: 100%;
  }
}
@media (max-width: 720px) {
  .grid-2 {
    grid-template-columns: 1fr;
  }
}
</style>
