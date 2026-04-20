<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import MsIcon from '@/components/ui/MsIcon.vue'

defineOptions({ name: 'TaskProgressPanel' })

const props = defineProps<{
  tasks: { name: string; progress: number; status: 'pending' | 'uploading' | 'done' | 'error'; startTime?: number; type?: 'upload' | 'compress' | 'decompress' }[]
}>()

const emit = defineEmits<{
  close: []
  cancel: []
}>()

const { t } = useI18n({ useScope: 'global' })

const allDone = computed(() => props.tasks.length > 0 && props.tasks.every(u => u.status === 'done' || u.status === 'error'))
const hasError = computed(() => props.tasks.some(u => u.status === 'error'))

const headerLabel = computed(() => {
  const task = props.tasks[0]
  if (!task) return ''
  if (allDone.value) {
    if (hasError.value) {
      if (task.type === 'compress') return t('userServers.file.compressFailed')
      if (task.type === 'decompress') return t('userServers.file.decompressFailed')
      return t('userServers.file.uploadFailed')
    }
    if (task.type === 'compress') return t('userServers.file.compressComplete')
    if (task.type === 'decompress') return t('userServers.file.decompressComplete')
    return t('userServers.file.uploadComplete')
  }
  if (task.type === 'compress') return t('userServers.file.compressing')
  if (task.type === 'decompress') return t('userServers.file.decompressing')
  return t('userServers.file.uploadProgress')
})

// Elapsed time ticker for indeterminate tasks
const now = ref(Date.now())
let timer: ReturnType<typeof setInterval> | null = null
onMounted(() => { timer = setInterval(() => { now.value = Date.now() }, 1000) })
onUnmounted(() => { if (timer) clearInterval(timer) })

function elapsed(startTime: number | undefined): string {
  if (!startTime) return ''
  const s = Math.floor((now.value - startTime) / 1000)
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m${s % 60}s`
}
</script>

<template>
  <Transition name="slide-up">
    <div v-if="tasks.length" class="upload-panel">
      <div class="upload-panel-header" :class="{ 'upload-panel-header--done': allDone && !hasError, 'upload-panel-header--error': allDone && hasError }">
        <span>
          <MsIcon v-if="allDone && !hasError" name="check_circle" size="xs" class="header-icon--done" />
          <MsIcon v-else-if="allDone && hasError" name="warning" size="xs" class="header-icon--error" />
          {{ headerLabel }}
        </span>
        <button class="upload-panel-close" @click="emit('close')">
          <MsIcon name="close" size="xs" />
        </button>
      </div>
      <div class="upload-panel-list">
        <div v-for="u in tasks" :key="u.name" class="upload-item">
          <MsIcon
            :name="u.status === 'done' ? 'check_circle' : u.status === 'error' ? 'error' : 'upload_file'"
            size="sm"
            :class="'upload-icon--' + u.status"
          />
          <span class="upload-name">{{ u.name }}</span>
          <span v-if="u.status === 'uploading' && u.progress >= 0" class="upload-pct">{{ u.progress }}%</span>
          <span v-else-if="u.status === 'uploading' && u.progress < 0 && u.startTime" class="upload-pct">{{ elapsed(u.startTime) }}</span>
          <span v-else-if="u.status === 'pending'" class="upload-pct upload-pct--pending">{{ t('userServers.file.uploadWaiting') }}</span>
          <button v-if="u.status === 'uploading' && u.progress >= 0" class="cancel-btn" :title="t('common.btn.cancel')" @click="emit('cancel')">
            <MsIcon name="close" size="xs" />
          </button>
        </div>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.upload-panel {
  position: fixed;
  bottom: 20px;
  right: 20px;
  z-index: 200;
  width: 300px;
  background: var(--bg2);
  border: 1px solid var(--bd);
  border-radius: var(--r-md);
  box-shadow: 0 4px 20px rgba(0, 0, 0, .4);
  overflow: hidden;
}

.upload-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--sp-2) var(--sp-3);
  border-bottom: 1px solid var(--bd);
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--t1);
}

.upload-panel-close {
  background: none;
  border: none;
  color: var(--t3);
  cursor: pointer;
  padding: 2px;
}

.upload-panel-list {
  max-height: 200px;
  overflow-y: auto;
  padding: var(--sp-2);
}

.upload-item {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-1) 0;
  font-size: var(--text-xs);
}

.upload-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--t2);
}

.upload-pct {
  color: var(--ac);
  font-weight: 500;
  white-space: nowrap;
}

.upload-pct--pending {
  color: var(--t3);
  font-weight: 400;
}

.cancel-btn {
  flex-shrink: 0;
  background: none;
  border: none;
  color: var(--t3);
  cursor: pointer;
  padding: 2px;
  border-radius: var(--r-xs);
  line-height: 0;
}
.cancel-btn:hover { color: var(--red); background: rgba(239, 96, 96, .1); }

:deep(.upload-icon--done) { color: var(--green); }
:deep(.upload-icon--error) { color: var(--red); }
:deep(.upload-icon--uploading) { color: var(--ac); }
:deep(.upload-icon--pending) { color: var(--t3); }

.upload-panel-header--done { background: rgba(52, 211, 153, .08); }
.upload-panel-header--error { background: rgba(239, 96, 96, .08); }
.header-icon--done { color: var(--green); vertical-align: middle; margin-right: 4px; }
.header-icon--error { color: var(--red); vertical-align: middle; margin-right: 4px; }

.slide-up-enter-active,
.slide-up-leave-active {
  transition: transform .25s, opacity .25s;
}

.slide-up-enter-from,
.slide-up-leave-to {
  transform: translateY(20px);
  opacity: 0;
}

@media (max-width: 768px) {
  .upload-panel {
    left: 10px;
    right: 10px;
    width: auto;
    bottom: 10px;
  }
}
</style>
