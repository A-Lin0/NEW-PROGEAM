<template>
  <div class="company-detail" v-loading="loading">
    <!-- ============ 新增：面包屑导航 ============ -->
    <el-breadcrumb separator="/" class="breadcrumb">
      <el-breadcrumb-item :to="{ path: '/companies' }">公司信息</el-breadcrumb-item>
      <el-breadcrumb-item>{{ company.name || '公司详情' }}</el-breadcrumb-item>
    </el-breadcrumb>

    <!-- ============ 新增：公司头部卡片 ============ -->
    <el-card v-if="company.id" class="header-card" shadow="never">
      <div class="company-header">
        <el-avatar :size="64" class="company-logo">
          {{ company.name?.charAt(0) }}
        </el-avatar>
        <div class="company-meta">
          <h1 class="company-name">{{ company.name }}</h1>
          <div class="company-tags">
            <el-tag v-if="company.industry" type="primary" effect="light" round>{{ company.industry }}</el-tag>
            <el-tag v-if="company.size" type="info" effect="light" round>{{ company.size }}</el-tag>
            <el-tag v-if="company.location" type="info" effect="light" round>
              <el-icon><Location /></el-icon>{{ company.location }}
            </el-tag>
          </div>
          <!-- 新增：面试难度统一浅蓝 -->
          <div v-if="company.avg_difficulty" class="company-difficulty">
            <span class="diff-label">面试难度</span>
            <el-rate
              v-model="company.avg_difficulty"
              disabled
              show-score
              :colors="['#a0cfff', '#409EFF', '#1f7ae0']"
              text-color="#409EFF"
            />
          </div>
        </div>
      </div>
    </el-card>

    <!-- ============ 新增：多标签页布局 ============ -->
    <el-card v-if="company.id" class="content-card" shadow="never">
      <el-tabs v-model="activeTab" class="detail-tabs">
        <!-- 标签1：基本信息 -->
        <el-tab-pane label="基本信息" name="basic">
          <el-descriptions :column="2" border class="info-desc">
            <el-descriptions-item label="公司名称">{{ company.name }}</el-descriptions-item>
            <el-descriptions-item label="行业">{{ company.industry || '-' }}</el-descriptions-item>
            <el-descriptions-item label="规模">{{ company.size || '-' }}</el-descriptions-item>
            <el-descriptions-item label="地点">{{ company.location || '-' }}</el-descriptions-item>
            <el-descriptions-item label="网站" :span="2">
              <a v-if="company.website" :href="company.website" target="_blank" class="website-link">
                {{ company.website }}
              </a>
              <span v-else class="empty-text">-</span>
            </el-descriptions-item>
            <el-descriptions-item label="面试难度" :span="2">
              <el-rate
                v-model="company.avg_difficulty"
                disabled
                show-score
                :colors="['#a0cfff', '#409EFF', '#1f7ae0']"
                text-color="#409EFF"
              />
            </el-descriptions-item>
          </el-descriptions>
        </el-tab-pane>

        <!-- 标签2：公司介绍 -->
        <el-tab-pane label="公司介绍" name="intro">
          <div v-if="company.description" class="text-block">
            <h3 class="block-title"><el-icon><Document /></el-icon>公司简介</h3>
            <p class="block-text">{{ company.description }}</p>

            <template v-if="company.culture">
              <h3 class="block-title"><el-icon><Flag /></el-icon>企业文化</h3>
              <p class="block-text">{{ company.culture }}</p>
            </template>

            <template v-if="company.benefits">
              <h3 class="block-title"><el-icon><Present /></el-icon>福利待遇</h3>
              <p class="block-text">{{ company.benefits }}</p>
            </template>
          </div>
          <el-empty v-else description="暂无公司介绍信息" />
        </el-tab-pane>

        <!-- 标签3：面试信息 -->
        <el-tab-pane label="面试信息" name="interview">
          <div v-if="company.interview_process" class="text-block">
            <h3 class="block-title"><el-icon><DocumentChecked /></el-icon>面试流程</h3>
            <p class="block-text">{{ company.interview_process }}</p>
          </div>
          <el-empty v-else description="暂无面试流程信息" />
        </el-tab-pane>

        <!-- 新增：招聘岗位信息 -->
        <el-tab-pane name="positions">
          <template #label>
            <span>招聘岗位</span>
            <el-badge
              v-if="company.positions && company.positions.length"
              :value="company.positions.length"
              class="position-badge"
              type="primary"
            />
          </template>
          <div v-if="company.positions && company.positions.length" class="position-list">
            <!-- 新增：岗位卡片列表，浅蓝主题 -->
            <div
              v-for="(pos, idx) in company.positions"
              :key="idx"
              class="position-card"
            >
              <div class="position-header">
                <div class="position-title-row">
                  <el-icon class="position-icon"><Briefcase /></el-icon>
                  <span class="position-name">{{ pos.name }}</span>
                  <el-tag size="small" effect="light" round class="position-salary">
                    {{ pos.salary }}
                  </el-tag>
                </div>
                <el-tag v-if="pos.department" type="info" effect="plain" size="small" round>
                  {{ pos.department }}
                </el-tag>
              </div>
              <div v-if="pos.requirement" class="position-requirement">
                <el-icon><InfoFilled /></el-icon>
                <span>{{ pos.requirement }}</span>
              </div>
            </div>
          </div>
          <el-empty v-else description="暂无招聘岗位信息" />
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <!-- ============ 行动按钮区：快捷入口携带公司信息跳转 ============ -->
    <div v-if="company.id" class="actions">
      <el-button type="primary" size="large" :icon="ChatDotRound" @click="goInterview">
        发起模拟面试（{{ company.name }}）
      </el-button>
      <el-button size="large" :icon="EditPen" @click="goResume">
        基于该公司优化简历
      </el-button>
    </div>

    <!-- ============ 新增：智能问答悬浮入口 & 侧边面板 ============ -->
    <!-- 悬浮按钮 -->
    <div v-if="company.id" class="qa-float-btn" @click="toggleQAPanel" :class="{ active: qaOpen }">
      <el-icon :size="22"><ChatDotSquare /></el-icon>
      <span class="qa-float-label">AI问答</span>
    </div>

    <!-- 侧边问答面板 -->
    <el-drawer
      v-model="qaOpen"
      direction="rtl"
      :size="480"
      :with-header="false"
      :close-on-click-modal="false"
      class="qa-drawer"
    >
      <div class="qa-drawer-inner">
        <!-- 头部 -->
        <div class="qa-drawer-header">
          <div class="qa-drawer-title">
            <el-icon><ChatDotSquare /></el-icon>
            <span>智能问答 · {{ company.name }}</span>
          </div>
          <el-button text circle @click="qaOpen = false">
            <el-icon><Close /></el-icon>
          </el-button>
        </div>

        <!-- 对话历史 -->
        <div class="qa-drawer-messages" ref="qaMsgRef">
          <div v-if="qaHistory.length === 0" class="qa-empty-hint">
            <el-icon><ChatLineRound /></el-icon>
            <p>向我提问关于 <strong>{{ company.name }}</strong> 的任何问题</p>
            <div class="qa-suggestions">
              <el-tag
                v-for="q in qaSuggestions"
                :key="q"
                effect="plain"
                class="qa-suggestion-tag"
                @click="quickAsk(q)"
              >
                {{ q }}
              </el-tag>
            </div>
          </div>
          <div
            v-for="(msg, i) in qaHistory"
            :key="i"
            :class="['qa-msg', msg.role]"
          >
            <div class="qa-msg-avatar" :class="msg.role">
              {{ msg.role === 'user' ? '我' : 'AI' }}
            </div>
            <div class="qa-msg-bubble">
              <div class="qa-msg-text" v-html="msg.html || msg.content"></div>
              <div class="qa-msg-time">{{ msg.time }}</div>
            </div>
          </div>
          <!-- 加载中 -->
          <div v-if="qaSending" class="qa-msg ai">
            <div class="qa-msg-avatar ai">AI</div>
            <div class="qa-msg-bubble">
              <div class="qa-msg-text typing">
                <span class="typing-dot"></span>
                <span class="typing-dot"></span>
                <span class="typing-dot"></span>
              </div>
            </div>
          </div>
        </div>

        <!-- 输入区 -->
        <div class="qa-drawer-input">
          <el-input
            v-model="qaInput"
            placeholder="输入问题..."
            :disabled="qaSending"
            @keyup.enter="sendQA"
          >
            <template #append>
              <el-button
                :icon="Promotion"
                :loading="qaSending"
                :disabled="!qaInput.trim() || qaSending"
                @click="sendQA"
              />
            </template>
          </el-input>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
/* 新增：Element Plus 图标 */
import {
  Location, Document, Flag, Present, DocumentChecked, ChatDotRound, EditPen,
  Briefcase, InfoFilled, ChatDotSquare, ChatLineRound, Close, Promotion,
} from '@element-plus/icons-vue'
/* 新增：API 引入 */
import { retrieverApi } from '../api/index.js'

const route = useRoute()
const router = useRouter()
const company = ref({})
const loading = ref(true)
/* 新增：当前激活标签 */
const activeTab = ref('basic')

/* ============ 新增：智能问答状态 ============ */
const qaOpen = ref(false)
const qaInput = ref('')
const qaSending = ref(false)
const qaHistory = ref([])  // [{ role: 'user'|'ai', content, html, time }]
const qaMsgRef = ref(null)

/* 新增：推荐问题列表 */
const qaSuggestions = ref([
  '这家公司的面试流程是怎样的？',
  '薪资福利待遇如何？',
  '技术面试考什么？',
  '公司文化和工作氛围怎么样？',
])

onMounted(async () => {
  try {
    // 权威数据源：从本地 companies.json 按 id 查找（修复后端中文字段编码异常导致「??」问题）
    const res = await fetch('/data/companies.json')
    const all = await res.json()
    const found = all.find(c => String(c.id) === String(route.params.id))
    company.value = found || {}
  } catch (e) {
    // 错误提示已由响应拦截器统一处理
  } finally {
    loading.value = false
  }
})

/* 快捷入口：携带公司信息跳转对应模块 */
function goInterview() {
  router.push({ path: '/interview', query: { company_id: company.value.id, company_name: company.value.name } })
}
function goResume() {
  const defaultPos = company.value.positions?.[0]?.name || ''
  router.push({
    path: '/resume',
    query: {
      company_id: company.value.id,
      company_name: company.value.name,
      default_position: defaultPos,
    },
  })
}

/* ============ 新增：智能问答功能 ============ */

function toggleQAPanel() {
  qaOpen.value = !qaOpen.value
  if (qaOpen.value) {
    nextTick(() => scrollQABottom())
  }
}

function quickAsk(question) {
  qaInput.value = question
  sendQA()
}

async function sendQA() {
  const query = qaInput.value.trim()
  if (!query || qaSending.value) return

  qaSending.value = true
  const now = new Date()
  const timeStr = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`

  // 添加用户消息
  qaHistory.value.push({ role: 'user', content: query, time: timeStr })
  qaInput.value = ''
  nextTick(() => scrollQABottom())

  try {
    const res = await retrieverApi.qa({
      query,
      company_id: String(company.value.id),
    })
    const data = res.data
    if (data.code === 0 && data.data) {
      const answer = data.data.answer || '暂无相关数据'
      const html = answer
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\n/g, '<br>')
      qaHistory.value.push({
        role: 'ai',
        content: answer,
        html,
        time: timeStr,
      })
    } else {
      qaHistory.value.push({
        role: 'ai',
        content: '抱歉，暂时无法回答该问题，请稍后重试。',
        time: timeStr,
      })
    }
  } catch (e) {
    qaHistory.value.push({
      role: 'ai',
      content: '网络请求失败，请检查网络后重试。',
      time: timeStr,
    })
  } finally {
    qaSending.value = false
    nextTick(() => scrollQABottom())
  }
}

function scrollQABottom() {
  nextTick(() => {
    if (qaMsgRef.value) {
      qaMsgRef.value.scrollTop = qaMsgRef.value.scrollHeight
    }
  })
}
</script>

<style scoped>
/* ============================================================
   新增美化样式：求职商务浅蓝主题
   ============================================================ */

.company-detail {
  padding: 20px;
  max-width: 1000px;
  margin: 0 auto;
}

/* ---------- 面包屑 ---------- */
.breadcrumb {
  margin-bottom: 16px;
}

/* ---------- 公司头部卡片 ---------- */
.header-card {
  border-radius: 8px;
  border: none;
  box-shadow: 0 2px 12px rgba(64, 158, 255, 0.08);
  margin-bottom: 20px;
  background: linear-gradient(135deg, #ecf5ff 0%, #f5f7fa 100%);
}

.company-header {
  display: flex;
  align-items: center;
  gap: 20px;
}

.company-logo {
  background: #409EFF;
  color: #ffffff;
  font-size: 28px;
  font-weight: 700;
  flex-shrink: 0;
}

.company-meta {
  flex: 1;
}

.company-name {
  font-size: 22px;
  font-weight: 600;
  color: #303133;
  margin: 0 0 10px;
}

.company-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}

.company-difficulty {
  display: flex;
  align-items: center;
  gap: 8px;
}

.diff-label {
  font-size: 13px;
  color: #909399;
}

/* ---------- 内容卡片 ---------- */
.content-card {
  border-radius: 8px;
  border: none;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.04);
}

/* ---------- 标签页 ---------- */
.detail-tabs :deep(.el-tabs__header) {
  margin: 0 0 20px;
}

.detail-tabs :deep(.el-tabs__item) {
  font-size: 15px;
  height: 44px;
  line-height: 44px;
}

.detail-tabs :deep(.el-tabs__active-bar) {
  background: #409EFF;
}

.detail-tabs :deep(.el-tabs__item.is-active) {
  color: #409EFF;
}

.detail-tabs :deep(.el-tabs__item:hover) {
  color: #409EFF;
}

/* ---------- 描述列表 ---------- */
.info-desc :deep(.el-descriptions__label) {
  width: 120px;
  background: #f5f7fa;
  font-weight: 600;
  color: #303133;
}

.info-desc :deep(.el-descriptions__content) {
  color: #606266;
}

/* ---------- 文本块 ---------- */
.text-block {
  line-height: 1.8;
}

.block-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 600;
  color: #303133;
  margin: 0 0 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid #ebeef5;
}

.block-title .el-icon {
  color: #409EFF;
}

.block-text {
  font-size: 14px;
  color: #606266;
  line-height: 1.8;
  margin: 0 0 24px;
  white-space: pre-wrap;
}

/* ---------- 网站链接 ---------- */
.website-link {
  color: #409EFF;
  text-decoration: none;
  word-break: break-all;
}

.website-link:hover {
  text-decoration: underline;
}

.empty-text {
  color: #c0c4cc;
}

/* ---------- 新增：招聘岗位卡片样式（浅蓝主题） ---------- */
.position-badge {
  margin-left: 6px;
}
.position-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.position-card {
  padding: 16px 20px;
  border: 1px solid #ebeef5;
  border-left: 3px solid #409EFF;
  border-radius: 8px;
  background: #fafbfc;
  transition: all 0.25s;
}
.position-card:hover {
  border-color: #c6e2ff;
  border-left-color: #1f7ae0;
  box-shadow: 0 4px 12px rgba(64, 158, 255, 0.1);
  background: #fff;
}
.position-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.position-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.position-icon {
  font-size: 18px;
  color: #409EFF;
}
.position-name {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
}
.position-salary {
  background: #ecf5ff;
  color: #1f7ae0;
  border-color: #d9ecff;
  font-weight: 600;
}
.position-requirement {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: 13px;
  color: #606266;
  line-height: 1.7;
}
.position-requirement .el-icon {
  color: #909399;
  margin-top: 3px;
  flex-shrink: 0;
}

/* ---------- 行动按钮区 ---------- */
.actions {
  margin-top: 24px;
  text-align: center;
  padding: 20px;
  background: #f5f7fa;
  border-radius: 8px;
}

.actions .el-button {
  min-width: 240px;
}

/* ---------- 响应式 ---------- */
@media (max-width: 768px) {
  .company-header {
    flex-direction: column;
    text-align: center;
  }
  .company-tags {
    justify-content: center;
  }
  .company-difficulty {
    justify-content: center;
  }
  .info-desc :deep(.el-descriptions) {
    --el-descriptions-item-bordered-label-background: #f5f7fa;
  }
  .actions {
    flex-direction: column;
  }
  .actions .el-button {
    width: 100%;
  }
}

/* ============================================================
   新增：智能问答侧边面板样式（求职商务浅蓝主题）
   ============================================================ */

/* 悬浮入口按钮 */
.qa-float-btn {
  position: fixed;
  right: 24px;
  bottom: 120px;
  width: 56px;
  height: 56px;
  border-radius: 50%;
  background: #409EFF;
  color: #fff;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  box-shadow: 0 4px 16px rgba(64, 158, 255, 0.35);
  transition: all 0.3s;
  z-index: 1000;
  user-select: none;
}
.qa-float-btn:hover {
  background: #337ecc;
  box-shadow: 0 6px 20px rgba(64, 158, 255, 0.45);
  transform: scale(1.05);
}
.qa-float-btn.active {
  background: #337ecc;
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.25);
}
.qa-float-label {
  font-size: 10px;
  margin-top: 2px;
  line-height: 1;
}

/* 问答抽屉 */
.qa-drawer-inner {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.qa-drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid #ebeef5;
  flex-shrink: 0;
}
.qa-drawer-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}
.qa-drawer-title .el-icon {
  color: #409EFF;
  font-size: 20px;
}

/* 消息区域 */
.qa-drawer-messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* 空状态提示 */
.qa-empty-hint {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #909399;
  gap: 12px;
  text-align: center;
}
.qa-empty-hint .el-icon {
  font-size: 48px;
  color: #c0c4cc;
}
.qa-empty-hint p {
  font-size: 14px;
  margin: 0;
}
.qa-empty-hint strong {
  color: #409EFF;
}
.qa-suggestions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
  margin-top: 8px;
}
.qa-suggestion-tag {
  cursor: pointer;
  font-size: 12px;
  padding: 4px 12px;
  border-radius: 16px;
  transition: all 0.2s;
}
.qa-suggestion-tag:hover {
  color: #409EFF;
  border-color: #409EFF;
  background: #ecf5ff;
}

/* 消息气泡（参考面试聊天页风格做轻量化适配） */
.qa-msg {
  display: flex;
  gap: 10px;
  max-width: 100%;
}
.qa-msg.user {
  flex-direction: row-reverse;
}
.qa-msg-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
  flex-shrink: 0;
}
.qa-msg-avatar.user {
  background: #409EFF;
  color: #fff;
}
.qa-msg-avatar.ai {
  background: #e6f0fa;
  color: #409EFF;
}
.qa-msg-bubble {
  max-width: 75%;
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.7;
  word-break: break-word;
}
.qa-msg.user .qa-msg-bubble {
  background: #409EFF;
  color: #fff;
  border-bottom-right-radius: 4px;
}
.qa-msg.ai .qa-msg-bubble {
  background: #f5f7fa;
  color: #303133;
  border-bottom-left-radius: 4px;
  border: 1px solid #e4e7ed;
}
.qa-msg-text :deep(strong) {
  color: inherit;
  font-weight: 600;
}
.qa-msg.ai .qa-msg-text :deep(strong) {
  color: #1f7ae0;
}
.qa-msg-time {
  font-size: 11px;
  margin-top: 4px;
  opacity: 0.7;
  text-align: right;
}

/* 打字机加载动画 */
.qa-msg-text.typing {
  display: flex;
  gap: 4px;
  align-items: center;
  padding: 4px 0;
}
.typing-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #909399;
  animation: typingBounce 1.4s infinite ease-in-out both;
}
.typing-dot:nth-child(1) { animation-delay: -0.32s; }
.typing-dot:nth-child(2) { animation-delay: -0.16s; }
.typing-dot:nth-child(3) { animation-delay: 0s; }
@keyframes typingBounce {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
  40% { transform: scale(1); opacity: 1; }
}

/* 输入区 */
.qa-drawer-input {
  padding: 12px 20px;
  border-top: 1px solid #ebeef5;
  flex-shrink: 0;
}
.qa-drawer-input :deep(.el-input-group__append) {
  padding: 0;
  background: none;
  border: none;
}
.qa-drawer-input :deep(.el-input-group__append .el-button) {
  border-radius: 0 6px 6px 0;
  border: 1px solid var(--el-input-border-color);
  border-left: none;
}

/* 响应式：窄屏适配 */
@media (max-width: 768px) {
  .qa-float-btn {
    right: 12px;
    bottom: 80px;
    width: 48px;
    height: 48px;
  }
  .qa-float-label {
    font-size: 9px;
  }
  .qa-drawer :deep(.el-drawer) {
    width: 100% !important;
  }
  .qa-msg-bubble {
    max-width: 85%;
  }
}
</style>
