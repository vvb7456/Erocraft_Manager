<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { apiErrorMessage } from '@/composables/apiClient'
import { useClipboard } from '@/composables/useClipboard'
import { useToast } from '@/composables/useToast'
import {
  getHostWingsConfiguration,
  getNodeConfiguration,
  type NodeConfigurationOut,
} from '@/api/adminNodesLocations'
import BaseModal from '@/components/ui/BaseModal.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import AlertBanner from '@/components/ui/AlertBanner.vue'
import Spinner from '@/components/ui/Spinner.vue'
import MsIcon from '@/components/ui/MsIcon.vue'

defineOptions({ name: 'NodeConfigModal' })

const props = defineProps<{
  modelValue: boolean
  nodeId?: number | null
  hostId?: number | null
  nodeName?: string
  zIndex?: number
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const { t } = useI18n({ useScope: 'global' })
const { copy } = useClipboard()
const { toast } = useToast()

const loading = ref(false)
const error = ref('')
const configData = ref<NodeConfigurationOut | null>(null)

async function loadConfig() {
  if (!props.nodeId && !props.hostId) return
  loading.value = true
  error.value = ''
  configData.value = null
  try {
    configData.value = props.hostId
      ? await getHostWingsConfiguration(props.hostId)
      : await getNodeConfiguration(props.nodeId!)
  } catch (err) {
    error.value = apiErrorMessage(err)
  } finally {
    loading.value = false
  }
}

watch(
  () => [props.modelValue, props.nodeId, props.hostId],
  ([open]) => {
    if (open) void loadConfig()
  },
)

async function copyYaml() {
  if (!configData.value?.yaml) return
  await copy(configData.value.yaml, {
    successMessage: t('hosts.nodes.config.copied'),
  })
}

async function copyDeployCmd() {
  if (!configData.value?.yaml) return
  const cmd = `mkdir -p /etc/pterodactyl && cat << 'EOF' > /etc/pterodactyl/config.yml\n${configData.value.yaml.trimEnd()}\nEOF`
  await copy(cmd, {
    successMessage: t('hosts.nodes.config.cmdCopied'),
  })
}

function downloadYaml() {
  if (!configData.value?.yaml) return
  const blob = new Blob([configData.value.yaml], { type: 'text/yaml;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  try {
    const a = document.createElement('a')
    a.href = url
    a.download = `config-node-${configData.value.node_id}.yml`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
  } catch (err) {
    toast(apiErrorMessage(err), 'error')
  } finally {
    URL.revokeObjectURL(url)
  }
}
</script>

<template>
  <BaseModal
    :model-value="modelValue"
    @update:model-value="emit('update:modelValue', $event)"
    :title="t('hosts.nodes.config.title')"
    :subtitle="configData?.node_name || nodeName || undefined"
    icon="code"
    size="lg"
    :z-index="zIndex"
  >
    <div v-if="loading" class="loading-box">
      <Spinner size="md" />
    </div>

    <AlertBanner v-else-if="error" tone="danger">
      {{ error }}
    </AlertBanner>

    <div v-else-if="configData" class="config-body">
      <AlertBanner tone="info" dense>
        {{ t('hosts.nodes.config.hint', { path: '/etc/pterodactyl/config.yml' }) }}
        {{ t('hosts.nodes.config.remote') }} <code>{{ configData.remote }}</code>
      </AlertBanner>

      <AlertBanner
        v-for="(warn, idx) in configData.warnings"
        :key="idx"
        tone="warning"
        dense
      >
        {{ warn }}
      </AlertBanner>

      <div class="yaml-card">
        <div class="yaml-header">
          <span class="yaml-filename mono">/etc/pterodactyl/config.yml</span>
          <div class="yaml-tools">
            <BaseButton size="xs" variant="ghost" @click="copyYaml">
              <MsIcon name="content_copy" size="xs" />{{ t('common.btn.copy') }}
            </BaseButton>
            <BaseButton size="xs" variant="ghost" @click="downloadYaml">
              <MsIcon name="download" size="xs" />{{ t('hosts.nodes.config.download') }}
            </BaseButton>
          </div>
        </div>
        <pre class="yaml-block no-break"><code class="no-break">{{ configData.yaml }}</code></pre>
      </div>
    </div>

    <template #footer>
      <BaseButton variant="default" @click="emit('update:modelValue', false)">
        {{ t('common.btn.close') }}
      </BaseButton>
      <template v-if="configData">
        <BaseButton variant="default" @click="copyDeployCmd">
          <MsIcon name="terminal" size="xs" />
          {{ t('hosts.nodes.config.copyCmd') }}
        </BaseButton>
        <BaseButton variant="primary" @click="copyYaml">
          <MsIcon name="content_copy" size="xs" />
          {{ t('hosts.nodes.config.copyYaml') }}
        </BaseButton>
      </template>
    </template>
  </BaseModal>
</template>

<style scoped>
.loading-box {
  display: flex;
  justify-content: center;
  padding: var(--sp-6) 0;
}
.config-body {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.yaml-card {
  border: 1px solid var(--bd);
  border-radius: var(--r-sm);
  overflow: hidden;
  background: var(--bg);
}
.yaml-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-2);
  padding: var(--sp-1) var(--sp-3);
  background: var(--bg2);
  border-bottom: 1px solid var(--bd);
  flex-wrap: wrap;
}
.yaml-filename {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--t3);
  min-width: 0;
  word-break: break-all;
}
.yaml-tools {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-1);
  flex-shrink: 0;
}
.yaml-block {
  margin: 0;
  padding: var(--sp-3);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  line-height: 1.55;
  color: var(--t1);
  overflow-x: auto;
  max-height: 44vh;
  white-space: pre;
}
</style>
