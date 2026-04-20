<script setup lang="ts">
import { ref, nextTick, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import MsIcon from '@/components/ui/MsIcon.vue'
import Spinner from '@/components/ui/Spinner.vue'
import ActionSheet from '@/components/ui/ActionSheet.vue'
import type { FileEntry } from '@/composables/useFileTree'

defineOptions({ name: 'FileContextMenu' })

const props = defineProps<{
  isEditable: (f: FileEntry) => boolean
  isArchive: (f: FileEntry) => boolean
  fileIcon: (f: FileEntry) => string
  operating?: boolean
  compressing?: boolean
  decompressing?: boolean
}>()

const emit = defineEmits<{
  open: [file: FileEntry]
  edit: [name: string]
  rename: [name: string]
  move: [name: string]
  download: [name: string]
  compress: [names: string[]]
  decompress: [name: string]
  delete: [name: string]
}>()

const { t } = useI18n({ useScope: 'global' })

// Desktop context menu
const contextMenu = ref<{ x: number; y: number; file: FileEntry } | null>(null)

// Mobile action sheet
const mobileActionOpen = ref(false)
const mobileActionFile = ref<FileEntry | null>(null)

function show(e: MouseEvent, f: FileEntry) {
  e.preventDefault()
  if (window.innerWidth <= 768) {
    mobileActionFile.value = f
    mobileActionOpen.value = true
    return
  }
  contextMenu.value = { x: e.clientX, y: e.clientY, file: f }
  nextTick(() => {
    const el = document.querySelector('.context-menu') as HTMLElement | null
    if (!el) return
    const rect = el.getBoundingClientRect()
    let { x, y } = contextMenu.value!
    if (x + rect.width > window.innerWidth) x = window.innerWidth - rect.width - 8
    if (y + rect.height > window.innerHeight) y = window.innerHeight - rect.height - 8
    if (x < 8) x = 8
    if (y < 8) y = 8
    contextMenu.value = { x, y, file: f }
  })
}

function close() {
  contextMenu.value = null
}

function act(action: string, f: FileEntry) {
  close()
  mobileActionOpen.value = false
  switch (action) {
    case 'open': emit('open', f); break
    case 'edit': emit('edit', f.name); break
    case 'rename': emit('rename', f.name); break
    case 'move': emit('move', f.name); break
    case 'download': emit('download', f.name); break
    case 'compress': emit('compress', [f.name]); break
    case 'decompress': emit('decompress', f.name); break
    case 'delete': emit('delete', f.name); break
  }
}

// Close context menu on click anywhere
if (typeof window !== 'undefined') {
  document.addEventListener('click', close)
  onUnmounted(() => document.removeEventListener('click', close))
}

defineExpose({ show, close })
</script>

<template>
  <!-- Desktop context menu -->
  <Teleport to="body">
    <div
      v-if="contextMenu"
      class="context-menu"
      :style="{ left: contextMenu.x + 'px', top: contextMenu.y + 'px' }"
      @click.stop
    >
      <div class="context-header">
        <MsIcon :name="fileIcon(contextMenu.file)" size="sm" />
        <span class="context-filename">{{ contextMenu.file.name }}</span>
      </div>
      <div class="context-divider" />
      <!-- Archive: decompress first -->
      <button v-if="contextMenu.file.file && isArchive(contextMenu.file)" class="context-item" :class="{ 'context-item--disabled': decompressing }" :disabled="decompressing" @click="act('decompress', contextMenu.file)">
        <MsIcon name="unarchive" size="sm" /> {{ t('userServers.file.decompress') }}
        <Spinner v-if="decompressing" class="context-spinner" />
      </button>
      <button v-else-if="!contextMenu.file.file || isEditable(contextMenu.file)" class="context-item" @click="act('open', contextMenu.file)">
          <MsIcon :name="contextMenu.file.file ? 'open_in_new' : 'folder_open'" size="sm" />
          {{ contextMenu.file.file ? t('userServers.file.openFile') : t('userServers.file.openFolder') }}
        </button>      <button v-if="contextMenu.file.file && isEditable(contextMenu.file)" class="context-item" @click="act('edit', contextMenu.file)">
        <MsIcon name="edit" size="sm" /> {{ t('userServers.file.edit') }}
      </button>
      <button class="context-item" :class="{ 'context-item--disabled': operating }" :disabled="operating" @click="act('rename', contextMenu.file)">
        <MsIcon name="drive_file_rename_outline" size="sm" /> {{ t('userServers.file.rename') }}
      </button>
      <button class="context-item" :class="{ 'context-item--disabled': operating }" :disabled="operating" @click="act('move', contextMenu.file)">
        <MsIcon name="drive_file_move" size="sm" /> {{ t('userServers.file.move') }}
      </button>
      <button v-if="contextMenu.file.file" class="context-item" @click="act('download', contextMenu.file)">
        <MsIcon name="download" size="sm" /> {{ t('userServers.file.download') }}
      </button>
      <div class="context-divider" />
      <button class="context-item" :class="{ 'context-item--disabled': compressing }" :disabled="compressing" @click="act('compress', contextMenu.file)">
        <MsIcon name="folder_zip" size="sm" /> {{ t('userServers.file.compress') }}
        <Spinner v-if="compressing" class="context-spinner" />
      </button>
      <div class="context-divider" />
      <button class="context-item context-item--danger" :class="{ 'context-item--disabled': operating }" :disabled="operating" @click="act('delete', contextMenu.file)">
        <MsIcon name="delete" size="sm" /> {{ t('userServers.file.delete') }}
      </button>
    </div>
  </Teleport>

  <!-- Mobile action sheet -->
  <ActionSheet v-model="mobileActionOpen" :title="mobileActionFile?.name">
    <template v-if="mobileActionFile">
      <button v-if="mobileActionFile.file && isArchive(mobileActionFile)" :disabled="decompressing" @click="act('decompress', mobileActionFile!)">
        <MsIcon name="unarchive" size="sm" /> {{ t('userServers.file.decompress') }}
        <Spinner v-if="decompressing" class="context-spinner" />
      </button>
      <button v-else-if="!mobileActionFile.file || isEditable(mobileActionFile)" @click="act('open', mobileActionFile!)">
        <MsIcon :name="mobileActionFile.file ? 'open_in_new' : 'folder_open'" size="sm" />
        {{ mobileActionFile.file ? t('userServers.file.openFile') : t('userServers.file.openFolder') }}
      </button>
      <button v-if="mobileActionFile.file && isEditable(mobileActionFile)" @click="act('edit', mobileActionFile!)">
        <MsIcon name="edit" size="sm" /> {{ t('userServers.file.edit') }}
      </button>
      <button :disabled="operating" @click="act('rename', mobileActionFile!)">
        <MsIcon name="drive_file_rename_outline" size="sm" /> {{ t('userServers.file.rename') }}
      </button>
      <button :disabled="operating" @click="act('move', mobileActionFile!)">
        <MsIcon name="drive_file_move" size="sm" /> {{ t('userServers.file.move') }}
      </button>
      <button v-if="mobileActionFile.file" @click="act('download', mobileActionFile!)">
        <MsIcon name="download" size="sm" /> {{ t('userServers.file.download') }}
      </button>
      <button :disabled="compressing" @click="act('compress', mobileActionFile!)">
        <MsIcon name="folder_zip" size="sm" /> {{ t('userServers.file.compress') }}
      </button>
      <button class="action-sheet--danger" :disabled="operating" @click="act('delete', mobileActionFile!)">
        <MsIcon name="delete" size="sm" /> {{ t('userServers.file.delete') }}
      </button>
    </template>
  </ActionSheet>
</template>

<style scoped>
.context-menu {
  position: fixed;
  z-index: 1000;
  background: var(--bg2);
  border: 1px solid var(--bd);
  border-radius: var(--r-md);
  box-shadow: 0 4px 20px rgba(0, 0, 0, .4);
  padding: var(--sp-1);
  min-width: 180px;
}

.context-header {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-2) var(--sp-3);
  color: var(--t2);
  font-size: var(--text-sm);
  font-weight: 500;
}

.context-filename {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.context-item {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  width: 100%;
  padding: var(--sp-2) var(--sp-3);
  background: none;
  border: none;
  font-size: var(--text-sm);
  font-family: inherit;
  color: var(--t1);
  cursor: pointer;
  border-radius: var(--r-xs);
  transition: background .1s;
}

.context-item:hover {
  background: var(--bg4);
}

.context-item--danger {
  color: var(--red);
}

.context-item--danger:hover {
  background: rgba(239, 96, 96, .1);
}

.context-item--disabled {
  opacity: 0.45;
  cursor: not-allowed;
  pointer-events: none;
}

.context-spinner {
  margin-left: auto;
  width: 14px;
  height: 14px;
}

.context-divider {
  height: 1px;
  background: var(--bd);
  margin: var(--sp-1) var(--sp-2);
}
</style>
