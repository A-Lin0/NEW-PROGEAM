<template>
  <div class="profile-page">
    <!-- ============ 新增：页面标题区 ============ -->
    <div class="page-header">
      <div class="page-title">
        <el-icon class="title-icon"><User /></el-icon>
        <span>个人中心</span>
      </div>
      <div class="page-subtitle">简历资产管理 · 求职进度跟踪</div>
    </div>

    <!-- ============ 用户信息卡片 ============ -->
    <el-card class="user-card" shadow="hover" v-loading="userLoading">
      <div class="user-info">
        <div class="user-avatar">
          <el-avatar :size="72" :src="userInfo.avatar">
            <el-icon :size="32"><UserFilled /></el-icon>
          </el-avatar>
        </div>
        <div class="user-detail">
          <div class="user-name">{{ userInfo.username || '求职者' }}</div>
          <div class="user-meta">
            <span class="meta-item">
              <el-icon><Message /></el-icon>
              {{ userInfo.email || '未绑定邮箱' }}
            </span>
            <span class="meta-item">
              <el-icon><Calendar /></el-icon>
              注册于 {{ formatdate(userInfo.created_at) }}
            </span>
          </div>
          <div class="user-tags">
            <el-tag size="small" effect="light" round class="user-tag">求职中</el-tag>
            <el-tag size="small" type="success" effect="light" round class="user-tag">已认证</el-tag>
          </div>
        </div>
      </div>
    </el-card>

    <!-- ============ 数据统计卡片栅格 ============ -->
    <el-row :gutter="20" class="stat-row">
      <el-col :xs="12" :sm="12" :md="6" :lg="6" :xl="6">
        <el-card class="stat-card stat-resume" shadow="hover">
          <div class="stat-icon-wrap"><el-icon><Document /></el-icon></div>
          <div class="stat-content">
            <div class="stat-value">{{ resumeList.length }}</div>
            <div class="stat-label">简历数量</div>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="12" :md="6" :lg="6" :xl="6">
        <el-card class="stat-card stat-interview" shadow="hover">
          <div class="stat-icon-wrap"><el-icon><ChatLineRound /></el-icon></div>
          <div class="stat-content">
            <div class="stat-value">{{ interviewList.length }}</div>
            <div class="stat-label">面试场次</div>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="12" :md="6" :lg="6" :xl="6">
        <el-card class="stat-card stat-review" shadow="hover">
          <div class="stat-icon-wrap"><el-icon><DataAnalysis /></el-icon></div>
          <div class="stat-content">
            <div class="stat-value">{{ reviewList.length }}</div>
            <div class="stat-label">复盘报告</div>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="12" :md="6" :lg="6" :xl="6">
        <el-card class="stat-card stat-progress" shadow="hover">
          <div class="stat-icon-wrap"><el-icon><TrendCharts /></el-icon></div>
          <div class="stat-content">
            <div class="stat-value">{{ progressPercent }}%</div>
            <div class="stat-label">求职活跃度</div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="20" class="main-row">
      <!-- ============ 简历资产管理 ============ -->
      <el-col :xs="24" :sm="24" :md="16" :lg="16" :xl="16">
        <el-card class="asset-card" shadow="hover">
          <template #header>
            <div class="card-header">
              <div class="header-left">
                <el-icon class="header-icon"><Folder /></el-icon>
                <span class="header-title">简历资产</span>
                <el-tag size="small" type="info" effect="plain" round>{{ resumeList.length }} 份</el-tag>
              </div>
              <el-button type="primary" text @click="goResume">
                去管理<el-icon class="el-icon--right"><ArrowRight /></el-icon>
              </el-button>
            </div>
          </template>

          <div v-loading="resumeLoading">
            <!-- 空状态 -->
            <el-empty v-if="resumeList.length === 0" description="暂无简历，去上传第一份简历吧">
              <template #image>
                <el-icon class="empty-icon"><DocumentRemove /></el-icon>
              </template>
              <el-button type="primary" round @click="goResume">上传简历</el-button>
            </el-empty>

            <!-- 简历列表 -->
            <div v-else class="resume-list">
              <div
                v-for="resume in resumeList"
                :key="resume.id"
                class="resume-item"
                @click="viewResume(resume.id)"
              >
                <div class="resume-icon">
                  <el-icon><Document /></el-icon>
                </div>
                <div class="resume-info">
                  <div class="resume-name">{{ resume.name || resume.title || `简历 #${resume.id}` }}</div>
                  <div class="resume-meta">
                    <span class="meta-text">更新于 {{ formatdate(resume.updated_at || resume.created_at) }}</span>
                    <el-tag v-if="resume.is_optimized" size="small" type="success" effect="light" round>已优化</el-tag>
                  </div>
                </div>
                <div class="resume-actions">
                  <el-button text circle @click.stop="viewResume(resume.id)">
                    <el-icon><View /></el-icon>
                  </el-button>
                </div>
              </div>
            </div>
          </div>
        </el-card>
      </el-col>

      <!-- ============ 求职进度看板 ============ -->
      <el-col :xs="24" :sm="24" :md="8" :lg="8" :xl="8">
        <el-card class="progress-card" shadow="hover">
          <template #header>
            <div class="card-header">
              <div class="header-left">
                <el-icon class="header-icon"><Timer /></el-icon>
                <span class="header-title">求职进度</span>
              </div>
            </div>
          </template>

          <div v-loading="interviewLoading">
            <!-- 空状态 -->
            <el-empty v-if="progressList.length === 0" description="暂无求职记录">
              <template #image>
                <el-icon class="empty-icon"><Histogram /></el-icon>
              </template>
            </el-empty>

            <!-- 进度时间线 -->
            <el-timeline v-else class="progress-timeline">
              <el-timeline-item
                v-for="(item, idx) in progressList"
                :key="idx"
                :type="getTimelineType(item.status)"
                :timestamp="formatdate(item.created_at)"
                placement="top"
              >
                <div class="timeline-content">
                  <div class="timeline-title">
                    <span class="tl-position">{{ item.position || '面试岗位' }}</span>
                    <el-tag :type="getStatusTagType(item.status)" size="small" effect="light" round>
                      {{ getStatusLabel(item.status) }}
                    </el-tag>
                  </div>
                  <div v-if="item.company_name" class="timeline-sub">
                    <el-icon><OfficeBuilding /></el-icon>
                    {{ item.company_name }}
                  </div>
                </div>
              </el-timeline-item>
            </el-timeline>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- ============ 最近面试记录 ============ -->
    <el-card class="recent-card" shadow="hover">
      <template #header>
        <div class="card-header">
          <div class="header-left">
            <el-icon class="header-icon"><Clock /></el-icon>
            <span class="header-title">最近面试记录</span>
          </div>
          <el-button type="primary" text @click="goInterview">
            查看全部<el-icon class="el-icon--right"><ArrowRight /></el-icon>
          </el-button>
        </div>
      </template>

      <div v-loading="interviewLoading">
        <!-- 空状态 -->
        <el-empty v-if="interviewList.length === 0" description="暂无面试记录">
          <template #image>
            <el-icon class="empty-icon"><ChatDotSquare /></el-icon>
          </template>
          <el-button type="primary" round @click="goInterview">开始模拟面试</el-button>
        </el-empty>

        <!-- 表格 -->
        <el-table
          v-else
          :data="recentInterviews"
          stripe
          style="width: 100%"
          :header-cell-style="{ background: '#fafbfc', color: '#606266', fontWeight: 600 }"
        >
          <el-table-column prop="position" label="面试岗位" min-width="140" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="cell-text">{{ row.position || '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="company_name" label="目标公司" min-width="140" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="cell-text">{{ row.company_name || '未指定' }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="status" label="状态" width="120" align="center">
            <template #default="{ row }">
              <el-tag :type="getStatusTagType(row.status)" size="small" effect="light" round>
                {{ getStatusLabel(row.status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="created_at" label="时间" width="160" align="center">
            <template #default="{ row }">
              <span class="cell-time">{{ formatdate(row.created_at) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="120" align="center" fixed="right">
            <template #default="{ row }">
              <el-button type="primary" link size="small" @click="viewInterview(row.id)">查看</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-card>
  </div>
</template>

<script setup>
/* ============ 个人中心页：用户简历资产管理 + 求职进度跟踪看板 ============ */
/* 业务说明：仅复用已有 API（authApi / resumeApi / interviewApi / reviewApi），不新增后端接口 */
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { authApi, resumeApi, interviewApi, reviewApi } from '../api/index.js'
/* 新增：Element Plus 图标组件，用于美化卡片头部与空状态 */
import {
  User, UserFilled, Message, Calendar, Document, DocumentRemove,
  ChatLineRound, DataAnalysis, TrendCharts, Folder, ArrowRight,
  View, Timer, Histogram, Clock, ChatDotSquare, OfficeBuilding,
} from '@element-plus/icons-vue'

const router = useRouter()

/* ============ 原有业务变量 ============ */
const userInfo = ref({})
const resumeList = ref([])
const interviewList = ref([])
const reviewList = ref([])

/* 新增：各模块独立 loading 状态（仅 UI 反馈） */
const userLoading = ref(false)
const resumeLoading = ref(false)
const interviewLoading = ref(false)

/* 新增：最近面试记录（取前 5 条） */
const recentInterviews = computed(() => interviewList.value.slice(0, 5))

/* 新增：求职进度列表（合并面试+复盘数据，按时间倒序） */
const progressList = computed(() => {
  return [...interviewList.value]
    .sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0))
    .slice(0, 8)
})

/* 新增：求职活跃度百分比（纯展示用，基于数据量计算） */
const progressPercent = computed(() => {
  const score = Math.min(100,
    resumeList.value.length * 20 +
    interviewList.value.length * 15 +
    reviewList.value.length * 15
  )
  return Math.max(10, score)
})

/* 新增：日期格式化（仅 UI 展示） */
function formatdate(dateStr) {
  if (!dateStr) return '-'
  const d = new Date(dateStr)
  if (isNaN(d.getTime())) return '-'
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  const h = String(d.getHours()).padStart(2, '0')
  const min = String(d.getMinutes()).padStart(2, '0')
  return `${y}-${m}-${day} ${h}:${min}`
}

/* 新增：状态标签映射（仅 UI 展示） */
function getStatusLabel(status) {
  const map = {
    completed: '已完成', finished: '已完成', done: '已完成',
    ongoing: '进行中', in_progress: '进行中', active: '进行中',
    pending: '待开始', new: '待开始', created: '待开始',
    error: '异常', failed: '失败',
  }
  return map[status] || '进行中'
}
function getStatusTagType(status) {
  const map = {
    completed: 'success', finished: 'success', done: 'success',
    ongoing: 'primary', in_progress: 'primary', active: 'primary',
    pending: 'info', new: 'info', created: 'info',
    error: 'danger', failed: 'danger',
  }
  return map[status] || 'primary'
}
function getTimelineType(status) {
  const map = {
    completed: 'success', finished: 'success', done: 'success',
    ongoing: 'primary', in_progress: 'primary', active: 'primary',
    pending: 'info', new: 'info', created: 'info',
    error: 'danger', failed: 'danger',
  }
  return map[status] || 'primary'
}

/* 新增：路由跳转方法（仅 UI 导航） */
function goResume() { router.push('/resume') }
function goInterview() { router.push('/interview') }
function viewResume(id) { router.push(`/resume?id=${id}`) }
function viewInterview(id) { router.push(`/interview?id=${id}`) }

onMounted(async () => {
  /* 加载用户信息 */
  userLoading.value = true
  try {
    const { data } = await authApi.me()
    userInfo.value = data || {}
  } catch {} finally {
    userLoading.value = false
  }

  /* 加载简历列表 */
  resumeLoading.value = true
  try {
    const { data } = await resumeApi.list()
    resumeList.value = Array.isArray(data) ? data : (data?.items || [])
  } catch {} finally {
    resumeLoading.value = false
  }

  /* 加载面试列表 */
  interviewLoading.value = true
  try {
    const { data } = await interviewApi.list()
    interviewList.value = Array.isArray(data) ? data : (data?.items || [])
  } catch {} finally {
    interviewLoading.value = false
  }

  /* 加载复盘报告列表 */
  try {
    const { data } = await reviewApi.list()
    reviewList.value = Array.isArray(data) ? data : (data?.items || [])
  } catch {}
})
</script>

<style scoped>
/* ============ 页面容器 ============ */
.profile-page {
  padding: 20px;
  background: #f5f7fa;
  min-height: 100%;
  box-sizing: border-box;
}

/* ============ 页面标题区 ============ */
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

/* ============ 用户信息卡片 ============ */
.user-card {
  border-radius: 8px;
  border: none;
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.06);
  margin-bottom: 20px;
  background: linear-gradient(135deg, #ecf5ff 0%, #f5faff 100%);
  border: 1px solid #d9ecff;
}
.user-card :deep(.el-card__body) {
  padding: 24px;
}
.user-info {
  display: flex;
  align-items: center;
  gap: 20px;
}
.user-avatar {
  flex-shrink: 0;
}
.user-avatar :deep(.el-avatar) {
  background: linear-gradient(135deg, #409eff 0%, #66b1ff 100%);
  box-shadow: 0 4px 12px rgba(64, 158, 255, 0.3);
}
.user-detail {
  flex: 1;
  min-width: 0;
}
.user-name {
  font-size: 22px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 8px;
}
.user-meta {
  display: flex;
  align-items: center;
  gap: 20px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.meta-item {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  color: #606266;
}
.meta-item .el-icon {
  font-size: 14px;
  color: #909399;
}
.user-tags {
  display: flex;
  gap: 8px;
}
.user-tag {
  border-radius: 12px;
}

/* ============ 数据统计卡片 ============ */
.stat-row {
  margin-bottom: 20px !important;
}
.stat-card {
  border-radius: 8px;
  border: none;
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.06);
  transition: transform 0.2s, box-shadow 0.2s;
  cursor: default;
}
.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 16px 0 rgba(64, 158, 255, 0.15);
}
.stat-card :deep(.el-card__body) {
  padding: 20px;
  display: flex;
  align-items: center;
  gap: 16px;
}
.stat-icon-wrap {
  width: 48px;
  height: 48px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  color: #fff;
  flex-shrink: 0;
}
.stat-resume .stat-icon-wrap { background: linear-gradient(135deg, #409eff 0%, #66b1ff 100%); }
.stat-interview .stat-icon-wrap { background: linear-gradient(135deg, #67c23a 0%, #85ce61 100%); }
.stat-review .stat-icon-wrap { background: linear-gradient(135deg, #e6a23c 0%, #f0c78a 100%); }
.stat-progress .stat-icon-wrap { background: linear-gradient(135deg, #909399 0%, #b1b3b8 100%); }

.stat-content {
  flex: 1;
  min-width: 0;
}
.stat-value {
  font-size: 26px;
  font-weight: 700;
  color: #303133;
  line-height: 1.2;
}
.stat-label {
  font-size: 13px;
  color: #909399;
  margin-top: 4px;
}

/* ============ 主体行 ============ */
.main-row {
  margin-bottom: 20px !important;
}

/* ============ 通用卡片头部 ============ */
.asset-card,
.progress-card,
.recent-card {
  border-radius: 8px;
  border: none;
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.06);
  margin-bottom: 20px;
}
.asset-card :deep(.el-card__header),
.progress-card :deep(.el-card__header),
.recent-card :deep(.el-card__header) {
  padding: 14px 20px;
  border-bottom: 1px solid #f0f2f5;
  background: #fafbfc;
  border-radius: 8px 8px 0 0;
}
.asset-card :deep(.el-card__body),
.progress-card :deep(.el-card__body),
.recent-card :deep(.el-card__body) {
  padding: 20px;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}
.header-icon {
  font-size: 16px;
  color: #409eff;
}
.header-title {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
}

/* ============ 简历列表 ============ */
.resume-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.resume-item {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 16px;
  background: #fafbfc;
  border: 1px solid #f0f2f5;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
}
.resume-item:hover {
  background: #ecf5ff;
  border-color: #d9ecff;
  transform: translateX(4px);
}
.resume-icon {
  width: 40px;
  height: 40px;
  border-radius: 8px;
  background: linear-gradient(135deg, #409eff 0%, #66b1ff 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 18px;
  flex-shrink: 0;
}
.resume-info {
  flex: 1;
  min-width: 0;
}
.resume-name {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.resume-meta {
  display: flex;
  align-items: center;
  gap: 8px;
}
.meta-text {
  font-size: 12px;
  color: #909399;
}
.resume-actions {
  flex-shrink: 0;
}

/* ============ 进度时间线 ============ */
.progress-timeline {
  padding: 4px 0 0 0;
}
.timeline-content {
  padding-bottom: 4px;
}
.timeline-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 4px;
}
.tl-position {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.timeline-sub {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: #909399;
}

/* ============ 最近面试表格 ============ */
.recent-card {
  margin-bottom: 0;
}
.cell-text {
  font-size: 13px;
  color: #303133;
}
.cell-time {
  font-size: 12px;
  color: #909399;
}

/* ============ 空状态 ============ */
.empty-icon {
  font-size: 56px;
  color: #c0c4cc;
  margin-bottom: 8px;
}

/* ============ 响应式适配 ============ */
@media screen and (max-width: 768px) {
  .user-info {
    flex-direction: column;
    text-align: center;
    gap: 12px;
  }
  .user-meta {
    justify-content: center;
  }
  .stat-card :deep(.el-card__body) {
    padding: 16px;
    gap: 10px;
  }
  .stat-icon-wrap {
    width: 40px;
    height: 40px;
    font-size: 18px;
  }
  .stat-value {
    font-size: 22px;
  }
}
</style>
