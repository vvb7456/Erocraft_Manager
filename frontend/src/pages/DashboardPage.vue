<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import StatCard from '@/components/ui/StatCard.vue'
import BaseCard from '@/components/ui/BaseCard.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import Spinner from '@/components/ui/Spinner.vue'
import AlertBanner from '@/components/ui/AlertBanner.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import PageHeader from '@/components/layout/PageHeader.vue'

defineOptions({ name: 'DashboardPage' })

const { t } = useI18n({ useScope: 'global' })
const { get, loading, error } = useApiFetch()

interface DashboardData {
  totalUsers: number
  totalServers: number
  normalCount: number
  statusDistribution: {
    normal: number
    expiring_soon: number
    expired: number
    suspended: number
    permanent: number
  }
}

const data = ref<DashboardData | null>(null)
const notConfigured = ref(false)

const normalRate = computed(() => {
  if (!data.value || data.value.totalServers === 0) return '0%'
  return Math.round((data.value.normalCount / data.value.totalServers) * 100) + '%'
})

const expiringSoonCount = computed(() => data.value?.statusDistribution.expiring_soon ?? 0)

const chartBars = computed(() => {
  if (!data.value) return []
  const d = data.value.statusDistribution
  const entries = [
    { label: t('dashboard.status.normal'), count: d.normal, color: 'var(--green)' },
    { label: t('dashboard.status.expiringSoon'), count: d.expiring_soon, color: 'var(--amber)' },
    { label: t('dashboard.status.expired'), count: d.expired, color: 'var(--red)' },
    { label: t('dashboard.status.suspended'), count: d.suspended, color: '#94a3b8' },
    { label: t('dashboard.status.permanent'), count: d.permanent ?? 0, color: 'var(--t3)' },
  ]
  const max = Math.max(...entries.map(e => e.count), 1)
  return entries.map(e => ({ ...e, pct: (e.count / max) * 100 }))
})

onMounted(async () => {
  const res = await get<DashboardData>('/api/dashboard')
  if (res) {
    data.value = res
  } else if (error.value) {
    notConfigured.value = true
  }
})
</script>

<template>
  <PageHeader icon="dashboard" :title="t('dashboard.title')" />

  <div class="page-body">
    <!-- Loading -->
    <div v-if="loading" style="display:flex;justify-content:center;padding:var(--sp-8)">
      <Spinner size="lg" />
    </div>

    <!-- Error / Not Configured -->
    <EmptyState
      v-else-if="notConfigured"
      icon="settings"
      :title="t('dashboard.notConfigured')"
      :message="t('dashboard.notConfiguredMsg')"
    >
      <BaseButton variant="primary" href="#/settings" style="margin-top: var(--sp-3)">
        {{ t('dashboard.goToSettings') }}
      </BaseButton>
    </EmptyState>

    <AlertBanner v-else-if="error" tone="danger" icon="error">
      {{ error }}
    </AlertBanner>

    <!-- Content -->
    <template v-else-if="data">
      <!-- KPI Cards -->
      <div class="stats-grid">
        <StatCard :label="t('dashboard.stats.totalUsers')" status="info">
          <template #value>
            <MsIcon name="group" size="sm" /> {{ data.totalUsers }}
          </template>
        </StatCard>
        <StatCard :label="t('dashboard.stats.totalServers')" status="info">
          <template #value>
            <MsIcon name="dns" size="sm" /> {{ data.totalServers }}
          </template>
        </StatCard>
        <StatCard :label="t('dashboard.stats.normalRate')" status="running">
          <template #value>
            <MsIcon name="check_circle" size="sm" /> {{ normalRate }}
          </template>
        </StatCard>
        <StatCard :label="t('dashboard.stats.expiringSoon')" :status="expiringSoonCount > 0 ? 'running' : 'info'">
          <template #value>
            <MsIcon name="warning" size="sm" /> {{ expiringSoonCount }}
          </template>
        </StatCard>
        <StatCard :label="t('dashboard.stats.expired')" :status="(data?.statusDistribution?.expired ?? 0) > 0 ? 'error' : 'info'">
          <template #value>
            <MsIcon name="error" size="sm" /> {{ data?.statusDistribution?.expired ?? 0 }}
          </template>
        </StatCard>
        <StatCard :label="t('dashboard.stats.suspended')" :status="(data?.statusDistribution?.suspended ?? 0) > 0 ? 'stopped' : 'info'">
          <template #value>
            <MsIcon name="block" size="sm" /> {{ data?.statusDistribution?.suspended ?? 0 }}
          </template>
        </StatCard>
      </div>

      <!-- Status Chart -->
      <BaseCard class="chart-card">
        <template #header>
          <h3 class="chart-title">{{ t('dashboard.chart.title') }}</h3>
        </template>

        <div class="bar-chart">
          <div v-for="bar in chartBars" :key="bar.label" class="bar-row">
            <span class="bar-label">{{ bar.label }}</span>
            <div class="bar-track">
              <div
                class="bar-fill"
                :style="{ width: bar.pct + '%', background: bar.color }"
              />
            </div>
            <span class="bar-count">{{ bar.count }}</span>
          </div>
        </div>
      </BaseCard>
    </template>
  </div>
</template>

<style scoped>
.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: var(--sp-4);
  margin-bottom: var(--sp-6);
}

.chart-card {
  margin-top: var(--sp-2);
}

.chart-title {
  font-size: 1rem;
  font-weight: 600;
  color: var(--t1);
  margin: 0;
}

.bar-chart {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  padding: var(--sp-2) 0;
}

.bar-row {
  display: grid;
  grid-template-columns: 80px 1fr 40px;
  align-items: center;
  gap: var(--sp-3);
}

.bar-label {
  font-size: .82rem;
  color: var(--t2);
  text-align: right;
}

.bar-track {
  height: 24px;
  background: var(--bg3);
  border-radius: var(--rs);
  overflow: hidden;
}

.bar-fill {
  height: 100%;
  border-radius: var(--rs);
  transition: width 0.6s ease;
  min-width: 2px;
}

.bar-count {
  font-size: .88rem;
  font-weight: 600;
  color: var(--t1);
  font-variant-numeric: tabular-nums;
}
</style>
