<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import BottomSheet from './BottomSheet.vue'
import MsIcon from './MsIcon.vue'

defineOptions({ name: 'MobileFilterSheet' })

export interface FilterColumn {
  key: string
  label: string
}

export interface FilterGroup {
  key: string
  label: string
  modelValue: string | number | boolean
  options: { value: string | number | boolean; label: string }[]
}

const props = defineProps<{
  open: boolean
  sortColumns: FilterColumn[]
  sortBy: string
  sortOrder: 'asc' | 'desc'
  filters?: FilterGroup[]
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  'sort': [column: string]
  'update:filter': [groupKey: string, value: string | number | boolean]
}>()

const { t } = useI18n({ useScope: 'global' })

const activeCount = computed(() => {
  let n = 0
  if (props.sortBy) n++
  if (props.filters) {
    for (const f of props.filters) {
      const first = f.options[0]
      if (first && f.modelValue !== first.value) n++
    }
  }
  return n
})

function onSort(col: string) {
  emit('sort', col)
}

function onFilter(groupKey: string, value: string | number | boolean) {
  emit('update:filter', groupKey, value)
}
</script>

<template>
  <BottomSheet
    :model-value="open"
    @update:model-value="emit('update:open', $event)"
    :title="t('common.filterSort.title')"
  >
    <div class="mfs">
      <!-- Sort section -->
      <div v-if="sortColumns.length" class="mfs__section">
        <div class="mfs__label">{{ t('common.filterSort.sortBy') }}</div>
        <div class="mfs__list">
          <button
            v-for="col in sortColumns"
            :key="col.key"
            type="button"
            class="mfs__item"
            :class="{ 'mfs__item--active': sortBy === col.key }"
            @click="onSort(col.key)"
          >
            <span>{{ col.label }}</span>
            <MsIcon
              v-if="sortBy === col.key"
              :name="sortOrder === 'asc' ? 'arrow_upward' : 'arrow_downward'"
              size="xs"
            />
          </button>
        </div>
      </div>

      <!-- Filter sections -->
      <div
        v-for="grp in filters"
        :key="grp.key"
        class="mfs__section"
      >
        <div class="mfs__label">{{ grp.label }}</div>
        <div class="mfs__list">
          <button
            v-for="opt in grp.options"
            :key="String(opt.value)"
            type="button"
            class="mfs__item"
            :class="{ 'mfs__item--active': grp.modelValue === opt.value }"
            @click="onFilter(grp.key, opt.value)"
          >
            <span>{{ opt.label }}</span>
            <MsIcon
              v-if="grp.modelValue === opt.value"
              name="check"
              size="xs"
            />
          </button>
        </div>
      </div>
    </div>
  </BottomSheet>
</template>

<style scoped>
.mfs {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}

.mfs__section {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}

.mfs__label {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--t3);
  text-transform: uppercase;
  letter-spacing: .04em;
  padding-bottom: var(--sp-1);
  border-bottom: 1px solid var(--bd);
}

.mfs__list {
  display: flex;
  flex-direction: column;
}

.mfs__item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: var(--sp-2) var(--sp-1);
  background: none;
  border: none;
  font: inherit;
  font-size: .88rem;
  color: var(--t2);
  cursor: pointer;
  border-radius: var(--r-sm);
  text-align: left;
  transition: background .12s, color .12s;
}

.mfs__item:hover {
  background: var(--bg3);
}

.mfs__item--active {
  color: var(--ac);
  font-weight: 500;
}
</style>
