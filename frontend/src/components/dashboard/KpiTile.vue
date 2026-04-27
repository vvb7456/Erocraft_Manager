<script setup lang="ts">
import MsIcon from '@/components/ui/MsIcon.vue'

defineOptions({ name: 'KpiTile' })

interface SubItem {
  label: string
  value: string | number
  tone?: 'default' | 'amber' | 'red' | 'green'
}

defineProps<{
  icon: string
  label: string
  value: string | number
  /** Optional unit suffix (e.g. "%") rendered smaller next to the value */
  unit?: string
  /** Tile-level emphasis tone for the value */
  tone?: 'default' | 'amber' | 'red' | 'green'
  /** Up to 3 secondary stats shown below the main value */
  subItems?: SubItem[]
}>()
</script>

<template>
  <div class="kpi-tile" :class="`tone-${tone ?? 'default'}`">
    <div class="kpi-head">
      <MsIcon :name="icon" size="sm" class="kpi-icon" />
      <span class="kpi-label">{{ label }}</span>
    </div>
    <div class="kpi-value">
      <span class="kpi-num">{{ value }}</span>
      <span v-if="unit" class="kpi-unit">{{ unit }}</span>
    </div>
    <div v-if="subItems && subItems.length" class="kpi-subs">
      <span
        v-for="s in subItems"
        :key="s.label"
        class="kpi-sub"
        :class="`sub-${s.tone ?? 'default'}`"
      >
        <span class="sub-label">{{ s.label }}</span>
        <span class="sub-value">{{ s.value }}</span>
      </span>
    </div>
  </div>
</template>

<style scoped>
.kpi-tile {
  background: var(--bg2);
  border: 1px solid var(--bd);
  border-radius: var(--r-lg);
  padding: var(--sp-4);
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  min-height: 100px;
  position: relative;
  overflow: hidden;
}
.kpi-tile::before {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(180deg, color-mix(in srgb, var(--ac) 4%, transparent), transparent 60%);
  pointer-events: none;
}
.kpi-tile.tone-amber { border-color: color-mix(in srgb, var(--amber) 50%, var(--bd)); }
.kpi-tile.tone-red { border-color: color-mix(in srgb, var(--red) 50%, var(--bd)); }
.kpi-tile.tone-green { border-color: color-mix(in srgb, var(--green) 50%, var(--bd)); }

.kpi-head {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  color: var(--t2);
  font-size: var(--text-xs);
  font-weight: 500;
  letter-spacing: 0.02em;
  text-transform: uppercase;
}
.kpi-icon { color: var(--t3); }

.kpi-value {
  display: flex;
  align-items: baseline;
  gap: 4px;
  color: var(--t1);
  line-height: 1;
}
.kpi-num {
  font-size: 2rem;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.02em;
}
.kpi-unit {
  font-size: 1rem;
  font-weight: 500;
  color: var(--t2);
}
.tone-amber .kpi-num { color: var(--amber); }
.tone-red .kpi-num { color: var(--red); }
.tone-green .kpi-num { color: var(--green); }

.kpi-subs {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-3);
  margin-top: auto;
  padding-top: var(--sp-1);
  font-size: var(--text-xs);
  font-variant-numeric: tabular-nums;
}
.kpi-sub {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.sub-label {
  color: var(--t3);
}
.sub-value {
  color: var(--t1);
  font-weight: 600;
}
.sub-amber .sub-value { color: var(--amber); }
.sub-red .sub-value { color: var(--red); }
.sub-green .sub-value { color: var(--green); }
</style>
