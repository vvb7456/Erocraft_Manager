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
:slotted(.batch-controls),
:slotted(.tb-batch) {
  display: flex;
  align-items: center;
  gap: 8px;
}

:slotted(.toolbar-end-row) {
  display: flex;
  align-items: center;
  gap: 8px;
}

:slotted(.toolbar-status),
:slotted(.tb-status),
:slotted(.tb-help) {
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

/* ── Mobile responsive convention classes (since 2026-05) ──
 *
 * Apply these classes on slot children to opt into the
 * standard mobile (≤768px) toolbar layout:
 *   - .tb-search    搜索框 → 单占整行
 *   - .tb-select-group   一组下拉 wrapper → 整行内子元素平分
 *   - .tb-btn-group      一组按钮 wrapper → 整行内子元素平分
 *   - .tb-status / .tb-help / .tb-batch  → 移动端隐藏
 *
 * Layout order on mobile follows DOM order. Recommended:
 *   #start: tb-search
 *   #end:   tb-select-group → tb-btn-group
 */

/* Group wrappers are always flex (desktop = inline horizontal cluster) */
:slotted(.tb-select-group),
:slotted(.tb-btn-group) {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

@media (max-width: 768px) {
  :slotted(.tb-search) {
    width: 100% !important;
    flex: 1 1 100% !important;
    min-width: 0 !important;
    max-width: none !important;
  }

  :slotted(.tb-select-group),
  :slotted(.tb-btn-group) {
    width: 100%;
  }

  :slotted(.tb-select-group) > *,
  :slotted(.tb-btn-group) > * {
    flex: 1 1 0;
    min-width: 0;
  }

  :slotted(.tb-status),
  :slotted(.tb-help),
  :slotted(.tb-batch) {
    display: none !important;
  }
}
</style>
