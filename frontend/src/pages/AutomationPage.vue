<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import PageHeader from '@/components/layout/PageHeader.vue'
import BaseCard from '@/components/ui/BaseCard.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import NumberInput from '@/components/form/NumberInput.vue'
import ToggleSwitch from '@/components/ui/ToggleSwitch.vue'
import SectionHeader from '@/components/ui/SectionHeader.vue'
import Spinner from '@/components/ui/Spinner.vue'

defineOptions({ name: 'AutomationPage' })

const { t } = useI18n({ useScope: 'global' })
const { get, post, loading } = useApiFetch()
const { toast } = useToast()

const form = ref({
  AUTOMATION_RUN_HOUR: 2,
  AUTOMATION_RUN_MINUTE: 0,
  AUTOMATION_SUSPEND_ENABLED: false,
  AUTOMATION_DELETE_ENABLED: false,
  AUTOMATION_DELETE_DAYS: 14,
  AUTOMATION_EMAIL_ENABLED: false,
  AUTOMATION_EMAIL_RUN_HOUR: 10,
  AUTOMATION_EMAIL_RUN_MINUTE: 0,
})

const saveLoading = ref(false)

async function loadData() {
  const data = await get<Record<string, any>>('/api/automation')
  if (data) Object.assign(form.value, data)
}

onMounted(loadData)

async function save() {
  saveLoading.value = true
  const res = await post<{ message: string }>('/api/automation', form.value)
  saveLoading.value = false
  if (res) toast(t('automation.saved'), 'success')
}
</script>

<template>
  <PageHeader :title="t('automation.title')" icon="schedule">
    <template #controls>
      <BaseButton variant="primary" :disabled="saveLoading" @click="save">
        <Spinner v-if="saveLoading" size="sm" />
        {{ t('automation.save') }}
      </BaseButton>
    </template>
  </PageHeader>

  <div class="page-body">
    <Spinner v-if="loading" />

    <template v-else>
      <p class="hint">{{ t('automation.restartHint') }}</p>

      <!-- Auto Suspend -->
      <BaseCard class="auto-card">
        <SectionHeader icon="pause_circle" flush>
          {{ t('automation.suspend.title') }}
        </SectionHeader>
        <p class="desc">{{ t('automation.suspend.desc') }}</p>

        <div class="field">
          <ToggleSwitch v-model="form.AUTOMATION_SUSPEND_ENABLED">
            {{ t('automation.suspend.enabled') }}
          </ToggleSwitch>
        </div>

        <div class="form-grid">
          <NumberInput :label="t('automation.suspend.runHour')" v-model="form.AUTOMATION_RUN_HOUR" :min="0" :max="23" />
          <NumberInput :label="t('automation.suspend.runMinute')" v-model="form.AUTOMATION_RUN_MINUTE" :min="0" :max="59" />
        </div>
      </BaseCard>

      <!-- Auto Delete -->
      <BaseCard class="auto-card">
        <SectionHeader icon="delete_forever" flush>
          {{ t('automation.delete.title') }}
        </SectionHeader>
        <p class="desc">{{ t('automation.delete.desc') }}</p>

        <div class="field">
          <ToggleSwitch v-model="form.AUTOMATION_DELETE_ENABLED">
            {{ t('automation.delete.enabled') }}
          </ToggleSwitch>
        </div>

        <div class="form-grid">
          <NumberInput :label="t('automation.delete.days')" v-model="form.AUTOMATION_DELETE_DAYS" :min="1" :max="365" />
        </div>
      </BaseCard>

      <!-- Email Reminder -->
      <BaseCard class="auto-card">
        <SectionHeader icon="mail" flush>
          {{ t('automation.email.title') }}
        </SectionHeader>
        <p class="desc">{{ t('automation.email.desc') }}</p>

        <div class="field">
          <ToggleSwitch v-model="form.AUTOMATION_EMAIL_ENABLED">
            {{ t('automation.email.enabled') }}
          </ToggleSwitch>
        </div>

        <div class="form-grid">
          <NumberInput :label="t('automation.email.runHour')" v-model="form.AUTOMATION_EMAIL_RUN_HOUR" :min="0" :max="23" />
          <NumberInput :label="t('automation.email.runMinute')" v-model="form.AUTOMATION_EMAIL_RUN_MINUTE" :min="0" :max="59" />
        </div>
      </BaseCard>
    </template>
  </div>
</template>

<style scoped>
.auto-card { max-width: 720px; }
.hint { color: var(--t2); font-size: .85rem; margin-bottom: var(--sp-4); }
.desc { color: var(--t2); font-size: .85rem; margin: var(--sp-1) 0 var(--sp-4); }
.field { margin-bottom: var(--sp-4); }
.form-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: var(--sp-4); }
</style>
