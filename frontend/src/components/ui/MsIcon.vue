<script setup lang="ts">
import { computed } from 'vue'
import { ICON_CODEPOINTS } from '@/config/icon-codepoints'

defineOptions({ name: 'MsIcon' })

const props = defineProps<{
  /** Material Symbols icon name */
  name: string
  /** Size variant: xxs(12) | xs(16) | sm(18, default) | md(20) | lg(32) | xl(48) */
  size?: 'xxs' | 'xs' | 'sm' | 'md' | 'lg' | 'xl'
  /** Override color. Pass explicit color value, or 'none' to inherit from parent */
  color?: string
}>()

/**
 * Global icon color palette — disabled for now, will re-enable after design finalization.
 * Categories: green(success), red(danger), amber(warning), blue(info),
 * purple(tools), pink(creative), cyan(tech), orange(notebook),
 * yellow(files/keys), muted(system)
 */
const ICON_COLORS: Record<string, string> = {}

const sizeClass = computed(() => {
  if (!props.size || props.size === 'sm') return 'ms-sm'
  if (props.size === 'md') return ''
  return `ms-${props.size}`
})

const iconChar = computed(() => ICON_CODEPOINTS[props.name] || props.name)

const iconStyle = computed(() => {
  if (props.color === 'none') return undefined
  const c = props.color || ICON_COLORS[props.name]
  return c ? { color: c } : undefined
})
</script>

<template>
  <span class="ms" :class="sizeClass" :style="iconStyle">{{ iconChar }}</span>
</template>
