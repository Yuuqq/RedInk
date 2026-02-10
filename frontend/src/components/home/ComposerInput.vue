<template>
  <!-- 主题输入组合框 -->
  <div class="composer-container">
    <!-- 输入区域 -->
    <div class="composer-input-wrapper">
      <div class="search-icon-static">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M21 21L16.65 16.65M19 11C19 15.4183 15.4183 19 11 19C6.58172 19 3 15.4183 3 11C3 6.58172 6.58172 3 11 3C15.4183 3 19 6.58172 19 11Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </div>
      <textarea
        ref="textareaRef"
        :value="modelValue"
        @input="handleInput"
        class="composer-textarea"
        placeholder="输入主题，例如：秋季显白美甲..."
        @keydown.enter.prevent="handleEnter"
        :disabled="loading"
        rows="1"
      ></textarea>
    </div>

    <!-- 已上传图片预览 -->
    <div v-if="uploadedImages.length > 0" class="uploaded-images-preview">
      <div
        v-for="(img, idx) in uploadedImages"
        :key="idx"
        class="uploaded-image-item"
      >
        <img :src="img.preview" :alt="`图片 ${idx + 1}`" />
        <button class="remove-image-btn" @click="removeImage(idx)">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="18" y1="6" x2="6" y2="18"></line>
            <line x1="6" y1="6" x2="18" y2="18"></line>
          </svg>
        </button>
      </div>
      <div class="upload-hint">
        这些图片将用于生成封面和内容参考
      </div>
    </div>

    <!-- 工具栏 -->
    <div class="composer-toolbar">
      <div class="toolbar-left">
        <label class="tool-btn upload-pill" :class="{ 'active': uploadedImages.length > 0, 'disabled': loading }" title="上传参考图">
          <input
            type="file"
            accept="image/*"
            multiple
            @change="handleImageUpload"
            :disabled="loading"
            style="display: none;"
          />
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
            <circle cx="8.5" cy="8.5" r="1.5"></circle>
            <polyline points="21 15 16 10 5 21"></polyline>
          </svg>
          <span class="upload-pill-label">参考图</span>
          <span v-if="uploadedImages.length > 0" class="badge-count">{{ uploadedImages.length }}/5</span>
        </label>
      </div>
      <div class="toolbar-right">
        <button
          class="btn btn-primary generate-btn"
          @click="$emit('generate')"
          :disabled="!modelValue.trim() || loading"
        >
          <span v-if="loading" class="spinner-sm"></span>
          <span v-else>生成大纲</span>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onUnmounted } from 'vue'

/**
 * 主题输入组合框组件
 *
 * 功能：
 * - 主题文本输入（自动调整高度）
 * - 参考图片上传（最多5张）
 * - 生成按钮
 */

// 定义上传的图片类型
interface UploadedImage {
  file: File
  preview: string
}

// 定义 Props
defineProps<{
  modelValue: string
  loading: boolean
}>()

// 定义 Emits
const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
  (e: 'generate'): void
  (e: 'imagesChange', images: File[]): void
}>()

// 输入框引用
const textareaRef = ref<HTMLTextAreaElement | null>(null)

// 已上传的图片
const uploadedImages = ref<UploadedImage[]>([])

/**
 * 处理输入变化
 */
function handleInput(event: Event) {
  const target = event.target as HTMLTextAreaElement
  emit('update:modelValue', target.value)
  adjustHeight()
}

/**
 * 处理回车键
 */
function handleEnter(e: KeyboardEvent) {
  if (e.shiftKey) return // 允许 Shift+Enter 换行
  emit('generate')
}

/**
 * 自动调整输入框高度
 */
function adjustHeight() {
  const el = textareaRef.value
  if (!el) return

  el.style.height = 'auto'
  const newHeight = Math.max(64, Math.min(el.scrollHeight, 200))
  el.style.height = newHeight + 'px'
}

/**
 * 处理图片上传
 */
function handleImageUpload(event: Event) {
  const target = event.target as HTMLInputElement
  if (!target.files) return

  const files = Array.from(target.files)
  files.forEach((file) => {
    // 限制最多 5 张图片
    if (uploadedImages.value.length >= 5) {
      return
    }
    // 创建预览 URL
    const preview = URL.createObjectURL(file)
    uploadedImages.value.push({ file, preview })
  })

  // 通知父组件
  emitImagesChange()

  // 清空 input，允许重复选择同一文件
  target.value = ''
}

/**
 * 移除图片
 */
function removeImage(index: number) {
  const img = uploadedImages.value[index]
  // 释放预览 URL
  URL.revokeObjectURL(img.preview)
  uploadedImages.value.splice(index, 1)

  // 通知父组件
  emitImagesChange()
}

/**
 * 通知父组件图片变化
 */
function emitImagesChange() {
  const files = uploadedImages.value.map(img => img.file)
  emit('imagesChange', files)
}

/**
 * 清理所有预览 URL
 */
function clearPreviews() {
  uploadedImages.value.forEach(img => URL.revokeObjectURL(img.preview))
  uploadedImages.value = []
}

function focus() {
  textareaRef.value?.focus()
}

// 组件卸载时清理
onUnmounted(() => {
  clearPreviews()
})

// 暴露方法给父组件
defineExpose({
  clearPreviews,
  focus
})
</script>

<style scoped>
/* 组合框容器 */
.composer-container {
  background: transparent;
  border-radius: 18px;
  padding: 0;
  box-shadow: none;
  border: none;
}

.composer-container:focus-within {
  outline: none;
}

/* 输入区域 */
.composer-input-wrapper {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 14px 14px 12px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.34);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.60),
    inset 0 0 0 1px rgba(255, 255, 255, 0.14),
    0 4px 24px rgba(0, 0, 0, 0.04);
  backdrop-filter: saturate(180%) blur(26px);
  -webkit-backdrop-filter: saturate(180%) blur(26px);
  transition: background 0.22s ease, box-shadow 0.22s ease, transform 0.22s ease;
}

.composer-container:focus-within .composer-input-wrapper {
  background: rgba(255, 255, 255, 0.42);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.74),
    inset 0 0 0 1px rgba(10, 132, 255, 0.36),
    0 0 0 3px rgba(10, 132, 255, 0.12),
    0 10px 34px rgba(0, 0, 0, 0.06);
}

.search-icon-static {
  flex-shrink: 0;
  padding-top: 10px;
  color: var(--text-secondary);
}

.composer-textarea {
  flex: 1;
  border: none;
  outline: none;
  font-size: 16px;
  line-height: 1.6;
  resize: none;
  min-height: 64px;
  max-height: 200px;
  padding: 8px 0 8px;
  font-family: inherit;
  color: var(--text-main);
  background: transparent;
  letter-spacing: -0.01em;
}

.composer-textarea::placeholder {
  color: var(--text-placeholder);
}

.composer-textarea:disabled {
  background: transparent;
  color: var(--text-placeholder);
}

/* 已上传图片预览 */
.uploaded-images-preview {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 12px;
  padding: 12px;
  background: rgba(120, 120, 128, 0.10);
  border-radius: 16px;
  align-items: center;
  border: 1px solid rgba(60, 60, 67, 0.12);
  backdrop-filter: saturate(180%) blur(16px);
  -webkit-backdrop-filter: saturate(180%) blur(16px);
}

.uploaded-image-item {
  position: relative;
  width: 60px;
  height: 60px;
  border-radius: 12px;
  overflow: hidden;
  box-shadow:
    0 1px 1px rgba(0, 0, 0, 0.04),
    0 10px 24px rgba(0, 0, 0, 0.10);
  border: 1px solid rgba(60, 60, 67, 0.14);
}

.uploaded-image-item img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.remove-image-btn {
  position: absolute;
  top: 2px;
  right: 2px;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: rgba(28, 28, 30, 0.52);
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  opacity: 0;
  transition: opacity 0.18s ease, background 0.18s ease;
  backdrop-filter: saturate(180%) blur(10px);
  -webkit-backdrop-filter: saturate(180%) blur(10px);
}

.uploaded-image-item:hover .remove-image-btn {
  opacity: 1;
}

.remove-image-btn:hover {
  background: rgba(10, 132, 255, 0.85);
}

.upload-hint {
  flex: 1;
  font-size: 12px;
  color: var(--text-sub);
  text-align: right;
}

/* 工具栏 */
.composer-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 12px;
  padding-top: 12px;
  border-top: none;
}

.toolbar-left {
  display: flex;
  gap: 8px;
}

.tool-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  height: 36px;
  border-radius: 999px;
  background: transparent;
  border: 1px solid rgba(60, 60, 67, 0.14);
  cursor: pointer;
  color: var(--text-sub);
  transition: background 0.18s ease, color 0.18s ease, box-shadow 0.18s ease;
  padding: 0 12px;
  gap: 8px;
}

.tool-btn:hover {
  background: rgba(120, 120, 128, 0.10);
  color: var(--text-main);
  border-color: rgba(60, 60, 67, 0.20);
}

.tool-btn.active {
  background: rgba(10, 132, 255, 0.12);
  color: var(--primary);
  border-color: rgba(10, 132, 255, 0.18);
  box-shadow: inset 0 0 0 1px rgba(10, 132, 255, 0.12);
}

.tool-btn:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}

.upload-pill {
  border-radius: 10px;
  min-width: 172px;
  height: 40px;
  justify-content: flex-start;
  padding: 0 12px;
  background: rgba(120, 120, 128, 0.08);
}

.upload-pill .badge-count {
  margin-left: auto;
}

.tool-btn.disabled {
  opacity: 0.55;
  cursor: not-allowed;
  pointer-events: none;
}

.badge-count {
  height: 20px;
  padding: 0 8px;
  background: rgba(10, 132, 255, 0.16);
  color: var(--primary);
  border-radius: 999px;
  font-size: 12px;
  font-weight: 650;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  box-shadow: inset 0 0 0 1px rgba(10, 132, 255, 0.14);
}

.upload-pill-label {
  font-size: 13px;
  font-weight: 600;
  letter-spacing: -0.01em;
}

/* 生成按钮 */
.generate-btn {
  padding: 10px 24px;
  font-size: 15px;
  border-radius: 14px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.generate-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 加载动画 */
.spinner-sm {
  width: 16px;
  height: 16px;
  border: 2px solid currentColor;
  border-top-color: transparent;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 900px) {
  .composer-textarea {
    font-size: 15px;
    min-height: 58px;
  }

  .uploaded-images-preview {
    padding: 12px;
  }

  .upload-hint {
    width: 100%;
    flex: 0 0 100%;
    text-align: left;
    margin-top: 6px;
  }
}

@media (prefers-color-scheme: dark) {
  .composer-input-wrapper {
    background: rgba(44, 44, 46, 0.26);
    box-shadow:
      inset 0 1px 0 rgba(255, 255, 255, 0.08),
      inset 0 0 0 1px rgba(255, 255, 255, 0.05),
      0 10px 34px rgba(0, 0, 0, 0.34);
  }

  .composer-container:focus-within .composer-input-wrapper {
    background: rgba(44, 44, 46, 0.32);
    box-shadow:
      inset 0 1px 0 rgba(255, 255, 255, 0.10),
      inset 0 0 0 1px rgba(10, 132, 255, 0.32),
      0 0 0 3px rgba(10, 132, 255, 0.22),
      0 18px 56px rgba(0, 0, 0, 0.46);
  }

  .uploaded-images-preview {
    background: rgba(235, 235, 245, 0.06);
    border-color: rgba(255, 255, 255, 0.08);
  }

  .tool-btn {
    background: transparent;
    border-color: rgba(255, 255, 255, 0.10);
    color: rgba(235, 235, 245, 0.72);
  }

  .upload-pill {
    background: rgba(235, 235, 245, 0.06);
  }

  .tool-btn:hover {
    background: rgba(235, 235, 245, 0.08);
    border-color: rgba(255, 255, 255, 0.14);
    color: rgba(235, 235, 245, 0.90);
  }
}
</style>
