<script setup lang="ts">
import { ref, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import BaseButton from '@/components/ui/BaseButton.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import Spinner from '@/components/ui/Spinner.vue'

defineOptions({ name: 'FileEditor' })

const props = defineProps<{
  serverId: number
  currentPath: string
}>()

const emit = defineEmits<{
  saved: []
}>()

const { t } = useI18n({ useScope: 'global' })
const { get, post } = useApiFetch()
const { toast } = useToast()

const open = ref(false)
const fileName = ref('')
const content = ref('')
const editorLoading = ref(false)
const saving = ref(false)
const editorRef = ref<HTMLDivElement | null>(null)
const mouseDownOnOverlay = ref(false)
let editorView: any = null

async function openFile(name: string, fileSize?: number) {
  if (fileSize && fileSize > 5 * 1024 * 1024) {
    toast(t('userServers.file.tooLarge'), 'warning')
    return
  }

  fileName.value = name
  editorLoading.value = true
  open.value = true
  content.value = ''

  const filePath = props.currentPath.replace(/\/$/, '') + '/' + name
  const data = await get<{ content: string }>(
    `/api/user/servers/${props.serverId}/files/contents?file=${encodeURIComponent(filePath)}`,
  )
  editorLoading.value = false
  if (data) {
    content.value = data.content
    await nextTick()
    initCodeMirror(data.content, name)
  }
}

async function initCodeMirror(doc: string, fName: string) {
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

  const lang = await detectLanguage(fName)

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
      { key: 'Mod-s', run: () => { save(); return true } },
    ]),
    EditorView.theme({
      '&': { height: '100%', fontSize: '13px' },
      '.cm-scroller': { fontFamily: "'IBM Plex Mono', monospace" },
      '.cm-content': { caretColor: 'var(--ac)' },
    }),
  ]

  if (lang) extensions.push(lang)

  editorView = new EditorView({
    state: EditorState.create({ doc, extensions }),
    parent: container,
  })
}

async function detectLanguage(fName: string) {
  const ext = fName.split('.').pop()?.toLowerCase() || ''
  switch (ext) {
    case 'json': { const { json } = await import('@codemirror/lang-json'); return json() }
    case 'js': case 'mjs': case 'cjs': { const { javascript } = await import('@codemirror/lang-javascript'); return javascript() }
    case 'ts': case 'mts': case 'cts': { const { javascript } = await import('@codemirror/lang-javascript'); return javascript({ typescript: true }) }
    case 'py': { const { python } = await import('@codemirror/lang-python'); return python() }
    case 'html': case 'htm': case 'xml': case 'svg': { const { html } = await import('@codemirror/lang-html'); return html() }
    case 'css': case 'scss': { const { css } = await import('@codemirror/lang-css'); return css() }
    case 'md': case 'markdown': { const { markdown } = await import('@codemirror/lang-markdown'); return markdown() }
    case 'yml': case 'yaml': { const { yaml } = await import('@codemirror/lang-yaml'); return yaml() }
    default: return null
  }
}

async function save() {
  if (saving.value) return
  saving.value = true

  const c = editorView ? editorView.state.doc.toString() : content.value
  const filePath = props.currentPath.replace(/\/$/, '') + '/' + fileName.value

  const res = await post(
    `/api/user/servers/${props.serverId}/files/write?file=${encodeURIComponent(filePath)}`,
    { content: c },
  )
  saving.value = false
  if (res !== undefined) {
    toast(t('userServers.file.saved'), 'success')
    emit('saved')
  }
}

function close() {
  open.value = false
  if (editorView) {
    editorView.destroy()
    editorView = null
  }
}

defineExpose({ openFile })
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="open" class="editor-overlay" @mousedown.self="mouseDownOnOverlay = true" @mouseup.self="if (mouseDownOnOverlay) close(); mouseDownOnOverlay = false" @click.self.prevent>
        <div class="editor-modal">
          <div class="editor-header">
            <div class="editor-title">
              <MsIcon name="edit" size="sm" />
              <span>{{ fileName }}</span>
            </div>
            <div class="editor-actions">
              <BaseButton size="xs" variant="primary" :loading="saving" @click="save">
                <MsIcon name="save" size="xs" />
                {{ t('userServers.file.save') }}
              </BaseButton>
              <button class="editor-close-btn" @click="close">
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
</template>

<style scoped>
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
  flex-shrink: 0;
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

.fade-enter-active,
.fade-leave-active {
  transition: opacity .2s;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

@media (max-width: 768px) {
  .editor-overlay {
    padding: 0;
  }

  .editor-modal {
    border-radius: 0;
    max-width: 100%;
    height: 100vh;
    height: 100dvh;
  }

  .editor-header {
    padding: var(--sp-2) var(--sp-3);
    position: sticky;
    top: 0;
    z-index: 1;
  }

  .editor-title span {
    max-width: 40vw;
  }
}
</style>
