<script setup lang="ts">
import { ref } from 'vue'
import { useAppStore } from '@/stores/app'
import { useHeaderHeight } from '@/composables/useHeaderHeight'
import { usePageHeaderActions } from '@/composables/usePageHeader'
import { useRouter, type RouteLocationRaw } from 'vue-router'
import MsIcon from '../ui/MsIcon.vue'

defineOptions({ name: 'PageHeader' })

interface BreadcrumbItem {
  label: string
  to?: RouteLocationRaw
}

const props = defineProps<{
  icon: string
  iconColor?: string
  title: string
  breadcrumbs?: BreadcrumbItem[]
}>()

const app = useAppStore()
const router = useRouter()
const header = ref<HTMLElement | null>(null)
const actions = usePageHeaderActions()
useHeaderHeight(header)

function goCrumb(item: BreadcrumbItem) {
  if (item.to) router.push(item.to)
}
</script>

<template>
  <div ref="header" class="page-header">
    <div class="page-header__main">
      <div class="page-title-group">
        <button class="mobile-menu-btn" :aria-label="$t('common.sidebar.toggle')" :aria-expanded="app.mobileSidebarOpen" @click="app.toggleMobileSidebar()">
          <MsIcon name="menu" size="md" />
        </button>
        <h2 class="page-header__title">
          <span v-if="props.breadcrumbs?.length" class="page-breadcrumbs">
            <template v-for="(item, index) in props.breadcrumbs" :key="`${index}-${item.label}`">
              <button
                v-if="item.to"
                class="page-breadcrumb"
                type="button"
                @click="goCrumb(item)"
              >
                {{ item.label }}
              </button>
              <span v-else class="page-breadcrumb page-breadcrumb--current">{{ item.label }}</span>
              <span
                v-if="index < props.breadcrumbs.length - 1"
                class="page-breadcrumb__sep"
              >/</span>
            </template>
          </span>
          <span v-else class="page-title-text">{{ title }}</span>
        </h2>
        <slot name="badge" />
      </div>
      <span v-if="$slots.default" class="page-header__divider" aria-hidden="true" />
      <div v-if="$slots.default" class="page-header__tabs"><slot /></div>
      <div ref="actions" class="top-toolbar">
        <slot name="controls" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.page-header { display: flex; align-items: center; position: sticky; top: 0; z-index: 40; flex-shrink: 0; min-height: 66px; padding: 16px clamp(28px, 2.5vw, 42px) 10px; background: var(--bg); container: header / inline-size; }
.page-header__main {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  min-height: 38px;
  gap: 14px;
  flex-wrap: wrap;
}

.page-title-group {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  max-width: 100%;
}
.page-title-text { overflow: hidden; text-overflow: ellipsis; }
.page-header__divider { height: 16px; width: 1px; background: var(--bd); flex-shrink: 0; }
.page-header__tabs { display: flex; align-items: center; min-width: 0; flex: 1; }
@container header (max-width: 760px) {
  .page-header__divider { display: none; }
  .page-header__tabs { flex-basis: 100%; order: 2; }
}

.page-header__title {
  margin: 0;
  display: inline-flex;
  align-items: center;
  font-size: var(--text-lg);
  font-weight: 700;
  letter-spacing: -.015em;
  line-height: 1.4;
  white-space: nowrap;
  min-width: 0;
  gap: 6px;
}

.page-breadcrumbs {
  min-width: 0;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.page-breadcrumb {
  max-width: min(34vw, 360px);
  min-width: 0;
  border: 0;
  padding: 0;
  background: transparent;
  color: var(--t1);
  font: inherit;
  line-height: inherit;
  cursor: pointer;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.page-breadcrumb:hover {
  color: var(--ac2);
}

.page-breadcrumb--current {
  cursor: default;
}

.page-breadcrumb__sep {
  color: var(--t3);
  flex-shrink: 0;
}

.top-toolbar {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin-left: auto;
  max-width: 100%;
  flex-wrap: wrap;
}
.top-toolbar:empty { display: none; }
.mobile-menu-btn { display: none; align-items: center; justify-content: center; flex-shrink: 0; padding: var(--sp-1); border: 0; border-radius: var(--r-sm); background: none; color: var(--t2); cursor: pointer; }
.mobile-menu-btn:hover { color: var(--ac); }

@media (max-width: 768px) {
  .page-header { padding: 12px 16px 8px; min-height: 58px; }
  .mobile-menu-btn { display: inline-flex; }
  .page-breadcrumb {
    max-width: 34vw;
  }
}
</style>
