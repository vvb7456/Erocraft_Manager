<script setup lang="ts">
// ServerSparkline — mini line chart for the admin server overview.
// emphasis.disabled prevents echarts from dimming the line on hover.
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

use([LineChart, GridComponent, TooltipComponent, CanvasRenderer])

defineOptions({ name: 'ServerSparkline' })

const props = withDefaults(defineProps<{
  label: string
  values: number[]
  unitFormatter?: (v: number) => string
  color?: string
  height?: number
  fill?: boolean
}>(), {
  color: 'var(--ac)',
  height: 64,
  fill: true,
})

const resolvedColor = ref('#14b8a6')
function readColor() {
  if (typeof document === 'undefined') return
  if (props.color.startsWith('var(')) {
    const name = props.color.slice(4, -1).trim()
    const val = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
    if (val) resolvedColor.value = val
  } else {
    resolvedColor.value = props.color
  }
}

let observer: MutationObserver | null = null
onMounted(() => {
  readColor()
  observer = new MutationObserver(readColor)
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class', 'data-theme'] })
})
onBeforeUnmount(() => observer?.disconnect())

const fmt = (v: number) =>
  props.unitFormatter ? props.unitFormatter(v) : v.toFixed(1)

const option = computed(() => {
  const data = props.values.map(v => Number.isFinite(v) ? v : 0)
  return {
    backgroundColor: 'transparent',
    grid: { left: 0, right: 0, top: 4, bottom: 0 },
    xAxis: {
      type: 'category',
      show: false,
      boundaryGap: false,
      data: data.map((_, i) => i),
    },
    yAxis: {
      type: 'value',
      show: false,
      min: (val: { min: number; max: number }) =>
        val.min === val.max ? val.min - 1 : val.min,
      max: (val: { min: number; max: number }) =>
        val.min === val.max ? val.max + 1 : val.max,
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'var(--bg3)',
      borderColor: 'var(--bd)',
      textStyle: { color: 'var(--t1)', fontSize: 11 },
      formatter: (params: Array<{ value: number }>) => fmt(params[0].value),
      axisPointer: { type: 'line', lineStyle: { color: resolvedColor.value, opacity: .4 } },
    },
    series: [{
      type: 'line',
      data,
      showSymbol: false,
      smooth: true,
      // Critical: prevent echarts from dimming the line when axisPointer hovers.
      emphasis: { disabled: true },
      lineStyle: { width: 1.5, color: resolvedColor.value },
      areaStyle: props.fill ? {
        color: {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: `color-mix(in srgb, ${resolvedColor.value} 40%, transparent)` },
            { offset: 1, color: `color-mix(in srgb, ${resolvedColor.value} 0%, transparent)` },
          ],
        },
      } : undefined,
      animation: false,
    }],
  }
})

const lastValue = computed(() => {
  if (!props.values.length) return '—'
  return fmt(props.values[props.values.length - 1])
})
</script>

<template>
  <div class="spark">
    <div class="spark__head">
      <span class="spark__label">{{ label }}</span>
      <span class="spark__last">{{ lastValue }}</span>
    </div>
    <VChart class="spark__chart" :style="{ height: `${height}px` }" :option="option" autoresize />
  </div>
</template>

<style scoped>
.spark {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  width: 100%;
  overflow: hidden;
}
.spark__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--sp-2);
}
.spark__label {
  color: var(--t3);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: .06em;
  text-transform: uppercase;
}
.spark__last {
  color: var(--t1);
  font-size: var(--text-xs);
  font-variant-numeric: tabular-nums;
  font-family: 'IBM Plex Mono', ui-monospace, monospace;
}
.spark__chart {
  width: 100%;
  min-width: 0;
}
</style>
