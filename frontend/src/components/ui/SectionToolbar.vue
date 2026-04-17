<script setup lang="ts">
defineOptions({ name: 'SectionToolbar' })
</script>

<template>
  <div class="section-toolbar">
    <div v-if="$slots.start" class="section-toolbar-start">
      <slot name="start" />
    </div>
    <div v-if="$slots.end" class="section-toolbar-end">
      <slot name="end" />
    </div>
  </div>
</template>

<style scoped>
.section-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.section-toolbar-start {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  flex-wrap: wrap;
  min-width: 0;
}

.section-toolbar-end {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  min-width: 0;
}

.section-toolbar-end {
  margin-left: auto;
}

@media (max-width: 720px) {
  .section-toolbar-start,
  .section-toolbar-end {
    width: 100%;
  }

  .section-toolbar-end {
    margin-left: 0;
    justify-content: flex-start;
  }
}

/* ── Slot content utilities ── */
:slotted(.batch-controls) {
  display: flex;
  align-items: center;
  gap: 8px;
}

:slotted(.toolbar-end-row) {
  display: flex;
  align-items: center;
  gap: 8px;
}

:slotted(.toolbar-status) {
  font-size: .82rem;
  color: var(--t3);
  white-space: nowrap;
}

@media (max-width: 768px) {
  :slotted(.batch-controls) {
    display: none;
  }

  :slotted(.toolbar-end-row) {
    width: 100%;
  }

  :slotted(.toolbar-half) {
    flex: 1;
    min-width: 0;
  }
}
</style>
