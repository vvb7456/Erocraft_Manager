import { ref, computed, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'
import { useServerActivityReporter } from '@/composables/useServerActivityReporter'
import type { FileEntry } from '@/composables/useFileTree'
import { validateFileName, sanitizeMovePath } from '@/utils/path'

export function useFileOperations(serverId: Ref<number | undefined>) {
  const { t } = useI18n({ useScope: 'global' })
  const { get, post } = useApiFetch()
  const { toast } = useToast()
  const { confirm } = useConfirm()
  const { reportServerActivity } = useServerActivityReporter(serverId)

  // ── State ──
  const currentPath = ref('/')
  const files = ref<FileEntry[]>([])
  const filesLoading = ref(false)
  const searchTerm = ref('')
  const selectedFiles = ref<Set<string>>(new Set())

  // Modal state
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

  // Compress state
  const compressing = ref(false)
  const decompressing = ref(false)

  // Operating guard for instant CRUD operations
  const operating = ref(false)

  function scheduleTaskCleanup() {
    setTimeout(() => {
      const allDone = tasks.value.every(u => u.status === 'done' || u.status === 'error')
      if (allDone) {
        tasks.value = []
        uploadPanelOpen.value = false
      }
    }, 3000)
  }

  // Upload state
  const uploadInputRef = ref<HTMLInputElement | null>(null)
  const dragOver = ref(false)
  const tasks = ref<{ name: string; progress: number; status: 'pending' | 'uploading' | 'done' | 'error'; startTime?: number }[]>([])
  const uploadPanelOpen = ref(false)

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

  const sortBy = ref<'name' | 'size' | 'modified'>('name')
  const sortOrder = ref<'asc' | 'desc'>('asc')

  const sortedFiles = computed(() => {
    let items = files.value
    if (searchTerm.value.trim()) {
      const q = searchTerm.value.toLowerCase()
      items = items.filter(f => f.name.toLowerCase().includes(q))
    }
    const dirs = items.filter(f => !f.file)
    const fls = items.filter(f => f.file)

    const cmp = (a: FileEntry, b: FileEntry): number => {
      let r = 0
      switch (sortBy.value) {
        case 'name':
          r = a.name.localeCompare(b.name)
          break
        case 'size':
          r = (a.size || 0) - (b.size || 0)
          break
        case 'modified':
          r = new Date(a.modified || 0).getTime() - new Date(b.modified || 0).getTime()
          break
      }
      return sortOrder.value === 'asc' ? r : -r
    }

    return [...dirs.sort(cmp), ...fls.sort(cmp)]
  })

  function toggleSort(col: 'name' | 'size' | 'modified') {
    if (sortBy.value === col) {
      sortOrder.value = sortOrder.value === 'asc' ? 'desc' : 'asc'
    } else {
      sortBy.value = col
      sortOrder.value = 'asc'
    }
  }

  const hasSelection = computed(() => selectedFiles.value.size > 0)
  const allSelected = computed(() => sortedFiles.value.length > 0 && selectedFiles.value.size === sortedFiles.value.length)

  // ── Helpers ──
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
    if (!serverId.value) return
    if (dir !== undefined) currentPath.value = dir
    selectedFiles.value = new Set()
    searchTerm.value = ''
    filesLoading.value = true
    const data = await get<FileEntry[]>(
      `/api/user/servers/${serverId.value}/files/list?directory=${encodeURIComponent(currentPath.value)}`,
      { silent: true },
    )
    filesLoading.value = false
    if (data) files.value = data
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

  // ── Inline validation errors ──
  const newFileError = computed(() => {
    const name = newFileName.value.trim()
    if (!name) return null
    const err = validateFileName(name)
    return err ? t(`userServers.file.validation.${err}`) : null
  })
  const newFolderError = computed(() => {
    const name = newFolderName.value.trim()
    if (!name) return null
    const err = validateFileName(name)
    return err ? t(`userServers.file.validation.${err}`) : null
  })
  const renameError = computed(() => {
    const name = renameTo.value.trim()
    if (!name) return null
    const err = validateFileName(name)
    return err ? t(`userServers.file.validation.${err}`) : null
  })

  // ── CRUD operations ──
  function openNewFile() {
    newFileName.value = ''
    newFileOpen.value = true
  }

  async function createFile() {
    if (!serverId.value || operating.value) return null
    const name = newFileName.value.trim()
    const err = validateFileName(name)
    if (err) { toast(t(`userServers.file.validation.${err}`), 'error'); return null }
    const filePath = currentPath.value.replace(/\/$/, '') + '/' + name
    operating.value = true
    try {
      const res = await post(
        `/api/user/servers/${serverId.value}/files/write?file=${encodeURIComponent(filePath)}`,
        { content: '' },
      )
      if (res !== undefined) {
        newFileOpen.value = false
        await loadFiles()
        return newFileName.value.trim()
      }
      return null
    } finally {
      operating.value = false
    }
  }

  function openNewFolder() {
    newFolderName.value = ''
    newFolderOpen.value = true
  }

  async function createFolder(onRefreshTree?: () => void) {
    if (!serverId.value) return
    const name = newFolderName.value.trim()
    const err = validateFileName(name)
    if (err) { toast(t(`userServers.file.validation.${err}`), 'error'); return }
    operating.value = true
    try {
      await post(`/api/user/servers/${serverId.value}/files/create-folder`, {
        name,
        path: currentPath.value,
      })
      newFolderOpen.value = false
      loadFiles()
      onRefreshTree?.()
    } finally {
      operating.value = false
    }
  }

  function openRename(fileName: string) {
    renameFrom.value = fileName
    renameTo.value = fileName
    renameOpen.value = true
  }

  async function doRename(onRefreshTree?: () => void) {
    if (!serverId.value) return
    const name = renameTo.value.trim()
    const err = validateFileName(name)
    if (err) { toast(t(`userServers.file.validation.${err}`), 'error'); return }
    operating.value = true
    try {
      await post(`/api/user/servers/${serverId.value}/files/rename`, {
        root: currentPath.value,
        from: renameFrom.value,
        to: name,
      })
      renameOpen.value = false
      loadFiles()
      onRefreshTree?.()
    } finally {
      operating.value = false
    }
  }

  function openMove(fileName: string) {
    moveFrom.value = fileName
    moveTo.value = ''
    moveOpen.value = true
  }

  async function doMove() {
    if (!serverId.value || !moveTo.value.trim()) return
    const destPath = sanitizeMovePath(moveTo.value)
    operating.value = true
    try {
      await post(`/api/user/servers/${serverId.value}/files/rename`, {
        root: currentPath.value,
        from: moveFrom.value,
        to: destPath.replace(/\/$/, '') + '/' + moveFrom.value,
      })
      moveOpen.value = false
      loadFiles()
    } finally {
      operating.value = false
    }
  }

  async function deleteFiles(fileNames: string[], onRefreshTree?: () => void) {
    if (!serverId.value || !fileNames.length || operating.value) return
    const ok = await confirm({
      title: t('common.confirm.deleteTitle'),
      message: t('userServers.file.confirmDelete', { n: fileNames.length }),
      confirmText: t('userServers.file.delete'),
      variant: 'danger',
    })
    if (!ok) return
    operating.value = true
    try {
      await post(`/api/user/servers/${serverId.value}/files/delete`, {
        root: currentPath.value,
        files: fileNames,
      })
      loadFiles()
      onRefreshTree?.()
    } finally {
      operating.value = false
    }
  }

  async function deleteSelected(onRefreshTree?: () => void) {
    await deleteFiles(Array.from(selectedFiles.value), onRefreshTree)
  }

  async function deleteSingle(name: string, onRefreshTree?: () => void) {
    await deleteFiles([name], onRefreshTree)
  }

  async function downloadFile(fileName: string) {
    if (!serverId.value) return
    const filePath = currentPath.value.replace(/\/$/, '') + '/' + fileName
    const data = await get<{ url: string }>(
      `/api/user/servers/${serverId.value}/files/download?file=${encodeURIComponent(filePath)}`,
    )
    if (data?.url) {
      window.open(data.url, '_blank')
    }
  }



  // ── Upload ──
  let activeXhr: XMLHttpRequest | null = null

  function triggerUpload() {
    uploadInputRef.value?.click()
  }

  function cancelUpload() {
    if (activeXhr) {
      activeXhr.abort()
      activeXhr = null
    }
    tasks.value = []
    uploadPanelOpen.value = false
  }

  async function handleUpload(e: Event) {
    const input = e.target as HTMLInputElement
    const fileList = input.files
    if (!fileList?.length || !serverId.value) return

    if (fileList.length > 1) {
      toast(t('userServers.file.singleFileOnly'), 'error')
      input.value = ''
      return
    }

    const tokenData = await get<{ token: string; baseUrl: string; serverUuid: string; uploadSize: number }>(
      `/api/user/servers/${serverId.value}/wings-token`,
    )
    if (!tokenData?.token) return

    const file = fileList[0]

    // Client-side size pre-check. Wings enforces upload_size via
    // http.MaxBytesReader which only errors AFTER receiving the full body,
    // so without this check the user would watch the upload progress reach
    // 100% before getting a failure. Reject early to save bandwidth.
    const limitMib = tokenData.uploadSize
    if (limitMib > 0 && file.size > limitMib * 1024 * 1024) {
      toast(t('userServers.file.uploadTooLarge', { limit: limitMib }), 'error')
      input.value = ''
      return
    }
    const taskEntry = { name: file.name, progress: 0, status: 'uploading' as const, startTime: Date.now(), type: 'upload' as const }
    tasks.value.push(taskEntry)
    uploadPanelOpen.value = true

    const uploadUrl = `${tokenData.baseUrl}/upload/file?token=${tokenData.token}&directory=${encodeURIComponent(currentPath.value)}`
    const idx = tasks.value.length - 1

    try {
      await new Promise<void>((resolve, reject) => {
        const xhr = new XMLHttpRequest()
        activeXhr = xhr
        xhr.open('POST', uploadUrl)

        xhr.upload.onprogress = (ev) => {
          if (ev.lengthComputable) {
            tasks.value[idx].progress = Math.round((ev.loaded / ev.total) * 100)
          }
        }

        xhr.onload = () => {
          activeXhr = null
          if (xhr.status >= 200 && xhr.status < 300) {
            tasks.value[idx].status = 'done'
            tasks.value[idx].progress = 100
          } else {
            tasks.value[idx].status = 'error'
          }
          resolve()
        }

        xhr.onerror = () => {
          activeXhr = null
          tasks.value[idx].status = 'error'
          resolve()
        }

        xhr.onabort = () => {
          activeXhr = null
          resolve()
        }

        const formData = new FormData()
        formData.append('files', file)
        xhr.send(formData)
      })
    } catch {
      // handled
    }

    if (tasks.value[idx]?.status === 'done') {
      void reportServerActivity('server:file.uploaded', {
        directory: currentPath.value,
        file: file.name,
      })
    }

    loadFiles()
    setTimeout(() => {
      tasks.value = []
      uploadPanelOpen.value = false
    }, 3000)

    input.value = ''
  }

  // ── Compress / Decompress ──
  async function compressFiles(fileNames: string[]) {
    if (!serverId.value || !fileNames.length || compressing.value) return
    compressing.value = true
    const taskName = fileNames.length === 1 ? fileNames[0] : `${fileNames.length} files`
    const taskEntry = { name: `⚙ ${t('userServers.file.compress')}: ${taskName}`, progress: -1, status: 'uploading' as const, startTime: Date.now(), type: 'compress' as const }
    tasks.value.push(taskEntry)
    uploadPanelOpen.value = true
    try {
      await post(`/api/user/servers/${serverId.value}/files/compress`, {
        root: currentPath.value,
        files: fileNames,
      })
      taskEntry.status = 'done' as any
      taskEntry.progress = 100
      loadFiles()
    } catch {
      taskEntry.status = 'error' as any
    } finally {
      compressing.value = false
      scheduleTaskCleanup()
    }
  }

  async function compressSelected() {
    await compressFiles(Array.from(selectedFiles.value))
  }

  async function decompressFile(fileName: string, onRefreshTree?: () => void) {
    if (!serverId.value || decompressing.value) return
    decompressing.value = true
    const taskEntry = { name: `⚙ ${t('userServers.file.decompress')}: ${fileName}`, progress: -1, status: 'uploading' as const, startTime: Date.now(), type: 'decompress' as const }
    tasks.value.push(taskEntry)
    uploadPanelOpen.value = true
    try {
      await post(`/api/user/servers/${serverId.value}/files/decompress`, {
        root: currentPath.value,
        file: fileName,
      })
      taskEntry.status = 'done' as any
      taskEntry.progress = 100
      loadFiles()
      onRefreshTree?.()
    } catch {
      taskEntry.status = 'error' as any
    } finally {
      decompressing.value = false
    }
    scheduleTaskCleanup()
  }

  // ── Batch move ──
  async function moveSelected() {
    if (!selectedFiles.value.size) return
    moveFrom.value = Array.from(selectedFiles.value).join(', ')
    moveTo.value = ''
    moveOpen.value = true
  }

  async function doBatchMove() {
    if (!serverId.value || !moveTo.value.trim() || !selectedFiles.value.size) return
    const destPath = moveTo.value.trim().replace(/\/$/, '')
    for (const name of selectedFiles.value) {
      await post(`/api/user/servers/${serverId.value}/files/rename`, {
        root: currentPath.value,
        from: name,
        to: destPath + '/' + name,
      })
    }
    moveOpen.value = false
    loadFiles()
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
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
    if (e.clientX <= rect.left || e.clientX >= rect.right || e.clientY <= rect.top || e.clientY >= rect.bottom) {
      dragOver.value = false
    }
  }

  function onDrop(e: DragEvent) {
    e.preventDefault()
    dragOver.value = false
    const items = e.dataTransfer?.items
    const fileList = e.dataTransfer?.files
    if (!fileList?.length) return

    // Detect folder drops
    if (items) {
      for (let i = 0; i < items.length; i++) {
        const entry = items[i].webkitGetAsEntry?.()
        if (entry?.isDirectory) {
          toast(t('userServers.file.folderUploadNotSupported'), 'error')
          return
        }
      }
    }

    if (fileList.length > 1) {
      toast(t('userServers.file.singleFileOnly'), 'error')
      return
    }

    const dataTransfer = new DataTransfer()
    dataTransfer.items.add(fileList[0])

    if (uploadInputRef.value) {
      uploadInputRef.value.files = dataTransfer.files
      uploadInputRef.value.dispatchEvent(new Event('change'))
    }
  }

  return {
    // State
    currentPath,
    files,
    filesLoading,
    searchTerm,
    selectedFiles,
    // Modal state
    newFolderOpen, newFolderName,
    newFileOpen, newFileName,
    renameOpen, renameFrom, renameTo,
    moveOpen, moveFrom, moveTo,
    // Upload state
    uploadInputRef, dragOver, tasks, uploadPanelOpen,
    // Compress state
    compressing,
    decompressing,
    // Operating guard
    operating,
    // Computed
    breadcrumbs, sortedFiles, hasSelection, allSelected,
    newFileError, newFolderError, renameError,
    // Sort
    sortBy, sortOrder, toggleSort,
    // Helpers
    isEditable, isArchive, fileIcon, formatSize, formatDate,
    // Operations
    loadFiles, toggleSelect, toggleSelectAll, clearSelection,
    openNewFile, createFile, openNewFolder, createFolder,
    openRename, doRename, openMove, doMove,
    deleteFiles, deleteSelected, deleteSingle,
    downloadFile,
    triggerUpload, handleUpload, cancelUpload,
    compressFiles, compressSelected, decompressFile,
    moveSelected, doBatchMove,
    // Drag & Drop
    onDragEnter, onDragOver, onDragLeave, onDrop,
  }
}
