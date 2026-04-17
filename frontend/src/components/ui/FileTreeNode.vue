<script setup lang="ts">
import MsIcon from './MsIcon.vue'

export interface TreeNode {
  name: string
  path: string
  children: TreeNode[] | null
  expanded: boolean
  loading: boolean
}

defineProps<{
  node: TreeNode
  currentPath: string
  depth?: number
}>()

const emit = defineEmits<{
  select: [node: TreeNode]
  toggle: [node: TreeNode]
}>()
</script>

<template>
  <div class="tree-node">
    <div
      class="tree-node-row"
      :class="{ active: currentPath === node.path }"
      :style="{ paddingLeft: ((depth ?? 0) * 16 + 8) + 'px' }"
      @click="emit('select', node)"
    >
      <span v-if="node.loading" class="tree-arrow-placeholder">
        <MsIcon name="progress_activity" size="xs" class="tree-spinner" />
      </span>
      <button
        v-else-if="node.children === null || node.children.length > 0"
        class="tree-arrow"
        :class="{ expanded: node.expanded }"
        @click.stop="emit('toggle', node)"
      >
        <MsIcon name="chevron_right" size="xs" />
      </button>
      <span v-else class="tree-arrow-placeholder" />
      <MsIcon :name="node.expanded ? 'folder_open' : 'folder'" size="sm" class="tree-folder-icon" :class="{ 'tree-folder-open': node.expanded }" />
      <span class="tree-node-label">{{ node.name }}</span>
    </div>
    <div v-if="node.expanded && node.children" class="tree-children">
      <FileTreeNode
        v-for="child in node.children"
        :key="child.name"
        :node="child"
        :current-path="currentPath"
        :depth="(depth ?? 0) + 1"
        @select="emit('select', $event)"
        @toggle="emit('toggle', $event)"
      />
    </div>
  </div>
</template>

<script lang="ts">
export default { name: 'FileTreeNode' }
</script>

<style scoped>
.tree-node-row {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  cursor: pointer;
  font-size: var(--text-sm);
  color: var(--t2);
  transition: background .1s;
  white-space: nowrap;
  min-height: 28px;
}

.tree-node-row:hover {
  background: rgba(20, 184, 166, .06);
}

.tree-node-row.active {
  background: rgba(20, 184, 166, .1);
  color: var(--ac);
}

.tree-arrow {
  background: none;
  border: none;
  color: var(--t3);
  cursor: pointer;
  padding: 0;
  display: flex;
  align-items: center;
  width: 16px;
  flex-shrink: 0;
  transition: transform .15s;
}

.tree-arrow.expanded {
  transform: rotate(90deg);
}

.tree-arrow-placeholder {
  width: 16px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
}

.tree-spinner {
  animation: spin 1s linear infinite;
  color: var(--t3);
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.tree-folder-icon {
  color: var(--ac);
  flex-shrink: 0;
}

.tree-folder-open {
  color: var(--ac2);
}

.tree-node-label {
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
