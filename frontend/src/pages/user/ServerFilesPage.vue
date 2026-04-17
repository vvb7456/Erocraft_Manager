<script setup lang="ts">
import { ref, inject, onMounted, computed, watch, nextTick, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseModal from '@/components/ui/BaseModal.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import SectionToolbar from '@/components/ui/SectionToolbar.vue'
import FilterInput from '@/components/ui/FilterInput.vue'
import ActionSheet from '@/components/ui/ActionSheet.vue'
import FileTreeNode, { type TreeNode } from '@/components/ui/FileTreeNode.vue'
import Spinner from '@/components/ui/Spinner.vue'

defineOptions({ name: 'ServerFilesPage' })

const { t } = useI18n({ useScope: 'global' })
const { get, post, loading } = useApiFetch()
const { toast } = useToast()
const { confirm } = useConfirm()

interface ServerDetail { id: number }

interface FileEntry {
  name: string
  mode: string
  mode_bits: string
  size: number
  file: boolean
  directory: boolean
  symlink: boolean
  mime: string
  created: string
  modified: string
}

const server = inject<Ref<ServerDetail | null>>('server')!

// ── State ──
const currentPath = ref('/')
const files = ref<FileEntry[]>([])
const filesLoading = ref(false)
const searchTerm = ref('')
const selectedFiles = ref<Set<string>>(new Set())

// Tree panel
const treeRoot = ref<TreeNode>({
  name: '/',
  path: '/',
  children: null,
  expanded: true,
  loading: false,
})

// Modals
const newFolderOpen = ref(false)
const newFolderName = ref('')
const newFileOpen = ref(false)
const newFileName = ref('')
const renameOpen = ref(false)
const renameFrom = ref('')
const renameTo = ref('')
const moveOpen = ref(false)
const moveFrom = ref('')
const moveTo = ref('')

// Editor
const editorOpen = ref(false)
const editorFile = ref('')
const editorContent = ref('')
const editorLoading = ref(false)
const editorSaving = ref(false)
const editorRef = ref<HTMLDivElement | null>(null)
let editorView: any = null

// Upload
const uploadInputRef = ref<HTMLInputElement | null>(null)
const dragOver = ref(false)
const uploads = ref<{ name: string; progress: number; status: 'pending' | 'uploading' | 'done' | 'error' }[]>([])
const uploadPanelOpen = ref(false)

// Right-click context menu
const contextMenu = ref<{ x: number; y: number; file: FileEntry } | null>(null)
const mobileActionOpen = ref(false)
const mobileActionFile = ref<FileEntry | null>(null)

// Column widths (percentages for name, size, date)
const colWidths = ref([55, 12, 16]) // name%, size%, date%
const tableColStyle = computed(() => ({
  '--col-name-w': colWidths.value[0] + '%',
  '--col-size-w': colWidths.value[1] + '%',
  '--col-date-w': colWidths.value[2] + '%',
} as Record<string, string>))

// ── Computed ──
const breadcrumbs = computed(() => {
  const parts = currentPath.value.split('/').filter(Boolean)
  const crumbs = [{ label: t('userServers.file.root'), path: '/' }]
  let path = '/'
  for (const p of parts) {
    path += p + '/'
    crumbs.push({ label: p, path })
  }
  return crumbs
})

const sortedFiles = computed(() => {
  let items = files.value
  // Apply search filter
  if (searchTerm.value.trim()) {
    const q = searchTerm.value.toLowerCase()
    items = items.filter(f => f.name.toLowerCase().includes(q))
  }
  const dirs = items.filter(f => !f.file).sort((a, b) => a.name.localeCompare(b.name))
  const fls = items.filter(f => f.file).sort((a, b) => a.name.localeCompare(b.name))
  return [...dirs, ...fls]
})

const hasSelection = computed(() => selectedFiles.value.size > 0)
const allSelected = computed(() => sortedFiles.value.length > 0 && selectedFiles.value.size === sortedFiles.value.length)

// ── File helpers ──
function isEditable(f: FileEntry): boolean {
  if (!f.file || f.size > 5 * 1024 * 1024) return false
  const ext = f.name.split('.').pop()?.toLowerCase() || ''
  const editable = [
    'txt', 'json', 'yml', 'yaml', 'toml', 'cfg', 'conf', 'ini', 'env',
    'js', 'ts', 'py', 'sh', 'bash', 'html', 'css', 'xml', 'md', 'log',
    'properties', 'csv', 'sql', 'lua', 'rb', 'java', 'php', 'c', 'cpp',
    'h', 'rs', 'go', 'dockerfile', 'gitignore', 'editorconfig',
  ]
  return editable.includes(ext) || f.mime?.startsWith('text/') || f.name.startsWith('.')
}

function isArchive(f: FileEntry): boolean {
  const ext = f.name.split('.').pop()?.toLowerCase() || ''
  return ['zip', 'tar', 'gz', 'tgz', 'rar', '7z', 'bz2', 'xz'].includes(ext)
}

function fileIcon(f: FileEntry): string {
  if (!f.file) return 'folder'
  const ext = f.name.split('.').pop()?.toLowerCase()
  if (['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'ico'].includes(ext || '')) return 'image'
  if (isArchive(f)) return 'folder_zip'
  if (['mp3', 'wav', 'ogg', 'flac'].includes(ext || '')) return 'audio_file'
  if (['mp4', 'avi', 'mkv', 'webm'].includes(ext || '')) return 'video_file'
  if (['json', 'yml', 'yaml', 'toml', 'xml'].includes(ext || '')) return 'data_object'
  if (['js', 'ts', 'py', 'sh', 'rb', 'go', 'rs', 'java', 'php', 'c', 'cpp', 'h'].includes(ext || '')) return 'code'
  if (['md', 'txt', 'log', 'csv'].includes(ext || '')) return 'description'
  return 'draft'
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
  return (bytes / (1024 * 1024 * 1024)).toFixed(2) + ' GB'
}

function formatDate(iso: string): string {
  if (!iso) return '\u2014'
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

// ── File list API ──
async function loadFiles(dir?: string) {
  if (!server.value) return
  if (dir !== undefined) currentPath.value = dir
  selectedFiles.value = new Set()
  searchTerm.value = ''
  filesLoading.value = true
  const data = await get<FileEntry[]>(
    `/api/user/servers/${server.value.id}/files/list?directory=${encodeURIComponent(currentPath.value)}`,
    { silent: true },
  )
  filesLoading.value = false
  if (data) files.value = data
}

onMounted(() => {
  loadFiles()
  loadTreeNode(treeRoot.value)
})

// ── Navigation ──
function navigateTo(path: string) {
  loadFiles(path)
  // Expand tree to show this path
  expandTreeToPath(path)
}

function openEntry(f: FileEntry) {
  if (f.directory) {
    const newPath = currentPath.value.replace(/\/$/, '') + '/' + f.name + '/'
    navigateTo(newPath)
  } else if (isEditable(f)) {
    openEditor(f.name)
  }
}

// ── Selection ──
function toggleSelect(name: string) {
  const s = new Set(selectedFiles.value)
  if (s.has(name)) s.delete(name)
  else s.add(name)
  selectedFiles.value = s
}

function toggleSelectAll() {
  if (allSelected.value) {
    selectedFiles.value = new Set()
  } else {
    selectedFiles.value = new Set(sortedFiles.value.map(f => f.name))
  }
}

function clearSelection() {
  selectedFiles.value = new Set()
}

// ── Tree panel ──
async function loadTreeNode(node: TreeNode) {
  if (!server.value) return
  node.loading = true
  const data = await get<FileEntry[]>(
    `/api/user/servers/${server.value.id}/files/list?directory=${encodeURIComponent(node.path)}`,
    { silent: true },
  )
  node.loading = false
  if (data) {
    node.children = data
      .filter(f => !f.file)
      .sort((a, b) => a.name.localeCompare(b.name))
      .map(f => ({
        name: f.name,
        path: node.path.replace(/\/$/, '') + '/' + f.name + '/',
        children: null,
        expanded: false,
        loading: false,
      }))
  }
}

function toggleTreeNode(node: TreeNode) {
  if (node.expanded) {
    node.expanded = false
  } else {
    node.expanded = true
    if (node.children === null) {
      loadTreeNode(node)
    }
  }
}

function selectTreeNode(node: TreeNode) {
  loadFiles(node.path)
}

async function expandTreeToPath(targetPath: string) {
  const parts = targetPath.split('/').filter(Boolean)
  let current = treeRoot.value
  current.expanded = true
  if (current.children === null) await loadTreeNode(current)

  for (const part of parts) {
    if (!current.children) break
    const child = current.children.find(c => c.name === part)
    if (!child) break
    child.expanded = true
    if (child.children === null) await loadTreeNode(child)
    current = child
  }
}

// ── Column resize ──
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

// ── Editor (CodeMirror 6) ──
async function openEditor(fileName: string) {
  if (!server.value) return
  const f = files.value.find(file => file.name === fileName)
  if (f && f.size > 5 * 1024 * 1024) {
    toast(t('userServers.file.tooLarge'), 'warning')
    return
  }

  editorFile.value = fileName
  editorLoading.value = true
  editorOpen.value = true
  editorContent.value = ''

  const filePath = currentPath.value.replace(/\/$/, '') + '/' + fileName
  const data = await get<{ content: string }>(
    `/api/user/servers/${server.value.id}/files/contents?file=${encodeURIComponent(filePath)}`,
  )
  editorLoading.value = false
  if (data) {
    editorContent.value = data.content
    await nextTick()
    initCodeMirror(data.content, fileName)
  }
}

async function initCodeMirror(content: string, fileName: string) {
  if (editorView) {
    editorView.destroy()
    editorView = null
  }

  const container = editorRef.value
  if (!container) return

  const { EditorView, keymap, lineNumbers, highlightActiveLine, highlightActiveLineGutter, drawSelection } = await import('@codemirror/view')
  const { EditorState } = await import('@codemirror/state')
  const { defaultKeymap, indentWithTab, history, historyKeymap } = await import('@codemirror/commands')
  const { syntaxHighlighting, defaultHighlightStyle, bracketMatching, indentOnInput } = await import('@codemirror/language')
  const { searchKeymap, highlightSelectionMatches } = await import('@codemirror/search')
  const { oneDark } = await import('@codemirror/theme-one-dark')

  const lang = await detectLanguage(fileName)

  const extensions = [
    lineNumbers(),
    highlightActiveLine(),
    highlightActiveLineGutter(),
    drawSelection(),
    bracketMatching(),
    indentOnInput(),
    history(),
    highlightSelectionMatches(),
    syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
    oneDark,
    keymap.of([
      ...defaultKeymap,
      ...historyKeymap,
      ...searchKeymap,
      indentWithTab,
      { key: 'Mod-s', run: () => { saveEditor(); return true } },
    ]),
    EditorView.theme({
      '&': { height: '100%', fontSize: '13px' },
      '.cm-scroller': { fontFamily: "'IBM Plex Mono', monospace" },
      '.cm-content': { caretColor: 'var(--ac)' },
    }),
  ]

  if (lang) extensions.push(lang)

  editorView = new EditorView({
    state: EditorState.create({ doc: content, extensions }),
    parent: container,
  })
}

async function detectLanguage(fileName: string) {
  const ext = fileName.split('.').pop()?.toLowerCase() || ''

  switch (ext) {
    case 'json': {
      const { json } = await import('@codemirror/lang-json')
      return json()
    }
    case 'js': case 'mjs': case 'cjs': {
      const { javascript } = await import('@codemirror/lang-javascript')
      return javascript()
    }
    case 'ts': case 'mts': case 'cts': {
      const { javascript } = await import('@codemirror/lang-javascript')
      return javascript({ typescript: true })
    }
    case 'py': {
      const { python } = await import('@codemirror/lang-python')
      return python()
    }
    case 'html': case 'htm': case 'xml': case 'svg': {
      const { html } = await import('@codemirror/lang-html')
      return html()
    }
    case 'css': case 'scss': {
      const { css } = await import('@codemirror/lang-css')
      return css()
    }
    case 'md': case 'markdown': {
      const { markdown } = await import('@codemirror/lang-markdown')
      return markdown()
    }
    case 'yml': case 'yaml': {
      const { yaml } = await import('@codemirror/lang-yaml')
      return yaml()
    }
    default:
      return null
  }
}

async function saveEditor() {
  if (!server.value || editorSaving.value) return
  editorSaving.value = true

  // Get content from CodeMirror if active
  const content = editorView ? editorView.state.doc.toString() : editorContent.value
  const filePath = currentPath.value.replace(/\/$/, '') + '/' + editorFile.value

  const res = await post(
    `/api/user/servers/${server.value.id}/files/write?file=${encodeURIComponent(filePath)}`,
    { content },
  )
  editorSaving.value = false
  if (res !== undefined) {
    toast(t('userServers.file.saved'), 'success')
  }
}

function closeEditor() {
  editorOpen.value = false
  if (editorView) {
    editorView.destroy()
    editorView = null
  }
}

// ── New File ──
function openNewFile() {
  newFileName.value = ''
  newFileOpen.value = true
}

async function createFile() {
  if (!server.value || !newFileName.value.trim()) return
  const filePath = currentPath.value.replace(/\/$/, '') + '/' + newFileName.value.trim()
  const res = await post(
    `/api/user/servers/${server.value.id}/files/write?file=${encodeURIComponent(filePath)}`,
    { content: '' },
  )
  if (res !== undefined) {
    newFileOpen.value = false
    await loadFiles()
    openEditor(newFileName.value.trim())
  }
}

// ── New Folder ──
function openNewFolder() {
  newFolderName.value = ''
  newFolderOpen.value = true
}

async function createFolder() {
  if (!server.value || !newFolderName.value.trim()) return
  await post(`/api/user/servers/${server.value.id}/files/create-folder`, {
    name: newFolderName.value.trim(),
    path: currentPath.value,
  })
  newFolderOpen.value = false
  loadFiles()
  refreshTreeAt(currentPath.value)
}

// ── Rename ──
function openRename(fileName: string) {
  renameFrom.value = fileName
  renameTo.value = fileName
  renameOpen.value = true
  contextMenu.value = null
}

async function doRename() {
  if (!server.value || !renameTo.value.trim()) return
  await post(`/api/user/servers/${server.value.id}/files/rename`, {
    root: currentPath.value,
    from: renameFrom.value,
    to: renameTo.value.trim(),
  })
  renameOpen.value = false
  loadFiles()
  refreshTreeAt(currentPath.value)
}

// ── Move ──
function openMove(fileName: string) {
  moveFrom.value = fileName
  moveTo.value = ''
  moveOpen.value = true
  contextMenu.value = null
}

async function doMove() {
  if (!server.value || !moveTo.value.trim()) return
  const destPath = moveTo.value.trim().replace(/\/$/, '')
  await post(`/api/user/servers/${server.value.id}/files/rename`, {
    root: currentPath.value,
    from: moveFrom.value,
    to: destPath + '/' + moveFrom.value,
  })
  moveOpen.value = false
  loadFiles()
}

// ── Delete ──
async function deleteFiles(fileNames: string[]) {
  if (!server.value || !fileNames.length) return
  const ok = await confirm({
    title: t('common.confirm.deleteTitle'),
    message: t('userServers.file.confirmDelete', { n: fileNames.length }),
    confirmText: t('userServers.file.delete'),
    variant: 'danger',
  })
  if (!ok) return
  await post(`/api/user/servers/${server.value.id}/files/delete`, {
    root: currentPath.value,
    files: fileNames,
  })
  loadFiles()
  refreshTreeAt(currentPath.value)
}

async function deleteSelected() {
  await deleteFiles(Array.from(selectedFiles.value))
}

async function deleteSingle(name: string) {
  contextMenu.value = null
  await deleteFiles([name])
}

// ── Download ──
async function downloadFile(fileName: string) {
  if (!server.value) return
  contextMenu.value = null
  const filePath = currentPath.value.replace(/\/$/, '') + '/' + fileName
  const data = await get<{ url: string }>(
    `/api/user/servers/${server.value.id}/files/download?file=${encodeURIComponent(filePath)}`,
  )
  if (data?.url) {
    window.open(data.url, '_blank')
  }
}

// ── Upload ──
function triggerUpload() {
  uploadInputRef.value?.click()
}

async function handleUpload(e: Event) {
  const input = e.target as HTMLInputElement
  const fileList = input.files
  if (!fileList?.length || !server.value) return

  const urlData = await post<{ url: string }>(
    `/api/user/servers/${server.value.id}/files/upload`,
    {},
  )
  if (!urlData?.url) return

  const items = Array.from(fileList).map(f => ({
    name: f.name,
    progress: 0,
    status: 'pending' as const,
    file: f,
  }))
  uploads.value.push(...items.map(({ file, ...rest }) => rest))
  uploadPanelOpen.value = true

  const uploadUrl = urlData.url + `&directory=${encodeURIComponent(currentPath.value)}`

  // Upload sequentially (max 3 concurrent)
  const queue = [...items]
  const concurrency = 3
  let active = 0

  async function processNext() {
    if (!queue.length) return
    const item = queue.shift()!
    active++
    const idx = uploads.value.findIndex(u => u.name === item.name && u.status === 'pending')
    if (idx >= 0) uploads.value[idx].status = 'uploading'

    try {
      await new Promise<void>((resolve, reject) => {
        const xhr = new XMLHttpRequest()
        xhr.open('POST', uploadUrl)

        xhr.upload.onprogress = (ev) => {
          if (ev.lengthComputable && idx >= 0) {
            uploads.value[idx].progress = Math.round((ev.loaded / ev.total) * 100)
          }
        }

        xhr.onload = () => {
          if (idx >= 0) {
            uploads.value[idx].status = 'done'
            uploads.value[idx].progress = 100
          }
          resolve()
        }

        xhr.onerror = () => {
          if (idx >= 0) uploads.value[idx].status = 'error'
          reject()
        }

        const formData = new FormData()
        formData.append('files', item.file)
        xhr.send(formData)
      })
    } catch {
      // Error already handled in xhr.onerror
    }

    active--
    processNext()
  }

  for (let i = 0; i < Math.min(concurrency, items.length); i++) {
    processNext()
  }

  // Wait for all done
  const checkDone = setInterval(() => {
    const allDone = uploads.value.every(u => u.status === 'done' || u.status === 'error')
    if (allDone) {
      clearInterval(checkDone)
      loadFiles()
      setTimeout(() => {
        uploads.value = []
        uploadPanelOpen.value = false
      }, 3000)
    }
  }, 500)

  input.value = ''
}

// ── Compress / Decompress ──
async function compressFiles(fileNames: string[]) {
  if (!server.value || !fileNames.length) return
  await post(`/api/user/servers/${server.value.id}/files/compress`, {
    root: currentPath.value,
    files: fileNames,
  })
  loadFiles()
}

async function compressSelected() {
  await compressFiles(Array.from(selectedFiles.value))
}

async function decompressFile(fileName: string) {
  if (!server.value) return
  contextMenu.value = null
  await post(`/api/user/servers/${server.value.id}/files/decompress`, {
    root: currentPath.value,
    file: fileName,
  })
  loadFiles()
  refreshTreeAt(currentPath.value)
}

// ── Batch move ──
async function moveSelected() {
  if (!selectedFiles.value.size) return
  moveFrom.value = Array.from(selectedFiles.value).join(', ')
  moveTo.value = ''
  moveOpen.value = true
}

async function doBatchMove() {
  if (!server.value || !moveTo.value.trim() || !selectedFiles.value.size) return
  const destPath = moveTo.value.trim().replace(/\/$/, '')
  for (const name of selectedFiles.value) {
    await post(`/api/user/servers/${server.value.id}/files/rename`, {
      root: currentPath.value,
      from: name,
      to: destPath + '/' + name,
    })
  }
  moveOpen.value = false
  loadFiles()
}

// ── Batch download ──
async function downloadSelected() {
  for (const name of selectedFiles.value) {
    const f = files.value.find(file => file.name === name)
    if (f?.file) await downloadFile(name)
  }
}

// ── Context menu ──
function onContextMenu(e: MouseEvent, f: FileEntry) {
  e.preventDefault()
  // Mobile: use ActionSheet
  if (window.innerWidth <= 768) {
    mobileActionFile.value = f
    mobileActionOpen.value = true
    return
  }
  // Desktop: position context menu with viewport boundary checking
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

function closeContextMenu() {
  contextMenu.value = null
}

// Close context menu on click anywhere
if (typeof window !== 'undefined') {
  document.addEventListener('click', closeContextMenu)
}

// ── Tree refresh helper ──
function refreshTreeAt(path: string) {
  const parts = path.split('/').filter(Boolean)
  let node = treeRoot.value
  if (path === '/') {
    loadTreeNode(node)
    return
  }
  for (const part of parts) {
    if (!node.children) break
    const child = node.children.find(c => c.name === part)
    if (child) node = child
    else break
  }
  loadTreeNode(node)
}

// ── Drag & Drop ──
function onDragEnter(e: DragEvent) {
  e.preventDefault()
  if (e.dataTransfer?.types.includes('Files')) {
    dragOver.value = true
  }
}

function onDragOver(e: DragEvent) {
  e.preventDefault()
}

function onDragLeave(e: DragEvent) {
  // Only close if leaving the container
  const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
  if (e.clientX <= rect.left || e.clientX >= rect.right || e.clientY <= rect.top || e.clientY >= rect.bottom) {
    dragOver.value = false
  }
}

function onDrop(e: DragEvent) {
  e.preventDefault()
  dragOver.value = false
  const fileList = e.dataTransfer?.files
  if (!fileList?.length) return

  // Create a synthetic input event
  const dataTransfer = new DataTransfer()
  for (const f of fileList) {
    dataTransfer.items.add(f)
  }

  // Trigger the upload flow
  if (uploadInputRef.value) {
    uploadInputRef.value.files = dataTransfer.files
    uploadInputRef.value.dispatchEvent(new Event('change'))
  }
}
</script>

<template>
  <div
    class="files-page"
    @dragenter="onDragEnter"
    @dragover="onDragOver"
    @dragleave="onDragLeave"
    @drop="onDrop"
  >
    <input ref="uploadInputRef" type="file" multiple hidden @change="handleUpload" />

    <!-- Left: Tree panel (standalone card) -->
    <aside class="tree-panel">
      <div class="tree-content">
        <FileTreeNode
          :node="treeRoot"
          :current-path="currentPath"
          :depth="0"
          @select="selectTreeNode"
          @toggle="toggleTreeNode"
        />
      </div>
    </aside>

    <!-- Right top: Toolbar (standalone) -->
    <SectionToolbar class="files-toolbar">
      <template #start>
        <template v-if="hasSelection">
          <button class="clear-selection-btn" @click="clearSelection">
            <MsIcon name="close" size="sm" />
          </button>
          <span class="selection-count">{{ t('userServers.file.selected', { n: selectedFiles.size }) }}</span>
        </template>
        <template v-else>
          <FilterInput
            v-model="searchTerm"
            :placeholder="t('userServers.file.searchPlaceholder')"
            class="file-search-input"
          />
          <div class="breadcrumbs">
            <button
              v-for="(crumb, i) in breadcrumbs"
              :key="crumb.path"
              class="breadcrumb"
              :class="{ active: i === breadcrumbs.length - 1 }"
              @click="navigateTo(crumb.path)"
            >{{ crumb.label }}</button>
          </div>
        </template>
      </template>
      <template #end>
        <template v-if="hasSelection">
          <BaseButton size="sm" @click="moveSelected">
            <MsIcon name="drive_file_move" size="xs" />
            <span class="btn-label">{{ t('userServers.file.move') }}</span>
          </BaseButton>
          <BaseButton size="sm" @click="compressSelected">
            <MsIcon name="folder_zip" size="xs" />
            <span class="btn-label">{{ t('userServers.file.compress') }}</span>
          </BaseButton>
          <BaseButton size="sm" @click="downloadSelected">
            <MsIcon name="download" size="xs" />
            <span class="btn-label">{{ t('userServers.file.download') }}</span>
          </BaseButton>
          <BaseButton size="sm" variant="danger" @click="deleteSelected">
            <MsIcon name="delete" size="xs" />
            <span class="btn-label">{{ t('userServers.file.delete') }}</span>
          </BaseButton>
        </template>
        <template v-else>
          <BaseButton size="sm" @click="openNewFile">
            <MsIcon name="note_add" size="xs" />
            <span class="btn-label">{{ t('userServers.file.newFile') }}</span>
          </BaseButton>
          <BaseButton size="sm" @click="openNewFolder">
            <MsIcon name="create_new_folder" size="xs" />
            <span class="btn-label">{{ t('userServers.file.newFolder') }}</span>
          </BaseButton>
          <BaseButton size="sm" @click="triggerUpload">
            <MsIcon name="upload" size="xs" />
            <span class="btn-label">{{ t('userServers.file.upload') }}</span>
          </BaseButton>
        </template>
      </template>
    </SectionToolbar>

    <!-- Right bottom: File list (standalone card) -->
    <div class="file-list-panel">
      <!-- Loading -->
      <div v-if="filesLoading" class="file-list-loading">
        <Spinner />
      </div>

      <!-- Empty -->
      <EmptyState
        v-else-if="!files.length"
        icon="folder_open"
        :title="t('userServers.file.empty')"
        density="compact"
      />

      <!-- No search results -->
      <EmptyState
        v-else-if="!sortedFiles.length"
        icon="search_off"
        :title="t('userServers.file.noResults')"
        density="compact"
      />

      <!-- File table -->
      <table v-else class="file-table" :style="tableColStyle">
        <thead>
          <tr>
            <th class="col-check">
              <input type="checkbox" :checked="allSelected" @change="toggleSelectAll" />
            </th>
            <th class="col-name">
              {{ t('userServers.file.name') }}
              <span class="col-resize" @mousedown.prevent="startColResize($event, 0)" />
            </th>
            <th class="col-size">
              {{ t('userServers.file.size') }}
              <span class="col-resize" @mousedown.prevent="startColResize($event, 1)" />
            </th>
            <th class="col-date">
              {{ t('userServers.file.modified') }}
              <span class="col-resize" @mousedown.prevent="startColResize($event, 2)" />
            </th>
            <th class="col-actions">{{ t('userServers.file.actions') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="f in sortedFiles"
            :key="f.name"
            :class="{ selected: selectedFiles.has(f.name) }"
            @click="openEntry(f)"
            @contextmenu="onContextMenu($event, f)"
          >
            <td class="col-check" @click.stop>
              <input type="checkbox" :checked="selectedFiles.has(f.name)" @change="toggleSelect(f.name)" />
            </td>
            <td class="col-name">
              <span class="file-name-cell">
                <MsIcon :name="fileIcon(f)" size="sm" class="file-icon" :class="{ 'file-icon--dir': !f.file }" />
                <span class="file-name-text">{{ f.name }}</span>
              </span>
            </td>
            <td class="col-size">{{ f.file ? formatSize(f.size) : '\u2014' }}</td>
            <td class="col-date">{{ formatDate(f.modified) }}</td>
            <td class="col-actions" @click.stop>
              <div class="row-actions">
                <button v-if="f.file && isEditable(f)" class="action-btn" :title="t('userServers.file.edit')" @click="openEditor(f.name)">
                  <MsIcon name="edit" size="sm" />
                </button>
                <button v-if="f.file" class="action-btn" :title="t('userServers.file.download')" @click="downloadFile(f.name)">
                  <MsIcon name="download" size="sm" />
                </button>
                <button class="action-btn" :title="t('userServers.file.rename')" @click="openRename(f.name)">
                  <MsIcon name="drive_file_rename_outline" size="sm" />
                </button>
                <button class="action-btn action-btn--danger" :title="t('userServers.file.delete')" @click="deleteSingle(f.name)">
                  <MsIcon name="delete" size="sm" />
                </button>
                <button class="action-btn" :title="t('userServers.file.moreActions')" @click="onContextMenu($event, f)">
                  <MsIcon name="more_vert" size="sm" />
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Drag overlay -->
    <Transition name="fade">
      <div v-if="dragOver" class="drag-overlay" @drop="onDrop" @dragover.prevent @dragleave.prevent>
        <div class="drag-overlay-content">
          <MsIcon name="upload" class="drag-icon" />
          <p>{{ t('userServers.file.dragHint') }}</p>
        </div>
      </div>
    </Transition>

    <!-- Context menu (desktop only) -->
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
        <button v-if="contextMenu.file.file && isEditable(contextMenu.file)" class="context-item" @click="openEditor(contextMenu.file.name); closeContextMenu()">
          <MsIcon name="edit" size="sm" /> {{ t('userServers.file.edit') }}
        </button>
        <button class="context-item" @click="openRename(contextMenu.file.name)">
          <MsIcon name="drive_file_rename_outline" size="sm" /> {{ t('userServers.file.rename') }}
        </button>
        <button class="context-item" @click="openMove(contextMenu.file.name)">
          <MsIcon name="drive_file_move" size="sm" /> {{ t('userServers.file.move') }}
        </button>
        <button v-if="contextMenu.file.file" class="context-item" @click="downloadFile(contextMenu.file.name)">
          <MsIcon name="download" size="sm" /> {{ t('userServers.file.download') }}
        </button>
        <div class="context-divider" />
        <button class="context-item" @click="compressFiles([contextMenu.file.name]); closeContextMenu()">
          <MsIcon name="folder_zip" size="sm" /> {{ t('userServers.file.compress') }}
        </button>
        <button v-if="contextMenu.file.file && isArchive(contextMenu.file)" class="context-item" @click="decompressFile(contextMenu.file.name)">
          <MsIcon name="unarchive" size="sm" /> {{ t('userServers.file.decompress') }}
        </button>
        <div class="context-divider" />
        <button class="context-item context-item--danger" @click="deleteSingle(contextMenu.file.name)">
          <MsIcon name="delete" size="sm" /> {{ t('userServers.file.delete') }}
        </button>
      </div>
    </Teleport>

    <!-- Mobile action sheet -->
    <ActionSheet v-model="mobileActionOpen" :title="mobileActionFile?.name">
      <template v-if="mobileActionFile">
        <button v-if="mobileActionFile.file && isEditable(mobileActionFile)" @click="mobileActionOpen = false; openEditor(mobileActionFile!.name)">
          <MsIcon name="edit" size="sm" /> {{ t('userServers.file.edit') }}
        </button>
        <button @click="mobileActionOpen = false; openRename(mobileActionFile!.name)">
          <MsIcon name="drive_file_rename_outline" size="sm" /> {{ t('userServers.file.rename') }}
        </button>
        <button @click="mobileActionOpen = false; openMove(mobileActionFile!.name)">
          <MsIcon name="drive_file_move" size="sm" /> {{ t('userServers.file.move') }}
        </button>
        <button v-if="mobileActionFile.file" @click="mobileActionOpen = false; downloadFile(mobileActionFile!.name)">
          <MsIcon name="download" size="sm" /> {{ t('userServers.file.download') }}
        </button>
        <button @click="mobileActionOpen = false; compressFiles([mobileActionFile!.name])">
          <MsIcon name="folder_zip" size="sm" /> {{ t('userServers.file.compress') }}
        </button>
        <button v-if="mobileActionFile.file && isArchive(mobileActionFile)" @click="mobileActionOpen = false; decompressFile(mobileActionFile!.name)">
          <MsIcon name="unarchive" size="sm" /> {{ t('userServers.file.decompress') }}
        </button>
        <button class="action-sheet--danger" @click="mobileActionOpen = false; deleteSingle(mobileActionFile!.name)">
          <MsIcon name="delete" size="sm" /> {{ t('userServers.file.delete') }}
        </button>
      </template>
    </ActionSheet>

    <!-- Upload progress panel -->
    <Transition name="slide-up">
      <div v-if="uploadPanelOpen && uploads.length" class="upload-panel">
        <div class="upload-panel-header">
          <span>
            {{ t('userServers.file.uploadProgress') }}
            ({{ uploads.filter(u => u.status === 'done').length }}/{{ uploads.length }})
          </span>
          <button class="upload-panel-close" @click="uploadPanelOpen = false">
            <MsIcon name="close" size="xs" />
          </button>
        </div>
        <div class="upload-panel-list">
          <div v-for="u in uploads" :key="u.name" class="upload-item">
            <MsIcon
              :name="u.status === 'done' ? 'check_circle' : u.status === 'error' ? 'error' : 'upload_file'"
              size="sm"
              :class="'upload-icon--' + u.status"
            />
            <span class="upload-name">{{ u.name }}</span>
            <span v-if="u.status === 'uploading'" class="upload-pct">{{ u.progress }}%</span>
            <span v-else-if="u.status === 'pending'" class="upload-pct upload-pct--pending">{{ t('userServers.file.uploadWaiting') }}</span>
          </div>
        </div>
      </div>
    </Transition>

    <!-- Editor modal (full-screen) -->
    <Teleport to="body">
      <Transition name="fade">
        <div v-if="editorOpen" class="editor-overlay" @click.self="closeEditor">
          <div class="editor-modal">
            <div class="editor-header">
              <div class="editor-title">
                <MsIcon name="edit" size="sm" />
                <span>{{ editorFile }}</span>
              </div>
              <div class="editor-actions">
                <BaseButton size="xs" variant="primary" :loading="editorSaving" @click="saveEditor">
                  <MsIcon name="save" size="xs" />
                  {{ t('userServers.file.save') }}
                </BaseButton>
                <button class="editor-close-btn" @click="closeEditor">
                  <MsIcon name="close" size="sm" />
                </button>
              </div>
            </div>
            <div class="editor-body">
              <div v-if="editorLoading" class="editor-loading">
                <Spinner />
              </div>
              <div v-else ref="editorRef" class="editor-container" />
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- New File modal -->
    <BaseModal v-model="newFileOpen" :title="t('userServers.file.newFile')">
      <BaseInput v-model="newFileName" :placeholder="t('userServers.file.fileName')" @keydown.enter="createFile" />
      <template #footer>
        <BaseButton @click="newFileOpen = false">{{ t('common.btn.cancel') }}</BaseButton>
        <BaseButton variant="primary" @click="createFile">{{ t('common.btn.confirm') }}</BaseButton>
      </template>
    </BaseModal>

    <!-- New Folder modal -->
    <BaseModal v-model="newFolderOpen" :title="t('userServers.file.newFolder')">
      <BaseInput v-model="newFolderName" :placeholder="t('userServers.file.folderName')" @keydown.enter="createFolder" />
      <template #footer>
        <BaseButton @click="newFolderOpen = false">{{ t('common.btn.cancel') }}</BaseButton>
        <BaseButton variant="primary" @click="createFolder">{{ t('common.btn.confirm') }}</BaseButton>
      </template>
    </BaseModal>

    <!-- Rename modal -->
    <BaseModal v-model="renameOpen" :title="t('userServers.file.rename')">
      <BaseInput v-model="renameTo" :placeholder="t('userServers.file.newName')" @keydown.enter="doRename" />
      <template #footer>
        <BaseButton @click="renameOpen = false">{{ t('common.btn.cancel') }}</BaseButton>
        <BaseButton variant="primary" @click="doRename">{{ t('common.btn.confirm') }}</BaseButton>
      </template>
    </BaseModal>

    <!-- Move modal -->
    <BaseModal v-model="moveOpen" :title="t('userServers.file.move')">
      <BaseInput v-model="moveTo" :placeholder="t('userServers.file.moveHint')" @keydown.enter="hasSelection ? doBatchMove() : doMove()" />
      <template #footer>
        <BaseButton @click="moveOpen = false">{{ t('common.btn.cancel') }}</BaseButton>
        <BaseButton variant="primary" @click="hasSelection ? doBatchMove() : doMove()">{{ t('common.btn.confirm') }}</BaseButton>
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
  padding: var(--sp-2) 0;
}

/* ── File list panel (standalone card, grid row 2 col 2) ── */
.file-list-panel {
  grid-column: 2;
  grid-row: 2;
  min-width: 0;
  min-height: 0;
  overflow: auto;
  border: 1px solid var(--bd);
  border-radius: var(--r-md);
  background: var(--bg2);
}

.file-list-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--sp-8);
}

/* ── File table ── */
.file-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--text-sm);
  table-layout: fixed;
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
  width: 32px;
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

/* ── Context menu ── */
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

.context-divider {
  height: 1px;
  background: var(--bd);
  margin: var(--sp-1) var(--sp-2);
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

/* ── Upload progress panel ── */
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

:deep(.upload-icon--done) {
  color: var(--green);
}

:deep(.upload-icon--error) {
  color: var(--red);
}

:deep(.upload-icon--uploading) {
  color: var(--ac);
}

:deep(.upload-icon--pending) {
  color: var(--t3);
}

/* ── Editor overlay ── */
.editor-overlay {
  position: fixed;
  inset: 0;
  z-index: 500;
  background: rgba(0, 0, 0, .7);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}

.editor-modal {
  width: 100%;
  max-width: 1100px;
  height: 90vh;
  display: flex;
  flex-direction: column;
  background: var(--bg);
  border: 1px solid var(--bd);
  border-radius: var(--r-lg);
  overflow: hidden;
}

.editor-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--sp-2) var(--sp-4);
  border-bottom: 1px solid var(--bd);
  background: var(--bg2);
  min-height: 44px;
}

.editor-title {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: var(--text-base);
  font-weight: 500;
  color: var(--t1);
  min-width: 0;
  overflow: hidden;
}

.editor-title span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.editor-actions {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}

.editor-close-btn {
  background: none;
  border: none;
  color: var(--t3);
  cursor: pointer;
  padding: 4px;
  border-radius: var(--r-xs);
  display: flex;
  align-items: center;
}

.editor-close-btn:hover {
  color: var(--t1);
  background: var(--bg4);
}

.editor-body {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.editor-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}

.editor-container {
  height: 100%;
}

.editor-container :deep(.cm-editor) {
  height: 100%;
}

.editor-container :deep(.cm-scroller) {
  overflow: auto;
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

.slide-up-enter-active,
.slide-up-leave-active {
  transition: transform .25s, opacity .25s;
}

.slide-up-enter-from,
.slide-up-leave-to {
  transform: translateY(20px);
  opacity: 0;
}

/* ── Responsive ── */
@media (max-width: 768px) {
  .files-page {
    grid-template-columns: 1fr;
    grid-template-rows: auto 1fr;
    height: calc(100vh - 160px);
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

  .upload-panel {
    left: 10px;
    right: 10px;
    width: auto;
    bottom: 10px;
  }

  .editor-overlay {
    padding: 0;
  }

  .editor-modal {
    border-radius: 0;
    max-width: 100%;
    height: 100vh;
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
