<script setup lang="ts">
import { computed, ref, watch, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import MsIcon from '@/components/ui/MsIcon.vue'
import Spinner from '@/components/ui/Spinner.vue'
import AgreementViewer from './AgreementViewer.vue'

defineOptions({ name: 'AgreementCheckboxGroup' })

interface RequiredAgreement {
  agreement_id: number
  slug: string
  scope: string
  version: number
  title: string
  body_md: string
}

const props = withDefaults(defineProps<{
  context: 'register' | 'purchase'
  eggId?: number | null
  modelValue: { agreement_id: number; version: number }[]
  defaultChecked?: boolean
}>(), {
  defaultChecked: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: { agreement_id: number; version: number }[]]
  'update:allAccepted': [value: boolean]
}>()

const { t, locale } = useI18n({ useScope: 'global' })

const loading = ref(false)
const agreements = ref<RequiredAgreement[]>([])
const acceptedIds = ref<Set<number>>(new Set())
const viewerSlug = ref<string | null>(null)
const viewerOpen = ref(false)
/** Set once the user manually toggles the checkbox, so a late-arriving
 * `defaultChecked` change (branding fetch resolving after mount) does
 * not override the user's explicit choice. */
const userTouched = ref(false)

function toggleAll() {
  userTouched.value = true
  const allOn = agreements.value.every(a => acceptedIds.value.has(a.agreement_id))
  const next = new Set(acceptedIds.value)
  if (allOn) {
    for (const a of agreements.value) next.delete(a.agreement_id)
  } else {
    for (const a of agreements.value) next.add(a.agreement_id)
  }
  acceptedIds.value = next
  emitChange()
}

function openViewer(slug: string) {
  viewerSlug.value = slug
  viewerOpen.value = true
}

const allAccepted = computed(() => {
  if (!agreements.value.length) return true
  return agreements.value.every(a => acceptedIds.value.has(a.agreement_id))
})

function emitChange() {
  const items = agreements.value
    .filter(a => acceptedIds.value.has(a.agreement_id))
    .map(a => ({ agreement_id: a.agreement_id, version: a.version }))
  emit('update:modelValue', items)
  emit('update:allAccepted', allAccepted.value)
}

async function load() {
  loading.value = true
  try {
    const params = new URLSearchParams()
    params.set('context', props.context)
    params.set('locale', locale.value)
    if (props.context === 'purchase' && props.eggId != null) {
      params.set('egg_id', String(props.eggId))
    }
    const res = await fetch(`/api/public/agreements?${params.toString()}`)
    if (!res.ok) {
      agreements.value = []
      return
    }
    agreements.value = (await res.json()) as RequiredAgreement[]
    acceptedIds.value = new Set()
    if (props.defaultChecked) {
      for (const a of agreements.value) acceptedIds.value.add(a.agreement_id)
    }
    emitChange()
  } catch {
    agreements.value = []
  } finally {
    loading.value = false
  }
}

watch(() => [props.context, props.eggId] as const, () => load())
// If branding (defaultChecked) resolves after the agreements list has
// already loaded, apply the default — but only if the user hasn't
// touched the checkbox in the meantime (their explicit choice wins).
watch(() => props.defaultChecked, (checked) => {
  if (!checked || userTouched.value || !agreements.value.length) return
  const next = new Set(acceptedIds.value)
  for (const a of agreements.value) next.add(a.agreement_id)
  acceptedIds.value = next
  emitChange()
})
onMounted(load)
</script>

<template>
  <div v-if="loading" class="agreement-loading">
    <Spinner size="sm" />
    <span>{{ t('agreements.viewer.loading') }}</span>
  </div>

  <label v-else class="agreement-inline" :class="{ 'agreement-inline--checked': allAccepted }">
    <span
      class="agreement-check"
      :class="{ 'agreement-check--on': allAccepted }"
      @click.prevent="toggleAll"
      @keydown.space.prevent="toggleAll"
      tabindex="0"
      role="checkbox"
      :aria-checked="allAccepted"
    >
      <MsIcon v-if="allAccepted" name="check" size="sm" />
    </span>
    <span class="agreement-text">
      {{ t('agreements.checkbox.label_prefix') }}<a
        href="#"
        class="agreement-link"
        @click.prevent="openViewer('tos')"
      >{{ t('agreements.checkbox.open_tos') }}</a>{{ t('agreements.checkbox.label_mid') }}<a
        href="#"
        class="agreement-link"
        @click.prevent="openViewer('privacy')"
      >{{ t('agreements.checkbox.open_privacy') }}</a>{{ t('agreements.checkbox.label_suffix') }}
    </span>
  </label>

  <AgreementViewer
    v-if="viewerSlug"
    v-model="viewerOpen"
    :slug="viewerSlug"
  />
</template>

<style scoped>
.agreement-loading {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  color: var(--t3);
  font-size: .8rem;
  padding: var(--sp-2) 0;
}

.agreement-inline {
  display: flex;
  align-items: flex-start;
  gap: var(--sp-2);
  cursor: pointer;
  user-select: none;
}

.agreement-check {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  min-width: 16px;
  border: 1.5px solid var(--bd);
  border-radius: 4px;
  color: var(--bg);
  cursor: pointer;
  transition: background .15s ease, border-color .15s ease;
  margin-top: 2px;
}

.agreement-check--on {
  background: var(--ac);
  border-color: var(--ac);
}

.agreement-text {
  font-size: .82rem;
  line-height: 1.5;
  color: var(--t2);
}

.agreement-link {
  color: var(--ac);
  cursor: pointer;
  font-size: inherit;
  text-decoration: none;
  transition: text-decoration .15s ease;
}

.agreement-link:hover {
  text-decoration: underline;
}
</style>
