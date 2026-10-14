<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import ToggleSwitch from '@/components/ui/ToggleSwitch.vue'
import NumberInput from '@/components/form/NumberInput.vue'
import FormField from '@/components/form/FormField.vue'
import type { MetricRule } from '@/types/notifications'
const props = defineProps<{ modelValue: Record<string, MetricRule>; defaults?: Record<string, MetricRule>; hostKind?: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: Record<string, MetricRule>] }>()
const { t } = useI18n()
const keys = computed(() => Object.keys(props.defaults || props.modelValue).filter(k => k !== 'cert_source_expiring' &&
  (!props.hostKind || props.hostKind === 'wings_node' || !['node_offline', 'wings_only_down'].includes(k))))
function value(key: string, field: keyof MetricRule) { return props.modelValue[key]?.[field] ?? props.defaults?.[key]?.[field] }
function set(key: string, field: keyof MetricRule, val: number | boolean) {
  emit('update:modelValue', { ...props.modelValue, [key]: { ...props.modelValue[key], [field]: val } })
}
</script>

<template>
  <div class="metric-rules">
    <div v-for="key in keys" :key="key" class="metric-rule">
      <FormField :label="t(`hosts.setting.alerting.types.${key}`)" layout="horizontal" keep-horizontal>
        <div class="rule-controls">
          <ToggleSwitch :model-value="Boolean(value(key, 'enabled'))" size="sm" :aria-label="t(`hosts.setting.alerting.types.${key}`)" @update:model-value="set(key, 'enabled', $event)" />
        </div>
      </FormField>
      <template v-if="value(key, 'enabled')">
        <FormField v-if="value(key, 'threshold') != null" :label="t(key === 'load_high' ? 'notifications.center.loadThreshold' : 'notifications.center.percentThreshold')" layout="horizontal">
          <NumberInput :model-value="Number(value(key, 'threshold'))" :min="key === 'load_high' ? 0.1 : 1" :max="100" :step="key === 'load_high' ? 0.1 : 1" @update:model-value="set(key, 'threshold', Number($event))" />
        </FormField>
        <FormField v-if="key === 'disk_high'" :label="t('notifications.center.warningThreshold')" layout="horizontal">
          <NumberInput :model-value="Number(value(key, 'warning_threshold'))" :min="1" :max="100" @update:model-value="set(key, 'warning_threshold', Number($event))" />
        </FormField>
        <FormField v-if="key === 'disk_critical'" :label="t('notifications.center.criticalThreshold')" layout="horizontal">
          <NumberInput :model-value="Number(value(key, 'critical_threshold'))" :min="1" :max="100" @update:model-value="set(key, 'critical_threshold', Number($event))" />
        </FormField>
        <FormField v-if="value(key, 'sustain_min') != null" :label="t('notifications.center.sustain')" layout="horizontal">
          <NumberInput :model-value="Number(value(key, 'sustain_min'))" :min="1" :max="60" @update:model-value="set(key, 'sustain_min', Number($event))" />
        </FormField>
      </template>
    </div>
  </div>
</template>

<style scoped>
.metric-rule { padding-top: var(--sp-3); border-bottom: 1px solid var(--bd); }
.metric-rule:first-child { padding-top: 0; }
.metric-rule:last-child { border-bottom: 0; }
.rule-controls { display: flex; align-items: center; flex-wrap: wrap; gap: var(--sp-2); }
</style>
