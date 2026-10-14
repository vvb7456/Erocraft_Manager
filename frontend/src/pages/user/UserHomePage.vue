<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAppStore } from '@/stores/app'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToday } from '@/composables/useToday'
import PageHeader from '@/components/layout/PageHeader.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import LoadingCenter from '@/components/ui/LoadingCenter.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import SupportModal from '@/components/billing/SupportModal.vue'

interface HomeServer {
  id: number
  name: string
  eggName: string
  planName: string | null
  daysLeft: number | null
  isSuspended: boolean
  isInstalling: boolean
}

const { t, locale } = useI18n()
const app = useAppStore()
const { get } = useApiFetch()
const today = useToday()
const dateLabel = computed(() => new Intl.DateTimeFormat(locale.value, {
  timeZone: 'UTC', year: 'numeric', month: 'long', day: 'numeric', weekday: 'long',
}).format(new Date(`${today.value}T12:00:00Z`)))
const servers = ref<HomeServer[] | null>(null)
const loading = ref(true)
const supportOpen = ref(false)
const previewServers = computed(() => servers.value?.slice(0, 3) ?? [])
const featureState = computed(() => {
  if (!servers.value?.length) return 'empty'
  return servers.value.some(server => server.daysLeft !== null && server.daysLeft <= 7) ? 'renewal' : 'normal'
})

async function load() {
  loading.value = true
  servers.value = await get<HomeServer[]>('/api/user/servers?scope=owner')
  loading.value = false
}

function serverNote(server: HomeServer) {
  if (server.isInstalling) return t('userServers.status.installing')
  if (server.isSuspended) return t('userServers.status.suspended')
  if (server.daysLeft === null) return t('userServers.permanent')
  return server.daysLeft < 0 ? t('userServers.expired') : t('userServers.daysLeft', { n: server.daysLeft })
}

onMounted(load)
</script>

<template>
  <PageHeader icon="home" :title="t('userHome.title')" />
  <div class="home-page">
    <header class="welcome">
      <div class="welcome-meta"><span>{{ app.displayName }}</span><time :datetime="today">{{ dateLabel }}</time></div>
      <h1>{{ t('userHome.greeting', { name: app.sessionUser?.username }) }}</h1>
      <p>{{ t('userHome.intro') }}</p>
    </header>

    <div class="home-grid">
      <section class="services" aria-labelledby="home-servers-title" :aria-busy="loading">
        <div class="section-heading">
          <h2 id="home-servers-title">{{ t('userServers.title') }}<span v-if="servers" class="service-count">{{ servers.length }}</span></h2>
          <RouterLink class="text-link" :to="{ name: 'user-servers' }"><span class="text-link__label">{{ t('userHome.viewAll') }}</span><MsIcon name="arrow_forward" size="xs" /></RouterLink>
        </div>
        <LoadingCenter v-if="loading" class="services-loading" />
        <div v-else-if="!servers" class="services-empty">
          <p>{{ t('userHome.loadFailed') }}</p>
          <BaseButton size="sm" @click="load">{{ t('userHome.retry') }}</BaseButton>
        </div>
        <ul v-else-if="servers.length" class="server-list">
          <li v-for="server in previewServers" :key="server.id">
            <RouterLink class="server-entry" :to="{ name: 'server-console', params: { id: server.id } }">
              <span class="server-mark"><MsIcon name="dns" size="md" /></span>
              <span class="server-identity"><strong>{{ server.name }}</strong><small>{{ server.planName || server.eggName }}</small></span>
              <span class="server-note" :class="{ 'server-note--attention': server.isSuspended || (server.daysLeft !== null && server.daysLeft <= 7) }">{{ serverNote(server) }}</span>
              <MsIcon name="chevron_right" size="sm" class="entry-arrow" />
            </RouterLink>
          </li>
        </ul>
        <div v-else class="services-empty">
          <span class="empty-mark"><MsIcon name="dns" size="lg" /></span>
          <h3>{{ t('userHome.emptyTitle') }}</h3>
          <p>{{ t('userHome.emptyHint') }}</p>
        </div>
      </section>

      <RouterLink v-if="servers" class="feature" :class="`feature--${featureState}`" :to="{ name: featureState === 'empty' ? 'user-plans' : 'user-servers' }">
        <span v-if="featureState === 'empty'" class="feature-label">{{ t('userHome.feature.empty.label') }}</span>
        <svg class="feature-art" viewBox="0 0 320 200" fill="none" aria-hidden="true">
          <g v-if="featureState === 'normal'">
            <path class="feature-art__surface" d="M68 30h166a16 16 0 0 1 16 16v72a16 16 0 0 1-16 16H112l-28 24v-24H68a16 16 0 0 1-16-16V46a16 16 0 0 1 16-16Z" />
            <path class="feature-art__surface" d="M186 110h76a12 12 0 0 1 12 12v38a12 12 0 0 1-12 12h-4v16l-22-16h-50a12 12 0 0 1-12-12v-38a12 12 0 0 1 12-12Z" />
            <path d="M86 65h130M86 86h92M198 140h52" />
          </g>
          <g v-else-if="featureState === 'renewal'">
            <circle class="feature-art__clock" cx="160" cy="88" r="59" />
            <circle class="feature-art__clock" cx="160" cy="88" r="48" />
            <path d="M160 55v36l25 16M160 34v8M160 134v8M106 88h8M206 88h8M102 172h116" />
          </g>
          <g v-else>
            <ellipse cx="173" cy="165" rx="108" ry="19" />
            <path class="feature-art__surface" d="m70 108 102 48 100-48-100-48Z" />
            <path class="feature-art__surface" d="m70 82 102 48 100-48-100-48Z" />
            <path class="feature-art__surface" d="m70 56 102 48 100-48-100-48Z" />
            <path d="M70 56v52m102-4v52m100-100v52" />
            <path class="feature-art__surface" d="m113 56 59 28 57-28-57-28Z" />
            <circle cx="172" cy="56" r="6" />
          </g>
        </svg>
        <div class="feature-heading">
          <h2>{{ t(`userHome.feature.${featureState}.title`) }}</h2>
          <p v-if="featureState !== 'empty'" class="feature-description">{{ t(`userHome.feature.${featureState}.description`) }}</p>
        </div>
        <span class="feature-action">{{ t(`userHome.feature.${featureState}.action`) }}<span class="feature-arrow"><MsIcon name="arrow_forward" size="md" /></span></span>
      </RouterLink>
      <div v-else class="feature feature--placeholder" aria-hidden="true"><span /><span /><span /></div>
    </div>

    <nav class="home-links" :aria-label="t('userHome.quickLinks')">
      <RouterLink class="home-link" :to="{ name: 'user-orders' }"><MsIcon name="receipt_long" size="md" /><span><strong>{{ t('billing.orders.pageTitle') }}</strong><small>{{ t('userHome.ordersHint') }}</small></span><MsIcon name="arrow_forward" size="sm" /></RouterLink>
      <RouterLink class="home-link" :to="{ name: 'user-promotions' }"><MsIcon name="redeem" size="md" /><span><strong>{{ t('nav.promotions') }}</strong><small>{{ t('userHome.promotionsHint') }}</small></span><MsIcon name="arrow_forward" size="sm" /></RouterLink>
      <a v-if="app.tutorialUrl" class="home-link" :href="app.tutorialUrl" target="_blank" rel="noopener noreferrer"><MsIcon name="menu_book" size="md" /><span><strong>{{ t('nav.tutorial') }}</strong><small>{{ t('userHome.tutorialHint') }}</small></span><MsIcon name="open_in_new" size="sm" /></a>
    </nav>
    <footer class="home-footer"><span>{{ t('userHome.help') }}</span><button type="button" class="text-link" @click="supportOpen = true"><span class="text-link__label">{{ t('billing.support.title') }}</span><MsIcon name="arrow_forward" size="xs" /></button></footer>
  </div>
  <SupportModal v-model="supportOpen" />
</template>

<style scoped>
.home-page { width: 100%; max-width: 1120px; margin: 0 auto; padding: 36px 40px 48px; }
.welcome { padding-bottom: 36px; }
.welcome-meta { display: flex; justify-content: space-between; flex-wrap: wrap; gap: var(--sp-2); color: var(--t3); font-size: var(--text-xs); letter-spacing: .04em; }
.welcome-meta > span { overflow-wrap: anywhere; }
.welcome h1 { margin: 22px 0 var(--sp-3); font-size: clamp(1.8rem, 3.5vw, 2.8rem); font-weight: 500; line-height: 1.3; letter-spacing: -.045em; overflow-wrap: anywhere; text-wrap: balance; }
.welcome p { color: var(--t2); font-size: var(--text-md); }
.home-grid { display: grid; grid-template-columns: minmax(0, 1.45fr) minmax(0, 1fr); gap: 40px; padding-bottom: 36px; }
.services { display: flex; flex-direction: column; min-width: 0; border-top: 1px solid var(--bd); }
.section-heading { display: flex; flex-shrink: 0; align-items: center; justify-content: space-between; gap: var(--sp-3); padding: var(--sp-5) 0 var(--sp-3); }
.section-heading h2 { display: flex; align-items: baseline; gap: var(--sp-2); font-size: var(--text-lg); font-weight: 500; }
.service-count { color: var(--t3); font-family: var(--font-tabular); font-size: var(--text-sm); }
.text-link { display: inline-flex; align-items: center; gap: var(--sp-2); border: 0; padding: 0; background: transparent; color: var(--ac); font: inherit; font-size: var(--text-sm); text-decoration: none; cursor: pointer; white-space: nowrap; }
.text-link:hover { color: var(--ac2); }
.text-link:hover .text-link__label { text-decoration: underline; text-underline-offset: 4px; }
.services-loading, .services-empty { flex: 1; min-height: 260px; }
.services-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: var(--sp-3); padding: var(--sp-4); color: var(--t2); text-align: center; }
.empty-mark { margin-bottom: var(--sp-2); color: var(--t3); }
.services-empty h3 { font-size: var(--text-xl); font-weight: 500; color: var(--t1); }
.services-empty p { font-size: var(--text-base); }
.server-list { list-style: none; }
.server-list li + li { border-top: 1px solid var(--bd); }
.server-entry { display: flex; align-items: center; gap: var(--sp-3); min-height: 84px; padding: var(--sp-4) 0; text-decoration: none; color: var(--t1); }
.server-mark { display: grid; place-items: center; flex-shrink: 0; width: 42px; height: 46px; background: var(--bg2); border: 1px solid var(--bd); border-radius: var(--r-md); color: var(--t2); transition: color .15s, border-color .15s; }
.server-identity { flex: 1; min-width: 0; display: grid; gap: var(--sp-1); }
.server-identity strong { font-size: var(--text-base); font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.server-identity small { color: var(--t3); font-size: var(--text-xs); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.server-note { color: var(--t3); font-size: var(--text-xs); white-space: nowrap; }
.server-note--attention { color: var(--amber); }
.entry-arrow { color: var(--t3); }
.server-entry:hover .server-mark { color: var(--ac); border-color: var(--ac); }
.server-entry:hover .entry-arrow { color: var(--ac); }
.feature { display: flex; flex-direction: column; min-width: 0; min-height: 360px; padding: var(--sp-6) var(--sp-8); border: 1px solid color-mix(in srgb, var(--ac) 22%, var(--bd)); border-radius: var(--r-lg); background: color-mix(in srgb, var(--ac) 8%, var(--bg2)); color: var(--t1); text-decoration: none; transition: border-color .2s, background .2s; }
.feature--empty { background: var(--bg2); }
.feature-label { font-size: var(--text-xs); color: var(--ac); }
.feature-art { display: block; align-self: center; width: 100%; max-width: 290px; height: 170px; color: var(--ac); stroke: currentColor; stroke-width: 1; stroke-linecap: round; stroke-linejoin: round; }
.feature-art ellipse { opacity: .15; }
.feature-art__surface { fill: color-mix(in srgb, var(--ac) 6%, var(--bg2)); }
.feature-art circle { fill: currentColor; stroke: none; }
.feature-art .feature-art__clock { fill: none; stroke: currentColor; }
.feature-heading { margin-top: auto; }
.feature h2 { font-size: clamp(1.45rem, 2.1vw, 1.9rem); font-weight: 500; line-height: 1.45; letter-spacing: -.03em; white-space: pre-line; text-wrap: balance; }
.feature-description { margin-top: var(--sp-2); color: var(--t2); font-size: var(--text-base); line-height: 1.6; }
.feature-action { display: flex; align-items: center; justify-content: space-between; gap: var(--sp-3); margin-top: var(--sp-5); font-size: var(--text-sm); color: var(--ac); }
.feature-arrow { display: grid; place-items: center; flex-shrink: 0; width: 34px; height: 34px; border: 1px solid color-mix(in srgb, var(--ac) 35%, transparent); border-radius: 50%; color: var(--ac); transition: transform .2s; }
a.feature:hover { border-color: var(--ac); background: color-mix(in srgb, var(--ac) 12%, var(--bg2)); }
.feature:hover .feature-arrow { transform: translateX(3px); }
.feature--placeholder { justify-content: flex-end; gap: var(--sp-4); border-color: var(--bd); background: var(--bg2); }
.feature--placeholder span { width: 75%; height: 20px; border-radius: var(--r-xs); background: var(--bg3); }
.feature--placeholder span:last-child { width: 40%; height: 12px; }
.home-links { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 220px), 1fr)); border-block: 1px solid var(--bd); }
.home-link { display: flex; align-items: center; gap: var(--sp-3); padding: var(--sp-6) var(--sp-4); color: var(--t2); text-decoration: none; transition: background .15s; }
.home-link > span:not(.ms) { display: grid; gap: var(--sp-1); flex: 1; min-width: 0; }
.home-link strong { color: var(--t1); font-size: var(--text-base); font-weight: 500; }
.home-link small { color: var(--t3); font-size: var(--text-xs); }
.home-link:hover { background: var(--bg2); color: var(--ac); }
.home-footer { display: flex; align-items: center; justify-content: flex-end; flex-wrap: wrap; gap: var(--sp-3); padding-top: var(--sp-5); color: var(--t3); font-size: var(--text-xs); }
.home-page :is(a, button):focus-visible { outline: 2px solid var(--ac); outline-offset: 5px; border-radius: var(--r-xs); }
@media (max-width: 1000px) { .home-page { padding: var(--sp-6); } .home-grid { gap: var(--sp-6); } .feature { padding: var(--sp-5); } }
@media (max-width: 700px) { .home-page { padding: var(--sp-5) var(--sp-4) var(--sp-8); } .welcome { padding-bottom: var(--sp-6); } .home-grid { grid-template-columns: minmax(0, 1fr); padding-bottom: var(--sp-6); } .feature { position: relative; overflow: hidden; min-height: 218px; padding: var(--sp-6); } .feature-art { position: absolute; right: -42px; top: 8px; width: 220px; opacity: .3; } .feature-label, .feature-heading, .feature-action { position: relative; } .feature--empty .feature-heading { margin-top: var(--sp-6); } .feature-action { margin-top: var(--sp-4); } .services-loading, .services-empty { min-height: 210px; } }
@media (max-width: 480px) { .home-links { grid-template-columns: minmax(0, 1fr); } .home-link { padding: var(--sp-4) 0; } .home-link + .home-link { border-top: 1px solid var(--bd); } .home-footer { justify-content: flex-start; } }
@media (prefers-reduced-motion: reduce) { .feature, .feature-arrow, .server-mark, .home-link { transition: none; } }
</style>
