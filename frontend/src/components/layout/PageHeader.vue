<script setup lang="ts">
/**
 * PageHeader — 复用的页面头部组件
 *
 * 与旧前端 core.js 的行为完全一致：
 * - mobile-menu-btn 在 header 最前面 (768px 以下显示)
 * - page-title-group 在左侧 (icon + title + 可选 badge slot)
 * - top-toolbar 在右侧 (可选 controls slot + theme toggle 始终在最末尾)
 */
import { useAppStore } from '@/stores/app'
import { computed } from 'vue'
import { useRoute, useRouter, type RouteLocationRaw } from 'vue-router'
import ThemeToggle from '@/components/ui/ThemeToggle.vue'
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
const route = useRoute()
const router = useRouter()

const isUserLayout = computed(() => route.meta.layout === 'user')

function toggleView() {
  if (!app.isAdmin) return
  if (isUserLayout.value) {
    router.push({ name: 'dashboard' })
  } else {
    router.push({ name: 'user-servers' })
  }
}

function goCrumb(item: BreadcrumbItem) {
  if (item.to) router.push(item.to)
}
</script>

<template>
  <div class="page-header">
    <button class="mobile-menu-btn" @click="app.toggleMobileSidebar()">
      <MsIcon name="menu" size="md" />
    </button>
    <div class="page-header__main">
      <div class="page-title-group">
        <h2 class="page-header__title">
          <MsIcon :name="icon" :color="iconColor" size="md" />
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
              >&gt;</span>
            </template>
          </span>
          <span v-else>{{ title }}</span>
        </h2>
        <slot name="badge" />
      </div>
      <div class="top-toolbar">
        <slot name="controls" />
        <button
          v-if="app.isAdmin"
          class="header-view-switch"
          :title="isUserLayout ? $t('nav.switchToAdmin') : $t('nav.switchToUser')"
          @click="toggleView"
        >
          <MsIcon :name="isUserLayout ? 'admin_panel_settings' : 'swap_horiz'" size="sm" />
        </button>
        <ThemeToggle />
      </div>
    </div>
  </div>
</template>

<style scoped>
.page-header__main {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}

.page-title-group {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.page-header__title {
  margin: 0;
  display: inline-flex;
  align-items: center;
  line-height: 1.1;
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
  flex-shrink: 0;
}

.header-view-switch {
  border: none;
  background: transparent;
  color: var(--t2);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 999px;
  cursor: pointer;
  transition: color .15s, background .15s;
}

.header-view-switch:hover {
  color: var(--ac2);
  background: color-mix(in srgb, var(--ac) 12%, transparent);
}

@media (max-width: 768px) {
  .page-breadcrumb {
    max-width: 34vw;
  }
}
</style>
