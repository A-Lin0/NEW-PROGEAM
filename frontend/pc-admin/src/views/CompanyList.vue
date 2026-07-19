<template>
  <div class="company-list">
    <!-- ============ 新增：页面标题区 ============ -->
    <div class="page-title-bar">
      <div class="title-left">
        <el-icon class="title-icon"><OfficeBuilding /></el-icon>
        <div>
          <h2 class="page-title">公司信息</h2>
          <p class="page-subtitle">浏览与管理目标求职公司信息</p>
        </div>
      </div>
      <!-- 新增：仅管理员可见添加公司按钮 -->
      <el-button v-if="isAdmin" type="primary" :icon="Plus" @click="openCreate">添加公司</el-button>
    </div>

    <!-- ============ 新增：统计卡片栅格 ============ -->
    <el-row :gutter="20" class="stat-row">
      <el-col :xs="24" :sm="12" :md="8">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-content">
            <el-icon class="stat-icon blue"><OfficeBuilding /></el-icon>
            <div class="stat-info">
              <div class="stat-value">{{ companies.length }}</div>
              <div class="stat-label">公司总数</div>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="12" :md="8">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-content">
            <el-icon class="stat-icon green"><DataAnalysis /></el-icon>
            <div class="stat-info">
              <div class="stat-value">{{ industryCount }}</div>
              <div class="stat-label">覆盖行业</div>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="12" :md="8">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-content">
            <el-icon class="stat-icon orange"><Star /></el-icon>
            <div class="stat-info">
              <div class="stat-value">{{ avgDifficulty }}</div>
              <div class="stat-label">平均面试难度</div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- ============ 搜索 & 表格卡片 ============ -->
    <el-card shadow="never" class="table-card">
      <!-- 搜索模式切换 -->
      <div class="search-mode-bar">
        <el-radio-group v-model="searchMode" size="small" @change="onModeChange">
          <el-radio-button value="keyword">
            <el-icon><Search /></el-icon>
            关键词搜索
          </el-radio-button>
          <el-radio-button value="qa">
            <el-icon><ChatDotSquare /></el-icon>
            智能问答
          </el-radio-button>
        </el-radio-group>
      </div>

      <!-- 搜索栏 -->
      <div class="search-bar">
        <el-input
          v-model="keyword"
          :placeholder="searchMode === 'qa' ? '输入自然语言问题，如：北京有哪些面试难度低的互联网公司...' : '搜索公司名称、行业...'"
          clearable
          class="search-input"
          @keyup.enter="onSearch"
          @clear="onSearch"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
          <template v-if="searchMode === 'qa'" #append>
            <el-button
              :icon="searchMode === 'qa' ? ChatDotSquare : Search"
              :loading="qaLoading"
              @click="submitQA"
            >
              提问
            </el-button>
          </template>
        </el-input>
        <el-button
          v-if="searchMode === 'keyword'"
          type="primary"
          :icon="Search"
          @click="search"
        >
          查询
        </el-button>
        <el-button
          v-else
          type="primary"
          :icon="ChatDotSquare"
          :loading="qaLoading"
          @click="submitQA"
        >
          提问
        </el-button>
      </div>

      <!-- 表格 -->
      <el-table
        :data="pagedData"
        v-loading="loading"
        stripe
        style="width: 100%"
        :empty-text="'暂无公司数据，点击右上角添加公司'"
      >
        <el-table-column prop="name" label="公司名称" min-width="180">
          <template #default="{ row }">
            <div class="company-cell">
              <el-avatar :size="34" class="company-avatar">{{ row.name?.charAt(0) }}</el-avatar>
              <span class="company-name-text">{{ row.name }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="industry" label="行业" width="120">
          <template #default="{ row }">
            <el-tag v-if="row.industry" type="info" effect="light" round>{{ row.industry }}</el-tag>
            <span v-else class="empty-text">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="size" label="规模" width="120">
          <template #default="{ row }">
            <span>{{ row.size || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="location" label="地点" width="120">
          <template #default="{ row }">
            <span>{{ row.location || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="avg_difficulty" label="面试难度" width="180">
          <template #default="{ row }">
            <!-- 新增：统一浅蓝配色 -->
            <el-rate
              v-model="row.avg_difficulty"
              disabled
              show-score
              :colors="['#a0cfff', '#409EFF', '#1f7ae0']"
              text-color="#409EFF"
            />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button size="small" :icon="View" @click="$router.push(`/companies/${row.id}`)">详情</el-button>
            <!-- 新增：编辑/删除仅管理员可见，普通用户只读 -->
            <el-button v-if="isAdmin" size="small" type="primary" :icon="Edit" @click="editCompany(row)">编辑</el-button>
            <el-popconfirm v-if="isAdmin" title="确认删除吗？" @confirm="handleDelete(row.id)">
              <template #reference>
                <el-button size="small" type="danger" :icon="Delete">删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>

      <!-- 新增：分页 -->
      <div class="pagination-bar">
        <el-pagination
          :current-page="currentPage"
          :page-size="pageSize"
          :page-sizes="[10, 20, 50]"
          :total="companies.length"
          layout="total, sizes, prev, pager, next, jumper"
          background
          @current-change="onPageChange"
          @size-change="onSizeChange"
        />
      </div>

      <!-- 新增：智能问答结果面板 -->
      <div v-if="searchMode === 'qa' && qaResult !== null" class="qa-panel">
        <el-divider />
        <div class="qa-header">
          <el-icon class="qa-icon"><ChatDotSquare /></el-icon>
          <span class="qa-title">AI 回答</span>
          <el-tag v-if="qaLoading" type="warning" size="small" effect="light">
            <el-icon class="is-loading"><Loading /></el-icon>思考中...
          </el-tag>
        </div>

        <!-- 答案内容 -->
        <div class="qa-answer">
          <div class="qa-answer-text" v-html="qaAnswerHtml"></div>
        </div>

        <!-- 空结果提示 -->
        <el-empty
          v-if="!qaResult.data?.has_result && !qaLoading"
          description="暂无相关数据，请尝试其他问题"
          :image-size="80"
        />

        <!-- 关联公司 -->
        <div
          v-if="qaResult.data?.related_companies?.length"
          class="qa-related"
        >
          <div class="qa-related-title">
            <el-icon><OfficeBuilding /></el-icon>
            关联公司（{{ qaResult.data.related_companies.length }}）
          </div>
          <div class="qa-related-list">
            <div
              v-for="(rc, idx) in qaResult.data.related_companies"
              :key="idx"
              class="qa-company-card"
              @click="goDetail(rc)"
            >
              <el-avatar :size="28" class="qa-company-avatar">{{ rc.name?.charAt(0) }}</el-avatar>
              <div class="qa-company-info">
                <span class="qa-company-name">{{ rc.name }}</span>
                <span v-if="rc.industry" class="qa-company-meta">{{ rc.industry }} · {{ rc.location }}</span>
              </div>
              <el-tag v-if="rc.relevance" size="small" effect="plain" round>{{ rc.relevance }}</el-tag>
            </div>
          </div>
        </div>
      </div>
    </el-card>

    <!-- ============ 添加/编辑弹窗（表单双列排版）============ -->
    <el-dialog
      v-model="showDialog"
      :title="editing ? '编辑公司' : '添加公司'"
      width="640px"
      align-center
      class="company-dialog"
    >
      <el-form :model="form" label-width="100px" size="large">
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="公司名称" required>
              <el-input v-model="form.name" placeholder="请输入公司名称" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="行业">
              <el-input v-model="form.industry" placeholder="请输入行业" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="规模">
              <el-select v-model="form.size" placeholder="请选择规模" style="width:100%">
                <el-option label="1-50人" value="1-50人" />
                <el-option label="50-200人" value="50-200人" />
                <el-option label="200-500人" value="200-500人" />
                <el-option label="500-2000人" value="500-2000人" />
                <el-option label="2000人以上" value="2000人以上" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="地点">
              <el-input v-model="form.location" placeholder="请输入地点" />
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item label="网站">
              <el-input v-model="form.website" placeholder="请输入公司网站" />
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item label="公司简介">
              <el-input v-model="form.description" type="textarea" :rows="3" placeholder="请输入公司简介" />
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item label="企业文化">
              <el-input v-model="form.culture" type="textarea" :rows="2" placeholder="请输入企业文化" />
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item label="福利待遇">
              <el-input v-model="form.benefits" type="textarea" :rows="2" placeholder="请输入福利待遇" />
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item label="面试流程">
              <el-input v-model="form.interview_process" type="textarea" :rows="2" placeholder="请输入面试流程" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="面试难度">
              <el-rate
                v-model="form.avg_difficulty"
                show-score
                :colors="['#a0cfff', '#409EFF', '#1f7ae0']"
                text-color="#409EFF"
              />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
      <template #footer>
        <el-button @click="showDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
/* 新增：Element Plus 图标 */
import {
  Search, Plus, Edit, Delete, View,
  OfficeBuilding, DataAnalysis, Star,
  ChatDotSquare, Loading,
} from '@element-plus/icons-vue'
/* 新增：API 引入 */
import { retrieverApi } from '../api/index.js'

const router = useRouter()

const keyword = ref('')
const companies = ref([])
const loading = ref(false)
const showDialog = ref(false)
const editing = ref(null)
/* 新增：管理员角色判断（控制增删改按钮显隐，普通用户只读） */
const isAdmin = computed(() => localStorage.getItem('role') === 'admin')
/* 新增：分页与保存状态 */
const currentPage = ref(1)
const pageSize = ref(10)
const saving = ref(false)

/* 新增：搜索模式 & 智能问答状态 */
const searchMode = ref('keyword')  // 'keyword' | 'qa'
const qaLoading = ref(false)
const qaResult = ref(null)         // { code, message, data: { answer, related_companies, has_result } }
const qaAnswerHtml = computed(() => {
  if (!qaResult.value?.data?.answer) return ''
  // 简单 Markdown 转换：换行 → <br>，**加粗** → <strong>
  return qaResult.value.data.answer
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br>')
})

/* 新增：统计计算属性 */
const industryCount = computed(() => {
  const set = new Set(companies.value.filter(c => c.industry).map(c => c.industry))
  return set.size
})
const avgDifficulty = computed(() => {
  if (!companies.value.length) return '0.0'
  const sum = companies.value.reduce((s, c) => s + (c.avg_difficulty || 0), 0)
  return (sum / companies.value.length).toFixed(1)
})
/* 新增：前端分页数据 */
const pagedData = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return companies.value.slice(start, start + pageSize.value)
})
/* 新增：分页组件事件回调（替代 v-model 双向绑定，避免 IDE 误报） */
function onPageChange(page) {
  currentPage.value = page
}
function onSizeChange(size) {
  pageSize.value = size
  currentPage.value = 1
}

const form = reactive({
  name: '', industry: '', size: '', location: '',
  website: '', description: '', culture: '',
  benefits: '', interview_process: '', avg_difficulty: 3,
})

/* 新增：从本地权威数据源 companies.json 加载初始数据，并合并 localStorage 中管理员的增删改记录 */
async function loadAll() {
  const res = await fetch('/data/companies.json')
  const base = await res.json()
  // 读取 localStorage 中管理员的修改（覆盖、新增、删除）
  const overrides = JSON.parse(localStorage.getItem('company_overrides') || '{}')
  const added = JSON.parse(localStorage.getItem('company_added') || '[]')
  const deleted = JSON.parse(localStorage.getItem('company_deleted') || '[]')
  // 合并：基础数据应用覆盖、排除删除，再拼接新增数据
  return base
    .filter(c => !deleted.includes(c.id))
    .map(c => ({ ...c, ...(overrides[c.id] || {}) }))
    .concat(added.filter(c => !deleted.includes(c.id)))
}

async function search() {
  loading.value = true
  try {
    // 权威数据源：以 frontend/pc-admin/public/data/companies.json 为准，合并 localStorage 增删改
    const all = await loadAll()
    // 前端按关键词过滤（公司名称、行业、地点）
    const kw = keyword.value.trim()
    const filtered = kw
      ? all.filter(c =>
          (c.name && c.name.includes(kw)) ||
          (c.industry && c.industry.includes(kw)) ||
          (c.location && c.location.includes(kw))
        )
      : all
    companies.value = filtered
    currentPage.value = 1
  } catch (e) {
    ElMessage.error('加载公司数据失败')
  } finally {
    loading.value = false
  }
}

/* 新增：打开添加弹窗前重置表单 */
function openCreate() {
  editing.value = null
  resetForm()
  showDialog.value = true
}

function editCompany(row) {
  editing.value = row.id
  Object.assign(form, row)
  showDialog.value = true
}

/* 修复：管理员增删改写入 localStorage 持久化，与列表数据源一致（避免后端 API 数据不同步） */
function handleSave() {
  saving.value = true
  try {
    if (editing.value) {
      // 编辑：写入覆盖记录
      const overrides = JSON.parse(localStorage.getItem('company_overrides') || '{}')
      overrides[editing.value] = { ...form }
      localStorage.setItem('company_overrides', JSON.stringify(overrides))
      ElMessage.success('更新成功')
    } else {
      // 新增：追加到 added 列表
      const added = JSON.parse(localStorage.getItem('company_added') || '[]')
      added.push({
        ...form,
        id: 'local_' + Date.now(),
      })
      localStorage.setItem('company_added', JSON.stringify(added))
      ElMessage.success('添加成功')
    }
    showDialog.value = false
    editing.value = null
    resetForm()
    search()
  } catch (e) {
    ElMessage.error('保存失败')
  } finally {
    saving.value = false
  }
}

function handleDelete(id) {
  const deleted = JSON.parse(localStorage.getItem('company_deleted') || '[]')
  if (!deleted.includes(id)) {
    deleted.push(id)
    localStorage.setItem('company_deleted', JSON.stringify(deleted))
  }
  ElMessage.success('删除成功')
  search()
}

/* 新增：搜索模式切换 */
function onModeChange(mode) {
  if (mode === 'keyword') {
    qaResult.value = null
  }
}

/* 新增：统一搜索入口（关键词搜索或智能问答，根据当前模式分发） */
function onSearch() {
  if (searchMode.value === 'keyword') {
    search()
  } else {
    submitQA()
  }
}

/* 新增：智能问答 */
async function submitQA() {
  const query = keyword.value.trim()
  if (!query) {
    ElMessage.warning('请输入问题')
    return
  }
  qaLoading.value = true
  qaResult.value = null
  try {
    const res = await retrieverApi.qa({ query })
    qaResult.value = res.data
    if (res.data.code !== 0) {
      ElMessage.error(res.data.message || '问答失败')
    }
  } catch (e) {
    ElMessage.error('问答请求失败，请稍后重试')
    qaResult.value = { code: 500, message: '请求失败', data: { answer: '', related_companies: [], has_result: false } }
  } finally {
    qaLoading.value = false
  }
}

/* 新增：点击关联公司跳转详情 */
function goDetail(company) {
  if (company.id) {
    router.push(`/companies/${company.id}`)
  } else if (company.name) {
    // 无 ID 时，尝试从本地列表匹配
    const found = companies.value.find(c => c.name === company.name)
    if (found) {
      router.push(`/companies/${found.id}`)
    }
  }
}

function resetForm() {
  Object.assign(form, {
    name: '', industry: '', size: '', location: '',
    website: '', description: '', culture: '',
    benefits: '', interview_process: '', avg_difficulty: 3,
  })
}

onMounted(() => { search() })
</script>

<style scoped>
/* ============================================================
   新增美化样式：求职商务浅蓝主题
   ============================================================ */

.company-list {
  padding: 20px;
  max-width: 1600px;
  margin: 0 auto;
}

/* ---------- 页面标题区 ---------- */
.page-title-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.title-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.title-icon {
  font-size: 32px;
  color: #409EFF;
  background: #ecf5ff;
  padding: 8px;
  border-radius: 8px;
}

.page-title {
  font-size: 20px;
  font-weight: 600;
  color: #303133;
  margin: 0 0 4px;
}

.page-subtitle {
  font-size: 13px;
  color: #909399;
  margin: 0;
}

/* ---------- 统计卡片 ---------- */
.stat-row {
  margin-bottom: 20px;
}

.stat-card {
  border-radius: 8px;
  border: none;
  box-shadow: 0 2px 12px rgba(64, 158, 255, 0.06);
  margin-bottom: 12px;
}

.stat-content {
  display: flex;
  align-items: center;
  gap: 16px;
}

.stat-icon {
  font-size: 24px;
  padding: 12px;
  border-radius: 8px;
}

.stat-icon.blue { color: #409EFF; background: #ecf5ff; }
.stat-icon.green { color: #67c23a; background: #f0f9eb; }
.stat-icon.orange { color: #e6a23c; background: #fdf6ec; }

.stat-value {
  font-size: 24px;
  font-weight: 700;
  color: #303133;
  line-height: 1.2;
}

.stat-label {
  font-size: 13px;
  color: #909399;
  margin-top: 4px;
}

/* ---------- 表格卡片 ---------- */
.table-card {
  border-radius: 8px;
  border: none;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.04);
}

.search-bar {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}

.search-input {
  width: 320px;
}

/* ---------- 表格交互：hover 高亮 ---------- */
:deep(.el-table) {
  border-radius: 6px;
  overflow: hidden;
}

:deep(.el-table th.el-table__cell) {
  background: #f5f7fa;
  color: #303133;
  font-weight: 600;
}

:deep(.el-table__row:hover > td) {
  background: #ecf5ff !important;
}

/* ---------- 公司单元格 ---------- */
.company-cell {
  display: flex;
  align-items: center;
  gap: 10px;
}

.company-avatar {
  background: #409EFF;
  color: #ffffff;
  font-size: 14px;
  font-weight: 600;
  flex-shrink: 0;
}

.company-name-text {
  font-weight: 500;
  color: #303133;
}

.empty-text {
  color: #c0c4cc;
}

/* ---------- 操作列按钮间距 ---------- */
:deep(.el-table .el-button + .el-button) {
  margin-left: 8px;
}

/* ---------- 分页 ---------- */
.pagination-bar {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid #f0f0f0;
}

/* ---------- 弹窗 ---------- */
.company-dialog :deep(.el-dialog) {
  border-radius: 8px;
  overflow: hidden;
}

.company-dialog :deep(.el-dialog__header) {
  background: #f5f7fa;
  margin: 0;
  padding: 18px 24px;
  border-bottom: 1px solid #ebeef5;
}

.company-dialog :deep(.el-dialog__body) {
  padding: 24px;
}

.company-dialog :deep(.el-input__wrapper),
.company-dialog :deep(.el-textarea__inner) {
  border-radius: 6px;
}

.company-dialog :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px #409EFF inset;
}

.company-dialog :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px #409EFF inset, 0 2px 8px rgba(64, 158, 255, 0.15);
}

/* ---------- 响应式 ---------- */
@media (max-width: 768px) {
  .search-bar {
    flex-direction: column;
  }
  .search-input {
    width: 100%;
  }
}

/* ============================================================
   新增：智能问答面板样式（求职商务浅蓝主题）
   ============================================================ */

/* 搜索模式切换 */
.search-mode-bar {
  margin-bottom: 12px;
}
.search-mode-bar :deep(.el-radio-button__inner) {
  border-radius: 6px;
  font-size: 13px;
}

/* Q&A 结果面板 */
.qa-panel {
  margin-top: 8px;
}

.qa-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
}
.qa-icon {
  font-size: 20px;
  color: #409EFF;
}
.qa-title {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
}

/* 答案内容 */
.qa-answer {
  padding: 16px 20px;
  background: #f5f7fa;
  border-radius: 8px;
  border-left: 3px solid #409EFF;
  margin-bottom: 16px;
  line-height: 1.8;
}
.qa-answer-text {
  font-size: 14px;
  color: #303133;
  word-break: break-word;
}
.qa-answer-text :deep(strong) {
  color: #1f7ae0;
  font-weight: 600;
}

/* 关联公司 */
.qa-related {
  margin-top: 8px;
}
.qa-related-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid #ebeef5;
}
.qa-related-title .el-icon {
  color: #409EFF;
}
.qa-related-list {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
.qa-company-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  background: #fff;
  min-width: 220px;
}
.qa-company-card:hover {
  border-color: #409EFF;
  background: #ecf5ff;
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.12);
}
.qa-company-avatar {
  background: #409EFF;
  color: #fff;
  font-size: 12px;
  flex-shrink: 0;
}
.qa-company-info {
  flex: 1;
  min-width: 0;
}
.qa-company-name {
  display: block;
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.qa-company-meta {
  display: block;
  font-size: 12px;
  color: #909399;
  margin-top: 2px;
}
</style>
