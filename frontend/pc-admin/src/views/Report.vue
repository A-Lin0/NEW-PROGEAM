<template>
  <div class="report-page">
    <h2>面试复盘</h2>

    <!-- ============ P0：列表页 ============ -->
    <el-card v-if="!currentReport">
      <!-- 新增：筛选与排序栏 -->
      <div class="filter-bar">
        <el-input
          v-model="filterCompany"
          placeholder="搜索目标公司"
          clearable
          class="filter-item"
          :prefix-icon="Search"
        />
        <el-input
          v-model="filterPosition"
          placeholder="搜索面试岗位"
          clearable
          class="filter-item"
          :prefix-icon="Search"
        />
        <el-select
          v-model="filterScoreRange"
          placeholder="分数区间"
          clearable
          class="filter-item"
        >
          <el-option label="优秀 (80-100)" value="80-100" />
          <el-option label="良好 (60-79)" value="60-79" />
          <el-option label="及格 (40-59)" value="40-59" />
          <el-option label="待提升 (0-39)" value="0-39" />
        </el-select>
        <el-date-picker
          v-model="filterDateRange"
          type="daterange"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          format="YYYY-MM-DD"
          value-format="YYYY-MM-DD"
          class="filter-item"
        />
        <el-select
          v-model="sortField"
          placeholder="排序"
          class="filter-item"
          style="width: 160px"
          @change="onSortChange"
        >
          <el-option label="总分降序" value="score-desc" />
          <el-option label="总分升序" value="score-asc" />
          <el-option label="日期降序" value="date-desc" />
          <el-option label="日期升序" value="date-asc" />
        </el-select>
      </div>

      <el-table :data="filteredReviews" v-loading="loading" stripe>
        <!-- 新增：目标公司 -->
        <el-table-column prop="company_name" label="目标公司" min-width="140">
          <template #default="{ row }">
            <span v-if="row.company_name" class="company-link" @click="goCompany(row.company_id)">
              {{ row.company_name }}
            </span>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="position" label="面试岗位" min-width="140" />
        <!-- 新增：面试难度 -->
        <el-table-column prop="difficulty" label="面试难度" width="120">
          <template #default="{ row }">
            <el-rate
              v-if="row.difficulty"
              :model-value="row.difficulty"
              disabled
              :colors="['#a0cfff', '#409EFF', '#1f7ae0']"
            />
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <!-- 新增：面试时长 -->
        <el-table-column prop="duration" label="面试时长" width="110">
          <template #default="{ row }">
            <span v-if="row.duration">{{ formatDuration(row.duration) }}</span>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <!-- 新增：完成阶段 -->
        <el-table-column prop="completed_stage" label="完成阶段" width="120">
          <template #default="{ row }">
            <el-tag v-if="row.completed_stage" size="small" effect="plain" round>
              {{ row.completed_stage }}
            </el-tag>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <!-- 总分：新增等级徽章 -->
        <el-table-column prop="overall_score" label="总分" width="130">
          <template #default="{ row }">
            <div v-if="row.overall_score != null" class="score-cell">
              <span class="score-value">{{ row.overall_score }}</span>
              <el-tag :type="gradeTagType(row.overall_score)" size="small" effect="dark">
                {{ gradeLabel(row.overall_score) }}
              </el-tag>
            </div>
            <span v-else class="text-muted">未评分</span>
          </template>
        </el-table-column>
        <!-- 日期：精确到秒，含时区转换 -->
        <el-table-column prop="created_at" label="面试时间" width="180">
          <template #default="{ row }">
            <span>{{ formatDate(row.created_at) }}</span>
          </template>
        </el-table-column>
        <!-- 操作：新增回看对话、删除 -->
        <el-table-column label="操作" width="320" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="viewReport(row)">查看报告</el-button>
            <el-button
              size="small"
              type="primary"
              :loading="row.id === generatingId"
              @click="generateReport(row)"
            >
              {{ row.has_review ? '重新生成' : '生成报告' }}
            </el-button>
            <!-- 新增：回看对话 -->
            <el-button size="small" plain :icon="ChatDotRound" @click="viewDialogue(row)">
              对话
            </el-button>
            <!-- 新增：删除记录 -->
            <el-button size="small" plain type="danger" :icon="Delete" @click="handleDelete(row)">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 新增：完整空状态引导 -->
      <div v-if="!loading && reviews.length === 0" class="empty-state">
        <el-empty description="暂无面试复盘记录">
          <template #image>
            <el-icon :size="80" color="#c0c4cc"><DataLine /></el-icon>
          </template>
          <el-button type="primary" @click="goInterview">去开始模拟面试</el-button>
        </el-empty>
      </div>
    </el-card>

    <!-- ============ P1：报告详情页（三大板块 + 可视化） ============ -->
    <el-card v-else>
      <template #header>
        <div class="detail-header">
          <el-button @click="currentReport = null">← 返回列表</el-button>
          <span class="detail-title">{{ reportPosition }} - 复盘报告</span>
          <!-- 新增：业务闭环快捷入口 -->
          <div class="detail-actions">
            <el-button
              v-if="reportData?.company_name"
              size="small"
              plain
              @click="goCompany(reportData.company_id)"
            >
              <el-icon><OfficeBuilding /></el-icon>公司详情
            </el-button>
            <el-button size="small" type="primary" plain @click="rePractice">
              <el-icon><RefreshRight /></el-icon>针对薄弱点再练一次
            </el-button>
            <el-button size="small" plain :icon="EditPen" @click="goResumeOptimize">
              优化对应简历
            </el-button>
          </div>
        </div>
      </template>

      <!-- 加载中：优化交互 -->
      <div v-if="streaming" class="loading-state">
        <el-icon class="is-loading" :size="28"><Loading /></el-icon>
        <div class="loading-text">
          <p class="loading-title">正在生成复盘报告</p>
          <p class="loading-desc">AI 正在深度分析你的面试表现，请稍候...</p>
        </div>
        <el-progress :percentage="100" :indeterminate="true" :stroke-width="4" style="width: 200px" />
      </div>

      <!-- 结构化报告 -->
      <div v-else-if="reportData" class="report-detail">
        <!-- 新增：Tab 标签页三大板块 -->
        <el-tabs v-model="activeTab" class="report-tabs">
          <!-- 板块1：综合评分 -->
          <el-tab-pane label="综合评分" name="score">
            <!-- 总分卡片：新增等级评价、公司/岗位/时长 -->
            <div class="score-card">
              <div class="score-circle" :style="{ '--score-color': scoreColor }">
                <span class="score-num">{{ reportData.total_score }}</span>
                <span class="score-label">综合总分</span>
              </div>
              <div class="score-info">
                <div class="score-grade">
                  <el-tag :type="gradeTagType(reportData.total_score)" size="large" effect="dark">
                    {{ gradeLabel(reportData.total_score) }}
                  </el-tag>
                </div>
                <div class="score-meta">
                  <span v-if="reportData.company_name">目标公司：{{ reportData.company_name }}</span>
                  <span v-if="reportData.target_position">目标岗位：{{ reportData.target_position }}</span>
                  <span v-if="reportData.duration">面试时长：{{ formatDuration(reportData.duration) }}</span>
                </div>
                <div class="score-desc">{{ reportData.overall_comment }}</div>
              </div>
            </div>

            <!-- 新增：五维度雷达图 -->
            <el-card v-if="reportData.dimension_scores" class="section-card">
              <template #header><span>五维度评分</span></template>
              <div ref="radarChartRef" class="radar-chart"></div>
            </el-card>

            <!-- 阶段得分（保留原有） -->
            <el-card v-if="reportData.stage_analysis && reportData.stage_analysis.length" class="section-card">
              <template #header><span>阶段得分</span></template>
              <div class="stage-scores">
                <div v-for="s in reportData.stage_analysis" :key="s.stage" class="stage-item">
                  <div class="stage-header">
                    <span class="stage-label">{{ s.label }}</span>
                    <span class="stage-meta">{{ s.question_count }}题</span>
                  </div>
                  <el-progress
                    :percentage="s.score"
                    :color="progressColor(s.score)"
                    :stroke-width="8"
                  />
                </div>
              </div>
            </el-card>
          </el-tab-pane>

          <!-- 板块2：逐题复盘 -->
          <el-tab-pane label="逐题复盘" name="questions">
            <div v-if="groupedQuestions.length" class="qa-list">
              <!-- 按阶段分组展示 -->
              <div
                v-for="(group, gi) in groupedQuestions"
                :key="gi"
                class="qa-stage-group"
              >
                <!-- 阶段分隔标题栏 -->
                <div class="qa-stage-header">
                  <span class="qa-stage-name">{{ group.label }}</span>
                  <span class="qa-stage-meta">共 {{ group.items.length }} 题 ｜ 阶段得分 {{ group.avgScore }} / 100</span>
                </div>

                <!-- 阶段内题目列表 -->
                <div
                  v-for="item in group.items"
                  :key="item.idx"
                  class="qa-item"
                >
                  <div class="qa-header" @click="toggleQuestion(item.idx)">
                    <div class="qa-header-left">
                      <el-tag size="small" type="info">第{{ item.seqInGroup }}题</el-tag>
                      <span class="qa-question-text">{{ item.q.question }}</span>
                    </div>
                    <div class="qa-header-right">
                      <span class="qa-score" :class="scoreClass(item.q.score)">{{ item.q.score || 0 }}分 / 100分</span>
                      <el-icon class="qa-expand-icon" :class="{ expanded: expandedQuestions[item.idx] }">
                        <ArrowDown />
                      </el-icon>
                    </div>
                  </div>
                  <!-- 题目详细内容（展开/收起） -->
                  <div v-show="expandedQuestions[item.idx]" class="qa-body">
                    <!-- 题干（加粗突出） -->
                    <div class="qa-question"><strong>题目：</strong> {{ item.q.question }}</div>
                    <!-- 答题区（语义化标识，替代原 A:） -->
                    <div class="qa-answer">
                      <div class="qa-answer-title">我的回答：</div>
                      <div class="qa-answer-content">
                        <template v-if="item.q.answer && String(item.q.answer).trim() && item.q.answer !== '跳过'">
                          {{ item.q.answer }}
                        </template>
                        <span v-else class="qa-skipped">未作答（跳过）</span>
                      </div>
                    </div>
                    <!-- 点评三段式：优点 + 不足 + 优化建议 -->
                    <div class="qa-review-block">
                      <div class="qa-review-title">【点评】</div>
                      <div class="qa-adv">
                        <span class="tag-pos">优点</span>
                        <ul v-if="item.q.advantages && item.q.advantages.length">
                          <li v-for="(a, j) in item.q.advantages" :key="j">{{ a }}</li>
                        </ul>
                        <span v-else class="qa-empty">本次回答未体现明显优势</span>
                      </div>
                      <div class="qa-dis">
                        <span class="tag-neg">不足</span>
                        <ul v-if="item.q.shortcomings && item.q.shortcomings.length">
                          <li v-for="(s, j) in item.q.shortcomings" :key="j">{{ s }}</li>
                        </ul>
                        <span v-else class="qa-empty">暂无对应评价</span>
                      </div>
                      <div class="qa-opt">
                        <span class="tag-opt">优化建议</span>
                        <span v-if="item.q.optimization">{{ item.q.optimization }}</span>
                        <span v-else class="qa-empty">暂无对应评价</span>
                      </div>
                    </div>
                    <!-- 参考答题思路（折叠项） -->
                    <details v-if="item.q.reference_answer" class="qa-ref-details">
                      <summary class="tag-ref">查看参考答题框架</summary>
                      <p class="qa-ref-content">{{ item.q.reference_answer }}</p>
                    </details>
                  </div>
                </div>
              </div>
            </div>
            <el-empty v-else description="暂无逐题分析数据" />
          </el-tab-pane>

          <!-- 板块3：提升建议 -->
          <el-tab-pane label="提升建议" name="improve">
            <!-- 整体问题 -->
            <el-card v-if="reportData.overall_problems && reportData.overall_problems.length" class="section-card">
              <template #header><span>整体问题</span></template>
              <ul class="problem-list">
                <li v-for="(p, i) in reportData.overall_problems" :key="i">{{ p }}</li>
              </ul>
            </el-card>

            <!-- 改进计划 -->
            <el-card v-if="reportData.improvement_plan" class="section-card">
              <template #header><span>改进计划</span></template>
              <div class="improve-plan">
                <div v-if="reportData.improvement_plan.short_term && reportData.improvement_plan.short_term.length">
                  <h4>短期提升（1周内）</h4>
                  <ul>
                    <li v-for="(s, i) in reportData.improvement_plan.short_term" :key="i">{{ s }}</li>
                  </ul>
                </div>
                <div v-if="reportData.improvement_plan.long_term && reportData.improvement_plan.long_term.length">
                  <h4>长期提升（1-3个月）</h4>
                  <ul>
                    <li v-for="(l, i) in reportData.improvement_plan.long_term" :key="i">{{ l }}</li>
                  </ul>
                </div>
                <div v-if="reportData.improvement_plan.practice_suggestions && reportData.improvement_plan.practice_suggestions.length">
                  <h4>练习建议</h4>
                  <ul>
                    <li v-for="(p, i) in reportData.improvement_plan.practice_suggestions" :key="i">{{ p }}</li>
                  </ul>
                </div>
              </div>
            </el-card>

            <!-- 新增：分维度提升建议 -->
            <el-card v-if="reportData.dimension_improvements" class="section-card">
              <template #header><span>分维度提升建议</span></template>
              <div class="dimension-improve-list">
                <div
                  v-for="(dim, dKey) in reportData.dimension_improvements"
                  :key="dKey"
                  class="dimension-improve-item"
                >
                  <div class="dim-improve-header">
                    <span class="dim-name">{{ dim.label || dKey }}</span>
                    <el-tag :type="dim.score >= 80 ? 'success' : dim.score >= 60 ? 'warning' : 'danger'" size="small">
                      {{ dim.score }}分
                    </el-tag>
                  </div>
                  <ul class="dim-improve-tips">
                    <li v-for="(tip, ti) in (dim.tips || [])" :key="ti">{{ tip }}</li>
                  </ul>
                </div>
              </div>
            </el-card>

            <el-empty v-if="!reportData.overall_problems?.length && !reportData.improvement_plan && !reportData.dimension_improvements" description="暂无提升建议数据" />
          </el-tab-pane>
        </el-tabs>
      </div>

      <!-- 旧格式文本兜底 -->
      <div v-else-if="reportContent" class="report-content">
        <p v-for="(line, i) in reportContent.split('\n')" :key="i">{{ line }}</p>
      </div>
    </el-card>

    <!-- 新增：对话原文弹窗（样式与面试模拟页一致 + 头部基础信息） -->
    <el-dialog
      v-model="dialogueVisible"
      title="面试对话历史"
      width="800px"
      :close-on-click-modal="false"
      top="5vh"
      @closed="onDialogueClosed"
    >
      <div class="dialogue-wrapper">
        <!-- 头部：面试基础信息 -->
        <div v-if="dialogueInfo" class="dialogue-header">
          <div class="dialogue-header-item">
            <span class="label">目标公司：</span>
            <span class="value">{{ dialogueInfo.company_name || '未指定公司' }}</span>
          </div>
          <div class="dialogue-header-item">
            <span class="label">面试岗位：</span>
            <span class="value">{{ dialogueInfo.position || '未指定岗位' }}</span>
          </div>
          <div class="dialogue-header-item">
            <span class="label">面试时间：</span>
            <span class="value">{{ formatDate(dialogueInfo.created_at) }}</span>
          </div>
          <div class="dialogue-header-item">
            <span class="label">总时长：</span>
            <span class="value">{{ formatDurationSeconds(dialogueInfo.duration_seconds) }}</span>
          </div>
          <div class="dialogue-header-item">
            <span class="label">面试总分：</span>
            <span class="value">{{ dialogueInfo.total_score != null ? dialogueInfo.total_score + ' 分' : '未评分' }}</span>
          </div>
        </div>

        <!-- 对话内容区（垂直滚动） -->
        <div v-loading="dialogueLoading" class="dialogue-content">
          <div v-if="dialogueMessages.length" class="dialogue-list">
            <div
              v-for="(msg, i) in dialogueMessages"
              :key="i"
              :class="['message', msg.role]"
            >
              <div class="avatar" :class="msg.role">
                {{ msg.role === 'interviewer' ? 'AI' : '我' }}
              </div>
              <div class="bubble-wrap">
                <div class="bubble">
                  <el-tag
                    v-if="msg.type === 'feedback'"
                    size="small"
                    type="warning"
                    effect="plain"
                    class="bubble-tag"
                  >点评</el-tag>
                  <el-tag
                    v-else-if="msg.type === 'question'"
                    size="small"
                    type="primary"
                    effect="plain"
                    class="bubble-tag"
                  >提问</el-tag>
                  <el-tag
                    v-else-if="msg.type === 'answer'"
                    size="small"
                    type="success"
                    effect="plain"
                    class="bubble-tag"
                  >回答</el-tag>
                  {{ msg.content }}
                </div>
                <div class="msg-meta">
                  <span class="role-name">{{ msg.role === 'interviewer' ? '面试官' : '候选人' }}</span>
                </div>
              </div>
            </div>
          </div>
          <el-empty v-else-if="!dialogueLoading" description="本场面试无对话记录" />
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { reviewApi } from '../api/index.js'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, ChatDotRound, Delete, DataLine, OfficeBuilding, RefreshRight, EditPen, ArrowDown, Loading } from '@element-plus/icons-vue'
import * as echarts from 'echarts'

const route = useRoute()
const router = useRouter()

/* ============ 原有变量 ============ */
const reviews = ref([])
const loading = ref(false)
const currentReport = ref(null)
const reportPosition = ref('')
const reportContent = ref('')
const reportData = ref(null)
const streaming = ref(false)
const generatingId = ref(null)

/* ============ P0 新增：筛选与排序 ============ */
const filterCompany = ref('')
const filterPosition = ref('')
const filterScoreRange = ref('')
const filterDateRange = ref(null)
const sortField = ref('date-desc')

/* 新增：筛选后数据 */
const filteredReviews = computed(() => {
  let list = [...reviews.value]

  // 公司名称筛选
  if (filterCompany.value) {
    const kw = filterCompany.value.toLowerCase()
    list = list.filter(r => (r.company_name || '').toLowerCase().includes(kw))
  }
  // 岗位筛选
  if (filterPosition.value) {
    const kw = filterPosition.value.toLowerCase()
    list = list.filter(r => (r.position || '').toLowerCase().includes(kw))
  }
  // 分数区间筛选
  if (filterScoreRange.value) {
    const [min, max] = filterScoreRange.value.split('-').map(Number)
    list = list.filter(r => r.overall_score != null && r.overall_score >= min && r.overall_score <= max)
  }
  // 日期范围筛选
  if (filterDateRange.value && filterDateRange.value.length === 2) {
    const [start, end] = filterDateRange.value
    list = list.filter(r => {
      if (!r.created_at) return false
      const d = r.created_at.slice(0, 10)
      return d >= start && d <= end
    })
  }

  // 排序
  const [field, order] = (sortField.value || 'date-desc').split('-')
  list.sort((a, b) => {
    let va, vb
    if (field === 'score') {
      va = Number(a.overall_score) || 0
      vb = Number(b.overall_score) || 0
    } else {
      va = a.created_at || ''
      vb = b.created_at || ''
    }
    if (order === 'asc') return va > vb ? 1 : -1
    return va < vb ? 1 : -1
  })

  return list
})

function onSortChange() {
  // 排序变更后自动刷新
}

/* ============ P0 新增：工具函数 ============ */

/* 阶段编码 → 中文语义映射（禁止前端直接暴露英文编码） */
const STAGE_LABEL_MAP = {
  intro: '开场白',
  self_intro: '自我介绍',
  tech_qa: '技术问答',
  star_qa: '行为面试',
  project_qa: '案例分析',
  reverse_qa: '反问环节',
  end: '已结束',
  completed: '已完成',
}

/* 阶段顺序（用于分组排序） */
const STAGE_ORDER = ['intro', 'self_intro', 'tech_qa', 'star_qa', 'project_qa', 'reverse_qa', 'end', 'completed']

/* 按阶段分组题目（用于逐题复盘 Tab 渲染） */
const groupedQuestions = computed(() => {
  const list = reportData.value?.question_by_question || []
  if (!list.length) return []
  // 按阶段聚合
  const groupMap = new Map()
  list.forEach((q, idx) => {
    const stageKey = q.stage || 'unknown'
    if (!groupMap.has(stageKey)) {
      groupMap.set(stageKey, { stage: stageKey, label: STAGE_LABEL_MAP[stageKey] || stageKey, items: [] })
    }
    groupMap.get(stageKey).items.push({ q, idx, seqInGroup: groupMap.get(stageKey).items.length + 1 })
  })
  // 按 STAGE_ORDER 排序
  const groups = Array.from(groupMap.values())
  groups.sort((a, b) => {
    const ia = STAGE_ORDER.indexOf(a.stage)
    const ib = STAGE_ORDER.indexOf(b.stage)
    return (ia === -1 ? 999 : ia) - (ib === -1 ? 999 : ib)
  })
  // 计算每个阶段的平均分
  groups.forEach(g => {
    const scores = g.items.map(it => Number(it.q.score) || 0)
    g.avgScore = scores.length ? Math.round(scores.reduce((s, v) => s + v, 0) / scores.length) : 0
  })
  return groups
})

/* 新增：等级标签 */
function gradeLabel(score) {
  if (score == null) return '未评分'
  if (score >= 80) return '优秀'
  if (score >= 60) return '良好'
  if (score >= 40) return '及格'
  return '待提升'
}
function gradeTagType(score) {
  if (score == null) return 'info'
  if (score >= 80) return 'success'
  if (score >= 60) return ''
  if (score >= 40) return 'warning'
  return 'danger'
}

/* 新增：日期格式化（精确到秒，自动处理 UTC 时区转换） */
function formatDate(dateStr) {
  if (!dateStr) return '-'
  try {
    // 后端返回带 +00:00 时区的 ISO 字符串，new Date() 会自动转为本地时间
    const d = new Date(dateStr)
    const y = d.getFullYear()
    const m = String(d.getMonth() + 1).padStart(2, '0')
    const day = String(d.getDate()).padStart(2, '0')
    const h = String(d.getHours()).padStart(2, '0')
    const min = String(d.getMinutes()).padStart(2, '0')
    const sec = String(d.getSeconds()).padStart(2, '0')
    return `${y}-${m}-${day} ${h}:${min}:${sec}`
  } catch {
    return dateStr
  }
}

/* 新增：时长格式化 */
function formatDuration(minutes) {
  if (minutes == null) return '-'
  if (minutes < 60) return `${minutes}分钟`
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return m > 0 ? `${h}小时${m}分钟` : `${h}小时`
}

/* 新增：秒级时长格式化（X分X秒） */
function formatDurationSeconds(seconds) {
  if (seconds == null || seconds <= 0) return '0分0秒'
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}分${s}秒`
}

/* ============ P0 新增：操作功能 ============ */

/* 新增：回看对话（异步调用 API 拉取完整对话历史） */
const dialogueVisible = ref(false)
const dialogueMessages = ref([])
const dialogueLoading = ref(false)
const dialogueInfo = ref(null)

async function viewDialogue(row) {
  dialogueVisible.value = true
  dialogueLoading.value = true
  dialogueMessages.value = []
  dialogueInfo.value = null
  try {
    const { data } = await reviewApi.getConversation(row.id)
    dialogueInfo.value = data.interview || null
    dialogueMessages.value = data.messages || []
    if (!data.has_data) {
      ElMessage.info('本场面试无对话记录')
    }
  } catch (e) {
    // 错误提示已由响应拦截器统一处理
    dialogueMessages.value = []
  } finally {
    dialogueLoading.value = false
  }
}

function onDialogueClosed() {
  // 关闭后清空数据，避免下次打开闪现上次内容
  dialogueMessages.value = []
  dialogueInfo.value = null
}

/* 新增：删除记录（按规范文案 + 软删除 + 自动刷新列表） */
async function handleDelete(row) {
  try {
    await ElMessageBox.confirm(
      '确认删除该条面试记录吗？删除后记录将从列表移除，对应复盘报告与对话历史同步失效，且无法恢复。',
      '删除确认',
      {
        confirmButtonText: '确认',
        cancelButtonText: '取消',
        type: 'warning',
        confirmButtonClass: 'el-button--danger',
      }
    )
  } catch (e) {
    // 用户点击取消，不做任何数据变更
    return
  }
  try {
    await reviewApi.delete(row.id)
    ElMessage.success('删除成功')
    loadReviews()
  } catch (e) {
    // 错误提示已由响应拦截器统一处理，保留当前列表状态，不强制刷新
  }
}

/* ============ P0 新增：业务跳转 ============ */
function goCompany(companyId) {
  if (companyId) router.push(`/companies/${companyId}`)
}

function goInterview() {
  router.push('/interview')
}

/* ============ P1 新增：详情页 Tab 切换 ============ */
const activeTab = ref('score')

/* ============ P1 新增：逐题展开/收起 ============ */
const expandedQuestions = ref({})

function toggleQuestion(index) {
  expandedQuestions.value[index] = !expandedQuestions.value[index]
}

/* ============ P1 新增：雷达图 ============ */
const radarChartRef = ref(null)
let radarChart = null

function initRadarChart() {
  if (!radarChartRef.value || !reportData.value?.dimension_scores) return
  const dims = reportData.value.dimension_scores
  const labels = Object.keys(dims)
  const values = Object.values(dims)
  if (labels.length === 0) return

  if (radarChart) radarChart.dispose()

  radarChart = echarts.init(radarChartRef.value)
  radarChart.setOption({
    tooltip: { trigger: 'item' },
    legend: { data: ['维度评分'], bottom: 0 },
    radar: {
      center: ['50%', '50%'],
      radius: '65%',
      indicator: labels.map(name => ({ name, max: 100 })),
      axisName: { fontSize: 13, color: '#606266' },
      splitArea: {
        areaStyle: { color: ['rgba(64, 158, 255, 0.05)', 'rgba(64, 158, 255, 0.1)'] }
      },
    },
    series: [{
      type: 'radar',
      name: '维度评分',
      data: [{ value: values, name: '维度评分' }],
      areaStyle: { color: 'rgba(64, 158, 255, 0.2)' },
      lineStyle: { color: '#409eff', width: 2 },
      itemStyle: { color: '#409eff', borderColor: '#fff', borderWidth: 2 },
      symbol: 'circle',
      symbolSize: 6,
    }],
  })
}

/* 监听报告数据变化，自动渲染雷达图 */
watch(reportData, (newVal) => {
  if (newVal?.dimension_scores) {
    nextTick(() => initRadarChart())
  }
})

/* ============ P1 新增：业务闭环跳转 ============ */

/* 针对薄弱点再练一次 */
function rePractice() {
  const query = {}
  if (reportData.value?.company_name) query.company_name = reportData.value.company_name
  if (reportData.value?.company_id) query.company_id = reportData.value.company_id
  if (reportData.value?.target_position) query.position = reportData.value.target_position
  router.push({ path: '/interview', query })
}

/* 优化对应简历 */
function goResumeOptimize() {
  const query = {}
  if (reportData.value?.company_id) query.company_id = reportData.value.company_id
  if (reportData.value?.company_name) query.company_name = reportData.value.company_name
  if (reportData.value?.target_position) query.default_position = reportData.value.target_position
  router.push({ path: '/resume', query })
}

/* ============ 原有评分计算 ============ */
const scoreColor = computed(() => {
  const s = reportData.value?.total_score || 0
  if (s >= 80) return '#67c23a'
  if (s >= 60) return '#409eff'
  if (s >= 40) return '#e6a23c'
  return '#f56c6c'
})

function progressColor(score) {
  if (score >= 80) return '#67c23a'
  if (score >= 60) return '#409eff'
  if (score >= 40) return '#e6a23c'
  return '#f56c6c'
}

function scoreClass(score) {
  if (score >= 8) return 'score-high'
  if (score >= 5) return 'score-mid'
  return 'score-low'
}

/* ============ 原有生命周期 ============ */
onMounted(() => {
  loadReviews()
  /* 从面试模拟页结束跳转携带 interview_id 时，自动生成该面试的复盘报告 */
  if (route.query.interview_id) {
    const id = route.query.interview_id
    reportPosition.value = route.query.position ? String(route.query.position) : '本次面试'
    currentReport.value = id
    generateReport({ id, position: reportPosition.value })
  }
})

/* ============ 原有数据加载 ============ */
async function loadReviews() {
  loading.value = true
  try {
    const { data } = await reviewApi.list()
    reviews.value = data.reviews || []
  } catch (e) {
    // 错误提示已由响应拦截器统一处理
  } finally {
    loading.value = false
  }
}

async function viewReport(row) {
  activeTab.value = 'score'
  expandedQuestions.value = {}
  currentReport.value = row.id
  reportPosition.value = row.position
  reportData.value = null
  reportContent.value = ''
  try {
    const { data } = await reviewApi.get(row.id)
    const raw = data.report
    if (!raw) {
      reportContent.value = '暂无报告'
      return
    }
    // 尝试解析为 JSON 结构
    try {
      reportData.value = JSON.parse(raw)
      // 默认展开所有题目
      const qs = reportData.value?.question_by_question || []
      qs.forEach((_, i) => { expandedQuestions.value[i] = true })
    } catch {
      reportContent.value = raw
    }
  } catch {
    reportContent.value = '加载失败'
  }
}

async function generateReport(row) {
  if (generatingId.value) {
    ElMessage.warning('正在生成报告中，请稍候...')
    return
  }
  generatingId.value = row.id
  streaming.value = true
  reportContent.value = ''
  reportData.value = null
  currentReport.value = row.id
  reportPosition.value = row.position
  activeTab.value = 'score'
  try {
    const response = await fetch(
      `/api/review/${row.id}/generate`,
      {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` },
      }
    )
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let full = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      const text = decoder.decode(value)
      const lines = text.split('\n')
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6)
          if (data === '[DONE]') break
          try {
            const json = JSON.parse(data)
            full += json.content || ''
          } catch {}
        }
      }
    }
    // 尝试解析为 JSON 结构
    try {
      reportData.value = JSON.parse(full)
      // 默认展开所有题目
      const qs = reportData.value?.question_by_question || []
      qs.forEach((_, i) => { expandedQuestions.value[i] = true })
    } catch {
      reportContent.value = full
    }
    ElMessage.success('报告生成完成')
    loadReviews()
  } catch (e) {
    ElMessage.error('生成失败')
  } finally {
    streaming.value = false
    generatingId.value = null
  }
}
</script>

<style scoped>
.report-page { padding: 20px; }

/* ============ P0 新增：筛选栏 ============ */
.filter-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 16px;
  align-items: center;
}
.filter-item {
  width: 200px;
}

/* ============ P0 新增：表格字段样式 ============ */
.text-muted {
  color: #c0c4cc;
}
.company-link {
  color: #409eff;
  cursor: pointer;
}
.company-link:hover {
  text-decoration: underline;
}
.score-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}
.score-value {
  font-weight: 600;
  font-size: 15px;
  color: #303133;
}

/* ============ P0 新增：空状态 ============ */
.empty-state {
  padding: 40px 0;
}

/* ============ P1 新增：详情页头部 ============ */
.detail-header {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}
.detail-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
  flex: 1;
}
.detail-actions {
  display: flex;
  gap: 8px;
}

/* ============ 原有：加载状态（优化） ============ */
.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  padding: 80px 20px;
  color: #909399;
}
.loading-text {
  text-align: center;
}
.loading-title {
  font-size: 16px;
  color: #606266;
  margin: 0 0 4px;
  font-weight: 500;
}
.loading-desc {
  font-size: 13px;
  color: #909399;
  margin: 0;
}

/* ============ P1 新增：Tab 样式 ============ */
.report-tabs {
  margin-top: -8px;
}

/* ============ 原有：总分卡片（优化） ============ */
.score-card {
  display: flex;
  align-items: flex-start;
  gap: 24px;
  padding: 24px;
  margin-bottom: 20px;
  background: linear-gradient(135deg, #f5f7fa 0%, #e8ecf1 100%);
  border-radius: 12px;
}
.score-circle {
  flex-shrink: 0;
  width: 100px;
  height: 100px;
  border-radius: 50%;
  border: 4px solid var(--score-color, #67c23a);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: #fff;
}
.score-num {
  font-size: 28px;
  font-weight: 700;
  color: var(--score-color, #67c23a);
}
.score-label {
  font-size: 12px;
  color: #909399;
  margin-top: 2px;
}
.score-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.score-grade {
  margin-bottom: 2px;
}
.score-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  font-size: 13px;
  color: #606266;
}
.score-desc {
  font-size: 14px;
  color: #606266;
  line-height: 1.8;
}

/* ============ P1 新增：雷达图 ============ */
.radar-chart {
  width: 100%;
  height: 360px;
}

/* ============ 通用卡片 ============ */
.section-card {
  margin-bottom: 16px;
}

/* ============ 原有：阶段得分 ============ */
.stage-scores {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.stage-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.stage-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.stage-label {
  font-size: 14px;
  font-weight: 500;
  color: #303133;
}
.stage-meta {
  font-size: 12px;
  color: #909399;
}

/* ============ P1 优化：逐题分析（支持展开/收起 + 阶段分组） ============ */
.qa-list {
  display: flex;
  flex-direction: column;
  gap: 20px;
}
/* 阶段分组容器 */
.qa-stage-group {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
/* 阶段分隔标题栏 */
.qa-stage-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  background: linear-gradient(135deg, #ecf5ff 0%, #f0f7ff 100%);
  border-left: 4px solid #409eff;
  border-radius: 6px;
  font-size: 14px;
}
.qa-stage-name {
  font-weight: 600;
  color: #303133;
  font-size: 15px;
}
.qa-stage-meta {
  font-size: 12px;
  color: #606266;
}
.qa-item {
  border-radius: 8px;
  border: 1px solid #ebeef5;
  overflow: hidden;
  transition: box-shadow 0.2s;
}
.qa-item:hover {
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
}
.qa-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  background: #fafafa;
  cursor: pointer;
  user-select: none;
  transition: background 0.2s;
}
.qa-header:hover {
  background: #f0f2f5;
}
.qa-header-left {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  min-width: 0;
}
.qa-question-text {
  font-size: 14px;
  color: #303133;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.qa-header-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}
.qa-score {
  font-weight: 600;
  font-size: 15px;
}
.qa-score.score-high { color: #67c23a; }
.qa-score.score-mid { color: #e6a23c; }
.qa-score.score-low { color: #f56c6c; }
.qa-expand-icon {
  color: #909399;
  transition: transform 0.3s;
}
.qa-expand-icon.expanded {
  transform: rotate(180deg);
}
.qa-body {
  padding: 16px;
  border-top: 1px solid #ebeef5;
  background: #fff;
}
.qa-question {
  margin-bottom: 12px;
  font-size: 14px;
  line-height: 1.7;
  color: #303133;
  font-weight: 500;
}
/* 答题区 */
.qa-answer {
  margin-bottom: 14px;
  padding: 10px 12px;
  background: #fafbfc;
  border-radius: 6px;
  border-left: 3px solid #909399;
}
.qa-answer-title {
  font-size: 13px;
  font-weight: 600;
  color: #606266;
  margin-bottom: 4px;
}
.qa-answer-content {
  font-size: 14px;
  line-height: 1.7;
  color: #303133;
  white-space: pre-wrap;
}
.qa-skipped {
  color: #c0c4cc;
  font-style: italic;
}
/* 点评三段式 */
.qa-review-block {
  margin-top: 12px;
  padding: 12px;
  background: #fff8e1;
  border-radius: 6px;
  border-left: 3px solid #e6a23c;
}
.qa-review-title {
  font-size: 14px;
  font-weight: 600;
  color: #e6a23c;
  margin-bottom: 8px;
}
.qa-adv, .qa-dis, .qa-opt, .qa-ref {
  margin-top: 8px;
  font-size: 13px;
  line-height: 1.7;
}
.qa-adv ul, .qa-dis ul {
  margin: 4px 0 0 16px;
  padding: 0;
}
.qa-empty {
  color: #c0c4cc;
  font-style: italic;
}
/* 参考答题思路折叠项 */
.qa-ref-details {
  margin-top: 12px;
  background: #ecf5ff;
  padding: 10px 12px;
  border-radius: 6px;
}
.qa-ref-details summary {
  cursor: pointer;
  font-weight: 500;
}
.qa-ref-content {
  margin: 8px 0 0;
  color: #606266;
  line-height: 1.7;
  white-space: pre-wrap;
}

.tag-pos, .tag-neg, .tag-opt, .tag-ref {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
  margin-right: 6px;
}
.tag-pos { background: #e1f3d8; color: #67c23a; }
.tag-neg { background: #fde2e2; color: #f56c6c; }
.tag-opt { background: #d9ecff; color: #409eff; }
.tag-ref { background: #e6f7ff; color: #1890ff; }

/* ============ 原有：整体问题 ============ */
.problem-list {
  margin: 0;
  padding-left: 20px;
  color: #e6a23c;
  line-height: 2;
}

/* ============ 原有：改进计划 ============ */
.improve-plan h4 {
  margin: 12px 0 6px;
  font-size: 14px;
  color: #303133;
}
.improve-plan ul {
  margin: 0 0 12px 20px;
  padding: 0;
  line-height: 1.8;
  color: #606266;
}

/* ============ P1 新增：分维度提升建议 ============ */
.dimension-improve-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.dimension-improve-item {
  padding: 14px 16px;
  background: #fafafa;
  border-radius: 8px;
  border-left: 3px solid #409eff;
}
.dim-improve-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.dim-name {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}
.dim-improve-tips {
  margin: 0;
  padding-left: 18px;
  line-height: 1.8;
  color: #606266;
  font-size: 13px;
}

/* ============ 原有：旧格式兜底 ============ */
.report-content {
  line-height: 2;
  white-space: pre-wrap;
  padding: 20px;
  background: #fafafa;
  border-radius: 8px;
  min-height: 300px;
}

/* ============ P0 新增：对话历史弹窗（样式与面试模拟页一致） ============ */
.dialogue-wrapper {
  display: flex;
  flex-direction: column;
}

/* 头部基础信息 */
.dialogue-header {
  display: flex;
  flex-wrap: wrap;
  gap: 20px;
  padding: 12px 16px;
  margin-bottom: 12px;
  background: linear-gradient(135deg, #f5f7fa 0%, #e8ecf1 100%);
  border-radius: 8px;
  font-size: 13px;
}
.dialogue-header-item {
  display: flex;
  align-items: center;
  gap: 4px;
}
.dialogue-header-item .label {
  color: #909399;
  font-weight: 500;
}
.dialogue-header-item .value {
  color: #303133;
  font-weight: 500;
}

/* 对话内容容器 */
.dialogue-content {
  max-height: 60vh;
  overflow-y: auto;
  padding: 8px 4px;
  background: #fafafa;
  border-radius: 8px;
}
.dialogue-content::-webkit-scrollbar {
  width: 6px;
}
.dialogue-content::-webkit-scrollbar-thumb {
  background: #dcdfe6;
  border-radius: 3px;
}

.dialogue-list {
  display: flex;
  flex-direction: column;
  padding: 8px 12px;
}

/* 消息气泡（与 InterviewSim.vue 样式一致） */
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

/* 消息类型标签 */
.bubble-tag {
  margin-right: 6px;
  vertical-align: middle;
}

/* 消息元信息 */
.msg-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
  font-size: 12px;
  color: #909399;
}
.role-name {
  font-weight: 500;
}
</style>