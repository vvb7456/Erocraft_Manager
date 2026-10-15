<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useDirtyFormSection } from '@/composables/useDirtyForm'
import { useToast } from '@/composables/useToast'
import { formSnapshot } from '@/utils/formState'
import BaseCard from '@/components/ui/BaseCard.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import SectionHeader from '@/components/ui/SectionHeader.vue'
import FormField from '@/components/form/FormField.vue'
import NumberInput from '@/components/form/NumberInput.vue'
import LoadingCenter from '@/components/ui/LoadingCenter.vue'

const { t } = useI18n()
const { get, put } = useApiFetch()
const { toast } = useToast()
const loading = ref(true)
const values = ref<{ monitor_interval_sec: number; monitor_retention_days: number } | null>(null)
const baseline = ref('')
const dirty = computed(() => !!values.value && formSnapshot(values.value) !== baseline.value)

async function load() {
  loading.value = true
  const result = await get<NonNullable<typeof values.value>>('/api/admin/global-defaults').finally(() => { loading.value = false })
  if (result) {
    values.value = { monitor_interval_sec: result.monitor_interval_sec, monitor_retention_days: result.monitor_retention_days }
    baseline.value = formSnapshot(values.value)
  }
}

async function save() {
  if (!values.value) return false
  const submitted = { ...values.value }
  if (!await put('/api/admin/global-defaults', submitted)) return false
  baseline.value = formSnapshot(submitted)
  toast(t('settings.saved'), 'success')
  return !dirty.value
}

useDirtyFormSection({
  name: 'host-monitoring',
  isDirty: dirty,
  save,
  discard: () => { values.value = JSON.parse(baseline.value) },
})
onMounted(load)
</script>

<template>
  <LoadingCenter v-if="loading" />
  <BaseCard v-else-if="values" variant="bg2" density="compact">
    <SectionHeader icon="monitoring" :subtitle="t('settings.monitoring.desc')" flush>{{ t('settings.monitoring.title') }}</SectionHeader>
    <FormField :label="t('settings.monitoring.interval')" layout="horizontal"><NumberInput v-model="values.monitor_interval_sec" :min="30" :max="3600" :step="10" /></FormField>
    <FormField :label="t('settings.monitoring.retention')" layout="horizontal"><NumberInput v-model="values.monitor_retention_days" :min="1" :max="365" /></FormField>
  </BaseCard>
  <BaseButton v-else @click="load">{{ t('notifications.reload') }}</BaseButton>
</template>
