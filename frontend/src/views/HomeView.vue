<template>
  <div class="container home">
    <ShowcaseBackground />

    <section class="home-hero">
      <div class="hero-surface">
        <div class="hero-copy">
          <div class="hero-badge">
            <span class="dot" />
            CSS Lab · Local-first
          </div>

          <h1 class="hero-title">把一个主题，变成一套图文</h1>
          <p class="hero-subtitle">输入主题，生成大纲与配图。支持本地 CLIProxyAPI，管理面板内置日志与历史清理。</p>

          <div class="hero-actions">
            <button class="btn btn-primary" type="button" :disabled="loading" @click="focusComposer">
              开始创作
            </button>
            <button class="btn btn-secondary" type="button" @click="goHistory">
              查看历史
            </button>
          </div>
        </div>

        <div class="hero-compose" ref="composerWrapRef">
          <div class="compose-card">
            <div class="compose-head">
              <div class="compose-title">输入主题</div>
              <div class="compose-hint">可上传最多 5 张参考图</div>
            </div>

            <ComposerInput
              ref="composerRef"
              v-model="topic"
              :loading="loading"
              @generate="handleGenerate"
              @imagesChange="handleImagesChange"
            />

            <div class="examples">
              <div class="examples-title">快速示例</div>
              <div class="examples-row">
                <button
                  v-for="(ex, idx) in examples"
                  :key="idx"
                  class="chip"
                  type="button"
                  @click="applyExample(ex)"
                >
                  {{ ex }}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

    </section>

    <div v-if="error" class="error-toast" role="status" aria-live="polite">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="10"></circle>
        <line x1="12" y1="8" x2="12" y2="12"></line>
        <line x1="12" y1="16" x2="12.01" y2="16"></line>
      </svg>
      {{ error }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useGeneratorStore } from '../stores/generator'
import { generateOutline, createHistory } from '../api'

import ShowcaseBackground from '../components/home/ShowcaseBackground.vue'
import ComposerInput from '../components/home/ComposerInput.vue'

const router = useRouter()
const store = useGeneratorStore()

const topic = ref('')
const loading = ref(false)
const error = ref('')
const composerRef = ref<InstanceType<typeof ComposerInput> | null>(null)
const composerWrapRef = ref<HTMLElement | null>(null)

const uploadedImageFiles = ref<File[]>([])

const examples = [
  '30 天极简护肤计划（敏感肌）',
  '一周高蛋白减脂早餐',
  '春季通勤穿搭：3 套万能组合',
  '新手健身：从 0 到 8 周',
  '提升专注力的桌面布置'
]

function handleImagesChange(images: File[]) {
  uploadedImageFiles.value = images
}

function applyExample(ex: string) {
  topic.value = ex
  focusComposer()
}

function focusComposer() {
  composerRef.value?.focus?.()
  composerWrapRef.value?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

function goHistory() {
  router.push('/history')
}

async function handleGenerate() {
  if (!topic.value.trim()) return

  loading.value = true
  error.value = ''

  try {
    const imageFiles = uploadedImageFiles.value

    const result = await generateOutline(topic.value.trim(), imageFiles.length > 0 ? imageFiles : undefined)

    if (result.success && result.pages) {
      store.setTopic(topic.value.trim())
      store.setOutline(result.outline || '', result.pages)

      try {
        const historyResult = await createHistory(topic.value.trim(), {
          raw: result.outline || '',
          pages: result.pages
        })

        if (historyResult.success && historyResult.record_id) {
          store.setRecordId(historyResult.record_id)
        } else {
          console.error('创建历史记录失败:', historyResult.error || '未知错误')
          store.setRecordId(null)
        }
      } catch (err: any) {
        console.error('创建历史记录异常:', err.message || err)
        store.setRecordId(null)
      }

      store.userImages = imageFiles.length > 0 ? imageFiles : []

      composerRef.value?.clearPreviews()
      uploadedImageFiles.value = []

      router.push('/outline')
    } else {
      error.value = result.error || '生成大纲失败'
    }
  } catch (err: any) {
    error.value = err.message || '网络错误，请重试'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.home {
  max-width: 1280px;
  padding-top: 10px;
  position: relative;
  z-index: 1;
}

.home-hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 18px;
  align-items: start;
  padding: 38px 0 18px;
}

.hero-surface {
  max-width: 1040px;
  margin: 0 auto;
  border-radius: 32px;
  padding: 40px 24px 24px;
  background: rgba(255, 255, 255, 0.45);
  border: none;
  box-shadow:
    inset 0 1px 0 0 rgba(255, 255, 255, 0.90),
    inset 0 0 0 1px rgba(255, 255, 255, 0.40),
    0 24px 48px -12px rgba(0, 0, 0, 0.06),
    0 0 0 1px rgba(0, 0, 0, 0.02);
  backdrop-filter: saturate(180%) blur(50px);
  -webkit-backdrop-filter: saturate(180%) blur(50px);
  position: relative;
  overflow: hidden;
  transition: transform 0.4s cubic-bezier(0.2, 0.8, 0.2, 1), box-shadow 0.4s cubic-bezier(0.2, 0.8, 0.2, 1);
}

.hero-surface:hover {
  transform: translateY(-2px);
  box-shadow:
    inset 0 1px 0 0 rgba(255, 255, 255, 0.95),
    inset 0 0 0 1px rgba(255, 255, 255, 0.50),
    0 32px 64px -12px rgba(0, 0, 0, 0.08),
    0 0 0 1px rgba(0, 0, 0, 0.02);
}

.hero-copy {
  max-width: 760px;
  margin: 0 auto;
  text-align: center;
  padding: 10px 4px 0;
  position: relative;
}

.hero-badge {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid var(--border-color);
  color: var(--text-sub);
  font-size: 13px;
  font-weight: 650;
  letter-spacing: -0.01em;
  backdrop-filter: saturate(180%) blur(12px);
  -webkit-backdrop-filter: saturate(180%) blur(12px);
}

.hero-badge .dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: var(--primary);
  box-shadow: 0 0 0 4px rgba(10, 132, 255, 0.14);
}

.hero-title {
  margin-top: 16px;
  font-size: clamp(40px, 5vw, 64px);
  line-height: 1.05;
  letter-spacing: -0.025em;
  font-weight: 700;
  color: var(--text-main);
  text-shadow: none;
}

.hero-subtitle {
  margin-top: 14px;
  font-size: 16px;
  line-height: 1.7;
  color: var(--text-sub);
  max-width: 680px;
  margin-left: auto;
  margin-right: auto;
}

.hero-actions {
  margin-top: 18px;
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  justify-content: center;
}

.examples-title {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--text-secondary);
  margin-bottom: 10px;
}

.examples-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: center;
}

.chip {
  border: 1px solid rgba(0, 0, 0, 0.03);
  background: rgba(255, 255, 255, 0.50);
  color: var(--text-main);
  border-radius: 999px;
  padding: 10px 16px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.02);
}

.chip:hover {
  background: rgba(255, 255, 255, 0.85);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06);
}

.hero-compose {
  margin: 18px auto 0;
  max-width: 960px;
}

.compose-card {
  background: rgba(255, 255, 255, 0.40);
  border: none;
  border-radius: 24px;
  padding: 16px;
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.30),
    0 4px 16px rgba(0, 0, 0, 0.03);
  backdrop-filter: blur(30px);
  -webkit-backdrop-filter: blur(30px);
  transition: transform 0.22s ease, box-shadow 0.22s ease, background 0.22s ease;
}

.compose-card:focus-within {
  transform: translateY(-1px);
  box-shadow:
    inset 0 0 0 1px rgba(10, 132, 255, 0.18),
    0 0 0 4px rgba(10, 132, 255, 0.12),
    0 10px 30px rgba(0, 0, 0, 0.06);
}

.compose-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.compose-title {
  font-size: 14px;
  font-weight: 750;
  letter-spacing: -0.01em;
  color: var(--text-main);
}

.compose-hint {
  font-size: 12px;
  color: var(--text-secondary);
}

.examples {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid rgba(60, 60, 67, 0.16);
}

@media (prefers-color-scheme: dark) {
  .hero-surface {
    background: rgba(30, 30, 30, 0.40);
    box-shadow:
      inset 0 1px 0 0 rgba(255, 255, 255, 0.15),
      inset 0 0 0 1px rgba(255, 255, 255, 0.05),
      0 24px 48px -12px rgba(0, 0, 0, 0.50);
  }

  .compose-card {
    background: rgba(40, 40, 40, 0.40);
    box-shadow:
      inset 0 0 0 1px rgba(255, 255, 255, 0.08);
  }

  .compose-card:focus-within {
    box-shadow:
      inset 0 0 0 1px rgba(10, 132, 255, 0.22),
      0 0 0 4px rgba(10, 132, 255, 0.20),
      0 18px 50px rgba(0, 0, 0, 0.42);
  }

  .chip {
    background: rgba(60, 60, 67, 0.40);
    border-color: rgba(255, 255, 255, 0.05);
    color: rgba(255, 255, 255, 0.90);
  }

  .chip:hover {
    background: rgba(80, 80, 88, 0.60);
  }

}

.error-toast {
  position: fixed;
  bottom: 22px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(255, 59, 48, 0.92);
  color: white;
  padding: 12px 16px;
  border-radius: 999px;
  box-shadow: 0 14px 40px rgba(0, 0, 0, 0.22);
  display: flex;
  align-items: center;
  gap: 8px;
  z-index: 1000;
  max-width: min(92vw, 720px);
}

@media (max-width: 720px) {
  .hero-actions {
    width: 100%;
  }

  .hero-actions .btn {
    flex: 1 1 0;
  }
}
</style>
