<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import MsIcon from '@/components/ui/MsIcon.vue'

defineOptions({ name: 'DashboardActivityRow' })

const props = defineProps<{
  timestamp: string | null
  actor: string
  status: string
  category?: string | null
  detailKey?: string | null
  detailParams?: Record<string, unknown> | null
}>()

const { t, te, tm, rt } = useI18n({ useScope: 'global' })

const timeAgo = computed(() => {
  if (!props.timestamp) return '--'
  const hasTz = /Z|[+-]\d{2}:?\d{2}$/.test(props.timestamp)
  const ts = new Date(hasTz ? props.timestamp : props.timestamp + 'Z').getTime()
  if (Number.isNaN(ts)) return '--'
  const delta = Math.max(0, Math.floor((Date.now() - ts) / 1000))
  if (delta < 60) return `${delta}s`
  if (delta < 3600) return `${Math.floor(delta / 60)}m`
  if (delta < 86400) return `${Math.floor(delta / 3600)}h`
  return `${Math.floor(delta / 86400)}d`
})

const actorLabel = computed(() => {
  if (props.actor === 'system') return t('logs.actor.system', 'system')
  if (props.actor === 'unknown') return t('logs.actor.unknown', 'unknown')
  return props.actor
})

const categoryLabel = computed(() => {
  const cat = props.category || 'other'
  const key = `logs.category.${cat}`
  return te(key) ? t(key) : cat
})

const statusMeta = computed(() => {
  switch (props.status) {
    case 'success': return { icon: 'check_circle', color: 'var(--green)' }
    case 'failure':
    case 'failed': return { icon: 'cancel', color: 'var(--red)' }
    case 'pending': return { icon: 'schedule', color: 'var(--amber)' }
    case 'partial': return { icon: 'warning', color: 'var(--amber)' }
    default: return { icon: 'info', color: 'var(--t3)' }
  }
})

const detailText = computed(() => {
  if (!props.detailKey) return ''
  const params: Record<string, unknown> = { ...(props.detailParams ?? {}) }
  if (typeof params.template === 'string') {
    params.template = t(`emailTemplates.${params.template}.title`, params.template)
  }
  if (typeof params.type === 'string') {
    params.type = t(`logs.reminderType.${params.type}`, params.type)
  }
  if (typeof params.kind === 'string') {
    params.kind = t(`hosts.kind.${params.kind}`, params.kind)
  }
  if (typeof params.language === 'string') {
    params.language = t(`logs.language.${params.language}`, params.language)
  }

  const detailMap = tm('logs.detail') as Record<string, unknown>
  const flat = detailMap?.[props.detailKey]
  if (typeof flat === 'string') return rt(flat, params)

  const escapedPath = `logs.detail.${props.detailKey.replace(/\./g, '\\.')}`
  if (te(escapedPath)) return t(escapedPath, params)
  return props.detailKey
})

const fullTitle = computed(() => {
  const parts = [categoryLabel.value]
  if (detailText.value) parts.push(detailText.value)
  if (props.timestamp) parts.push(props.timestamp)
  return parts.join(' · ')
})
</script>

<template>
  <div class="act-row" :title="fullTitle">
    <span class="ago">{{ timeAgo }}</span>
    <MsIcon :name="statusMeta.icon" size="xs" :style="{ color: statusMeta.color }" class="st" />
    <span class="actor">{{ actorLabel }}</span>
    <span class="action">{{ categoryLabel }}</span>
    <span v-if="detailText" class="sep">·</span>
    <span v-if="detailText" class="detail">{{ detailText }}</span>
  </div>
</template>

<style scoped>
.act-row {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: 6px var(--sp-2);
  border-bottom: 1px solid var(--bd);
  font-size: var(--text-xs);
  color: var(--t2);
  min-width: 0;
}
.act-row:last-child { border-bottom: none; }
.ago {
  font-family: var(--font-mono);
  color: var(--t3);
  font-variant-numeric: tabular-nums;
  width: 38px;
  text-align: right;
  flex-shrink: 0;
}
.st { flex-shrink: 0; }
.actor {
  color: var(--t1);
  font-weight: 600;
  white-space: nowrap;
  flex-shrink: 0;
  max-width: 100px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.action {
  color: var(--t2);
  white-space: nowrap;
  flex-shrink: 0;
}
.sep { color: var(--t3); flex-shrink: 0; }
.detail {
  color: var(--t3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1 1 auto;
  min-width: 0;
}
</style>
