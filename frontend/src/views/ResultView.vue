<template>
  <div class="container">
    <div class="page-header">
      <div>
        <h1 class="page-title">创作完成</h1>
        <p class="page-subtitle">恭喜！你的图文已生成完毕，共 {{ store.images.length }} 张</p>
      </div>
      <div class="page-actions">
        <button class="btn btn-secondary" @click="startOver">
          再来一篇
        </button>
        <button class="btn btn-primary" @click="downloadAll">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
          一键下载
        </button>
      </div>
    </div>

    <div class="card">
      <div class="grid-cols-4">
        <div v-for="image in store.images" :key="image.index" class="image-card">
          <!-- Image Area -->
          <div
            v-if="image.url"
            class="result-image"
            @click="viewImage(image.url)"
          >
            <img
              :src="image.url"
              :alt="`第 ${image.index + 1} 页`"
              class="result-image-img"
            />
            <!-- Regenerating Overlay -->
            <div v-if="regeneratingIndex === image.index" class="regenerating-overlay">
               <div class="spinner spinner-primary"></div>
               <span class="regenerating-text">重绘中...</span>
            </div>

            <!-- Hover Overlay -->
            <div v-else class="hover-overlay">
              预览大图
            </div>
          </div>

          <!-- Action Bar -->
          <div class="result-actions">
            <span class="result-meta">Page {{ image.index + 1 }}</span>
            <div class="result-actions-right">
              <button
                class="icon-btn"
                title="重新生成此图"
                @click="handleRegenerate(image)"
                :disabled="regeneratingIndex === image.index"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M23 4v6h-6"></path><path d="M1 20v-6h6"></path><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path></svg>
              </button>
              <button
                class="btn-link"
                @click="downloadOne(image)"
              >
                下载
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 标题、文案、标签生成区域 -->
    <ContentDisplay />
  </div>
</template>

<style scoped>
/* Result images */
.result-image {
  position: relative;
  aspect-ratio: 3/4;
  overflow: hidden;
  cursor: pointer;
}

.result-image-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform 0.3s ease;
}

.image-card:hover .result-image-img {
  transform: scale(1.05);
}

.regenerating-overlay {
  position: absolute;
  inset: 0;
  background: rgba(255, 255, 255, 0.78);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  z-index: 10;
  backdrop-filter: saturate(180%) blur(12px);
  -webkit-backdrop-filter: saturate(180%) blur(12px);
}

.spinner-primary {
  width: 24px;
  height: 24px;
  border-width: 2px;
  border-color: var(--primary);
  border-top-color: transparent;
}

.regenerating-text {
  font-size: 12px;
  color: var(--primary);
  margin-top: 8px;
  font-weight: 650;
}

.hover-overlay {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.30);
  opacity: 0;
  transition: opacity 0.2s ease;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-weight: 650;
  backdrop-filter: blur(2px);
  -webkit-backdrop-filter: blur(2px);
}

/* 确保图片预览区域正确填充 */
.image-card > div:first-child {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.image-card:hover .hover-overlay {
  opacity: 1;
}

.result-actions {
  padding: 12px;
  border-top: 1px solid var(--border-color);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.result-meta {
  font-size: 12px;
  color: var(--text-sub);
}

.result-actions-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.btn-link {
  border: none;
  background: transparent;
  color: var(--primary);
  cursor: pointer;
  font-size: 12px;
  font-weight: 650;
  padding: 6px 8px;
  border-radius: 10px;
  transition: background 0.2s ease, color 0.2s ease;
}

.btn-link:hover {
  background: rgba(10, 132, 255, 0.12);
}
</style>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useGeneratorStore } from '../stores/generator'
import { regenerateImage } from '../api'
import ContentDisplay from '../components/result/ContentDisplay.vue'

const router = useRouter()
const store = useGeneratorStore()
const regeneratingIndex = ref<number | null>(null)

const viewImage = (url: string) => {
  const baseUrl = url.split('?')[0]
  window.open(baseUrl + '?thumbnail=false', '_blank')
}

const startOver = () => {
  store.reset()
  router.push('/')
}

const downloadOne = (image: any) => {
  if (image.url) {
    const link = document.createElement('a')
    const baseUrl = image.url.split('?')[0]
    link.href = baseUrl + '?thumbnail=false'
    link.download = `rednote_page_${image.index + 1}.png`
    link.click()
  }
}

const downloadAll = () => {
  if (store.recordId) {
    const link = document.createElement('a')
    link.href = `/api/history/${store.recordId}/download`
    link.click()
  } else {
    store.images.forEach((image, index) => {
      if (image.url) {
        setTimeout(() => {
          const link = document.createElement('a')
          const baseUrl = image.url.split('?')[0]
          link.href = baseUrl + '?thumbnail=false'
          link.download = `rednote_page_${image.index + 1}.png`
          link.click()
        }, index * 300)
      }
    })
  }
}

const handleRegenerate = async (image: any) => {
  if (!store.taskId || regeneratingIndex.value !== null) return

  regeneratingIndex.value = image.index
  try {
    // Find the page content from outline
    const pageContent = store.outline.pages.find(p => p.index === image.index)
    if (!pageContent) {
       alert('无法找到对应页面的内容')
       return
    }

    // 构建上下文信息
    const context = {
      fullOutline: store.outline.raw || '',
      userTopic: store.topic || ''
    }

    const result = await regenerateImage(store.taskId, pageContent, true, context)
    if (result.success && result.image_url) {
       const newUrl = result.image_url
       store.updateImage(image.index, newUrl)
    } else {
       alert('重绘失败: ' + (result.error || '未知错误'))
    }
  } catch (e: any) {
    alert('重绘失败: ' + e.message)
  } finally {
    regeneratingIndex.value = null
  }
}
</script>
