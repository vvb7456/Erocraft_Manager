<script setup lang="ts">
import { ref, useId } from 'vue'
import MsIcon from '@/components/ui/MsIcon.vue'

defineOptions({ name: 'CollapsibleGroup' })

const props = withDefaults(defineProps<{
  title?: string
  subtitle?: string
  count?: number
  icon?: string
  suffix?: string
  defaultOpen?: boolean
}>(), {
  defaultOpen: true,
})

const expanded = ref(props.defaultOpen)
const contentId = useId()

function toggle() {
  expanded.value = !expanded.value
}
</script>

<template>
  <div class="collapsible-group">
    <div class="collapsible-group__header" :class="{ 'collapsible-group__header--described': subtitle }">
      <button type="button" class="collapsible-group__trigger" :aria-expanded="expanded" :aria-controls="contentId" @click="toggle">
      <MsIcon name="expand_more" size="sm" color="none" class="collapsible-group__arrow" :class="{ 'collapsible-group__arrow--collapsed': !expanded }" />
      <slot name="header" :expanded="expanded">
        <MsIcon v-if="icon" :name="icon" size="xs" color="none" class="collapsible-group__icon" />
        <span class="collapsible-group__heading">
          <span class="collapsible-group__title">{{ title }}</span>
          <span v-if="subtitle" class="collapsible-group__subtitle">{{ subtitle }}</span>
        </span>
        <span v-if="count != null" class="collapsible-group__count">{{ count }}</span>
        <span v-if="suffix" class="collapsible-group__suffix">{{ suffix }}</span>
      </slot>
      </button>
      <span v-if="$slots['title-right']" class="collapsible-group__right">
        <slot name="title-right" />
      </span>
    </div>
    <div v-show="expanded" :id="contentId" class="collapsible-group__body">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.collapsible-group__header, .collapsible-group__trigger {
  display: flex;
  align-items: center;
  gap: 6px;
}
.collapsible-group__trigger {
  flex: 1;
  min-width: 0;
  padding: var(--sp-2) 0;
  border: 0;
  background: none;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
  user-select: none;
  font-size: var(--text-base);
  font-weight: 500;
}
.collapsible-group__trigger:focus-visible { outline: 2px solid var(--ac); outline-offset: 2px; border-radius: var(--r-sm); }

.collapsible-group__arrow {
  font-size: 16px;
  transition: transform .2s;
}

.collapsible-group__arrow--collapsed {
  transform: rotate(-90deg);
}

.collapsible-group__icon {
  color: var(--t2);
}

.collapsible-group__title {
  color: var(--t1);
}

.collapsible-group__heading { min-width: 0; }
.collapsible-group__header--described .collapsible-group__title { font-size: .95rem; font-weight: 600; }
.collapsible-group__subtitle {
  display: block;
  margin-top: var(--sp-2);
  color: var(--t2);
  font-size: var(--text-base);
  font-weight: 400;
  line-height: 1.55;
}

.collapsible-group__count {
  font-size: var(--text-sm);
  color: var(--t3);
  font-weight: 400;
}

.collapsible-group__suffix {
  font-size: .72rem;
  color: var(--t3);
  font-weight: 400;
}

.collapsible-group__right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 6px;
}

.collapsible-group__body {
  padding-top: 2px;
}
</style>
