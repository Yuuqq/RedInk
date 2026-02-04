<template>
  <div class="container container-wide">
    <div class="page-header">
      <div>
        <h1 class="page-title">编辑大纲</h1>
        <p class="page-subtitle">
          调整页面顺序，修改文案，打造完美内容
          <span v-if="isSaving" class="pill pill-info">保存中...</span>
          <span v-else class="pill pill-success">已保存</span>
        </p>
      </div>
      <div class="page-actions">
        <button class="btn btn-secondary" @click="goBack">
          上一步
        </button>
        <button class="btn btn-primary" @click="startGeneration">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 6px;"><path d="M20.24 12.24a6 6 0 0 0-8.49-8.49L5 10.5V19h8.5z"></path><line x1="16" y1="8" x2="2" y2="22"></line><line x1="17.5" y1="15" x2="9" y2="15"></line></svg>
          开始生成图片
        </button>
      </div>
    </div>

    <div class="outline-grid">
      <div 
        v-for="(page, idx) in store.outline.pages" 
        :key="page.index"
        class="card outline-card"
        :draggable="true"
        @dragstart="onDragStart($event, idx)"
        @dragover.prevent="onDragOver($event, idx)"
        @drop="onDrop($event, idx)"
        :class="{ 'dragging-over': dragOverIndex === idx }"
      >
        <!-- 拖拽手柄 (改为右上角或更加隐蔽) -->
        <div class="card-top-bar">
          <div class="page-info">
             <span class="page-number">P{{ idx + 1 }}</span>
             <span class="pill page-type" :class="page.type">{{ getPageTypeName(page.type) }}</span>
          </div>
          
          <div class="card-controls">
            <div class="drag-handle" title="拖拽排序">
               <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="12" r="1"></circle><circle cx="9" cy="5" r="1"></circle><circle cx="9" cy="19" r="1"></circle><circle cx="15" cy="12" r="1"></circle><circle cx="15" cy="5" r="1"></circle><circle cx="15" cy="19" r="1"></circle></svg>
            </div>
            <button class="icon-btn" @click="deletePage(idx)" title="删除此页">
               <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
            </button>
          </div>
        </div>

        <textarea
          v-model="page.content"
          class="textarea-paper"
          placeholder="在此输入文案..."
          @input="store.updatePage(page.index, page.content)"
        />
        
        <div class="word-count">{{ page.content.length }} 字</div>
      </div>

      <!-- 添加按钮卡片 -->
      <div class="card add-card-dashed" @click="addPage('content')">
        <div class="add-content">
          <div class="add-icon">+</div>
          <span>添加页面</span>
        </div>
      </div>
    </div>
    
    <div class="page-bottom-spacer"></div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, watch, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useGeneratorStore } from '../stores/generator'
import { updateHistory, createHistory } from '../api'

const router = useRouter()
const store = useGeneratorStore()

const dragOverIndex = ref<number | null>(null)
const draggedIndex = ref<number | null>(null)
// 保存状态指示
const isSaving = ref(false)

const getPageTypeName = (type: string) => {
  const names = {
    cover: '封面',
    content: '内容',
    summary: '总结'
  }
  return names[type as keyof typeof names] || '内容'
}

// 拖拽逻辑
const onDragStart = (e: DragEvent, index: number) => {
  draggedIndex.value = index
  if (e.dataTransfer) {
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.dropEffect = 'move'
  }
}

const onDragOver = (e: DragEvent, index: number) => {
  if (draggedIndex.value === index) return
  dragOverIndex.value = index
}

const onDrop = (e: DragEvent, index: number) => {
  dragOverIndex.value = null
  if (draggedIndex.value !== null && draggedIndex.value !== index) {
    store.movePage(draggedIndex.value, index)
  }
  draggedIndex.value = null
}

const deletePage = (index: number) => {
  if (confirm('确定要删除这一页吗？')) {
    store.deletePage(index)
  }
}

const addPage = (type: 'cover' | 'content' | 'summary') => {
  store.addPage(type, '')
  // 滚动到底部
  nextTick(() => {
    window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' })
  })
}

const goBack = () => {
  router.back()
}

const startGeneration = async () => {
  // 如果有待保存的内容，先强制保存
  if (saveTimer !== null) {
    clearTimeout(saveTimer)
    saveTimer = null
    await autoSaveOutline()
  }
  router.push('/generate')
}

// ==================== 自动保存功能 ====================

// 防抖定时器
let saveTimer: number | null = null

/**
 * 自动保存大纲到历史记录
 * 当大纲内容发生变化时，自动更新到后端
 */
const autoSaveOutline = async () => {
  // 如果没有 recordId，说明还未创建历史记录，无法自动保存
  if (!store.recordId) {
    console.warn('未找到历史记录ID，无法自动保存')
    return
  }

  // 如果没有大纲内容，不需要保存
  if (!store.outline.pages || store.outline.pages.length === 0) {
    return
  }

  try {
    isSaving.value = true

    // 调用更新历史记录 API
    const result = await updateHistory(store.recordId, {
      outline: {
        raw: store.outline.raw,
        pages: store.outline.pages
      }
    })

    if (!result.success) {
      console.error('自动保存失败:', result.error)
    } else {
      console.log('大纲已自动保存')
    }
  } catch (error) {
    console.error('自动保存出错:', error)
  } finally {
    isSaving.value = false
  }
}

/**
 * 防抖函数：延迟执行保存操作
 * 避免用户频繁编辑时产生大量请求
 */
const debouncedSave = () => {
  // 清除之前的定时器
  if (saveTimer !== null) {
    clearTimeout(saveTimer)
  }

  // 设置新的定时器，300ms 后执行保存
  saveTimer = window.setTimeout(() => {
    autoSaveOutline()
    saveTimer = null
  }, 300)
}

/**
 * 页面加载时检查历史记录
 * 如果没有 recordId 但有大纲数据，尝试创建历史记录
 */
const checkAndCreateHistory = async () => {
  // 如果已经有 recordId，无需创建
  if (store.recordId) {
    console.log('已存在历史记录ID:', store.recordId)
    return
  }

  // 如果有大纲数据但没有 recordId，说明是异常情况，尝试创建
  if (store.outline.pages && store.outline.pages.length > 0) {
    console.log('检测到大纲数据但无历史记录ID，尝试创建历史记录')

    try {
      const result = await createHistory(
        store.topic || '未命名主题',
        {
          raw: store.outline.raw,
          pages: store.outline.pages
        },
        store.taskId || undefined
      )

      if (result.success && result.record_id) {
        store.setRecordId(result.record_id)
        console.log('历史记录创建成功，ID:', result.record_id)
      } else {
        console.error('创建历史记录失败:', result.error)
      }
    } catch (error) {
      console.error('创建历史记录出错:', error)
    }
  }
}

// 组件挂载时检查历史记录
onMounted(() => {
  checkAndCreateHistory()
})

// 组件卸载时清理定时器
onUnmounted(() => {
  if (saveTimer !== null) {
    clearTimeout(saveTimer)
    saveTimer = null
  }
})

// 监听大纲变化，触发自动保存
watch(
  () => store.outline.pages,
  () => {
    // 使用防抖函数，避免频繁请求
    debouncedSave()
  },
  { deep: true } // 深度监听，确保能检测到数组内部对象的变化
)
</script>

<style scoped>
/* 网格布局 */
.outline-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 18px;
}

.outline-card {
  display: flex;
  flex-direction: column;
  padding: 18px;
  transition: transform 0.22s ease, box-shadow 0.22s ease, border-color 0.22s ease;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  background: var(--bg-card);
  box-shadow: var(--shadow-sm);
  min-height: 360px;
  position: relative;
}

.outline-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
  z-index: 10;
}

.outline-card.dragging-over {
  border: 1px dashed rgba(10, 132, 255, 0.55);
  box-shadow: 0 0 0 3px rgba(10, 132, 255, 0.12) inset, var(--shadow-sm);
}

/* 顶部栏 */
.card-top-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border-color);
}

.page-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.page-number {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-placeholder);
  font-family: var(--font-mono);
}

.page-type {
  font-size: 11px;
  padding: 3px 10px;
  text-transform: none;
  letter-spacing: -0.01em;
}
.page-type.cover { background: rgba(255, 59, 48, 0.10); border-color: rgba(255, 59, 48, 0.18); color: #b42318; }
.page-type.content { background: rgba(120, 120, 128, 0.12); border-color: rgba(120, 120, 128, 0.18); color: var(--text-sub); }
.page-type.summary { background: rgba(52, 199, 89, 0.12); border-color: rgba(52, 199, 89, 0.22); color: #248a3d; }

.card-controls {
  display: flex;
  gap: 8px;
  opacity: 0.5;
  transition: opacity 0.2s;
}
.outline-card:hover .card-controls { opacity: 1; }

.drag-handle {
  cursor: grab;
  padding: 4px;
  color: var(--text-secondary);
}
.drag-handle:active { cursor: grabbing; }

.icon-btn {
  width: 30px;
  height: 30px;
  border-radius: 10px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-secondary);
  padding: 0;
}
.icon-btn:hover {
  background: rgba(255, 59, 48, 0.10);
  color: #b42318;
  border-color: rgba(255, 59, 48, 0.16);
}

/* 文本区域 - 核心 */
.textarea-paper {
  flex: 1; /* 占据剩余空间 */
  width: 100%;
  border: none;
  background: transparent;
  padding: 0;
  font-size: 15px;
  line-height: 1.7;
  color: var(--text-main);
  resize: none; /* 禁止手动拉伸，保持卡片整体感 */
  font-family: inherit;
  margin-bottom: 10px;
}

.textarea-paper:focus {
  outline: none;
}

.word-count {
  text-align: right;
  font-size: 11px;
  color: var(--text-placeholder);
  margin-top: auto;
}

/* 添加卡片 */
.add-card-dashed {
  border: 1px dashed rgba(60, 60, 67, 0.22);
  background: transparent;
  box-shadow: none;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  min-height: 360px;
  color: var(--text-secondary);
  transition: all 0.2s;
}

.add-card-dashed:hover {
  border-color: rgba(10, 132, 255, 0.42);
  color: var(--primary);
  background: rgba(10, 132, 255, 0.06);
}

.add-content {
  text-align: center;
}

.add-icon {
  font-size: 32px;
  font-weight: 300;
  margin-bottom: 8px;
}

.page-bottom-spacer {
  height: 84px;
}
</style>
