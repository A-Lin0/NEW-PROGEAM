<template>
  <div class="interview-sim">
    <!-- ============ 新增：页面标题区 ============ -->
    <div class="page-header">
      <div class="page-title">
        <el-icon class="title-icon"><ChatLineRound /></el-icon>
        <span>模拟面试</span>
      </div>
      <div class="page-subtitle">AI 面试官 · 沉浸式对话训练</div>
    </div>

    <el-row :gutter="20" class="main-row">
      <!-- ============ 对话区 ============ -->
      <el-col :xs="24" :sm="24" :md="16" :lg="16" :xl="16">
        <el-card class="chat-card" shadow="hover">
          <template #header>
            <div class="chat-header">
              <div class="header-left">
                <span class="status-dot" :class="{ active: started && streaming, idle: !started }"></span>
                <span class="header-title">AI 面试官</span>
                <el-tag v-if="currentPhase" size="small" effect="light" round class="phase-tag">
                  {{ currentPhase }}
                </el-tag>
                <!-- UI 隐藏：Qx/10 题号标签（后端计数逻辑保持不变） -->
                <!-- <el-tag v-if="started && totalQuestions > 0" size="small" effect="dark" round class="count-tag">
                  Q{{ questionIndex + 1 }}/{{ totalQuestions }}
                </el-tag> -->
              </div>
            </div>
          </template>

          <!-- 消息列表 -->
          <div class="chat-messages" ref="chatRef">
            <!-- 空状态占位 -->
            <div v-if="messages.length === 0 && !streaming" class="empty-state">
              <el-empty description="尚未开始对话，请在右侧选择公司并开始面试">
                <template #image>
                  <el-icon class="empty-icon"><ChatDotSquare /></el-icon>
                </template>
              </el-empty>
            </div>

            <!-- 历史消息气泡 -->
            <div
              v-for="(msg, i) in messages"
              :key="i"
              :class="['message', msg.role]"
            >
              <div class="avatar" :class="msg.role">
                {{ msg.role === 'interviewer' ? 'AI' : '我' }}
              </div>
              <div class="bubble-wrap">
                <div class="bubble">{{ msg.content }}</div>
                <div class="msg-meta">
                  <span class="role-name">{{ msg.role === 'interviewer' ? '面试官' : '候选人' }}</span>
                  <span class="msg-time">{{ formatTime(msg.time) }}</span>
                </div>
              </div>
            </div>

            <!-- 流式加载气泡 -->
            <div v-if="streaming" class="message interviewer">
              <div class="avatar interviewer">AI</div>
              <div class="bubble-wrap">
                <div class="bubble streaming">
                  <span class="stream-text">{{ streamContent }}</span>
                  <span class="typing-cursor">▍</span>
                </div>
                <div class="msg-meta">
                  <span class="role-name">面试官</span>
                  <span class="typing-hint">正在输入...</span>
                </div>
              </div>
            </div>
          </div>

          <!-- 输入区：整合到卡片底部 -->
          <div class="input-area">
            <el-input
              v-model="input"
              type="textarea"
              :rows="3"
              resize="none"
              placeholder="输入你的回答，Ctrl + Enter 快速发送..."
              :disabled="streaming || phase === 'completed'"
              @keyup.enter.ctrl="sendAnswer"
            />
            <div class="input-actions">
              <span class="hint">
                <el-icon><InfoFilled /></el-icon>
                Ctrl + Enter 发送
              </span>
              <div class="action-buttons">
                <el-button
                  type="primary"
                  :loading="streaming"
                  :disabled="!input.trim() || streaming || !started"
                  @click="sendAnswer"
                >
                  <el-icon v-if="!streaming"><Promotion /></el-icon>
                  发送回答
                </el-button>
                <el-button :disabled="streaming || !started" @click="nextQuestion">
                  <el-icon><Right /></el-icon>
                  下一题
                </el-button>
                <el-button type="warning" plain :disabled="streaming || !started" @click="endInterview">
                  <el-icon><CircleClose /></el-icon>
                  结束面试
                </el-button>
              </div>
            </div>
          </div>
        </el-card>
      </el-col>

      <!-- ============ 侧边栏 ============ -->
      <el-col :xs="24" :sm="24" :md="8" :lg="8" :xl="8">
        <!-- 面试信息 -->
        <el-card class="side-card" shadow="hover">
          <template #header>
            <div class="side-header">
              <el-icon class="side-icon"><Setting /></el-icon>
              <span>面试信息</span>
            </div>
          </template>
          <el-form label-width="80px" size="default" class="side-form">
            <el-form-item label="目标公司">
              <el-select
                v-model="selectedCompany"
                filterable
                clearable
                placeholder="选择公司（可选）"
                style="width:100%"
              >
                <el-option v-for="c in companies" :key="c.id" :label="c.name" :value="c.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="目标岗位">
              <el-select
                v-model="position"
                filterable
                allow-create
                default-first-option
                clearable
                :placeholder="selectedCompany ? '选择岗位（或手动输入）' : '请先选择公司'"
                style="width:100%"
              >
                <el-option
                  v-for="pos in currentPositions"
                  :key="pos.name"
                  :label="`${pos.name}（${pos.salary}）`"
                  :value="pos.name"
                />
              </el-select>
            </el-form-item>
            <el-form-item>
              <el-button
                type="success"
                class="start-btn"
                :loading="starting"
                :disabled="!position || started"
                @click="startInterview"
              >
                <el-icon v-if="!starting"><VideoPlay /></el-icon>
                {{ started ? '面试进行中' : '开始面试' }}
              </el-button>
            </el-form-item>
          </el-form>
        </el-card>

        <!-- 答题进度（增强版：实时进度条 + 阶段内题目计数） -->
        <el-card class="side-card progress-card" shadow="hover">
          <template #header>
            <div class="side-header">
              <el-icon class="side-icon"><DataLine /></el-icon>
              <span>答题进度</span>
              <span class="progress-percent">{{ progressPercent }}%</span>
            </div>
          </template>
          <!-- UI 隐藏：进度条 + 完成题数文字（后端进度计算逻辑保持不变） -->
          <!-- <div class="overall-progress">
            <el-progress
              :percentage="progressPercent"
              :stroke-width="10"
              :show-text="false"
              :color="progressColor"
            />
            <span class="progress-text">
              已完成 <strong>{{ answeredCount }}</strong> / {{ totalQuestionsAll }} 题
            </span>
          </div> -->
          <!-- 阶段步骤（含题目进度） -->
          <el-steps direction="vertical" :active="phaseIndex" align-center>
            <el-step
              v-for="(step, idx) in stageSteps"
              :key="idx"
              :title="step.title"
              :description="step.description"
            />
          </el-steps>
        </el-card>

        <!-- 新增：操作提示 -->
        <el-card class="side-card tip-card" shadow="hover">
          <template #header>
            <div class="side-header">
              <el-icon class="side-icon"><Bell /></el-icon>
              <span>面试提示</span>
            </div>
          </template>
          <ul class="tip-list">
            <li>认真阅读 AI 面试官的提问</li>
            <li>回答需条理清晰、重点突出</li>
            <li>可点击「下一题」跳过当前问题</li>
            <li>结束后将自动生成复盘报告</li>
          </ul>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, nextTick, watch, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { interviewApi } from '../api/index.js'
import { ElMessage, ElMessageBox } from 'element-plus'
/* 新增：Element Plus 图标组件，用于美化头部与按钮 */
import {
  ChatLineRound, ChatDotSquare, InfoFilled,
  Promotion, Right, CircleClose, Setting, VideoPlay,
  DataLine, Bell,
} from '@element-plus/icons-vue'

const PHASES = ['intro', 'technical', 'behavioral', 'case', 'closing']
const PHASE_LABELS = {
  intro: '自我介绍', technical: '技术问答', behavioral: '行为面试',
  case: '案例分析', closing: '反问环节',
}
// 前端阶段名 → 后端 stage 名的映射（用于 META 解析）
const PHASE_TO_STAGE = {
  intro: 'self_intro', technical: 'tech_qa', behavioral: 'star_qa',
  case: 'project_qa', closing: 'reverse_qa',
}
const STAGE_TO_PHASE = {
  self_intro: 'intro', tech_qa: 'technical', star_qa: 'behavioral',
  project_qa: 'case', reverse_qa: 'closing',
}
// 题目数量配置（与后端 QUESTION_BANK_CONFIG 一致）
const STAGE_QUESTION_COUNT = {
  self_intro: 1, tech_qa: 3, star_qa: 2, project_qa: 3, reverse_qa: 1,
}

const messages = ref([])
const input = ref('')
const streaming = ref(false)
const streamContent = ref('')
const started = ref(false)
const currentPhase = ref('')
const phase = ref('intro')
const interviewId = ref(null)
const questionIndex = ref(0)    // 当前阶段第几题（0-based）
const totalQuestions = ref(0)   // 当前阶段总题数

const selectedCompany = ref('')
const position = ref('')
const companies = ref([])

const phaseIndex = ref(0)

const chatRef = ref(null)

const route = useRoute()
const router = useRouter()

/* 新增：面试启动 loading 状态（仅 UI 反馈，不影响业务逻辑） */
const starting = ref(false)
/* 新增：初始化标志，避免 onMounted 时 watch 误清 query 传入的岗位 */
const initialized = ref(false)

/* 新增：基于选中公司联动返回岗位列表（目标岗位下拉数据源） */
const currentPositions = computed(() => {
  if (!selectedCompany.value) return []
  const matched = companies.value.find((c) => c.id === selectedCompany.value)
  return (matched && matched.positions) || []
})

/* 进度百分比计算（含阶段内题目进度） */
const totalQuestionsAll = 1 + 3 + 2 + 3 + 1 // = 10

/* 新增：实时已答题数（基于用户消息计数，秒级响应，不等后端 META） */
const answeredCount = computed(() => {
  if (!started.value) return 0
  if (phase.value === 'completed') return totalQuestionsAll
  return messages.value.filter((m) => m.role === 'user').length
})

/* 新增：进度条渐变色 */
const progressColor = computed(() => {
  const p = progressPercent.value
  if (p < 30) return '#e6a23c'
  if (p < 70) return '#409eff'
  return '#67c23a'
})

const progressPercent = computed(() => {
  if (!started.value) return 0
  if (phase.value === 'completed') return 100
  // questionIndex 已改为全局题号(0-9)，直接作为已完成题数
  // 取 questionIndex 与 answeredCount 较大值，确保乐观更新也生效
  const completed = Math.min(
    Math.max(questionIndex.value, answeredCount.value),
    totalQuestionsAll
  )
  return Math.round((completed / totalQuestionsAll) * 100)
})

/* 新增：阶段步骤描述（动态显示各阶段题目进度） */
// 各阶段全局起始题号（与后端 STAGE_START_INDEX 一致）
const STAGE_START_INDEX = { self_intro: 0, tech_qa: 1, star_qa: 4, project_qa: 6, reverse_qa: 9 }
const stageSteps = computed(() => {
  const phaseNames = ['intro', 'technical', 'behavioral', 'case', 'closing']
  const titles = ['自我介绍', '技术问答', '行为面试', '案例分析', '反问环节']
  const descs = ['开场介绍', '专业能力', '软技能考察', '综合应用', '主动提问']
  return phaseNames.map((p, i) => {
    const stage = PHASE_TO_STAGE[p]
    const total = STAGE_QUESTION_COUNT[stage] || 0
    // 已完成阶段：显示全部完成
    if (i < phaseIndex.value) {
      return { title: titles[i], description: `${descs[i]}（${total}/${total}）` }
    }
    // 当前阶段：从全局题号换算阶段内已答题数
    if (i === phaseIndex.value && started.value) {
      const stageStart = STAGE_START_INDEX[stage] || 0
      const done = Math.min(Math.max(questionIndex.value - stageStart, 0), total)
      return { title: titles[i], description: `${descs[i]}（${done}/${total}）` }
    }
    // 未开始阶段
    return { title: titles[i], description: `${descs[i]}（0/${total}）` }
  })
})

/* 新增：消息时间格式化（仅 UI 展示） */
function formatTime(time) {
  if (!time) return ''
  const d = new Date(time)
  const h = String(d.getHours()).padStart(2, '0')
  const m = String(d.getMinutes()).padStart(2, '0')
  return `${h}:${m}`
}

onMounted(async () => {
  try {
    // 修复：从本地权威数据源 companies.json 加载，避免后端中文字段编码异常导致目标公司乱码
    const res = await fetch('/data/companies.json')
    companies.value = await res.json()
  } catch {}
  /* 从公司详情/简历页跳转携带参数时自动填充 */
  if (route.query.company_id) selectedCompany.value = route.query.company_id
  if (route.query.company_name) {
    if (!selectedCompany.value) {
      const matched = companies.value.find((c) => c.name === route.query.company_name)
      if (matched) selectedCompany.value = matched.id
    }
  }
  if (route.query.position) position.value = route.query.position
  initialized.value = true

  /* 恢复面试进度：优先从 route query，其次从 localStorage */
  const savedId = route.query.interview_id || localStorage.getItem('active_interview_id')
  if (savedId) {
    try {
      const token = localStorage.getItem('token')
      const resp = await fetch(`/api/interview/${savedId}/session-state`, {
        headers: { 'Authorization': `Bearer ${token}` },
      })
      if (resp.ok) {
        const state = await resp.json()
        if (state.session_status === 'active' || state.session_status === 'ongoing') {
          interviewId.value = savedId
          started.value = true
          localStorage.setItem('active_interview_id', savedId)
          // 恢复阶段状态
          const backendStage = state.current_stage || 'self_intro'
          const frontPhase = STAGE_TO_PHASE[backendStage] || 'intro'
          phase.value = frontPhase
          phaseIndex.value = PHASES.indexOf(frontPhase)
          currentPhase.value = PHASE_LABELS[frontPhase] || ''
          questionIndex.value = state.question_index || 0
          totalQuestions.value = state.total_questions || STAGE_QUESTION_COUNT[backendStage] || 0
          // 恢复历史消息
          if (state.history && state.history.length > 0) {
            messages.value = state.history.map((h) => ({
              role: h.role,
              content: h.content,
              time: h.time || Date.now(),
            }))
            ElMessage.info(`已恢复面试进度（当前阶段：${currentPhase.value}，历史消息 ${state.history.length} 条）`)
          } else if (state.messages_count > 0) {
            ElMessage.info(`已恢复面试进度（当前阶段：${currentPhase.value}）`)
          }
        } else {
          localStorage.removeItem('active_interview_id')
        }
      }
    } catch {
      localStorage.removeItem('active_interview_id')
    }
  }
})

function scrollToBottom() {
  nextTick(() => {
    if (chatRef.value) {
      chatRef.value.scrollTop = chatRef.value.scrollHeight
    }
  })
}

watch(streamContent, scrollToBottom)
watch(messages, scrollToBottom, { deep: true })
/* 新增：切换目标公司时清空已选岗位，避免岗位与公司不匹配（初始化阶段跳过） */
watch(selectedCompany, () => {
  if (!initialized.value) return
  position.value = ''
})

async function startInterview() {
  starting.value = true
  started.value = true
  messages.value = []
  phase.value = 'intro'
  phaseIndex.value = 0
  currentPhase.value = PHASE_LABELS['intro']
  questionIndex.value = 0
  totalQuestions.value = 10  // 全局总题数，与后端 TOTAL_QUESTIONS 一致

  // 通过选中公司 ID 查找公司名称，作为目标公司字符串一并提交给后端持久化
  // 后端 InterviewStart schema 支持 company_name 字段，存入 interviews.target_company_name
  let targetCompanyName = ''
  if (selectedCompany.value) {
    const matched = companies.value.find((c) => c.id === selectedCompany.value)
    if (matched && matched.name) {
      targetCompanyName = matched.name
    }
  }

  try {
    const { data } = await interviewApi.start({
      position: position.value,
      company_name: targetCompanyName || undefined,
    })
    interviewId.value = data.id
    // 持久化到 localStorage，防止页面切换后丢失进度
    localStorage.setItem('active_interview_id', data.id)
  } catch (e) {
    const detail = e.response?.data?.detail
    const msg = Array.isArray(detail)
      ? detail.map((d) => d.msg || JSON.stringify(d)).join('；')
      : detail || '创建面试失败'
    ElMessage.error(msg)
    started.value = false
    starting.value = false
    return
  }

  // 发送"开始"命令获取第一个问题
  await sendCommand('start')
  starting.value = false
}

async function sendCommand(command) {
  if (!interviewId.value) return
  streaming.value = true
  streamContent.value = ''
  try {
    const response = await fetch(
      `/api/interview/${interviewId.value}/command`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('token')}`,
        },
        body: JSON.stringify({ command }),
      }
    )
    if (!response.ok) {
      ElMessage.error(`面试指令失败(${response.status})`)
      streaming.value = false
      return
    }
    await processStream(response, 'interviewer')
  } catch (e) {
    ElMessage.error('请求失败')
  } finally {
    streaming.value = false
  }
}

async function sendAnswer() {
  if (!input.value.trim() || !interviewId.value) return
  /* 新增：为消息附加时间戳（仅 UI 展示用） */
  messages.value.push({ role: 'user', content: input.value, time: Date.now() })
  const answer = input.value
  input.value = ''
  scrollToBottom()

  /* 新增：立即更新答题进度（乐观更新），不等后端 META 事件，实现秒级实时跟进 */
  /* 边界：questionIndex 为 0-based，上限为 totalQuestions-1，避免显示 Q11/10 */
  if (questionIndex.value < (totalQuestions.value || 1) - 1) {
    questionIndex.value++
  }

  streaming.value = true
  streamContent.value = ''
  try {
    const response = await fetch(
      `/api/interview/${interviewId.value}/chat`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('token')}`,
        },
        body: JSON.stringify({ answer }),
      }
    )
    await processStream(response, 'interviewer')
  } catch (e) {
    ElMessage.error('请求失败')
  } finally {
    streaming.value = false
  }
}

async function processStream(response, role) {
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let fullContent = ''
  let buffer = ''
  let streamEnded = false
  while (true) {
    const { done, value } = await reader.read()
    if (done) {
      // 流结束时刷新缓冲区中的剩余数据
      if (buffer.trim()) {
        const line = buffer.trim()
        if (line.startsWith('data: ')) {
          const data = line.slice(6)
          if (data !== '[DONE]') {
            try {
              const json = JSON.parse(data)
              if (json.type !== 'meta') {
                fullContent += json.content || ''
              }
            } catch {}
          }
        }
      }
      break
    }
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    // 保留最后一个可能不完整的行
    buffer = lines.pop() || ''
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const data = line.slice(6)
        if (data === '[DONE]') {
          streamEnded = true
          break
        }
        try {
          const json = JSON.parse(data)
          if (json.type === 'meta') {
            // 处理阶段元数据：同步前端 UI 阶段/题目进度
            const meta = json.meta || {}
            if (meta.next_stage) {
              const frontPhase = STAGE_TO_PHASE[meta.next_stage] || null
              if (frontPhase) {
                phase.value = frontPhase
                phaseIndex.value = PHASES.indexOf(frontPhase)
                currentPhase.value = PHASE_LABELS[frontPhase] || ''
              }
              if (meta.next_stage === 'end') {
                phase.value = 'completed'
                phaseIndex.value = 5
                currentPhase.value = '已完成'
              }
              totalQuestions.value = meta.total_questions || STAGE_QUESTION_COUNT[meta.next_stage] || 0
            }
            if (meta.question_index !== undefined) {
              questionIndex.value = meta.question_index
            }
            if (meta.session_finished) {
              phase.value = 'completed'
              phaseIndex.value = 5
              currentPhase.value = '已完成'
            }
            continue
          }
          // content 类型
          const content = json.content || ''
          fullContent += content
          streamContent.value = fullContent
        } catch {}
      }
    }
    if (streamEnded) break
  }
  if (fullContent) {
    /* 为面试官消息附加时间戳（仅 UI 展示用） */
    messages.value.push({ role, content: fullContent, time: Date.now() })
    // 立即清空流式气泡，避免与已推送消息视觉重复
    streamContent.value = ''
  }
}

async function nextQuestion() {
  /* 新增：立即更新答题进度（乐观更新），不等后端 META 事件 */
  if (questionIndex.value < (totalQuestions.value || 1) - 1) {
    questionIndex.value++
  }
  await sendCommand('next')
}

async function endInterview() {
  try {
    await ElMessageBox.confirm('确认结束本次面试？结束后将自动生成复盘报告', '结束面试', {
      confirmButtonText: '结束并生成复盘',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  phase.value = 'completed'
  phaseIndex.value = 5
  currentPhase.value = '已完成'
  await sendCommand('end')
  // 清理持久化进度
  localStorage.removeItem('active_interview_id')
  ElMessage.success('面试已结束，正在跳转复盘页面')
  /* 自动跳转至复盘详情，携带面试 id 触发生成 */
  setTimeout(() => {
    router.push({ path: '/report', query: { interview_id: interviewId.value } })
  }, 800)
}
</script>

<style scoped>
/* ============ 页面容器 ============ */
.interview-sim {
  padding: 20px;
  background: #f5f7fa;
  min-height: 100%;
  box-sizing: border-box;
}

/* ============ 新增：页面标题区 ============ */
.page-header {
  margin-bottom: 20px;
  padding: 4px 0 16px;
  border-bottom: 1px solid #ebeef5;
}
.page-title {
  display: flex;
  align-items: center;
  font-size: 20px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 6px;
}
.title-icon {
  font-size: 22px;
  color: #409eff;
  margin-right: 8px;
}
.page-subtitle {
  font-size: 13px;
  color: #909399;
  letter-spacing: 0.5px;
}

.main-row {
  margin: 0 !important;
}

/* ============ 对话区卡片 ============ */
.chat-card {
  border-radius: 8px;
  border: none;
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.06);
}
.chat-card :deep(.el-card__header) {
  padding: 14px 20px;
  border-bottom: 1px solid #f0f2f5;
  background: #fafbfc;
  border-radius: 8px 8px 0 0;
}
.chat-card :deep(.el-card__body) {
  padding: 0;
  display: flex;
  flex-direction: column;
  height: calc(100vh - 280px);
  min-height: 520px;
}

/* ============ 对话头部 ============ */
.chat-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}
.header-title {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
}
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #c0c4cc;
  transition: background 0.3s;
}
.status-dot.active {
  background: #67c23a;
  animation: pulse 1.5s infinite;
}
.status-dot.idle {
  background: #c0c4cc;
}
@keyframes pulse {
  0% { box-shadow: 0 0 0 0 rgba(103, 194, 58, 0.6); }
  70% { box-shadow: 0 0 0 6px rgba(103, 194, 58, 0); }
  100% { box-shadow: 0 0 0 0 rgba(103, 194, 58, 0); }
}
.phase-tag {
  background: #ecf5ff;
  color: #409eff;
  border-color: #d9ecff;
}
.count-tag {
  background: #67c23a;
  color: #fff;
  border-color: #67c23a;
  font-weight: 600;
}

/* ============ 消息列表 ============ */
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  background: #f5f7fa;
  scroll-behavior: smooth;
}
.chat-messages::-webkit-scrollbar {
  width: 6px;
}
.chat-messages::-webkit-scrollbar-thumb {
  background: #dcdfe6;
  border-radius: 3px;
}
.chat-messages::-webkit-scrollbar-thumb:hover {
  background: #c0c4cc;
}

/* 空状态 */
.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  min-height: 300px;
}
.empty-icon {
  font-size: 64px;
  color: #c0c4cc;
  margin-bottom: 12px;
}

/* 消息气泡 */
.message {
  display: flex;
  margin-bottom: 20px;
  animation: fadeIn 0.3s ease;
}
.message.user {
  flex-direction: row-reverse;
}
@keyframes fadeIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

/* 头像 */
.avatar {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 600;
  border-radius: 50%;
  margin: 0 12px;
  flex-shrink: 0;
  color: #fff;
}
.avatar.interviewer {
  background: linear-gradient(135deg, #409eff 0%, #66b1ff 100%);
  box-shadow: 0 2px 6px rgba(64, 158, 255, 0.3);
}
.avatar.user {
  background: linear-gradient(135deg, #67c23a 0%, #85ce61 100%);
  box-shadow: 0 2px 6px rgba(103, 194, 58, 0.3);
}

/* 气泡包装 */
.bubble-wrap {
  max-width: 70%;
  display: flex;
  flex-direction: column;
}
.message.user .bubble-wrap {
  align-items: flex-end;
}
.message.interviewer .bubble-wrap {
  align-items: flex-start;
}

/* 气泡 */
.bubble {
  padding: 12px 16px;
  border-radius: 12px;
  line-height: 1.7;
  font-size: 14px;
  white-space: pre-wrap;
  word-break: break-word;
  position: relative;
}
.message.interviewer .bubble {
  background: #fff;
  color: #303133;
  border: 1px solid #ebeef5;
  border-top-left-radius: 4px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.04);
}
.message.user .bubble {
  background: linear-gradient(135deg, #409eff 0%, #66b1ff 100%);
  color: #fff;
  border-top-right-radius: 4px;
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.25);
}

/* 消息元信息 */
.msg-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
  padding: 0 4px;
  font-size: 12px;
  color: #909399;
}
.role-name {
  font-weight: 500;
}
.msg-time {
  color: #c0c4cc;
}
.typing-hint {
  color: #409eff;
  font-style: italic;
}
.typing-hint::before {
  content: '';
  display: inline-block;
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: #409eff;
  margin-right: 4px;
  animation: blink 1s infinite;
  vertical-align: middle;
}

/* 流式加载光标 */
.streaming {
  position: relative;
}
.typing-cursor {
  display: inline-block;
  color: #409eff;
  font-weight: bold;
  animation: blink 0.8s infinite;
  margin-left: 2px;
}
@keyframes blink {
  0%, 50% { opacity: 1; }
  51%, 100% { opacity: 0; }
}

/* ============ 输入区 ============ */
.input-area {
  padding: 16px 20px;
  border-top: 1px solid #f0f2f5;
  background: #fff;
  border-radius: 0 0 8px 8px;
}
.input-area :deep(.el-textarea__inner) {
  border-radius: 8px;
  border-color: #dcdfe6;
  transition: all 0.2s;
}
.input-area :deep(.el-textarea__inner:hover) {
  border-color: #c0c4cc;
}
.input-area :deep(.el-textarea__inner:focus) {
  border-color: #409eff;
  box-shadow: 0 0 0 2px rgba(64, 158, 255, 0.12);
}
.input-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 12px;
}
.hint {
  display: flex;
  align-items: center;
  gap: 4px;
  color: #909399;
  font-size: 12px;
}
.action-buttons {
  display: flex;
  gap: 8px;
}
.action-buttons .el-button {
  border-radius: 6px;
}
.action-buttons .el-button--primary {
  background: linear-gradient(135deg, #409eff 0%, #66b1ff 100%);
  border: none;
}

/* ============ 侧边栏卡片 ============ */
.side-card {
  border-radius: 8px;
  border: none;
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.06);
  margin-bottom: 16px;
}
.side-card :deep(.el-card__header) {
  padding: 12px 20px;
  border-bottom: 1px solid #f0f2f5;
  background: #fafbfc;
  border-radius: 8px 8px 0 0;
}
.side-card :deep(.el-card__body) {
  padding: 20px;
}
.side-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}
.side-icon {
  font-size: 16px;
  color: #409eff;
}
.progress-percent {
  margin-left: auto;
  font-size: 13px;
  color: #409eff;
  font-weight: 600;
}

/* 侧边表单 */
.side-form :deep(.el-form-item) {
  margin-bottom: 18px;
}
.side-form :deep(.el-input__wrapper),
.side-form :deep(.el-select .el-input__wrapper) {
  border-radius: 6px;
}
.start-btn {
  width: 100%;
  border-radius: 6px;
  background: linear-gradient(135deg, #67c23a 0%, #85ce61 100%);
  border: none;
}

/* 进度卡片 */
/* 新增：总体进度条区域 */
.overall-progress {
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid #f0f2f5;
}
.progress-text {
  display: block;
  margin-top: 8px;
  font-size: 13px;
  color: #606266;
  text-align: center;
}
.progress-text strong {
  color: #409eff;
  font-size: 15px;
}
.progress-card :deep(.el-steps) {
  padding: 4px 0;
}
.progress-card :deep(.el-step__title.is-process) {
  color: #409eff;
  font-weight: 600;
}
.progress-card :deep(.el-step__head.is-process) {
  color: #409eff;
  border-color: #409eff;
}
.progress-card :deep(.el-step__head.is-process .el-step__icon-inner) {
  background: #409eff;
  color: #fff;
  border-radius: 50%;
}
/* 新增：已完成步骤的绿色对勾强化 */
.progress-card :deep(.el-step__head.is-finish) {
  color: #67c23a;
  border-color: #67c23a;
}
.progress-card :deep(.el-step__head.is-finish .el-step__icon-inner) {
  background: #67c23a;
  color: #fff;
  border-radius: 50%;
}
/* 新增：步骤描述文字中的题目进度 */
.progress-card :deep(.el-step__description) {
  font-size: 12px;
  color: #909399;
  transition: color 0.3s;
}
.progress-card :deep(.el-step__description.is-process) {
  color: #606266;
  font-weight: 500;
}

/* 提示卡片 */
.tip-card {
  background: linear-gradient(135deg, #ecf5ff 0%, #f5faff 100%);
  border: 1px solid #d9ecff;
}
.tip-list {
  margin: 0;
  padding-left: 18px;
  list-style: none;
}
.tip-list li {
  position: relative;
  padding: 6px 0;
  font-size: 13px;
  color: #606266;
  line-height: 1.6;
}
.tip-list li::before {
  content: '';
  position: absolute;
  left: -12px;
  top: 14px;
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: #409eff;
}

/* ============ 响应式适配 ============ */
@media screen and (max-width: 992px) {
  .chat-card :deep(.el-card__body) {
    height: auto;
    min-height: 480px;
  }
  .side-card {
    margin-bottom: 16px;
  }
}
</style>
