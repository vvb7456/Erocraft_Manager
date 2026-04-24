<script setup lang="ts">
// Placeholder admin server detail page.
// Full design lives in docs/ADMIN_SERVER_DETAIL_DESIGN.md (TODO).
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '@/components/layout/PageHeader.vue'
import BaseCard from '@/components/ui/BaseCard.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import MsIcon from '@/components/ui/MsIcon.vue'

const route = useRoute()
const router = useRouter()
const serverId = String(route.params.id ?? '')
</script>

<template>
  <PageHeader icon="dns" :title="`服务器 #${serverId}`">
    <template #controls>
      <BaseButton variant="secondary" size="sm" @click="router.push({ name: 'servers' })">
        <MsIcon name="arrow_back" size="xs" /> 返回列表
      </BaseButton>
    </template>
  </PageHeader>

  <div class="page-body">
    <BaseCard variant="bg2">
      <h3 class="section-title">敬请期待</h3>
      <p class="hint">
        管理员服务器详情页正在设计中。完整方案见
        <code>docs/ADMIN_SERVER_DETAIL_DESIGN.md</code>。
      </p>
    </BaseCard>
  </div>
</template>

<style scoped>
.section-title {
  margin: 0 0 var(--sp-2);
  font-size: var(--text-md);
  font-weight: 600;
  color: var(--t1);
}
.hint {
  margin: 0;
  color: var(--t2);
  font-size: var(--text-sm);
}
code {
  font-family: 'IBM Plex Mono', ui-monospace, monospace;
  background: var(--bg3);
  padding: 2px 6px;
  border-radius: var(--r-xs);
  color: var(--ac2);
}
</style>
