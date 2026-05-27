<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import MsIcon from '@/components/ui/MsIcon.vue'

defineOptions({ name: 'DashboardExpiringRow' })

const props = defineProps<{
  id: number
  name: string
  ownerUsername: string | null
  ownerEmail?: string | null
  nodeName?: string | null
  expiresAt?: string | null
  daysLeft: number
  isSuspended: boolean
}>()

const { t } = useI18n({ useScope: 'global' })
const router = useRouter()

const tone = computed<'red' | 'amber' | 't2'>(() => {
  if (props.daysLeft <= 2) return 'red'
  if (props.daysLeft <= 7) return 'amber'
  return 't2'
})

const expiresShort = computed(() => {
  if (!props.expiresAt) return null
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(props.expiresAt)
  return m ? `${m[2]}-${m[3]}` : props.expiresAt
})

function navigate() {
  router.push(`/admin/servers/${props.id}/overview`)
}
</script>

<template>
  <div class="exp-row" role="button" tabindex="0" @click="navigate" @keyup.enter="navigate">
    <span class="days" :class="`tone-${tone}`">
      <span class="num">{{ Math.max(daysLeft, 0) }}</span><span class="unit">{{ t('dashboard.expiring.daysUnit') }}</span>
    </span>
    <span class="name" :title="name">{{ name }}</span>
    <span v-if="expiresShort" class="exp-date" :title="expiresAt || ''">
      <MsIcon name="event" size="xs" />{{ expiresShort }}
    </span>
    <span class="owner" :title="ownerEmail || ownerUsername || ''">
      <MsIcon name="person" size="xs" />{{ ownerUsername || '—' }}
    </span>
    <span v-if="nodeName" class="node" :title="nodeName">{{ nodeName }}</span>
    <span v-if="isSuspended" class="susp">{{ t('dashboard.status.suspended') }}</span>
  </div>
</template>

<style scoped>
.exp-row {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: 6px var(--sp-2);
  cursor: pointer;
  transition: background .12s ease;
  border-bottom: 1px solid var(--bd);
  font-size: var(--text-xs);
  color: var(--t2);
  min-width: 0;
}
.exp-row:last-child { border-bottom: none; }
.exp-row:hover,
.exp-row:focus-visible {
  background: var(--bg3);
  outline: none;
}

.days {
  display: inline-flex;
  align-items: baseline;
  gap: 1px;
  padding: 2px 6px;
  border-radius: var(--r-sm);
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
  min-width: 44px;
  justify-content: center;
}
.num { font-size: var(--text-sm); font-weight: 700; }
.unit { font-size: 10px; opacity: 0.75; }
.tone-red { background: color-mix(in srgb, var(--red) 16%, transparent); color: var(--red); }
.tone-amber { background: color-mix(in srgb, var(--amber) 16%, transparent); color: var(--amber); }
.tone-t2 { background: var(--bg3); color: var(--t2); }

.name {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--t1);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1 1 auto;
  min-width: 0;
}
.exp-date,
.owner {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  flex-shrink: 0;
  font-family: var(--font-mono);
  color: var(--t3);
}
.owner {
  font-family: inherit;
  color: var(--t2);
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.node {
  padding: 1px 6px;
  border-radius: var(--r-sm);
  background: var(--bg);
  color: var(--t3);
  font-family: var(--font-mono);
  font-size: 10px;
  flex-shrink: 0;
  max-width: 100px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.susp {
  padding: 1px 6px;
  border-radius: var(--r-sm);
  background: color-mix(in srgb, var(--red) 18%, transparent);
  color: var(--red);
  font-weight: 600;
  flex-shrink: 0;
}

/* 移动端隐藏节点信息，避免折行或溢出 */
@media (max-width: 768px) {
  .exp-row .node { display: none; }
}
</style>
