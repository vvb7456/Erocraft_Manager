<script setup lang="ts">
// CreateAllocationsModal — bulk create node allocations.
// Mirrors the Pterodactyl Panel "Allocations → Assign Ports" modal:
//   IP (default 0.0.0.0) + alias (default node FQDN) + port expression.
// Live preview of expanded port count gives the operator immediate
// feedback before they submit.
//
// Backend contract:
//   POST /api/admin/hosts/{host_id}/allocations
//   body: { ip: string, alias?: string, ports: string }
//   201 → { created: AllocationOut[], skipped: [{port, reason}] }
//   400 → invalid ip/expression (i18n key under common.apiErrors)
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'

import BaseModal from '@/components/ui/BaseModal.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import FormField from '@/components/form/FormField.vue'
import HelpTip from '@/components/ui/HelpTip.vue'
import MsIcon from '@/components/ui/MsIcon.vue'

defineOptions({ name: 'CreateAllocationsModal' })

const props = defineProps<{
  modelValue: boolean
  hostId: number
  defaultAlias?: string
}>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  'created': []
}>()

const { t } = useI18n({ useScope: 'global' })
const { post } = useApiFetch()
const { toast } = useToast()

const ip = ref('0.0.0.0')
const alias = ref('')
const ports = ref('')
const submitting = ref(false)

watch(() => props.modelValue, (open) => {
  if (open) {
    ip.value = '0.0.0.0'
    alias.value = props.defaultAlias || ''
    ports.value = ''
    submitting.value = false
  }
})

// Mirrors backend `app/api/utils/port_expression.py`:
//   "8000,8005-8010,9000" → set of distinct ports in [1, 65535].
// We replicate parsing client-side strictly for the live preview;
// the backend remains the single source of truth.
const PORT_MIN = 1
const PORT_MAX = 65535
const TOKEN_RE = /^(\d+)(?:-(\d+))?$/

interface Preview {
  count: number
  error: string | null
}

const preview = computed<Preview>(() => {
  const expr = ports.value.trim()
  if (!expr) return { count: 0, error: null }
  const out = new Set<number>()
  for (const raw of expr.split(',')) {
    const tok = raw.trim()
    if (!tok) continue
    const m = TOKEN_RE.exec(tok)
    if (!m) return { count: 0, error: tok }
    const a = Number(m[1])
    const b = m[2] !== undefined ? Number(m[2]) : a
    if (!Number.isFinite(a) || !Number.isFinite(b)) return { count: 0, error: tok }
    if (a < PORT_MIN || b < PORT_MIN || a > PORT_MAX || b > PORT_MAX) return { count: 0, error: tok }
    const lo = Math.min(a, b)
    const hi = Math.max(a, b)
    for (let p = lo; p <= hi; p += 1) out.add(p)
  }
  return { count: out.size, error: null }
})

const canSubmit = computed(() => {
  if (submitting.value) return false
  if (!ip.value.trim()) return false
  if (!ports.value.trim()) return false
  if (preview.value.error) return false
  if (preview.value.count <= 0) return false
  return true
})

async function submit() {
  if (!canSubmit.value) return
  submitting.value = true
  try {
    const body: Record<string, unknown> = {
      ip: ip.value.trim(),
      ports: ports.value.trim(),
    }
    if (alias.value.trim()) body.alias = alias.value.trim()
    const res = await post<{
      created: { id: number; port: number }[]
      skipped: { port: number; reason: string }[]
    }>(`/api/admin/hosts/${props.hostId}/allocations`, body)
    if (!res) return  // useApiFetch already toasted the error
    const c = res.created.length
    const s = res.skipped.length
    toast(
      s > 0
        ? t('hosts.allocations.create.toastSkipped', { created: c, skipped: s })
        : t('hosts.allocations.create.toastOk', { created: c }),
      s > 0 ? 'warning' : 'success',
    )
    emit('created')
    emit('update:modelValue', false)
  } catch (err: any) {
    toast(err?.message || t('hosts.allocations.create.failed'), 'error')
  } finally {
    submitting.value = false
  }
}

function cancel() {
  if (submitting.value) return
  emit('update:modelValue', false)
}
</script>

<template>
  <BaseModal
    :modelValue="modelValue"
    @update:modelValue="emit('update:modelValue', $event)"
    :title="t('hosts.allocations.create.title')"
    icon="add_circle"
    size="md"
  >
    <div class="form-grid">
      <FormField layout="horizontal" bordered>
        <template #label>
          {{ t('hosts.allocations.create.ip') }}
          <HelpTip :text="t('hosts.allocations.create.ipHint')" />
        </template>
        <BaseInput v-model="ip" mono placeholder="0.0.0.0" />
      </FormField>

      <FormField layout="horizontal" bordered>
        <template #label>
          {{ t('hosts.allocations.create.alias') }}
          <HelpTip :text="t('hosts.allocations.create.aliasHint')" />
        </template>
        <BaseInput v-model="alias" placeholder="node.example.com" />
      </FormField>

      <FormField layout="horizontal" bordered>
        <template #label>
          {{ t('hosts.allocations.create.ports') }}
          <HelpTip :text="t('hosts.allocations.create.portsHint')" />
        </template>
        <BaseInput v-model="ports" mono placeholder="8000,8005-8010,9000" />
      </FormField>

      <div
        v-if="preview.error || preview.count > 0"
        class="preview"
        :class="{ 'preview--err': !!preview.error }"
      >
        <MsIcon
          :name="preview.error ? 'error' : 'check_circle'"
          size="xs"
        />
        <span v-if="preview.error">
          {{ t('hosts.allocations.create.previewError', { err: preview.error }) }}
        </span>
        <span v-else>
          {{ t('hosts.allocations.create.preview', { n: preview.count }) }}
        </span>
      </div>
    </div>

    <template #footer>
      <BaseButton variant="default" :disabled="submitting" @click="cancel">
        {{ t('hosts.allocations.create.cancel') }}
      </BaseButton>
      <BaseButton
        variant="primary"
        :loading="submitting"
        :disabled="!canSubmit"
        @click="submit"
      >
        {{ t('hosts.allocations.create.submit') }}
      </BaseButton>
    </template>
  </BaseModal>
</template>

<style scoped>
.form-grid {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}

.preview {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-2) var(--sp-3);
  font-size: var(--text-sm);
  color: var(--t2);
  min-height: 1.6em;
}
.preview--err { color: var(--red); }
</style>
