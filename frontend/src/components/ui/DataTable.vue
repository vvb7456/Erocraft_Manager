<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import MsIcon from './MsIcon.vue'
import Spinner from './Spinner.vue'
import EmptyState from './EmptyState.vue'

export interface DataTableColumn {
  key: string
  label: string
  sortable?: boolean
  class?: string
}

const props = withDefaults(defineProps<{
  /** Rows to display on the current page */
  items: any[]
  /** Current page (1-indexed) */
  page: number
  /** Total page count */
  totalPages: number
  /** Items per page */
  perPage: number
  /** Label for the per-page input (e.g. "条/页") */
  perPageLabel?: string
  /** Current sort column key */
  sortBy?: string
  /** Current sort direction */
  sortOrder?: 'asc' | 'desc'
  /** Show loading spinner */
  loading?: boolean
  /** Empty icon */
  emptyIcon?: string
  /** Empty message */
  emptyText?: string
  /** Row key field */
  rowKey?: string
}>(), {
  perPageLabel: '',
  sortBy: '',
  sortOrder: 'asc',
  loading: false,
  emptyIcon: 'table_rows',
  rowKey: 'id',
})

const { t } = useI18n({ useScope: 'global' })

const emit = defineEmits<{
  'update:page': [value: number]
  'update:perPage': [value: number]
  sort: [column: string]
}>()

function onPerPageChange(e: Event) {
  const v = Math.max(1, Math.min(500, Number((e.target as HTMLInputElement).value) || 20))
  emit('update:perPage', v)
  emit('update:page', 1)
}

const sortIcon = computed(() =>
  props.sortOrder === 'asc' ? 'arrow_upward' : 'arrow_downward',
)

const isMobile = ref(false)
const mql = typeof window !== 'undefined' ? window.matchMedia('(max-width: 768px)') : null
function onMediaChange(e: MediaQueryListEvent | MediaQueryList) { isMobile.value = e.matches }
onMounted(() => { if (mql) { onMediaChange(mql); mql.addEventListener('change', onMediaChange) } })
onUnmounted(() => { mql?.removeEventListener('change', onMediaChange) })

// Jump-to-page popover
const jumpOpen = ref(false)
const jumpValue = ref('')
const jumpInputRef = ref<HTMLInputElement | null>(null)
async function openJump() {
  if (props.totalPages <= 1) return
  jumpValue.value = String(props.page)
  jumpOpen.value = true
  await Promise.resolve()
  jumpInputRef.value?.focus()
  jumpInputRef.value?.select()
}
function closeJump() { jumpOpen.value = false }
function submitJump() {
  const n = Math.max(1, Math.min(props.totalPages, Math.floor(Number(jumpValue.value)) || props.page))
  jumpOpen.value = false
  if (n !== props.page) emit('update:page', n)
}
</script>

<template>
  <!-- Loading -->
  <div v-if="loading" class="dt-center-loading">
    <Spinner size="lg" />
  </div>

  <!-- Empty -->
  <template v-else-if="items.length === 0">
    <slot name="empty">
      <EmptyState :icon="emptyIcon" :title="emptyText || t('common.empty')" />
    </slot>
  </template>

  <!-- Table (desktop) or Cards (mobile) -->
  <template v-else>
    <!-- Mobile card view -->
    <div v-if="isMobile && $slots.card" class="dt-card-list">
      <div
        v-for="(item, index) in items"
        :key="rowKey ? item[rowKey] : index"
        class="dt-card"
      >
        <slot name="card" :item="item" :index="index" />
      </div>
    </div>

    <!-- Desktop table view -->
    <div v-else class="dt-table-wrap">
      <table class="dt-table">
        <thead>
          <tr>
            <slot name="header" :sort-by="sortBy" :sort-order="sortOrder" :sort-icon="sortIcon" />
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(item, index) in items"
            :key="rowKey ? item[rowKey] : index"
          >
            <slot name="row" :item="item" :index="index" />
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Pagination footer -->
    <div class="dt-footer" :class="{ 'dt-footer--mobile': isMobile }">
      <div class="dt-footer-spacer" />
      <div class="dt-pagination">
        <button class="dt-page-btn" :disabled="page <= 1" @click="emit('update:page', 1)">
          <MsIcon name="first_page" size="xs" />
        </button>
        <button class="dt-page-btn" :disabled="page <= 1" @click="emit('update:page', page - 1)">
          <MsIcon name="chevron_left" size="xs" />
        </button>
        <span class="dt-page-info">
          <input
            v-if="jumpOpen"
            ref="jumpInputRef"
            v-model="jumpValue"
            type="number"
            class="dt-page-jump"
            :min="1"
            :max="totalPages"
            @keydown.enter="submitJump"
            @keydown.esc="closeJump"
            @blur="submitJump"
          />
          <button
            v-else
            type="button"
            class="dt-page-cur"
            :disabled="totalPages <= 1"
            :title="t('common.pagination.jump', { n: totalPages })"
            @click="openJump"
          >{{ page }}</button>
          <span class="dt-page-sep">/</span>
          <span class="dt-page-total">{{ totalPages }}</span>
        </span>
        <button class="dt-page-btn" :disabled="page >= totalPages" @click="emit('update:page', page + 1)">
          <MsIcon name="chevron_right" size="xs" />
        </button>
        <button class="dt-page-btn" :disabled="page >= totalPages" @click="emit('update:page', totalPages)">
          <MsIcon name="last_page" size="xs" />
        </button>
      </div>
      <div class="dt-footer-right">
        <input
          type="number"
          class="dt-per-page-input"
          :value="perPage"
          min="1"
          max="500"
          @change="onPerPageChange"
        />
        <span v-if="perPageLabel" class="dt-per-page-label">{{ perPageLabel }}</span>
      </div>
    </div>
  </template>
</template>

<style scoped>
.dt-center-loading {
  display: flex;
  justify-content: center;
  padding: var(--sp-8);
}

.dt-table-wrap {
  overflow-x: auto;
  /* Contain horizontal overscroll so iOS rubber-band doesn't propagate to
     the page (relevant only on iPad / wide-mobile where the desktop table
     view is shown; on phones DataTable switches to the card layout). */
  overscroll-behavior-x: contain;
}

.dt-table {
  width: 100%;
  border-collapse: collapse;
  font-size: .85rem;
}

.dt-table :deep(th),
.dt-table :deep(td) {
  padding: var(--sp-3) var(--sp-3);
  text-align: left;
  border-bottom: 1px solid var(--bd);
  white-space: nowrap;
}

.dt-table :deep(th) {
  font-size: .78rem;
  font-weight: 600;
  color: var(--t3);
  text-transform: uppercase;
  letter-spacing: .3px;
  background: var(--bg2);
  position: sticky;
  top: 0;
  z-index: 1;
}

.dt-table :deep(th.sortable) {
  cursor: pointer;
  user-select: none;
}

.dt-table :deep(th.sortable:hover) {
  color: var(--t1);
}

.dt-table :deep(tbody tr:hover) {
  background: color-mix(in srgb, var(--ac) 4%, transparent);
}

/* The last row already has the footer's top border just below it; dropping
   its own bottom border avoids a 2px "double separator" look. */
.dt-table :deep(tbody tr:last-child td) {
  border-bottom: none;
}

/* Footer */
.dt-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--sp-2) var(--sp-3);
  border-top: 1px solid var(--bd);
  font-size: .78rem;
  color: var(--t3);
}

.dt-footer-spacer {
  flex: 1;
}

.dt-pagination {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}

.dt-page-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: 1px solid var(--bd);
  border-radius: var(--r-sm);
  background: var(--bg2);
  color: var(--t2);
  cursor: pointer;
  transition: background .15s;
}

.dt-page-btn:hover:not(:disabled) {
  background: var(--bg2);
}

.dt-page-btn:disabled {
  opacity: .35;
  cursor: not-allowed;
}

.dt-page-info {
  font-variant-numeric: tabular-nums;
  min-width: 48px;
  text-align: center;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  justify-content: center;
}
.dt-page-cur {
  background: transparent;
  border: 0;
  padding: 2px 6px;
  border-radius: var(--r-xs);
  color: var(--ac);
  cursor: pointer;
  font: inherit;
  font-variant-numeric: tabular-nums;
}
.dt-page-cur:hover:not(:disabled) { background: var(--bg3); }
.dt-page-cur:disabled { color: inherit; cursor: default; }
.dt-page-sep { color: var(--t3); }
.dt-page-total { color: var(--t2); }
.dt-page-jump {
  width: 56px;
  padding: 2px 6px;
  border: 1px solid var(--ac);
  border-radius: var(--r-sm);
  background: var(--bg-in);
  color: var(--t1);
  font-size: inherit;
  text-align: center;
  -moz-appearance: textfield;
}
.dt-page-jump::-webkit-outer-spin-button,
.dt-page-jump::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }

.dt-footer-right {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--sp-2);
}

.dt-per-page-input {
  width: 56px;
  padding: 2px 6px;
  border: 1px solid var(--bd);
  border-radius: var(--r-sm);
  background: var(--bg2);
  color: var(--t1);
  font-size: .78rem;
  text-align: center;
  -moz-appearance: textfield;
}

.dt-per-page-input::-webkit-inner-spin-button,
.dt-per-page-input::-webkit-outer-spin-button {
  -webkit-appearance: none;
  margin: 0;
}

.dt-per-page-label {
  white-space: nowrap;
}

/* Card list (mobile) */
.dt-card-list {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.dt-card {
  background: var(--bg2);
  border: 1px solid var(--bd);
  border-radius: var(--r-md);
  padding: var(--sp-3) var(--sp-4);
  -webkit-tap-highlight-color: transparent;
}

.dt-card:active {
  background: var(--bg2);
}

/* Mobile pagination */
.dt-footer--mobile {
  flex-wrap: wrap;
  justify-content: center;
}

.dt-footer--mobile .dt-footer-spacer,
.dt-footer--mobile .dt-footer-right {
  display: none;
}
</style>
