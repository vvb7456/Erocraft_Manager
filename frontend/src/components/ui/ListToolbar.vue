<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import SectionToolbar from './SectionToolbar.vue'
import BaseButton from './BaseButton.vue'

defineProps<{ selectedCount: number; busy?: boolean }>()
defineEmits<{ clear: [] }>()
const { t } = useI18n()
</script>

<template>
  <div class="list-toolbar">
    <SectionToolbar v-if="!selectedCount">
      <template v-if="$slots.start" #start><slot name="start" /></template>
      <template v-if="$slots.end" #end><slot name="end" /></template>
    </SectionToolbar>
    <div v-else class="selection-toolbar" role="group" :aria-label="t('common.selection.actions')" :aria-busy="busy">
      <div class="selection-summary">
        <strong role="status">{{ t('common.selection.count', { count: selectedCount }) }}</strong>
        <BaseButton size="sm" variant="ghost" :disabled="busy" @click="$emit('clear')">{{ t('common.selection.clear') }}</BaseButton>
      </div>
      <fieldset class="selection-actions" :disabled="busy">
        <slot name="selection-actions" />
      </fieldset>
    </div>
  </div>
</template>

<style scoped>
.list-toolbar { min-width: 0; margin-bottom: 12px; container: list-toolbar / inline-size; }
.list-toolbar :deep(.section-toolbar) { margin-bottom: 0; }
.selection-toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: var(--sp-2) var(--sp-4); min-height: 36px; }
.selection-summary { display: flex; align-items: center; gap: var(--sp-3); color: var(--ac); font-size: var(--text-sm); white-space: nowrap; }
.selection-actions { display: flex; flex-wrap: wrap; align-items: center; gap: var(--sp-2); min-width: 0; margin: 0 0 0 auto; padding: 0; border: 0; }
@container list-toolbar (max-width: 600px) {
  .selection-actions { margin-left: 0; }
  .selection-actions :deep(.selection-action-label) { display: none; }
  .selection-actions :deep(.base-btn) { min-width: 36px; min-height: 36px; justify-content: center; }
}
</style>
