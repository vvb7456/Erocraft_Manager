<script setup lang="ts">
// ServerStatTile — compact resource tile used inside the admin server
// overview hero card.
//
// Layout:
//   ┌─────────────────────────┐
//   │ LABEL                   │  ← uppercase eyebrow
//   │ 3.2 GiB                 │  ← big value
//   │ ▰▰▰▰▰▱▱▱▱▱  60%         │  ← UsageBar + percent (omitted when no limit)
//   │ / 4 GiB                 │  ← limit / supplementary text
//   └─────────────────────────┘
//
// Props:
//   - label, value, sub (limit text), percent (0–100, omit to hide bar)
//   - stale: dim values + show "stale" tag (used when wings is unreachable)
//   - tone: optional override for value color
import { computed } from 'vue'
import UsageBar from '@/components/ui/UsageBar.vue'

defineOptions({ name: 'ServerStatTile' })

const props = withDefaults(defineProps<{
  label: string
  value: string
  sub?: string
  percent?: number | null
  stale?: boolean
  warning?: number
  danger?: number
}>(), {
  percent: null,
  stale: false,
  warning: 70,
  danger: 90,
})

const showBar = computed(() => props.percent != null && Number.isFinite(props.percent))
const percentText = computed(() => {
  if (props.percent == null) return ''
  return `${Math.round(props.percent)}%`
})
</script>

<template>
  <div class="tile" :class="{ 'tile--stale': stale }">
    <div class="tile__head">
      <span class="tile__label">{{ label }}</span>
      <span v-if="stale" class="tile__stale">stale</span>
    </div>
    <div class="tile__value">{{ value }}</div>
    <div v-if="showBar" class="tile__bar">
      <UsageBar :percent="percent ?? 0" :warning="warning" :danger="danger" :height="4" />
      <span class="tile__pct">{{ percentText }}</span>
    </div>
    <div v-if="sub" class="tile__sub">{{ sub }}</div>
  </div>
</template>

<style scoped>
.tile {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
  padding: var(--sp-3);
  background: var(--bg3);
  border: 1px solid var(--bd);
  border-radius: var(--r-sm);
  min-width: 0;
}

.tile__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-1);
}

.tile__label {
  color: var(--t3);
  font-size: var(--text-xs);
  font-weight: 600;
  letter-spacing: .06em;
  text-transform: uppercase;
}

.tile__stale {
  font-size: 10px;
  color: var(--amber);
  text-transform: uppercase;
  letter-spacing: .04em;
  border: 1px solid color-mix(in srgb, var(--amber) 40%, transparent);
  padding: 0 4px;
  border-radius: 3px;
}

.tile__value {
  color: var(--t1);
  font-size: 1.3rem;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  line-height: 1.1;
  font-family: 'IBM Plex Mono', ui-monospace, monospace;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.tile__bar {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin-top: 2px;
}
.tile__bar :deep(.usage-bar) {
  flex: 1;
}
.tile__pct {
  color: var(--t3);
  font-size: var(--text-xs);
  font-variant-numeric: tabular-nums;
  min-width: 30px;
  text-align: right;
}

.tile__sub {
  color: var(--t3);
  font-size: var(--text-xs);
  font-family: 'IBM Plex Mono', ui-monospace, monospace;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.tile--stale .tile__value,
.tile--stale .tile__sub {
  opacity: .55;
}
</style>
