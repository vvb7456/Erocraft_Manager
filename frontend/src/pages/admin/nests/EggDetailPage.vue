<script setup lang="ts">
import { computed, provide, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { apiErrorMessage } from '@/composables/apiClient'
import { useToast } from '@/composables/useToast'
import {
  getEgg,
  type AffectedPlanWarning,
  type EggDetailOut,
} from '@/api/adminNestsEggs'
import PageHeader from '@/components/layout/PageHeader.vue'
import TabSwitcher from '@/components/ui/TabSwitcher.vue'
import LoadingCenter from '@/components/ui/LoadingCenter.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import AlertBanner from '@/components/ui/AlertBanner.vue'
import Badge from '@/components/ui/Badge.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import MsIcon from '@/components/ui/MsIcon.vue'

defineOptions({ name: 'EggDetailPage' })

const { t } = useI18n({ useScope: 'global' })
const route = useRoute()
const router = useRouter()
const { toast } = useToast()

const eggId = computed(() => Number(route.params.eggId))
const egg = ref<EggDetailOut | null>(null)
const loading = ref(false)
const loadError = ref('')
const affectedPlans = ref<AffectedPlanWarning[]>([])

async function loadEgg(silent = false) {
  if (!Number.isFinite(eggId.value)) {
    loadError.value = ''
    return
  }
  if (!silent) {
    loading.value = true
    loadError.value = ''
  }
  try {
    egg.value = await getEgg(eggId.value)
    loadError.value = ''
  } catch (err) {
    const msg = apiErrorMessage(err)
    loadError.value = msg
    toast(msg, 'error')
  } finally {
    if (!silent) loading.value = false
  }
}

function setEgg(next: EggDetailOut) {
  egg.value = next
}

function setAffectedPlans(plans: AffectedPlanWarning[]) {
  affectedPlans.value = plans
}

provide('eggDetail', egg)
provide('reloadEgg', () => loadEgg(true))
provide('setEggDetail', setEgg)
provide('setAffectedPlans', setAffectedPlans)

const tabs = computed(() => [
  { key: 'egg-settings', label: t('nests.egg.tabs.settings'), icon: 'settings' },
  { key: 'egg-variables', label: t('nests.egg.tabs.variables'), icon: 'tune' },
  { key: 'egg-scripts', label: t('nests.egg.tabs.scripts'), icon: 'terminal' },
])

const activeTab = computed(() => {
  const name = route.name as string | undefined
  return name && tabs.value.some(tab => tab.key === name) ? name : 'egg-settings'
})

const breadcrumbs = computed(() => [
  { label: t('nests.title'), to: { name: 'nests' } },
  {
    label: egg.value?.name || (Number.isFinite(eggId.value) ? `#${eggId.value}` : t('nests.egg.notFoundTitle')),
  },
])

watch(
  eggId,
  (id, prev) => {
    if (!Number.isFinite(id)) {
      egg.value = null
      affectedPlans.value = []
      loadError.value = ''
      return
    }
    if (id !== prev) {
      egg.value = null
      affectedPlans.value = []
      loadError.value = ''
    }
    void loadEgg(false)
  },
  { immediate: true },
)

function onTabChange(key: string) {
  void router.push({ name: key, params: { eggId: eggId.value } })
}

function goPlans() {
  void router.push({ name: 'admin-plans' })
}

function goNests() {
  void router.push({ name: 'nests', query: { tab: 'eggs' } })
}
</script>

<template>
  <LoadingCenter v-if="loading && !egg" />

  <template v-else>
    <PageHeader
      icon="deployed_code"
      :title="egg?.name || (Number.isFinite(eggId) ? `#${eggId}` : t('nests.egg.notFoundTitle'))"
      :breadcrumbs="breadcrumbs"
    >
      <TabSwitcher v-if="egg" :tabs="tabs" :model-value="activeTab" @update:model-value="onTabChange" />
    </PageHeader>

    <div class="page-body">
      <EmptyState
        v-if="!egg"
        icon="error_outline"
        :title="t('nests.egg.notFoundTitle')"
        :message="loadError || t('nests.egg.notFoundDesc')"
      >
        <BaseButton variant="default" @click="goNests">
          <MsIcon name="arrow_back" size="xs" /> {{ t('nests.egg.backToList') }}
        </BaseButton>
        <BaseButton v-if="Number.isFinite(eggId)" variant="primary" @click="loadEgg(false)">
          <MsIcon name="refresh" size="xs" /> {{ t('common.btn.retry') }}
        </BaseButton>
      </EmptyState>

      <template v-else>
        <AlertBanner
          v-if="affectedPlans.length > 0"
          tone="warning"
          closable
          class="affected-banner"
          @close="affectedPlans = []"
        >
          <div class="affected-plans">
            <div class="affected-plans__head">
              <strong>{{ t('nests.affectedPlans.title', { n: affectedPlans.length }) }}</strong>
              <BaseButton size="sm" variant="default" @click="goPlans">
                <MsIcon name="open_in_new" size="xs" /> {{ t('nests.affectedPlans.goPlans') }}
              </BaseButton>
            </div>
            <p class="affected-plans__desc">{{ t('nests.affectedPlans.desc') }}</p>
            <ul class="affected-plans__list">
              <li v-for="plan in affectedPlans" :key="plan.id">
                <span class="plan-name">{{ plan.name }}</span>
                <code>{{ plan.code }}</code>
                <Badge size="sm" :color="plan.is_active ? 'var(--amber)' : 'var(--t3)'">
                  {{ plan.is_active ? t('nests.affectedPlans.active') : t('nests.affectedPlans.inactive') }}
                </Badge>
                <span class="plan-reason">{{ plan.reason }}</span>
              </li>
            </ul>
          </div>
        </AlertBanner>
        <RouterView :key="eggId" />
      </template>
    </div>
  </template>
</template>

<style scoped>
.affected-banner {
  margin-bottom: var(--sp-4);
}
.affected-plans {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}
.affected-plans__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-2);
  flex-wrap: wrap;
}
.affected-plans__desc {
  margin: 0;
  color: var(--t2);
  font-size: var(--text-xs);
}
.affected-plans__list {
  margin: var(--sp-1) 0 0;
  padding-left: 18px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.affected-plans__list li {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
  font-size: var(--text-xs);
}
.plan-name {
  font-weight: 600;
  color: var(--t1);
}
.plan-reason {
  color: var(--t2);
}
</style>
