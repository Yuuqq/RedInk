<template>
  <div class="container">
    <div class="page-header">
      <h1 class="page-title">管理面板</h1>
      <p class="page-subtitle">任务监控、CLIProxyAPI 快速接入与健康检查（默认仅本机/内网可访问）</p>
    </div>

    <div class="grid">
      <div class="card">
        <div class="section-header">
          <div>
            <h2 class="section-title">CLIProxyAPI 快速接入</h2>
            <p class="section-desc">一键写入文本/图片服务商配置，适配本地代理</p>
          </div>
          <RouterLink class="btn btn-ghost" to="/settings">高级设置</RouterLink>
        </div>

        <div class="form-grid">
          <label class="field">
            <span class="label">API Base URL</span>
            <input v-model="quick.baseUrl" class="input" placeholder="http://127.0.0.1:8317/v1" />
          </label>
          <label class="field">
            <span class="label">API Key</span>
            <input v-model="quick.apiKey" class="input" placeholder="whoisyourai" />
          </label>
          <label class="field">
            <span class="label">文本模型</span>
            <input v-model="quick.textModel" class="input" placeholder="gemini-3-pro-preview" />
          </label>
          <label class="field">
            <span class="label">图片模型</span>
            <input v-model="quick.imageModel" class="input" placeholder="gemini-3-pro-image-preview" />
          </label>
        </div>

        <div class="actions">
          <button class="btn btn-primary" :disabled="savingQuick" @click="applyQuickSetup">
            {{ savingQuick ? '保存中...' : '保存并设为默认' }}
          </button>
          <button class="btn btn-secondary" :disabled="testingQuick" @click="testQuickSetup">
            {{ testingQuick ? '测试中...' : '测试连接' }}
          </button>
        </div>

        <div v-if="quickMessage" class="hint" :class="{ error: quickMessageType === 'error' }">
          {{ quickMessage }}
        </div>
      </div>

      <div class="card">
        <div class="section-header">
          <div>
            <h2 class="section-title">健康检查</h2>
            <p class="section-desc">后端状态、当前激活服务商与上游连通性</p>
          </div>
          <button class="btn btn-ghost" :disabled="loadingHealth" @click="loadHealth">
            刷新
          </button>
        </div>

        <div v-if="loadingHealth" class="hint">加载中...</div>
        <div v-else-if="health?.success" class="health">
          <div class="kv">
            <div class="k">Python</div>
            <div class="v">{{ health.platform?.python }}</div>
          </div>
          <div class="kv">
            <div class="k">系统</div>
            <div class="v">{{ health.platform?.system }} {{ health.platform?.release }}</div>
          </div>
          <div class="kv">
            <div class="k">文本服务</div>
            <div class="v">
              {{ health.providers?.text?.active_provider || '-' }} / {{ health.providers?.text?.model || '-' }}
            </div>
          </div>
          <div class="kv">
            <div class="k">图片服务</div>
            <div class="v">
              {{ health.providers?.image?.active_provider || '-' }} / {{ health.providers?.image?.model || '-' }}
            </div>
          </div>

          <div v-if="health.probes && Object.keys(health.probes).length" class="probe">
            <div class="probe-title">上游探测</div>
            <pre class="pre">{{ JSON.stringify(health.probes, null, 2) }}</pre>
          </div>
        </div>
        <div v-else class="hint error">
          {{ health?.error || '健康检查失败' }}
        </div>
      </div>
    </div>

    <div class="card">
      <div class="section-header">
        <div>
          <h2 class="section-title">历史目录统计与清理</h2>
          <p class="section-desc">扫描 `history/` 目录，识别孤儿任务目录并支持按时间清理</p>
        </div>
        <button class="btn btn-ghost" :disabled="history.loading" @click="loadHistoryStats">刷新</button>
      </div>

      <div v-if="history.loading" class="hint">加载中...</div>
      <div v-else-if="history.stats" class="history-grid">
        <div class="kv">
          <div class="k">目录</div>
          <div class="v mono">{{ history.stats.history_root }}</div>
        </div>
        <div class="kv">
          <div class="k">总大小</div>
          <div class="v">{{ formatBytes(history.stats.total_bytes) }}</div>
        </div>
        <div class="kv">
          <div class="k">任务目录数</div>
          <div class="v">{{ history.stats.total_task_dirs }}</div>
        </div>
        <div class="kv">
          <div class="k">记录数</div>
          <div class="v">{{ history.stats.total_records }}</div>
        </div>
        <div class="kv">
          <div class="k">孤儿任务目录</div>
          <div class="v danger">{{ history.stats.orphan_task_dirs_count }}</div>
        </div>
        <div class="kv">
          <div class="k">记录引用但目录缺失</div>
          <div class="v">{{ history.stats.referenced_missing_task_dirs_count }}</div>
        </div>
      </div>

      <div class="actions history-actions">
        <label class="field-inline">
          <span class="label">scope</span>
          <select v-model="history.scope" class="input input-small">
            <option value="orphan">orphan（仅孤儿）</option>
            <option value="all">all（全部，危险）</option>
          </select>
        </label>
        <label class="checkbox">
          <input v-model="history.deleteOrphans" type="checkbox" />
          <span>清理孤儿任务目录</span>
        </label>
        <label class="field-inline">
          <span class="label">清理 N 天前（0=不启用）</span>
          <input v-model.number="history.olderThanDays" type="number" min="0" class="input input-small" />
        </label>
        <label class="field-inline">
          <span class="label">只保留最近 N 个（0=不启用）</span>
          <input v-model.number="history.keepLastN" type="number" min="0" class="input input-small" />
        </label>
        <label class="field-inline">
          <span class="label">只删超过 MB</span>
          <input v-model.number="history.largerThanMB" type="number" min="0" step="10" class="input input-small" />
        </label>
        <label class="checkbox">
          <input v-model="history.dryRun" type="checkbox" />
          <span>Dry-run（不实际删除）</span>
        </label>
        <button class="btn btn-secondary" :disabled="history.cleaning" @click="runHistoryCleanup">
          {{ history.cleaning ? '执行中...' : '执行清理' }}
        </button>
      </div>

      <div v-if="history.message" class="hint" :class="{ error: history.messageType === 'error' }">
        {{ history.message }}
      </div>
    </div>

    <div class="card">
      <div class="section-header">
        <div>
          <h2 class="section-title">日志面板</h2>
          <p class="section-desc">读取后端 `logs/redink.log`（支持增量拉取与下载）</p>
        </div>
        <div class="actions-inline">
          <a class="btn btn-ghost" :href="getAdminLogsDownloadUrl()" target="_blank" rel="noopener noreferrer">下载</a>
          <button class="btn btn-ghost" :disabled="logs.loading" @click="rotateLogs">轮转</button>
          <button class="btn btn-ghost" :disabled="logs.loading" @click="loadLogs(true)">重置</button>
          <button class="btn btn-ghost" :disabled="logs.loading" @click="loadLogs(false)">刷新</button>
          <label class="checkbox">
            <input v-model="logs.autoFollow" type="checkbox" />
            <span>自动跟随</span>
          </label>
        </div>
      </div>

      <div v-if="logs.error" class="hint error">{{ logs.error }}</div>
      <div v-if="logs.warnings && logs.warnings.length" class="hint error">
        {{ logs.warnings[0].message }}
      </div>
      <div class="log-meta">
        <div>offset: <span class="mono">{{ logs.offset }}</span></div>
        <div>size: <span class="mono">{{ formatBytes(logs.size) }}</span></div>
      </div>
      <pre class="pre log-pre">{{ logs.content || '(no logs yet)' }}</pre>
    </div>

    <div class="card">
      <div class="section-header">
        <div>
          <h2 class="section-title">任务监控</h2>
          <p class="section-desc">仅显示内存中仍保留的任务状态（可用于重试/排查）</p>
        </div>
        <div class="actions-inline">
          <button class="btn btn-ghost" :disabled="loadingTasks" @click="loadTasks">刷新</button>
          <label class="checkbox">
            <input v-model="autoRefresh" type="checkbox" />
            <span>自动刷新</span>
          </label>
        </div>
      </div>

      <div v-if="loadingTasks" class="hint">加载中...</div>
      <div v-else-if="tasks.length === 0" class="hint">暂无任务（或任务已过期清理）</div>
      <div v-else class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>task_id</th>
              <th>更新时间</th>
              <th>已生成</th>
              <th>失败</th>
              <th>封面</th>
              <th style="width: 260px;">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="t in tasks" :key="t.task_id">
              <td class="mono">{{ t.task_id }}</td>
              <td>{{ formatTs(t.updated_at || t.created_at) }}</td>
              <td>{{ t.generated_count }}</td>
              <td :class="{ danger: t.failed_count > 0 }">{{ t.failed_count }}</td>
              <td>{{ t.has_cover ? '是' : '否' }}</td>
              <td class="ops">
                <button class="btn btn-mini" @click="openTask(t.task_id)">查看</button>
                <button class="btn btn-mini btn-secondary" :disabled="cleaningTask === t.task_id"
                  @click="cleanupTask(t.task_id, false)">
                  清理内存
                </button>
                <button class="btn btn-mini btn-danger" :disabled="cleaningTask === t.task_id"
                  @click="cleanupTask(t.task_id, true)">
                  删除文件
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="taskMessage" class="hint" :class="{ error: taskMessageType === 'error' }">
        {{ taskMessage }}
      </div>
    </div>

    <!-- Task Modal -->
    <div v-if="taskModal.visible" class="modal-overlay" @click.self="closeTaskModal">
      <div class="modal">
        <div class="modal-header">
          <div class="modal-title">任务详情：<span class="mono">{{ taskModal.taskId }}</span></div>
          <button class="btn btn-ghost" @click="closeTaskModal">关闭</button>
        </div>
        <div class="modal-body">
          <div v-if="taskModal.loading" class="hint">加载中...</div>
          <div v-else-if="taskModal.error" class="hint error">{{ taskModal.error }}</div>
          <pre v-else class="pre">{{ taskModal.json }}</pre>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import axios from 'axios'
import { RouterLink } from 'vue-router'
import {
  cleanupAdminTask,
  getAdminHealth,
  getAdminLogs,
  getAdminLogsDownloadUrl,
  rotateAdminLogs,
  getAdminHistoryStats,
  cleanupAdminHistory,
  listAdminTasks,
  testConnection,
  updateConfig,
  type AdminTask,
  type AdminHealthResponse,
} from '../api'

const loadingHealth = ref(false)
const health = ref<AdminHealthResponse | null>(null)

const loadingTasks = ref(false)
const tasks = ref<AdminTask[]>([])
const autoRefresh = ref(true)
let intervalId: number | null = null

const savingQuick = ref(false)
const testingQuick = ref(false)
const quickMessage = ref('')
const quickMessageType = ref<'info' | 'error'>('info')

const taskMessage = ref('')
const taskMessageType = ref<'info' | 'error'>('info')
const cleaningTask = ref<string | null>(null)

const quick = reactive({
  baseUrl: 'http://127.0.0.1:8317/v1',
  apiKey: 'whoisyourai',
  textModel: 'gemini-3-pro-preview',
  imageModel: 'gemini-3-pro-image-preview',
})

const taskModal = reactive({
  visible: false,
  loading: false,
  taskId: '',
  json: '',
  error: '',
})

const logs = reactive({
  loading: false,
  autoFollow: true,
  offset: 0,
  size: 0,
  content: '',
  error: '',
  warnings: [] as any[],
})

const history = reactive({
  loading: false,
  cleaning: false,
  stats: null as any,
  olderThanDays: 14,
  deleteOrphans: true,
  dryRun: true,
  message: '',
  messageType: 'info' as 'info' | 'error',
  scope: 'orphan' as 'orphan' | 'all',
  keepLastN: 0,
  largerThanMB: 0,
})

function formatTs(ts?: number) {
  if (!ts) return '-'
  try {
    return new Date(ts * 1000).toLocaleString()
  } catch {
    return String(ts)
  }
}

function formatBytes(n?: number) {
  if (!n && n !== 0) return '-'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let v = n
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v.toFixed(i === 0 ? 0 : 2)} ${units[i]}`
}

async function loadHealth() {
  loadingHealth.value = true
  try {
    health.value = await getAdminHealth()
  } catch (e: any) {
    health.value = { success: false, error: e?.response?.data?.error || e?.message || String(e) }
  } finally {
    loadingHealth.value = false
  }
}

async function loadTasks() {
  loadingTasks.value = true
  try {
    const r = await listAdminTasks()
    if (r.success && r.tasks) {
      tasks.value = r.tasks
      taskMessage.value = ''
    } else {
      taskMessageType.value = 'error'
      taskMessage.value = r.error || '加载任务失败'
    }
  } catch (e: any) {
    taskMessageType.value = 'error'
    taskMessage.value = e?.response?.data?.error || e?.message || String(e)
  } finally {
    loadingTasks.value = false
  }
}

async function loadLogs(reset: boolean = false) {
  logs.loading = true
  logs.error = ''
  try {
    const offset = reset ? 0 : logs.offset
    const r = await getAdminLogs({ offset, max_bytes: 256 * 1024 })
    if (r.success) {
      if (reset) logs.content = ''
      const chunk = r.content || ''
      logs.content += chunk
      // prevent UI from freezing on huge logs
      if (logs.content.length > 1_500_000) {
        logs.content = logs.content.slice(-1_000_000)
      }
      logs.offset = r.next_offset || logs.offset
      logs.size = r.size || logs.size
      logs.warnings = (r as any).warnings || []
    } else {
      logs.error = r.error || '读取日志失败'
    }
  } catch (e: any) {
    logs.error = e?.response?.data?.error || e?.message || String(e)
  } finally {
    logs.loading = false
  }
}

async function rotateLogs() {
  const ok = confirm('将立即轮转后端日志文件（会先备份再清空当前日志）。继续吗？')
  if (!ok) return
  logs.loading = true
  logs.error = ''
  try {
    const r = await rotateAdminLogs()
    if (!r.success) {
      logs.error = r.error || '轮转失败'
    } else {
      // reset offset and reload fresh
      logs.offset = 0
      logs.content = ''
      await loadLogs(true)
    }
  } catch (e: any) {
    logs.error = e?.response?.data?.error || e?.message || String(e)
  } finally {
    logs.loading = false
  }
}

async function loadHistoryStats() {
  history.loading = true
  history.message = ''
  try {
    const r = await getAdminHistoryStats()
    if (r.success) {
      history.stats = r.stats
    } else {
      history.messageType = 'error'
      history.message = r.error || '获取历史统计失败'
    }
  } catch (e: any) {
    history.messageType = 'error'
    history.message = e?.response?.data?.error || e?.message || String(e)
  } finally {
    history.loading = false
  }
}

async function runHistoryCleanup() {
  history.cleaning = true
    history.message = ''
  try {
    const effectiveScopeAll = history.scope === 'all' && !history.deleteOrphans
    if (effectiveScopeAll && !history.dryRun) {
      const ok = confirm(
        `scope=all 将影响所有 history 任务目录（包括仍被历史记录引用的任务）。\n` +
        `这可能导致历史记录图片丢失。\n确定继续吗？`
      )
      if (!ok) {
        history.cleaning = false
        return
      }
    }

    if (!history.dryRun) {
      const olderLabel = history.olderThanDays > 0 ? `${history.olderThanDays} 天前` : '未启用'
      const keepLabel = history.keepLastN > 0 ? `仅保留最近 ${history.keepLastN} 个` : '未启用'
      const sizeLabel = history.largerThanMB > 0 ? `>= ${history.largerThanMB} MB` : '未启用'
      const ok = confirm(
        `你已关闭 Dry-run，将实际删除 history 目录内容。\n` +
        `条件：scope=${history.scope}，清理孤儿=${history.deleteOrphans ? '是' : '否'}，清理=${olderLabel}，${keepLabel}，大小阈值=${sizeLabel}。\n` +
        `确定继续吗？`
      )
      if (!ok) {
        history.cleaning = false
        return
      }
    }

    const r = await cleanupAdminHistory({
      scope: history.scope,
      delete_orphan_tasks: history.deleteOrphans,
      older_than_days: history.olderThanDays > 0 ? history.olderThanDays : undefined,
      keep_last_n: history.keepLastN > 0 ? history.keepLastN : undefined,
      larger_than_mb: history.largerThanMB > 0 ? history.largerThanMB : undefined,
      dry_run: history.dryRun,
      ...(!history.dryRun && (history.deleteOrphans || history.scope === 'orphan')
        ? { confirm_delete_orphans: 'YES_DELETE_ORPHAN_TASKS' }
        : {}),
      ...(history.scope === 'all' && !history.deleteOrphans && !history.dryRun
        ? { confirm_delete_any: 'YES_DELETE_ANY_TASKS' }
        : {}),
    })
    if (r.success) {
      history.messageType = 'info'
      history.message = `完成：计划/删除 ${(r.deleted || []).length} 个目录，失败 ${(r.failed || []).length} 个（dry_run=${history.dryRun ? 'true' : 'false'}）`
      await loadHistoryStats()
    } else {
      history.messageType = 'error'
      history.message = r.error || '清理失败'
    }
  } catch (e: any) {
    history.messageType = 'error'
    history.message = e?.response?.data?.error || e?.message || String(e)
  } finally {
    history.cleaning = false
  }
}

function startAutoRefresh() {
  stopAutoRefresh()
  intervalId = window.setInterval(() => {
    if (!autoRefresh.value) return
    loadTasks()
    loadHealth()
    if (logs.autoFollow) loadLogs(false)
  }, 5000)
}

function stopAutoRefresh() {
  if (intervalId) {
    window.clearInterval(intervalId)
    intervalId = null
  }
}

async function applyQuickSetup() {
  savingQuick.value = true
  quickMessage.value = ''
  try {
    const config = {
      text_generation: {
        active_provider: 'cliproxy',
        providers: {
          cliproxy: {
            type: 'openai_compatible',
            api_key: quick.apiKey,
            base_url: quick.baseUrl,
            model: quick.textModel,
            endpoint_type: '/v1/chat/completions',
          }
        }
      },
      image_generation: {
        active_provider: 'cliproxy',
        providers: {
          cliproxy: {
            type: 'image_api',
            api_key: quick.apiKey,
            base_url: quick.baseUrl,
            model: quick.imageModel,
            endpoint_type: '/v1/chat/completions',
            high_concurrency: false,
            short_prompt: false,
          }
        }
      }
    }

    const r = await updateConfig(config as any)
    if (r.success) {
      quickMessageType.value = 'info'
      quickMessage.value = '配置已保存并设为默认（cliproxy）'
      await loadHealth()
    } else {
      quickMessageType.value = 'error'
      quickMessage.value = r.error || '保存失败'
    }
  } catch (e: any) {
    quickMessageType.value = 'error'
    quickMessage.value = e?.response?.data?.error || e?.message || String(e)
  } finally {
    savingQuick.value = false
  }
}

async function testQuickSetup() {
  testingQuick.value = true
  quickMessage.value = ''
  try {
    // Text probe
    const t = await testConnection({
      type: 'openai_compatible',
      api_key: quick.apiKey,
      base_url: quick.baseUrl,
      model: quick.textModel,
    })

    // Image probe: for cliproxy the chat endpoint still works, use type=image_api
    const i = await testConnection({
      type: 'image_api',
      api_key: quick.apiKey,
      base_url: quick.baseUrl,
      model: quick.imageModel,
    })

    if (t.success && i.success) {
      quickMessageType.value = 'info'
      quickMessage.value = `连接成功：文本=${t.message || 'OK'}；图片=${i.message || 'OK'}`
    } else {
      quickMessageType.value = 'error'
      quickMessage.value = `连接失败：文本=${t.error || 'unknown'}；图片=${i.error || 'unknown'}`
    }
  } catch (e: any) {
    quickMessageType.value = 'error'
    quickMessage.value = e?.response?.data?.error || e?.message || String(e)
  } finally {
    testingQuick.value = false
  }
}

async function cleanupTask(taskId: string, deleteFiles: boolean) {
  cleaningTask.value = taskId
  taskMessage.value = ''
  try {
    if (deleteFiles) {
      const ok = confirm(`将删除 history/${taskId} 目录内的所有文件，且不可恢复。确定继续吗？`)
      if (!ok) {
        cleaningTask.value = null
        return
      }
    }

    const r = await cleanupAdminTask(taskId, deleteFiles)
    if (r.success) {
      taskMessageType.value = 'info'
      taskMessage.value = deleteFiles
        ? `已清理内存并尝试删除文件：${taskId}`
        : `已清理内存：${taskId}`
      await loadTasks()
    } else {
      taskMessageType.value = 'error'
      taskMessage.value = r.error || '操作失败'
    }
  } catch (e: any) {
    taskMessageType.value = 'error'
    taskMessage.value = e?.response?.data?.error || e?.message || String(e)
  } finally {
    cleaningTask.value = null
  }
}

async function openTask(taskId: string) {
  taskModal.visible = true
  taskModal.loading = true
  taskModal.taskId = taskId
  taskModal.error = ''
  taskModal.json = ''
  try {
    const resp = await axios.get(`/api/task/${encodeURIComponent(taskId)}`)
    taskModal.json = JSON.stringify(resp.data, null, 2)
  } catch (e: any) {
    taskModal.error = e?.response?.data?.error || e?.message || String(e)
  } finally {
    taskModal.loading = false
  }
}

function closeTaskModal() {
  taskModal.visible = false
}

watch(autoRefresh, (v) => {
  if (v) startAutoRefresh()
  else stopAutoRefresh()
})

watch(
  () => history.deleteOrphans,
  (v) => {
    // delete_orphan_tasks=true 时后端会强制只作用于 orphan；这里同步 UI，避免误解 scope=all 的含义
    if (v && history.scope === 'all') history.scope = 'orphan'
  }
)

onMounted(async () => {
  await Promise.all([loadHealth(), loadTasks(), loadHistoryStats()])
  await loadLogs(true)
  if (autoRefresh.value) startAutoRefresh()
})

onUnmounted(() => {
  stopAutoRefresh()
})
</script>

<style scoped>
.grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 16px;
}

@media (max-width: 960px) {
  .grid {
    grid-template-columns: 1fr;
  }
}

.section-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.section-title {
  font-size: 18px;
  font-weight: 650;
  margin: 0 0 4px 0;
  color: var(--text-main);
}

.section-desc {
  font-size: 13px;
  margin: 0;
  color: var(--text-sub);
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

@media (max-width: 720px) {
  .form-grid {
    grid-template-columns: 1fr;
  }
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.label {
  font-size: 12px;
  color: var(--text-sub);
}

.input {
  padding: 10px 12px;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.86);
  color: var(--text-main);
  outline: none;
}

.actions {
  display: flex;
  gap: 10px;
  margin-top: 12px;
  flex-wrap: wrap;
}

.actions-inline {
  display: flex;
  align-items: center;
  gap: 12px;
}

.btn-ghost {
  background: transparent;
  border: 1px solid var(--border-color);
  color: var(--text-main);
  text-decoration: none;
}

.hint {
  margin-top: 10px;
  font-size: 12px;
  color: var(--text-sub);
}

.hint.error {
  color: #b42318;
}

.health {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px 14px;
}

.history-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 10px 14px;
  margin-top: 6px;
}

@media (max-width: 960px) {
  .history-grid {
    grid-template-columns: 1fr;
  }
}

.history-actions {
  align-items: center;
}

.field-inline {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.input-small {
  width: 110px;
}

.log-meta {
  display: flex;
  gap: 16px;
  font-size: 12px;
  color: var(--text-sub);
  margin: 6px 0 10px 0;
}

.log-pre {
  max-height: 50vh;
}

.kv .k {
  font-size: 12px;
  color: var(--text-sub);
  margin-bottom: 4px;
}

.kv .v {
  font-size: 13px;
  color: var(--text-main);
  word-break: break-all;
}

.probe {
  grid-column: 1 / -1;
  margin-top: 8px;
}

.probe-title {
  font-size: 12px;
  color: var(--text-sub);
  margin-bottom: 6px;
}

.table-wrap {
  overflow: auto;
}

.table {
  width: 100%;
  border-collapse: collapse;
}

.table th,
.table td {
  border-bottom: 1px solid var(--border-color);
  padding: 10px 8px;
  text-align: left;
  font-size: 13px;
  white-space: nowrap;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
}

.danger {
  color: #b42318;
  font-weight: 600;
}

.ops {
  display: flex;
  gap: 8px;
}

.btn-mini {
  padding: 6px 10px;
  font-size: 12px;
}

.btn-danger {
  background: rgba(255, 59, 48, 0.10);
  border: 1px solid rgba(255, 59, 48, 0.18);
  color: #b42318;
}

.checkbox {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--text-sub);
}

.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.42);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  z-index: 9999;
}

.modal {
  width: min(960px, 100%);
  background: var(--bg-elevated);
  border-radius: 14px;
  border: 1px solid var(--border-color);
  box-shadow: var(--shadow-lg);
  overflow: hidden;
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  border-bottom: 1px solid var(--border-color);
}

.modal-title {
  font-weight: 650;
}

.modal-body {
  padding: 12px 14px;
}

.pre {
  background: rgba(120, 120, 128, 0.10);
  color: var(--text-main);
  border: 1px solid var(--border-color);
  padding: 12px;
  border-radius: 10px;
  overflow: auto;
  max-height: 60vh;
  font-size: 12px;
}

@media (prefers-color-scheme: dark) {
  .input {
    background: rgba(44, 44, 46, 0.7);
  }

  .pre {
    background: rgba(235, 235, 245, 0.06);
  }
}
</style>
