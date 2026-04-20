import { ref, type Ref } from 'vue'
import { useApiFetch } from '@/composables/useApiFetch'
import type { TreeNode } from '@/components/ui/FileTreeNode.vue'

export interface FileEntry {
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

export function useFileTree(serverId: Ref<number | undefined>) {
  const { get } = useApiFetch()

  const treeRoot = ref<TreeNode>({
    name: '/',
    path: '/',
    children: null,
    expanded: true,
    loading: false,
  })

  async function loadTreeNode(node: TreeNode) {
    if (!serverId.value) return
    node.loading = true
    const data = await get<FileEntry[]>(
      `/api/user/servers/${serverId.value}/files/list?directory=${encodeURIComponent(node.path)}`,
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

  return {
    treeRoot,
    loadTreeNode,
    toggleTreeNode,
    expandTreeToPath,
    refreshTreeAt,
  }
}
