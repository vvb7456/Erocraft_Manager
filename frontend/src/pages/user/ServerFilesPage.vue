<script setup lang="ts">
import { ref, inject, onMounted, computed, watch, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useFileTree } from '@/composables/useFileTree'
import { useFileOperations } from '@/composables/useFileOperations'
import type { FileEntry } from '@/composables/useFileTree'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseModal from '@/components/ui/BaseModal.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import SectionToolbar from '@/components/ui/SectionToolbar.vue'
import FilterInput from '@/components/ui/FilterInput.vue'
import FileTreeNode from '@/components/ui/FileTreeNode.vue'
import Spinner from '@/components/ui/Spinner.vue'
import FileEditor from '@/components/file/FileEditor.vue'
import FileContextMenu from '@/components/file/FileContextMenu.vue'
import TaskProgressPanel from '@/components/file/TaskProgressPanel.vue'

defineOptions({ name: 'ServerFilesPage' })

const { t } = useI18n({ useScope: 'global' })

interface ServerDetail { id: number }
const server = inject<Ref<ServerDetail | null>>('server')!
const serverId = computed(() => server.value?.id)

// ── Composables ──
const tree = useFileTree(serverId as Ref<number | undefined>)
const moveTree = useFileTree(serverId as Ref<number | undefined>)
const ops = useFileOperations(serverId as Ref<number | undefined>)
const moveSelectedPath = ref('/')
const moveTreeExpanded = ref(false)

// ── Component refs ──
const editorRef = ref<InstanceType<typeof FileEditor> | null>(null)
const contextMenuRef = ref<InstanceType<typeof FileContextMenu> | null>(null)

// ── Column resize ──
const colWidths = ref([55, 12, 16])
const tableColStyle = computed(() => ({
  '--col-name-w': colWidths.value[0] + '%',
  '--col-size-w': colWidths.value[1] + '%',
  '--col-date-w': colWidths.value[2] + '%',
} as Record<string, string>))

function startColResize(e: MouseEvent, colIndex: number) {
  const startX = e.clientX
  const startWidths = [...colWidths.value]
  const nextIndex = colIndex + 1
  const tableEl = (e.target as HTMLElement).closest('table')
  if (!tableEl) return
  const totalWidth = tableEl.clientWidth
  const hasNext = nextIndex < startWidths.length

  const onMove = (ev: MouseEvent) => {
    const deltaPx = ev.clientX - startX
    const deltaPct = (deltaPx / totalWidth) * 100
    colWidths.value[colIndex] = Math.max(8, startWidths[colIndex] + deltaPct)
    if (hasNext) {
      colWidths.value[nextIndex] = Math.max(8, startWidths[nextIndex] - deltaPct)
    }
  }
  const onUp = () => {
    document.removeEventListener('mousemove', onMove)
    document.removeEventListener('mouseup', onUp)
  }
  document.addEventListener('mousemove', onMove)
  document.addEventListener('mouseup', onUp)
}

// ── Tree refresh helper ──
function refreshTree() {
  tree.refreshTreeAt(ops.currentPath.value)
}

// ── Init ──
onMounted(async () => {
  await ops.loadFiles()
  tree.loadTreeNode(tree.treeRoot.value)
})

// ── Move tree picker ──
watch(() => ops.moveOpen.value, (open) => {
  if (open) {
    moveSelectedPath.value = ops.currentPath.value
    moveTreeExpanded.value = false
    moveTree.treeRoot.value = {
      name: '/',
      path: '/',
      children: null,
      expanded: true,
      loading: false,
    }
    moveTree.loadTreeNode(moveTree.treeRoot.value)
    moveTree.expandTreeToPath(ops.currentPath.value)
  }
})

function selectMoveTarget(node: { path: string }) {
  moveSelectedPath.value = node.path
  moveTreeExpanded.value = false
}

function confirmMove() {
  ops.moveTo.value = moveSelectedPath.value
  if (ops.hasSelection.value) {
    ops.doBatchMove()
  } else {
    ops.doMove()
  }
}

// ── Navigation ──
function navigateTo(path: string) {
  ops.loadFiles(path)
  tree.expandTreeToPath(path)
}

function navigateUp() {
  const parts = ops.currentPath.value.replace(/\/$/, '').split('/').filter(Boolean)
  parts.pop()
  navigateTo(parts.length ? '/' + parts.join('/') + '/' : '/')
}

function selectTreeNode(node: { path: string }) {
  ops.loadFiles(node.path)
}

function openEntry(e: MouseEvent, f: FileEntry) {
  // Mobile: show action menu instead of direct open
  if (window.innerWidth <= 768) {
    contextMenuRef.value?.show(e, f)
    return
  }
  if (f.directory) {
    navigateTo(ops.currentPath.value.replace(/\/$/, '') + '/' + f.name + '/')
  } else if (ops.isEditable(f)) {
    editorRef.value?.openFile(f.name, f.size)
  }
}

function onOpen(f: FileEntry) {
  if (f.directory) {
    navigateTo(ops.currentPath.value.replace(/\/$/, '') + '/' + f.name + '/')
  } else if (ops.isEditable(f)) {
    editorRef.value?.openFile(f.name, f.size)
  }
}

// ── Context menu actions ──
function onEdit(name: string) {
  const f = ops.files.value.find(file => file.name === name)
  editorRef.value?.openFile(name, f?.size)
}

async function onCreateFile() {
  const name = await ops.createFile()
  if (name) editorRef.value?.openFile(name)
}
</script>

<template>
  <div
    class="files-page"
    @dragenter="ops.onDragEnter"
    @dragover="ops.onDragOver"
    @dragleave="ops.onDragLeave"
    @drop="ops.onDrop"
  >
    <input :ref="(el: any) => { ops.uploadInputRef.value = el }" type="file" hidden @change="ops.handleUpload" />

    <!-- Left: Tree panel (standalone card) -->
    <aside class="tree-panel">
      <div class="tree-content">
        <FileTreeNode
          :node="tree.treeRoot.value"
          :current-path="ops.currentPath.value"
          :depth="0"
          @select="selectTreeNode"
          @toggle="tree.toggleTreeNode"
        />
      </div>
    </aside>

    <!-- Right top: Toolbar (standalone) -->
    <SectionToolbar class="files-toolbar">
      <template #start>
        <template v-if="ops.hasSelection.value">
          <button class="clear-selection-btn" @click="ops.clearSelection">
            <MsIcon name="close" size="sm" />
          </button>
          <span class="selection-count">{{ t('userServers.file.selected', { n: ops.selectedFiles.value.size }) }}</span>
        </template>
        <template v-else>
          <FilterInput
            v-model="ops.searchTerm.value"
            :placeholder="t('userServers.file.searchPlaceholder')"
            class="file-search-input"
          />
          <div class="breadcrumbs">
            <button
              v-for="(crumb, i) in ops.breadcrumbs.value"
              :key="crumb.path"
              class="breadcrumb"
              :class="{ active: i === ops.breadcrumbs.value.length - 1 }"
              @click="navigateTo(crumb.path)"
            >{{ crumb.label }}</button>
          </div>
        </template>
      </template>
      <template #end>
        <template v-if="ops.hasSelection.value">
          <BaseButton size="sm" @click="ops.moveSelected">
            <MsIcon name="drive_file_move" size="xs" />
            <span class="btn-label">{{ t('userServers.file.move') }}</span>
          </BaseButton>
          <BaseButton size="sm" :loading="ops.compressing.value" :disabled="ops.compressing.value" @click="ops.compressSelected">
            <MsIcon name="folder_zip" size="xs" />
            <span class="btn-label">{{ t('userServers.file.compress') }}</span>
          </BaseButton>
          <BaseButton size="sm" variant="danger" @click="ops.deleteSelected(refreshTree)">
            <MsIcon name="delete" size="xs" />
            <span class="btn-label">{{ t('userServers.file.delete') }}</span>
          </BaseButton>
        </template>
        <template v-else>
          <BaseButton size="sm" @click="ops.openNewFile">
            <MsIcon name="note_add" size="xs" />
            <span class="btn-label">{{ t('userServers.file.newFile') }}</span>
          </BaseButton>
          <BaseButton size="sm" @click="ops.openNewFolder">
            <MsIcon name="create_new_folder" size="xs" />
            <span class="btn-label">{{ t('userServers.file.newFolder') }}</span>
          </BaseButton>
          <BaseButton size="sm" @click="ops.triggerUpload">
            <MsIcon name="upload" size="xs" />
            <span class="btn-label">{{ t('userServers.file.upload') }}</span>
          </BaseButton>
        </template>
      </template>
    </SectionToolbar>

    <!-- Right bottom: File list (standalone card) -->
    <div class="file-list-panel">
      <!-- File table (always shown) -->
      <table class="file-table" :style="tableColStyle">
        <thead>
          <tr>
            <th class="col-check">
              <input type="checkbox" :checked="ops.allSelected.value" @change="ops.toggleSelectAll" />
            </th>
            <th class="col-name sortable" @click="ops.toggleSort('name')">
              {{ t('userServers.file.name') }}
              <MsIcon v-if="ops.sortBy.value === 'name'" :name="ops.sortOrder.value === 'asc' ? 'arrow_upward' : 'arrow_downward'" size="xs" />
              <span class="col-resize" @mousedown.prevent="startColResize($event, 0)" />
            </th>
            <th class="col-size sortable" @click="ops.toggleSort('size')">
              {{ t('userServers.file.size') }}
              <MsIcon v-if="ops.sortBy.value === 'size'" :name="ops.sortOrder.value === 'asc' ? 'arrow_upward' : 'arrow_downward'" size="xs" />
              <span class="col-resize" @mousedown.prevent="startColResize($event, 1)" />
            </th>
            <th class="col-date sortable" @click="ops.toggleSort('modified')">
              {{ t('userServers.file.modified') }}
              <MsIcon v-if="ops.sortBy.value === 'modified'" :name="ops.sortOrder.value === 'asc' ? 'arrow_upward' : 'arrow_downward'" size="xs" />
              <span class="col-resize" @mousedown.prevent="startColResize($event, 2)" />
            </th>
            <th class="col-actions">{{ t('userServers.file.actions') }}</th>
          </tr>
        </thead>
        <tbody>
          <!-- Parent directory -->
          <tr v-if="ops.currentPath.value !== '/'" class="parent-row" @click="navigateUp">
            <td class="col-check">
              <MsIcon name="subdirectory_arrow_left" size="sm" class="file-icon file-icon--dir" />
            </td>
            <td class="col-name">
              <span class="file-name-cell">
                <span class="file-name-text">..</span>
              </span>
            </td>
            <td class="col-size"></td>
            <td class="col-date"></td>
            <td class="col-actions"></td>
          </tr>
          <!-- File rows -->
          <tr
            v-for="f in ops.sortedFiles.value"
            :key="f.name"
            :class="{ selected: ops.selectedFiles.value.has(f.name) }"
            @click="openEntry($event, f)"
            @contextmenu="contextMenuRef?.show($event, f)"
          >
            <td class="col-check" @click.stop>
              <input type="checkbox" :checked="ops.selectedFiles.value.has(f.name)" @change="ops.toggleSelect(f.name)" />
            </td>
            <td class="col-name">
              <span class="file-name-cell">
                <MsIcon :name="ops.fileIcon(f)" size="sm" class="file-icon" :class="{ 'file-icon--dir': !f.file }" />
                <span class="file-name-text">{{ f.name }}</span>
              </span>
            </td>
            <td class="col-size">{{ f.file ? ops.formatSize(f.size) : '\u2014' }}</td>
            <td class="col-date">{{ ops.formatDate(f.modified) }}</td>
            <td class="col-actions" @click.stop>
              <div class="row-actions">
                <button v-if="f.file && ops.isEditable(f)" class="action-btn" :title="t('userServers.file.edit')" @click="onEdit(f.name)">
                  <MsIcon name="edit" size="sm" />
                </button>
                <button v-if="f.file" class="action-btn" :title="t('userServers.file.download')" @click="ops.downloadFile(f.name)">
                  <MsIcon name="download" size="sm" />
                </button>
                <button class="action-btn" :title="t('userServers.file.rename')" @click="ops.openRename(f.name)">
                  <MsIcon name="drive_file_rename_outline" size="sm" />
                </button>
                <button class="action-btn action-btn--danger" :title="t('userServers.file.delete')" @click="ops.deleteSingle(f.name, refreshTree)">
                  <MsIcon name="delete" size="sm" />
                </button>
                <button class="action-btn" :title="t('userServers.file.moreActions')" @click="contextMenuRef?.show($event, f)">
                  <MsIcon name="more_vert" size="sm" />
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
      <!-- Loading -->
      <div v-if="ops.filesLoading.value" class="empty-state-fill">
        <Spinner />
      </div>
      <!-- Empty state -->
      <div v-else-if="!ops.sortedFiles.value.length" class="empty-state-fill">
        <div class="empty-cell-content">
          <MsIcon :name="ops.files.value.length ? 'search_off' : 'folder_open'" size="md" />
          <span>{{ ops.files.value.length ? t('userServers.file.noResults') : t('userServers.file.empty') }}</span>
        </div>
      </div>
    </div>

    <!-- Drag overlay -->
    <Transition name="fade">
      <div v-if="ops.dragOver.value" class="drag-overlay" @drop.stop="ops.onDrop" @dragover.prevent @dragleave.prevent>
        <div class="drag-overlay-content">
          <MsIcon name="upload" class="drag-icon" />
          <p>{{ t('userServers.file.dragHint') }}</p>
        </div>
      </div>
    </Transition>

    <!-- Context menu -->
    <FileContextMenu
      ref="contextMenuRef"
      :is-editable="ops.isEditable"
      :is-archive="ops.isArchive"
      :file-icon="ops.fileIcon"
      :operating="ops.operating.value"
      :compressing="ops.compressing.value"
      :decompressing="ops.decompressing.value"
      @open="onOpen"
      @edit="onEdit"
      @rename="ops.openRename"
      @move="ops.openMove"
      @download="ops.downloadFile"
      @compress="ops.compressFiles"
      @decompress="(n: string) => ops.decompressFile(n, refreshTree)"
      @delete="(n: string) => ops.deleteSingle(n, refreshTree)"
    />

    <!-- Task progress panel -->
    <TaskProgressPanel
      :tasks="ops.tasks.value"
      @close="ops.uploadPanelOpen.value = false"
      @cancel="ops.cancelUpload()"
    />

    <!-- Editor -->
    <FileEditor
      ref="editorRef"
      :server-id="serverId!"
      :current-path="ops.currentPath.value"
      @saved="ops.loadFiles()"
    />

    <!-- New File modal -->
    <BaseModal v-model="ops.newFileOpen.value" :title="t('userServers.file.newFile')">
      <BaseInput v-model="ops.newFileName.value" :placeholder="t('userServers.file.fileName')" @keydown.enter="onCreateFile" />
      <p v-if="ops.newFileError.value" class="field-error">{{ ops.newFileError.value }}</p>
      <template #footer>
        <BaseButton @click="ops.newFileOpen.value = false">{{ t('common.btn.cancel') }}</BaseButton>
        <BaseButton variant="primary" :disabled="!!ops.newFileError.value || !ops.newFileName.value.trim()" @click="onCreateFile">{{ t('common.btn.confirm') }}</BaseButton>
      </template>
    </BaseModal>

    <!-- New Folder modal -->
    <BaseModal v-model="ops.newFolderOpen.value" :title="t('userServers.file.newFolder')">
      <BaseInput v-model="ops.newFolderName.value" :placeholder="t('userServers.file.folderName')" @keydown.enter="ops.createFolder(refreshTree)" />
      <p v-if="ops.newFolderError.value" class="field-error">{{ ops.newFolderError.value }}</p>
      <template #footer>
        <BaseButton @click="ops.newFolderOpen.value = false">{{ t('common.btn.cancel') }}</BaseButton>
        <BaseButton variant="primary" :disabled="!!ops.newFolderError.value || !ops.newFolderName.value.trim()" @click="ops.createFolder(refreshTree)">{{ t('common.btn.confirm') }}</BaseButton>
      </template>
    </BaseModal>

    <!-- Rename modal -->
    <BaseModal v-model="ops.renameOpen.value" :title="t('userServers.file.rename')">
      <BaseInput v-model="ops.renameTo.value" :placeholder="t('userServers.file.newName')" @keydown.enter="ops.doRename(refreshTree)" />
      <p v-if="ops.renameError.value" class="field-error">{{ ops.renameError.value }}</p>
      <template #footer>
        <BaseButton @click="ops.renameOpen.value = false">{{ t('common.btn.cancel') }}</BaseButton>
        <BaseButton variant="primary" :disabled="!!ops.renameError.value || !ops.renameTo.value.trim()" @click="ops.doRename(refreshTree)">{{ t('common.btn.confirm') }}</BaseButton>
      </template>
    </BaseModal>

    <!-- Move modal -->
    <BaseModal v-model="ops.moveOpen.value" :title="t('userServers.file.move')">
      <p class="move-info">{{ ops.moveFrom.value }}</p>
      <p class="move-dest-label">{{ t('userServers.file.moveTo') }}</p>
      <div class="move-select-wrapper">
        <button class="move-select-trigger" @click="moveTreeExpanded = !moveTreeExpanded">
          <span class="move-select-value">{{ moveSelectedPath }}</span>
          <MsIcon :name="moveTreeExpanded ? 'expand_less' : 'expand_more'" size="sm" />
        </button>
        <div v-if="moveTreeExpanded" class="move-tree-container">
          <FileTreeNode
            :node="moveTree.treeRoot.value"
            :current-path="moveSelectedPath"
            @select="selectMoveTarget"
            @toggle="moveTree.toggleTreeNode"
          />
        </div>
      </div>
      <template #footer>
        <BaseButton @click="ops.moveOpen.value = false">{{ t('common.btn.cancel') }}</BaseButton>
        <BaseButton variant="primary" @click="confirmMove">{{ t('common.btn.confirm') }}</BaseButton>
      </template>
    </BaseModal>
  </div>
</template>

<style scoped>
/* ── Toolbar ── */
.files-toolbar {
  grid-column: 2;
  grid-row: 1;
  margin-bottom: 0;
  --btn-py-sm: 7px;
}

.file-search-input {
  width: 180px;
  flex-shrink: 0;
}

.clear-selection-btn {
  background: none;
  border: none;
  color: var(--t2);
  cursor: pointer;
  padding: 4px;
  border-radius: var(--r-xs);
  display: flex;
  align-items: center;
}

.clear-selection-btn:hover {
  color: var(--t1);
  background: var(--bg4);
}

.selection-count {
  font-size: var(--text-sm);
  color: var(--ac);
  font-weight: 500;
  white-space: nowrap;
}

.btn-label {
  display: inline;
}

/* ── Breadcrumbs ── */
.breadcrumbs {
  display: flex;
  align-items: center;
  gap: 2px;
  overflow-x: auto;
  /* Contain horizontal rubber-band on iOS — a deep path can overflow on phones. */
  overscroll-behavior-x: contain;
  min-width: 0;
}

.breadcrumb {
  background: none;
  border: none;
  color: var(--t3);
  font-size: var(--text-sm);
  padding: 2px 6px;
  border-radius: var(--r-xs);
  cursor: pointer;
  white-space: nowrap;
  font-family: inherit;
}

.breadcrumb:hover {
  background: var(--bg4);
  color: var(--t1);
}

.breadcrumb.active {
  color: var(--t1);
  font-weight: 500;
  cursor: default;
}

.breadcrumb + .breadcrumb::before {
  content: '/';
  color: var(--t3);
  margin-right: 4px;
  opacity: .5;
}

/* ── Page layout (CSS grid: 3 independent areas) ── */
.files-page {
  display: grid;
  grid-template-columns: 20% 1fr;
  grid-template-rows: auto 1fr;
  gap: var(--sp-3);
  position: relative;
  height: calc(100vh - 180px);
  height: calc(100dvh - 180px);
  min-height: 360px;
}

/* ── Tree panel (standalone card, spans both rows) ── */
.tree-panel {
  grid-row: 1 / -1;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--bd);
  border-radius: var(--r-md);
  background: var(--bg2);
  overflow: hidden;
}

.tree-content {
  flex: 1;
  overflow-y: auto;
  overscroll-behavior: contain;
  -webkit-overflow-scrolling: touch;
  padding: var(--sp-2) 0;
}

/* ── File list panel (standalone card, grid row 2 col 2) ── */
.file-list-panel {
  grid-column: 2;
  grid-row: 2;
  min-width: 0;
  min-height: 0;
  overflow: auto;
  overscroll-behavior: contain;
  -webkit-overflow-scrolling: touch;
  border: 1px solid var(--bd);
  border-radius: var(--r-md);
  background: var(--bg2);
  display: flex;
  flex-direction: column;
}

/* ── Parent row ── */
.parent-row {
  cursor: pointer;
}

.parent-row:hover td {
  background: rgba(20, 184, 166, .04);
}

/* ── Empty state (flex fill) ── */
.empty-state-fill {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--t3);
}

.empty-cell-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--sp-2);
  font-size: var(--text-sm);
}

/* ── File table ── */
.file-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--text-sm);
}

.file-table th {
  text-align: left;
  padding: var(--sp-2) var(--sp-3);
  color: var(--t3);
  font-weight: 500;
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: .04em;
  border-bottom: 1px solid var(--bd);
  background: var(--bg3);
  position: sticky;
  top: 0;
  z-index: 1;
  overflow: hidden;
  user-select: none;
}

.file-table th.sortable {
  cursor: pointer;
}

.file-table th.sortable:hover {
  color: var(--t1);
}

.file-table td {
  padding: var(--sp-1) var(--sp-3);
  border-bottom: 1px solid color-mix(in srgb, var(--bd) 40%, transparent);
  color: var(--t2);
  vertical-align: middle;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-table tr:last-child td {
  border-bottom: none;
}

.file-table tbody tr {
  cursor: pointer;
  transition: background .1s;
}

.file-table tbody tr:hover td {
  background: rgba(20, 184, 166, .04);
}

.file-table tbody tr.selected td {
  background: rgba(20, 184, 166, .08);
}

.col-check {
  width: 1%;
  white-space: nowrap;
  text-align: center;
  cursor: default;
}

.col-check input[type="checkbox"] {
  margin: 0;
  vertical-align: middle;
}

.col-name {
  position: relative;
  width: var(--col-name-w, 55%);
}

.file-name-cell {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  min-width: 0;
}

.col-size {
  position: relative;
  color: var(--t3);
  width: var(--col-size-w, 10%);
}

.col-date {
  position: relative;
  color: var(--t3);
  width: var(--col-date-w, 14%);
}

.col-actions {
  width: 140px;
  padding-right: var(--sp-3) !important;
}

/* ── Column resize handle ── */
.col-resize {
  position: absolute;
  right: -6px;
  top: 0;
  bottom: 0;
  width: 12px;
  cursor: col-resize;
  z-index: 2;
}

.col-resize::after {
  content: '';
  position: absolute;
  left: 50%;
  top: 4px;
  bottom: 4px;
  width: 3px;
  margin-left: -1.5px;
  border-radius: 2px;
  background: var(--t3);
  opacity: .35;
  transition: opacity .15s, background .15s;
}

.col-resize:hover::after,
.col-resize:active::after {
  background: var(--ac);
  opacity: 1;
}

/* ── Row inline actions ── */
.row-actions {
  display: flex;
  align-items: center;
  gap: 2px;
}

.file-table tbody tr:hover .row-actions {
  opacity: 1;
}

.file-icon {
  color: var(--t3);
  flex-shrink: 0;
}

.file-icon--dir {
  color: var(--ac);
}

.file-name-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.action-btn {
  background: none;
  border: none;
  color: var(--t3);
  cursor: pointer;
  padding: 4px;
  border-radius: var(--r-xs);
  display: flex;
  align-items: center;
}

.action-btn:hover {
  color: var(--t1);
  background: var(--bg4);
}

.action-btn--danger:hover {
  color: var(--red);
}

/* ── Move modal ── */
.field-error {
  color: var(--red);
  font-size: var(--text-xs);
  margin-top: var(--sp-1);
}

.move-info {
  color: var(--t2);
  font-size: var(--text-sm);
  margin-bottom: var(--sp-3);
  word-break: break-all;
}

.move-dest-label {
  color: var(--t3);
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: .04em;
  margin-bottom: var(--sp-2);
}

.move-select-wrapper {
  position: relative;
}

.move-select-trigger {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--sp-2) var(--sp-3);
  background: var(--bg-in);
  border: 1px solid var(--bd);
  border-radius: var(--r-md);
  color: var(--t1);
  font-size: var(--text-sm);
  cursor: pointer;
  transition: border-color .15s;
}

.move-select-trigger:hover {
  border-color: var(--bd-f);
}

.move-select-value {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.move-tree-container {
  max-height: 250px;
  overflow-y: auto;
  border: 1px solid var(--bd);
  border-top: none;
  border-radius: 0 0 var(--r-md) var(--r-md);
  background: var(--bg-in);
  padding: var(--sp-1) 0;
}

/* ── Drag overlay ── */
.drag-overlay {
  position: absolute;
  inset: 0;
  z-index: 100;
  background: rgba(0, 0, 0, .6);
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--r-md);
}

.drag-overlay-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-8);
  border: 2px dashed var(--ac);
  border-radius: var(--r-lg);
  color: var(--t1);
  font-size: var(--text-md);
}

.drag-icon {
  font-size: 48px;
  color: var(--ac);
}

/* ── Transitions ── */
.fade-enter-active,
.fade-leave-active {
  transition: opacity .2s;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* ── Responsive ── */
@media (max-width: 768px) {
  .files-page {
    grid-template-columns: 1fr;
    grid-template-rows: auto 1fr;
    height: calc(100vh - 160px);
    height: calc(100dvh - 160px);
  }

  .tree-panel {
    display: none;
  }

  .files-toolbar {
    grid-column: 1;
    grid-row: 1;
  }

  .file-list-panel {
    grid-column: 1;
    grid-row: 2;
  }

  /* Toolbar: search full width, buttons equal width on second row */
  .files-toolbar :deep(.section-toolbar) {
    flex-wrap: wrap;
  }

  .files-toolbar :deep(.section-toolbar-start) {
    width: 100%;
  }

  .files-toolbar :deep(.section-toolbar-end) {
    width: 100%;
    margin-left: 0;
  }

  .file-search-input {
    width: 100% !important;
    flex: 1;
  }

  .files-toolbar :deep(.section-toolbar-end) .base-btn {
    flex: 1;
    justify-content: center;
  }

  .col-date {
    display: none;
  }

  .col-size {
    width: 60px;
  }

  .col-actions {
    display: none;
  }
}

@media (max-width: 480px) {
  .col-size {
    display: none;
  }

  .breadcrumbs {
    display: none;
  }
}
</style>
