<template>
  <div class="company-detail" v-loading="loading">
    <!-- ============ 面包屑导航（美化：增加可点击返回能力） ============ -->
    <el-breadcrumb separator="/" class="breadcrumb">
      <el-breadcrumb-item :to="{ path: '/companies' }">公司信息</el-breadcrumb-item>
      <el-breadcrumb-item>{{ company.name || '公司详情' }}</el-breadcrumb-item>
    </el-breadcrumb>

    <!-- ============ 美化升级：头部信息卡片（放大Logo + 核心标签 + 数据可视化 + 收藏） ============ -->
    <el-card v-if="company.id" class="header-card" shadow="never">
      <div class="company-header">
        <!-- 放大Logo（80px）+ 浅蓝渐变背景 -->
        <el-avatar :size="80" class="company-logo">
          {{ company.name?.charAt(0) }}
        </el-avatar>

        <!-- 公司基础信息 -->
        <div class="company-meta">
          <div class="company-name-row">
            <h1 class="company-name">{{ company.name }}</h1>
            <!-- 新增：收藏按钮（前端 localStorage 存储，不涉及后端） -->
            <el-tooltip :content="isFavorited ? '取消收藏' : '收藏公司'" placement="top">
              <el-button
                circle
                :type="isFavorited ? 'danger' : 'default'"
                :icon="isFavorited ? StarFilled : Star"
                class="favorite-btn"
                @click="toggleFavorite"
              />
            </el-tooltip>
          </div>

          <!-- 核心标签：行业 / 规模 / 地点 / 派生标签 -->
          <div class="company-tags">
            <el-tag v-if="company.industry" type="primary" effect="light" round size="small">
              <el-icon><OfficeBuilding /></el-icon>{{ company.industry }}
            </el-tag>
            <el-tag v-if="company.size" type="info" effect="light" round size="small">
              <el-icon><User /></el-icon>{{ company.size }}
            </el-tag>
            <el-tag v-if="company.location" type="info" effect="light" round size="small">
              <el-icon><Location /></el-icon>{{ company.location }}
            </el-tag>
            <!-- 新增：派生标签（按规模派生「大厂」「头部」标签，纯前端推导） -->
            <el-tag
              v-if="company.size && company.size.includes('2000人')"
              type="success"
              effect="plain"
              round
              size="small"
            >
              头部大厂
            </el-tag>
            <el-tag
              v-if="company.avg_difficulty && company.avg_difficulty >= 4"
              type="warning"
              effect="plain"
              round
              size="small"
            >
              高面试难度
            </el-tag>
          </div>

          <!-- 新增：官网链接（带外链标识，符合使用习惯） -->
          <a
            v-if="company.website"
            :href="company.website"
            target="_blank"
            rel="noopener noreferrer"
            class="website-link"
          >
            <el-icon><Link /></el-icon>
            <span>{{ company.website }}</span>
            <el-icon class="external-icon"><TopRight /></el-icon>
          </a>
        </div>
      </div>

      <!-- 新增：核心数据可视化卡片（难度 / 平均薪资 / 面试轮次 / 在招岗位） -->
      <div class="stat-grid">
        <div class="stat-item">
          <div class="stat-label">面试难度</div>
          <div class="stat-value-row">
            <el-rate
              v-model="company.avg_difficulty"
              disabled
              show-score
              :colors="['#a0cfff', '#409EFF', '#1f7ae0']"
              text-color="#409EFF"
              size="small"
            />
          </div>
          <div class="stat-desc">{{ difficultyDesc }}</div>
        </div>

        <div class="stat-item">
          <div class="stat-label">平均薪资范围</div>
          <div class="stat-value-row">
            <span class="stat-value">{{ avgSalaryRange }}</span>
          </div>
          <div class="stat-desc">在招岗位综合统计</div>
        </div>

        <div class="stat-item">
          <div class="stat-label">面试轮次</div>
          <div class="stat-value-row">
            <span class="stat-value">{{ interviewRoundCount }}</span>
            <span class="stat-unit">轮</span>
          </div>
          <div class="stat-desc">标准面试流程</div>
        </div>

        <div class="stat-item">
          <div class="stat-label">在招岗位</div>
          <div class="stat-value-row">
            <span class="stat-value">{{ company.positions?.length || 0 }}</span>
            <span class="stat-unit">个</span>
          </div>
          <div class="stat-desc">覆盖{{ positionDepartmentCount }}个部门</div>
        </div>
      </div>
    </el-card>

    <!-- ============ 美化升级：主+辅双栏栅格布局 ============ -->
    <div v-if="company.id" class="main-layout">
      <!-- 左侧：Tabs 主内容 -->
      <el-card class="content-card" shadow="never">
        <el-tabs v-model="activeTab" class="detail-tabs">
          <!-- 标签1：基本信息（升级为多维度信息卡片网格） -->
          <el-tab-pane label="基本信息" name="basic">
            <!-- 保留原有描述列表，作为基础信息表格 -->
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

            <!-- 新增：高价值信息卡片网格（基于现有数据派生） -->
            <div class="info-card-grid">
              <div class="info-card">
                <div class="info-card-header">
                  <el-icon class="info-card-icon"><Calendar /></el-icon>
                  <span class="info-card-title">面试难度说明</span>
                </div>
                <p class="info-card-text">
                  难度 {{ company.avg_difficulty || '-' }} / 5.0，
                  {{ difficultyDesc }}，{{ difficultyFocus }}
                </p>
              </div>

              <div class="info-card">
                <div class="info-card-header">
                  <el-icon class="info-card-icon"><Money /></el-icon>
                  <span class="info-card-title">薪资结构</span>
                </div>
                <p class="info-card-text">
                  {{ avgSalaryRange }} / 月，
                  薪资月份{{ salaryMonths || '14-16薪' }}
                </p>
              </div>

              <div class="info-card">
                <div class="info-card-header">
                  <el-icon class="info-card-icon"><Briefcase /></el-icon>
                  <span class="info-card-title">核心业务线</span>
                </div>
                <p class="info-card-text">{{ coreBusinessLines }}</p>
              </div>

              <div class="info-card">
                <div class="info-card-header">
                  <el-icon class="info-card-icon"><Present /></el-icon>
                  <span class="info-card-title">员工福利关键词</span>
                </div>
                <div class="benefit-tags">
                  <el-tag
                    v-for="(b, i) in benefitKeywords"
                    :key="i"
                    effect="plain"
                    type="success"
                    size="small"
                    round
                  >
                    {{ b }}
                  </el-tag>
                </div>
              </div>
            </div>
          </el-tab-pane>

          <!-- 标签2：公司介绍（拆分为模块化卡片） -->
          <el-tab-pane label="公司介绍" name="intro">
            <div v-if="company.description || company.culture || company.benefits" class="intro-modules">
              <!-- 模块1：公司概况 -->
              <div v-if="company.description" class="intro-card">
                <h3 class="block-title">
                  <el-icon><Document /></el-icon>公司概况
                </h3>
                <p class="block-text">{{ company.description }}</p>
              </div>

              <!-- 模块2：企业文化 -->
              <div v-if="company.culture" class="intro-card">
                <h3 class="block-title">
                  <el-icon><Flag /></el-icon>企业文化
                </h3>
                <div class="culture-tags">
                  <el-tag
                    v-for="(c, i) in cultureKeywords"
                    :key="i"
                    effect="light"
                    type="primary"
                    round
                  >
                    {{ c }}
                  </el-tag>
                </div>
              </div>

              <!-- 模块3：员工福利 -->
              <div v-if="company.benefits" class="intro-card">
                <h3 class="block-title">
                  <el-icon><Present /></el-icon>员工福利
                </h3>
                <p class="block-text">{{ company.benefits }}</p>
              </div>

              <!-- 模块4：面试整体流程 -->
              <div v-if="company.interview_process" class="intro-card">
                <h3 class="block-title">
                  <el-icon><DocumentChecked /></el-icon>面试整体流程
                </h3>
                <p class="block-text">{{ company.interview_process }}</p>
              </div>
            </div>
            <el-empty v-else description="暂无公司介绍信息" :image-size="120" />
          </el-tab-pane>

          <!-- 标签3：面试信息（升级为时间轴+特点卡片） -->
          <el-tab-pane label="面试信息" name="interview">
            <div v-if="company.interview_process" class="interview-block">
              <!-- 模块1：面试流程时间轴（结构化展示） -->
              <h3 class="block-title">
                <el-icon><DocumentChecked /></el-icon>面试流程时间轴
              </h3>
              <el-timeline class="interview-timeline">
                <el-timeline-item
                  v-for="(step, idx) in interviewSteps"
                  :key="idx"
                  :type="idx === 0 ? 'primary' : 'info'"
                  :hollow="idx !== 0"
                  :timestamp="`第 ${idx + 1} 步`"
                  placement="top"
                >
                  <div class="timeline-content">
                    <span class="timeline-title">{{ step }}</span>
                    <span class="timeline-desc">{{ getStepDesc(idx) }}</span>
                  </div>
                </el-timeline-item>
              </el-timeline>

              <!-- 模块2：面试考情特点卡片 -->
              <h3 class="block-title" style="margin-top: 24px">
                <el-icon><Aim /></el-icon>面试考情分析
              </h3>
              <div class="interview-feature-grid">
                <div class="feature-card">
                  <div class="feature-icon-wrapper blue">
                    <el-icon><View /></el-icon>
                  </div>
                  <div class="feature-content">
                    <div class="feature-title">考察重点</div>
                    <div class="feature-desc">{{ difficultyFocus }}</div>
                  </div>
                </div>

                <div class="feature-card">
                  <div class="feature-icon-wrapper green">
                    <el-icon><TrendCharts /></el-icon>
                  </div>
                  <div class="feature-content">
                    <div class="feature-title">面试特点</div>
                    <div class="feature-desc">{{ interviewFeature }}</div>
                  </div>
                </div>

                <div class="feature-card">
                  <div class="feature-icon-wrapper orange">
                    <el-icon><WarnTriangleFilled /></el-icon>
                  </div>
                  <div class="feature-content">
                    <div class="feature-title">避坑提示</div>
                    <div class="feature-desc">{{ interviewAvoidTip }}</div>
                  </div>
                </div>
              </div>

              <!-- 模块3：CTA 行动区 -->
              <div class="interview-cta">
                <div class="cta-text">
                  <el-icon><Promotion /></el-icon>
                  <span>立即开始针对 {{ company.name }} 的模拟面试</span>
                </div>
                <el-button type="primary" :icon="ChatDotRound" @click="goInterview">
                  开始模拟面试
                </el-button>
              </div>
            </div>
            <el-empty v-else description="暂无面试流程信息" :image-size="120" />
          </el-tab-pane>

          <!-- 标签4：招聘岗位（每个岗位新增「针对该岗位发起模拟面试」按钮） -->
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
                <!-- 新增：岗位操作按钮区 -->
                <div class="position-actions">
                  <el-button
                    type="primary"
                    size="small"
                    :icon="ChatDotRound"
                    @click="goInterviewWithPosition(pos.name)"
                  >
                    针对该岗位发起模拟面试
                  </el-button>
                  <el-button
                    size="small"
                    :icon="EditPen"
                    @click="goResumeWithPosition(pos.name)"
                  >
                    针对该岗位优化简历
                  </el-button>
                </div>
              </div>
            </div>
            <el-empty v-else description="暂无招聘岗位信息" :image-size="120" />
          </el-tab-pane>
        </el-tabs>
      </el-card>

      <!-- 右侧：辅助快速信息卡（侧栏） -->
      <aside class="side-bar">
        <!-- 快速入口卡 -->
        <el-card class="side-card" shadow="never">
          <div class="side-card-title">
            <el-icon><Lightning /></el-icon>
            <span>快速入口</span>
          </div>
          <div class="side-action-list">
            <el-button
              type="primary"
              class="side-action-btn"
              :icon="ChatDotRound"
              @click="goInterview"
            >
              发起模拟面试
            </el-button>
            <el-button
              class="side-action-btn"
              :icon="EditPen"
              @click="goResume"
            >
              优化简历
            </el-button>
            <el-button
              class="side-action-btn"
              :icon="ChatDotSquare"
              @click="openQAWithCompanyContext"
            >
              AI 问答
            </el-button>
          </div>
        </el-card>

        <!-- 公司速览卡 -->
        <el-card class="side-card" shadow="never">
          <div class="side-card-title">
            <el-icon><InfoFilled /></el-icon>
            <span>公司速览</span>
          </div>
          <ul class="side-info-list">
            <li>
              <span class="side-info-label">行业</span>
              <span class="side-info-value">{{ company.industry || '-' }}</span>
            </li>
            <li>
              <span class="side-info-label">规模</span>
              <span class="side-info-value">{{ company.size || '-' }}</span>
            </li>
            <li>
              <span class="side-info-label">地点</span>
              <span class="side-info-value">{{ company.location || '-' }}</span>
            </li>
            <li>
              <span class="side-info-label">面试轮次</span>
              <span class="side-info-value">{{ interviewRoundCount }} 轮</span>
            </li>
            <li>
              <span class="side-info-label">在招岗位</span>
              <span class="side-info-value">{{ company.positions?.length || 0 }} 个</span>
            </li>
          </ul>
        </el-card>

        <!-- 求职追踪卡（前端 localStorage 简单统计） -->
        <el-card class="side-card" shadow="never">
          <div class="side-card-title">
            <el-icon><TrendCharts /></el-icon>
            <span>我的求职追踪</span>
          </div>
          <div class="tracking-tip">
            <el-icon><InfoFilled /></el-icon>
            <span>从该公司发起模拟面试，复盘列表「目标公司」将自动填充</span>
          </div>
        </el-card>
      </aside>
    </div>

    <!-- ============ 行动按钮区（保留作为底部 CTA，主操作移到侧栏） ============ -->
    <div v-if="company.id" class="actions">
      <el-button type="primary" size="large" :icon="ChatDotRound" @click="goInterview">
        发起模拟面试（{{ company.name }}）
      </el-button>
      <el-button size="large" :icon="EditPen" @click="goResume">
        基于该公司优化简历
      </el-button>
    </div>

    <!-- ============ 新增：发起模拟面试岗位选择弹窗 ============ -->
    <el-dialog
      v-model="interviewDialogVisible"
      title="选择目标岗位"
      width="480px"
      class="position-select-dialog"
    >
      <div class="dialog-tip">
        <el-icon><InfoFilled /></el-icon>
        <span>选定岗位后，将生成贴合该岗位要求的专属面试题</span>
      </div>
      <el-radio-group v-model="selectedPosition" class="position-radio-group">
        <el-radio
          v-for="pos in (company.positions || [])"
          :key="pos.name"
          :value="pos.name"
          class="position-radio"
        >
          <div class="position-radio-content">
            <span class="position-radio-name">{{ pos.name }}</span>
            <span class="position-radio-salary">{{ pos.salary }}</span>
          </div>
        </el-radio>
        <el-radio value="" class="position-radio">
          <div class="position-radio-content">
            <span class="position-radio-name">通用岗位（不指定）</span>
            <span class="position-radio-salary">综合面试题</span>
          </div>
        </el-radio>
      </el-radio-group>
      <template #footer>
        <el-button @click="interviewDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="interviewLoading" @click="confirmStartInterview">
          开始面试
        </el-button>
      </template>
    </el-dialog>

    <!-- ============ 新增：智能问答悬浮入口 & 侧边面板（场景化引导语） ============ -->
    <!-- 悬浮按钮（场景化文案） -->
    <div
      v-if="company.id"
      class="qa-float-btn"
      @click="openQAWithCompanyContext"
      :class="{ active: qaOpen }"
    >
      <el-icon :size="22"><ChatDotSquare /></el-icon>
      <span class="qa-float-label">问问我{{ companyNameShort }}的面试</span>
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
            <!-- 美化：场景化引导语，带入公司上下文 -->
            <p>问问我 <strong>{{ company.name }}</strong> 的面试技巧、岗位偏好、避坑要点</p>
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
            :placeholder="`问问我${companyNameShort}的面试技巧...`"
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
import { ref, computed, onMounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
/* 新增：Element Plus 图标（含美化升级新增图标） */
import {
  Location, Document, Flag, Present, DocumentChecked, ChatDotRound, EditPen,
  Briefcase, InfoFilled, ChatDotSquare, ChatLineRound, Close, Promotion,
  OfficeBuilding, User, Link, TopRight, Calendar, Money, Aim, View,
  TrendCharts, WarnTriangleFilled, Star, StarFilled, Lightning,
} from '@element-plus/icons-vue'
/* 新增：API 引入 */
import { retrieverApi } from '../api/index.js'

const route = useRoute()
const router = useRouter()
const company = ref({})
const loading = ref(true)
/* 新增：当前激活标签 */
const activeTab = ref('basic')

/* ============ 新增：收藏功能状态（纯前端 localStorage） ============ */
const isFavorited = ref(false)

/* ============ 新增：发起模拟面试岗位选择弹窗状态 ============ */
const interviewDialogVisible = ref(false)
const selectedPosition = ref('')
const interviewLoading = ref(false)

/* ============ 新增：智能问答状态 ============ */
const qaOpen = ref(false)
const qaInput = ref('')
const qaSending = ref(false)
const qaHistory = ref([])  // [{ role: 'user'|'ai', content, html, time }]
const qaMsgRef = ref(null)

/* 新增：推荐问题列表（场景化：默认带入公司上下文） */
const qaSuggestions = computed(() => [
  `${company.value.name}的面试流程是怎样的？`,
  `${company.value.name}面试侧重考察哪些能力？`,
  `${company.value.name}的薪资福利待遇如何？`,
  `${company.value.name}的工作氛围和价值观是什么？`,
])

/* ============ 新增：派生计算属性（基于现有数据最大化利用） ============ */

/* 公司名简称（取前4字，用于悬浮按钮文案） */
const companyNameShort = computed(() => {
  const name = company.value.name || ''
  return name.length > 4 ? name.slice(0, 4) : name
})

/* 面试难度文字说明 */
const difficultyDesc = computed(() => {
  const d = company.value.avg_difficulty
  if (!d) return '暂无数据'
  if (d >= 4.5) return '极高，竞争激烈'
  if (d >= 4) return '较高，侧重项目深挖与场景题考察'
  if (d >= 3) return '中等，常规技术+项目考察'
  if (d >= 2) return '偏低，基础面为主'
  return '较低，常规流程'
})

/* 难度对应考察重点 */
const difficultyFocus = computed(() => {
  const d = company.value.avg_difficulty
  if (d >= 4) return '项目深挖、场景题、系统设计、压力面'
  if (d >= 3) return '基础知识、项目经验、技术广度'
  return '基础技能、过往经历'
})

/* 平均薪资范围（从 positions 派生） */
const avgSalaryRange = computed(() => {
  const positions = company.value.positions || []
  if (!positions.length) return '暂无数据'
  const minArr = []
  const maxArr = []
  positions.forEach(p => {
    const m = String(p.salary || '').match(/(\d+)-(\d+)K/)
    if (m) {
      minArr.push(Number(m[1]))
      maxArr.push(Number(m[2]))
    }
  })
  if (!minArr.length) return positions[0]?.salary || '暂无数据'
  const min = Math.min(...minArr)
  const max = Math.max(...maxArr)
  return `${min}-${max}K`
})

/* 薪资月份 */
const salaryMonths = computed(() => {
  const positions = company.value.positions || []
  if (!positions.length) return ''
  const m = String(positions[0].salary || '').match(/(\d+)薪/)
  return m ? m[1] + '薪' : ''
})

/* 核心业务线（从 description 派生关键词） */
const coreBusinessLines = computed(() => {
  const desc = company.value.description || ''
  if (!desc) return '-'
  // 简单关键词提取：寻找「旗下」「业务」「产品」相关字眼
  return desc.length > 60 ? desc.slice(0, 60) + '...' : desc
})

/* 福利关键词（从 benefits 拆分） */
const benefitKeywords = computed(() => {
  const benefits = company.value.benefits || ''
  if (!benefits) return ['暂无数据']
  return benefits.split(/[、，,；;]/).filter(s => s.trim()).slice(0, 6)
})

/* 企业文化关键词（从 culture 拆分） */
const cultureKeywords = computed(() => {
  const culture = company.value.culture || ''
  if (!culture) return ['暂无数据']
  return culture.split(/[、，,；;]/).filter(s => s.trim()).slice(0, 6)
})

/* 面试轮次数（从 interview_process 派生） */
const interviewRoundCount = computed(() => {
  const process = company.value.interview_process || ''
  if (!process) return 0
  // 按 → 分割统计轮次
  const steps = process.split('→').map(s => s.trim()).filter(Boolean)
  return steps.length
})

/* 面试步骤数组 */
const interviewSteps = computed(() => {
  const process = company.value.interview_process || ''
  if (!process) return []
  return process.split('→').map(s => s.trim()).filter(Boolean)
})

/* 在招岗位覆盖部门数 */
const positionDepartmentCount = computed(() => {
  const positions = company.value.positions || []
  const depts = new Set(positions.map(p => p.department).filter(Boolean))
  return depts.size
})

/* 面试特点 */
const interviewFeature = computed(() => {
  const d = company.value.avg_difficulty
  if (d >= 4) return '多轮技术深挖，注重项目落地能力'
  if (d >= 3) return '常规技术面+HR面，重视基础与沟通'
  return '流程简化，以基础考察为主'
})

/* 避坑提示 */
const interviewAvoidTip = computed(() => {
  const d = company.value.avg_difficulty
  if (d >= 4) return '提前准备项目细节、数据指标、复盘思路'
  if (d >= 3) return '注意表达逻辑清晰，避免空泛描述'
  return '了解公司业务方向，避免面试冷场'
})

/* 面试步骤说明 */
function getStepDesc(idx) {
  const map = [
    '初步筛选与基础信息核实',
    '专业能力与项目经验考察',
    '技术深挖或综合能力评估',
    '终面或HR面试',
    '录用确认',
  ]
  return map[idx] || ''
}

onMounted(async () => {
  try {
    // 权威数据源：从本地 companies.json 按 id 查找（修复后端中文字段编码异常导致「??」问题）
    const res = await fetch('/data/companies.json')
    const all = await res.json()
    const found = all.find(c => String(c.id) === String(route.params.id))
    company.value = found || {}
    // 新增：加载收藏状态
    loadFavoriteStatus()
  } catch (e) {
    // 错误提示已由响应拦截器统一处理
  } finally {
    loading.value = false
  }
})

/* 快捷入口：携带公司信息跳转对应模块 */
function goInterview() {
  // 美化：升级为弹窗选岗位后再跳转
  if (company.value.positions && company.value.positions.length) {
    selectedPosition.value = ''
    interviewDialogVisible.value = true
  } else {
    router.push({ path: '/interview', query: { company_id: company.value.id, company_name: company.value.name } })
  }
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

/* 新增：针对特定岗位发起模拟面试 */
function goInterviewWithPosition(positionName) {
  router.push({
    path: '/interview',
    query: {
      company_id: company.value.id,
      company_name: company.value.name,
      target_position: positionName,
    },
  })
}

/* 新增：针对特定岗位优化简历 */
function goResumeWithPosition(positionName) {
  router.push({
    path: '/resume',
    query: {
      company_id: company.value.id,
      company_name: company.value.name,
      default_position: positionName,
    },
  })
}

/* 新增：确认开始模拟面试（弹窗确认后跳转） */
function confirmStartInterview() {
  interviewLoading.value = true
  const query = {
    company_id: company.value.id,
    company_name: company.value.name,
  }
  if (selectedPosition.value) {
    query.target_position = selectedPosition.value
  }
  router.push({ path: '/interview', query })
}

/* ============ 新增：收藏公司功能（localStorage 纯前端实现） ============ */
function loadFavoriteStatus() {
  try {
    const list = JSON.parse(localStorage.getItem('favorite_companies') || '[]')
    isFavorited.value = list.includes(company.value.id)
  } catch {
    isFavorited.value = false
  }
}

function toggleFavorite() {
  try {
    const list = JSON.parse(localStorage.getItem('favorite_companies') || '[]')
    const idx = list.indexOf(company.value.id)
    if (idx >= 0) {
      list.splice(idx, 1)
      isFavorited.value = false
      ElMessage.success('已取消收藏')
    } else {
      list.push(company.value.id)
      isFavorited.value = true
      ElMessage.success('已加入求职清单')
    }
    localStorage.setItem('favorite_companies', JSON.stringify(list))
  } catch {
    ElMessage.error('操作失败，请重试')
  }
}

/* ============ 新增：智能问答功能 ============ */

function openQAWithCompanyContext() {
  qaOpen.value = true
  if (qaOpen.value) {
    nextTick(() => scrollQABottom())
  }
}

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
   美化升级样式：求职商务浅蓝主题（高密度信息布局）
   适配 1200~1920 分辨率
   ============================================================ */

.company-detail {
  padding: 20px;
  max-width: 1280px;
  margin: 0 auto;
}

/* ---------- 面包屑 ---------- */
.breadcrumb {
  margin-bottom: 16px;
}

/* ---------- 头部卡片（升级） ---------- */
.header-card {
  border-radius: 8px;
  border: none;
  box-shadow: 0 2px 12px rgba(64, 158, 255, 0.08);
  margin-bottom: 20px;
  background: linear-gradient(135deg, #ecf5ff 0%, #f5f7fa 60%, #ffffff 100%);
}

.company-header {
  display: flex;
  align-items: flex-start;
  gap: 24px;
  padding-bottom: 20px;
  border-bottom: 1px dashed #d9ecff;
}

.company-logo {
  background: linear-gradient(135deg, #409EFF, #1f7ae0);
  color: #ffffff;
  font-size: 36px;
  font-weight: 700;
  flex-shrink: 0;
  box-shadow: 0 4px 12px rgba(64, 158, 255, 0.3);
}

.company-meta {
  flex: 1;
  min-width: 0;
}

.company-name-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.company-name {
  font-size: 24px;
  font-weight: 700;
  color: #303133;
  margin: 0;
}

.favorite-btn {
  border: none;
}

.company-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}

.company-tags .el-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

/* ---------- 官网链接（带外链标识） ---------- */
.website-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: #409EFF;
  text-decoration: none;
  font-size: 13px;
  word-break: break-all;
  transition: color 0.2s;
}

.website-link:hover {
  color: #1f7ae0;
  text-decoration: underline;
}

.website-link .external-icon {
  font-size: 12px;
}

/* ---------- 数据可视化卡片栅格 ---------- */
.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-top: 20px;
}

.stat-item {
  background: #ffffff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 14px 16px;
  transition: all 0.25s;
}

.stat-item:hover {
  border-color: #c6e2ff;
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.1);
  transform: translateY(-1px);
}

.stat-label {
  font-size: 12px;
  color: #909399;
  margin-bottom: 8px;
}

.stat-value-row {
  display: flex;
  align-items: baseline;
  gap: 4px;
  margin-bottom: 6px;
}

.stat-value {
  font-size: 20px;
  font-weight: 700;
  color: #409EFF;
  line-height: 1;
}

.stat-unit {
  font-size: 12px;
  color: #909399;
}

.stat-desc {
  font-size: 11px;
  color: #c0c4cc;
}

/* ---------- 主+辅双栏布局 ---------- */
.main-layout {
  display: grid;
  grid-template-columns: 1fr 280px;
  gap: 20px;
  align-items: start;
}

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

/* ---------- 基本信息Tab：高价值信息卡片网格 ---------- */
.info-card-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 14px;
  margin-top: 20px;
}

.info-card {
  background: #fafbfc;
  border: 1px solid #ebeef5;
  border-left: 3px solid #409EFF;
  border-radius: 8px;
  padding: 14px 16px;
  transition: all 0.25s;
}

.info-card:hover {
  border-color: #c6e2ff;
  border-left-color: #1f7ae0;
  box-shadow: 0 4px 12px rgba(64, 158, 255, 0.1);
  background: #fff;
}

.info-card-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
}

.info-card-icon {
  color: #409EFF;
  font-size: 16px;
}

.info-card-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}

.info-card-text {
  font-size: 13px;
  color: #606266;
  line-height: 1.7;
  margin: 0;
}

.benefit-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

/* ---------- 公司介绍Tab：模块化卡片 ---------- */
.intro-modules {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.intro-card {
  background: #fafbfc;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 16px 20px;
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
  margin: 0;
  white-space: pre-wrap;
}

.culture-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

/* ---------- 面试信息Tab：时间轴+特点卡片 ---------- */
.interview-block {
  line-height: 1.8;
}

.interview-timeline {
  padding-left: 8px;
}

.timeline-content {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.timeline-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}

.timeline-desc {
  font-size: 12px;
  color: #909399;
}

.interview-feature-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
  margin-top: 12px;
}

.feature-card {
  background: #fafbfc;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 14px 16px;
  display: flex;
  gap: 12px;
  align-items: flex-start;
  transition: all 0.25s;
}

.feature-card:hover {
  border-color: #c6e2ff;
  box-shadow: 0 4px 12px rgba(64, 158, 255, 0.08);
  background: #fff;
}

.feature-icon-wrapper {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  flex-shrink: 0;
}

.feature-icon-wrapper.blue {
  background: #ecf5ff;
  color: #409EFF;
}

.feature-icon-wrapper.green {
  background: #f0f9eb;
  color: #67c23a;
}

.feature-icon-wrapper.orange {
  background: #fdf6ec;
  color: #e6a23c;
}

.feature-content {
  flex: 1;
  min-width: 0;
}

.feature-title {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 4px;
}

.feature-desc {
  font-size: 12px;
  color: #606266;
  line-height: 1.6;
}

.interview-cta {
  margin-top: 20px;
  padding: 16px 20px;
  background: linear-gradient(135deg, #ecf5ff 0%, #f5f7fa 100%);
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border: 1px solid #d9ecff;
}

.cta-text {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  color: #1f7ae0;
  font-weight: 500;
}

/* ---------- 网站链接（描述列表内） ---------- */
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

/* ---------- 招聘岗位卡片（升级：新增按钮区） ---------- */
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
  margin-bottom: 12px;
}
.position-requirement .el-icon {
  color: #909399;
  margin-top: 3px;
  flex-shrink: 0;
}
/* 新增：岗位操作按钮区 */
.position-actions {
  display: flex;
  gap: 8px;
  padding-top: 10px;
  border-top: 1px dashed #ebeef5;
}

/* ---------- 侧栏 ---------- */
.side-bar {
  display: flex;
  flex-direction: column;
  gap: 16px;
  position: sticky;
  top: 20px;
}

.side-card {
  border-radius: 8px;
  border: none;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.04);
}

.side-card-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 12px;
}

.side-card-title .el-icon {
  color: #409EFF;
}

.side-action-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.side-action-btn {
  width: 100%;
  margin-left: 0 !important;
}

.side-info-list {
  list-style: none;
  padding: 0;
  margin: 0;
}

.side-info-list li {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  padding: 8px 0;
  border-bottom: 1px dashed #ebeef5;
}

.side-info-list li:last-child {
  border-bottom: none;
}

.side-info-label {
  color: #909399;
}

.side-info-value {
  color: #303133;
  font-weight: 500;
}

.tracking-tip {
  display: flex;
  gap: 6px;
  align-items: flex-start;
  font-size: 12px;
  color: #909399;
  line-height: 1.6;
  background: #ecf5ff;
  padding: 10px 12px;
  border-radius: 6px;
}

.tracking-tip .el-icon {
  color: #409EFF;
  flex-shrink: 0;
  margin-top: 2px;
}

/* ---------- 岗位选择弹窗 ---------- */
.position-select-dialog :deep(.el-dialog__body) {
  padding: 12px 20px;
}

.dialog-tip {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #909399;
  margin-bottom: 16px;
  background: #ecf5ff;
  padding: 10px 12px;
  border-radius: 6px;
}

.dialog-tip .el-icon {
  color: #409EFF;
}

.position-radio-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
}

.position-radio {
  width: 100%;
  height: auto !important;
  padding: 10px 12px !important;
  border: 1px solid #ebeef5;
  border-radius: 8px !important;
  margin-right: 0 !important;
}

.position-radio :deep(.el-radio__label) {
  width: 100%;
}

.position-radio-content {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
}

.position-radio-name {
  font-size: 14px;
  color: #303133;
  font-weight: 500;
}

.position-radio-salary {
  font-size: 12px;
  color: #1f7ae0;
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

/* ============================================================
   智能问答侧边面板样式（求职商务浅蓝主题）
   ============================================================ */

/* 悬浮入口按钮 */
.qa-float-btn {
  position: fixed;
  right: 24px;
  bottom: 120px;
  min-width: 56px;
  max-width: 120px;
  height: 56px;
  padding: 0 12px;
  border-radius: 28px;
  background: #409EFF;
  color: #fff;
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 6px;
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
  font-size: 11px;
  line-height: 1.2;
  white-space: nowrap;
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

/* 消息气泡 */
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

/* ============================================================
   响应式适配（1200~1920 主流分辨率 + 平板/移动端降级）
   ============================================================ */
@media (max-width: 1200px) {
  .main-layout {
    grid-template-columns: 1fr;
  }
  .side-bar {
    position: static;
    flex-direction: row;
    flex-wrap: wrap;
  }
  .side-card {
    flex: 1;
    min-width: 260px;
  }
}

@media (max-width: 992px) {
  .stat-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  .info-card-grid,
  .interview-feature-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .company-detail {
    padding: 12px;
  }
  .company-header {
    flex-direction: column;
    text-align: center;
    gap: 12px;
  }
  .company-name-row {
    justify-content: center;
  }
  .company-tags {
    justify-content: center;
  }
  .stat-grid {
    grid-template-columns: 1fr;
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
  .qa-float-btn {
    right: 12px;
    bottom: 80px;
    height: 48px;
    min-width: 48px;
    padding: 0 10px;
    border-radius: 24px;
  }
  .qa-float-label {
    font-size: 10px;
  }
  .qa-drawer :deep(.el-drawer) {
    width: 100% !important;
  }
  .qa-msg-bubble {
    max-width: 85%;
  }
  .interview-cta {
    flex-direction: column;
    gap: 12px;
    align-items: flex-start;
  }
}
</style>
