<script setup lang="ts">
import { computed } from 'vue'
import MsIcon from './MsIcon.vue'

defineOptions({ name: 'SortTh' })

const props = defineProps<{
  /** Column key passed back via the `sort` event */
  col: string
  /** Currently active sort column key */
  sortBy: string
  /** Current sort direction */
  sortOrder: 'asc' | 'desc'
}>()

const emit = defineEmits<{
  sort: [col: string]
}>()

const active = computed(() => props.sortBy === props.col)
const ariaSort = computed<'ascending' | 'descending' | 'none'>(() =>
  !active.value ? 'none' : props.sortOrder === 'asc' ? 'ascending' : 'descending',
)
</script>

<template>
  <th
    class="sortable"
    :class="{ 'sort-active': active }"
    :aria-sort="ariaSort"
    @click="emit('sort', col)"
  >
    <span class="sort-th-inner">
      <span class="sort-th-label"><slot /></span>
      <MsIcon
        :name="active ? (sortOrder === 'asc' ? 'arrow_upward' : 'arrow_downward') : 'arrow_upward'"
        size="xs"
        class="sort-th-icon"
        aria-hidden="true"
      />
    </span>
  </th>
</template>

<style scoped>
.sort-th-inner {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  white-space: nowrap;
  vertical-align: middle;
  max-width: 100%;
}

.sort-th-label {
  overflow: hidden;
  text-overflow: ellipsis;
}

.sort-th-icon {
  color: var(--t3);
  font-size: 14px;
  width: 14px;
  height: 14px;
  line-height: 1;
  flex-shrink: 0;
  vertical-align: middle;
  opacity: 0;
  transition: opacity 0.15s ease, color 0.15s ease;
}

th.sortable:hover .sort-th-icon {
  opacity: 0.35;
  color: var(--t3);
}

th.sortable.sort-active .sort-th-icon {
  opacity: 1;
  color: var(--ac);
}
</style>
