<template>
  <div class="resume-optimize">
    <h2>AI 简历优化</h2>

    <el-row :gutter="20">
      <el-col :span="14">
        <el-card>
          <template #header>
            <div class="card-header">
              <span>编辑简历</span>
              <div>
                <el-select v-model="sectionType" style="width:160px;margin-right:8px">
                  <el-option label="个人总结" value="summary" />
                  <el-option label="教育背景" value="education" />
                  <el-option label="工作经历" value="experience" />
                  <el-option label="实习经历" value="internship" />
                  <el-option label="项目经历" value="project" />
                  <el-option label="专业技能" value="skills" />
                  <el-option label="自我评价" value="evaluation" />
                  <el-option label="荣誉奖项" value="awards" />
                  <el-option label="作品集链接" value="portfolio" />
                </el-select>
                <el-button type="primary" :loading="optimizing" @click="handleOptimize">
                  智能优化
                </el-button>
                <el-button :loading="analyzing" @click="handleAnalyze">全面分析</el-button>
              </div>
            </div>
          </template>
          <el-input
            v-model="content"
            type="textarea"
            :rows="16"
            :placeholder="contentPlaceholder"
          />
        </el-card>

        <el-card style="margin-top:16px">
          <template #header><span>目标公司与岗位（可选）</span></template>
          <!-- 新增：目标公司改为可搜索下拉选择，直连公司知识库 -->
          <el-select
            v-model="targetCompany"
            filterable
            clearable
            placeholder="搜索并选择目标公司（可从公司详情带入）"
            class="target-select"
            @change="onCompanyChange"
          >
            <el-option
              v-for="c in companyList"
              :key="c.id"
              :label="c.name"
              :value="c.id"
            >
              <div class="company-option">
                <span class="company-option-name">{{ c.name }}</span>
                <el-tag size="small" effect="plain" round>{{ c.industry }}</el-tag>
              </div>
            </el-option>
          </el-select>
          <!-- 新增：目标岗位联动公司预设岗位，支持自定义输入 -->
          <el-select
            v-model="targetPosition"
            filterable
            allow-create
            clearable
            :disabled="!targetCompany"
            placeholder="选择岗位（支持自定义输入）"
            class="target-select"
            @change="onPositionChange"
          >
            <el-option
              v-for="pos in availablePositions"
              :key="pos.name"
              :label="pos.name"
              :value="pos.name"
            >
              <span>{{ pos.name }}</span>
              <span class="position-dept">{{ pos.department }}</span>
            </el-option>
          </el-select>
          <el-input
            v-model="jobDescription"
            type="textarea"
            :rows="4"
            placeholder="粘贴目标岗位的 JD，AI 将根据岗位要求进行针对性优化..."
          />
        </el-card>
      </el-col>

      <el-col :span="10">
        <el-card>
          <template #header>
            <div class="card-header">
              <span>AI 建议</span>
              <div v-if="aiResult">
                <el-button size="small" :icon="DocumentCopy" @click="copyResult">复制</el-button>
                <el-button size="small" type="primary" :icon="Collection" :loading="saving" @click="saveToLibrary">保存到简历库</el-button>
              </div>
            </div>
          </template>
          <div class="ai-output" ref="outputRef">
            <div v-if="aiResult">
              <p v-for="(line, i) in aiResult.split('\n')" :key="i">{{ line }}</p>
            </div>
            <el-empty v-else description="点击「智能优化」或「全面分析」开始" />
          </div>
          <div v-if="aiResult" class="ai-actions">
            <el-button type="success" plain :icon="ChatLineRound" @click="goInterview">用此简历去模拟面试</el-button>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { resumeApi } from '../api/index.js'
import { ElMessage } from 'element-plus'
import { DocumentCopy, Collection, ChatLineRound } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()

const content = ref('')
const sectionType = ref('experience')
const jobDescription = ref('')
/* 新增：根据所选简历模块动态切换输入框提示文案 */
const contentPlaceholder = computed(() => {
  const map = {
    summary: '请输入个人总结，如：5年前端开发经验，擅长 Vue/React，主导过多个大型项目落地...',
    education: '请输入教育背景，如：2018-2022 XX大学 计算机科学与技术 本科 GPA 3.8/4.0...',
    experience: '请输入工作经历，如：2022至今 XX公司 前端开发工程师，负责 XX 项目，使用 Vue3 + TypeScript 重构...',
    internship: '请输入实习经历，如：2021年 XX公司 前端实习生，参与 XX 项目的页面开发与 bug 修复...',
    project: '请输入项目经历，如：智能面试辅导系统 - 基于 Vue3 + FastAPI 开发，负责前端架构搭建与核心组件实现...',
    skills: '请输入专业技能，如：熟练掌握 HTML/CSS/JavaScript，熟悉 Vue3/React，了解 Node.js，熟练使用 Git...',
    evaluation: '请输入自我评价，如：学习能力强，具备良好的沟通能力与团队协作精神，对技术有持续热情...',
    awards: '请输入荣誉奖项，如：2021年 校级一等奖学金；2022年 ACM 程序设计竞赛省级二等奖...',
    portfolio: '请输入作品集链接，如：GitHub：https://github.com/xxx；个人博客：https://xxx.com；掘金主页：...',
  }
  return map[sectionType.value] || '请在此输入需要优化的简历内容...'
})
const aiResult = ref('')
const optimizing = ref(false)
const analyzing = ref(false)
const saving = ref(false)

/* ============ 新增：公司知识库联动 ============ */
const companyList = ref([])  // 全量公司数据
const targetCompany = ref('')  // 选中的公司 ID（原为文本输入，现改为下拉选择）
const targetPosition = ref('')

/* 新增：当前选中公司的完整数据 */
const selectedCompany = computed(() => {
  return companyList.value.find(c => c.id === targetCompany.value) || null
})

/* 新增：当前公司的预设岗位列表 */
const availablePositions = computed(() => {
  if (!selectedCompany.value?.positions) return []
  return selectedCompany.value.positions
})

/* 新增：公司切换时自动带出岗位并预填充 JD */
function onCompanyChange(companyId) {
  // 清空岗位
  targetPosition.value = ''
  // 自动填充 JD 基础信息
  if (companyId) {
    const company = companyList.value.find(c => c.id === companyId)
    if (company) {
      const parts = []
      if (company.description) parts.push(`【公司简介】${company.description}`)
      if (company.culture) parts.push(`【企业文化】${company.culture}`)
      if (company.benefits) parts.push(`【薪资福利】${company.benefits}`)
      if (company.interview_process) parts.push(`【面试流程】${company.interview_process}`)
      jobDescription.value = parts.join('\n\n')
    }
  } else {
    jobDescription.value = ''
  }
}

/* 新增：岗位切换时更新 JD 中的岗位要求 */
function onPositionChange(positionName) {
  if (!positionName || !selectedCompany.value) return
  const pos = selectedCompany.value.positions?.find(p => p.name === positionName)
  if (pos) {
    const base = jobDescription.value || ''
    const posInfo = `\n\n【目标岗位】${pos.name}（${pos.department}）\n【任职要求】${pos.requirement}\n【参考薪资】${pos.salary}`
    // 避免重复追加
    if (!base.includes(pos.name)) {
      jobDescription.value = base + posInfo
    }
  }
}

/* 从公司详情页跳转携带参数时自动填充 */
onMounted(async () => {
  // 加载公司知识库
  try {
    const res = await fetch('/data/companies.json')
    companyList.value = await res.json()
  } catch {}
  // 路由参数自动填充
  if (route.query.company_id) {
    targetCompany.value = route.query.company_id
    onCompanyChange(route.query.company_id)
  } else if (route.query.company_name) {
    const matched = companyList.value.find(c => c.name === route.query.company_name)
    if (matched) {
      targetCompany.value = matched.id
      onCompanyChange(matched.id)
    }
  }
  if (route.query.default_position) {
    targetPosition.value = route.query.default_position
    onPositionChange(route.query.default_position)
  }
})

/* SSE 流式请求统一封装：使用相对路径走 Vite 代理 */
async function streamRequest(url, payload) {
  return fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${localStorage.getItem('token')}`,
    },
    body: JSON.stringify(payload),
  })
}

/* 解析 SSE 流，逐字累加到 aiResult */
async function parseStream(response) {
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let full = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    const text = decoder.decode(value)
    for (const line of text.split('\n')) {
      if (line.startsWith('data: ')) {
        const data = line.slice(6)
        if (data === '[DONE]') return full
        try {
          const json = JSON.parse(data)
          full += json.content || ''
          aiResult.value = full
        } catch {}
      }
    }
  }
  return full
}

async function handleOptimize() {
  if (!content.value.trim()) {
    ElMessage.warning('请先输入简历内容')
    return
  }
  optimizing.value = true
  aiResult.value = ''
  try {
    const response = await streamRequest('/api/resume/optimize', {
      content: content.value,
      section_type: sectionType.value,
      job_description: jobDescription.value,
      /* 新增：透传公司与岗位上下文，供后端 Agent 定制化优化 */
      company_id: targetCompany.value || null,
      target_position: targetPosition.value || null,
    })
    await parseStream(response)
    ElMessage.success('优化完成')
  } catch (e) {
    ElMessage.error('优化请求失败')
  } finally {
    optimizing.value = false
  }
}

async function handleAnalyze() {
  if (!content.value.trim()) {
    ElMessage.warning('请先输入简历内容')
    return
  }
  analyzing.value = true
  aiResult.value = ''
  try {
    const response = await streamRequest('/api/resume/analyze', {
      content: content.value,
      section_type: 'full',
      job_description: jobDescription.value,
      /* 新增：透传公司与岗位上下文，供后端 Agent 定制化分析 */
      company_id: targetCompany.value || null,
      target_position: targetPosition.value || null,
    })
    await parseStream(response)
    ElMessage.success('分析完成')
  } catch (e) {
    ElMessage.error('分析请求失败')
  } finally {
    analyzing.value = false
  }
}

/* 复制优化结果 */
async function copyResult() {
  try {
    await navigator.clipboard.writeText(aiResult.value)
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.error('复制失败')
  }
}

/* 保存到我的简历库 */
async function saveToLibrary() {
  saving.value = true
  try {
    await resumeApi.create({
      title: targetPosition.value ? `${targetPosition.value}-简历` : 'AI优化简历',
      raw_text: content.value,
      summary: aiResult.value,
      target_company: selectedCompany.value?.name || targetCompany.value || null,
      target_position: targetPosition.value || null,
    })
    ElMessage.success('已保存到简历库')
  } catch (e) {
    // 错误提示已由响应拦截器统一处理
  } finally {
    saving.value = false
  }
}

/* 用当前简历去模拟面试 */
function goInterview() {
  router.push({
    path: '/interview',
    query: {
      company_id: targetCompany.value || undefined,
      company_name: selectedCompany.value?.name || undefined,
      position: targetPosition.value || undefined,
    },
  })
}
</script>

<style scoped>
.resume-optimize { padding: 20px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.ai-output {
  min-height: 400px;
  max-height: 600px;
  overflow-y: auto;
  white-space: pre-wrap;
  line-height: 1.8;
  padding: 12px;
  background: #f8f9fa;
  border-radius: 8px;
  font-size: 14px;
}
.ai-actions {
  margin-top: 12px;
  text-align: center;
}

/* ============ 新增：目标公司/岗位下拉选择样式 ============ */
.target-select {
  width: 100%;
  margin-bottom: 12px;
}
.company-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}
.company-option-name {
  font-size: 14px;
  color: #303133;
}
.position-dept {
  color: #909399;
  font-size: 12px;
  margin-left: 8px;
}
</style>
