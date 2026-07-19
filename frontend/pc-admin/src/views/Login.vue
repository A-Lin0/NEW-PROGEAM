<template>
  <div class="login-container">
    <!-- ============ 新增：左侧品牌展示区（求职向商务浅蓝主题） ============ -->
    <div class="login-brand">
      <div class="brand-inner">
        <div class="brand-logo">
          <el-icon :size="40"><Promotion /></el-icon>
          <span class="brand-name">AI 面试辅导系统</span>
        </div>
        <h1 class="brand-title">求职路上<br />每一步都更稳妥</h1>
        <p class="brand-desc">公司信息速览 · 简历智能优化 · 模拟面试演练 · 复盘评分报告</p>
        <ul class="brand-features">
          <li><el-icon><Check /></el-icon> 覆盖主流公司信息与面经</li>
          <li><el-icon><Check /></el-icon> AI 简历润色与 ATS 诊断</li>
          <li><el-icon><Check /></el-icon> 结构化面试模拟与复盘</li>
        </ul>
      </div>
      <div class="brand-footer">© 2026 AI 面试辅导系统 · 助力求职</div>
    </div>

    <!-- ============ 右侧登录/注册表单区 ============ -->
    <div class="login-panel">
      <el-card class="login-card" shadow="always">
        <div class="card-header">
          <h2 class="title">欢迎登录</h2>
          <p class="subtitle">请选择身份并使用账号登录系统</p>
        </div>

        <!-- ===== 新增：用户/管理员身份切换选项卡 ===== -->
        <el-tabs v-model="loginType" class="login-tabs">
          <el-tab-pane label="用户登录" name="user" />
          <el-tab-pane label="管理员登录" name="admin" />
        </el-tabs>

        <!-- ===== 以下为原有业务表单结构，仅新增 icon 前缀与 class ===== -->
        <el-form :model="form" :rules="rules" ref="formRef" label-width="0" size="large">
          <el-form-item prop="username">
            <el-input v-model="form.username" :placeholder="loginType === 'admin' ? '管理员账号' : '用户名'" clearable>
              <template #prefix><el-icon><User /></el-icon></template>
            </el-input>
          </el-form-item>
          <el-form-item prop="password">
            <el-input
              v-model="form.password"
              type="password"
              placeholder="密码"
              show-password
              @keyup.enter="handleLogin"
            >
              <template #prefix><el-icon><Lock /></el-icon></template>
            </el-input>
          </el-form-item>
          <el-form-item>
            <el-button
              type="primary"
              size="large"
              :loading="loading"
              class="submit-btn"
              @click="handleLogin"
            >
              {{ loginType === 'admin' ? '管理员登录' : '登 录' }}
            </el-button>
          </el-form-item>
          <!-- 管理员不开放注册入口，仅用户登录显示注册提示 -->
          <p v-if="loginType === 'user'" class="tip">
            还没有账号？<el-button type="primary" link @click="showRegister = true">立即注册</el-button>
          </p>
          <p v-else class="tip admin-tip">
            <el-icon><InfoFilled /></el-icon> 管理员账号由系统开发者预置，不开放注册
          </p>
        </el-form>
      </el-card>
    </div>

    <!-- ============ 注册弹窗（视觉升级：圆角、间距、icon 前缀） ============ -->
    <el-dialog
      v-model="showRegister"
      title="用户注册"
      width="440px"
      align-center
      class="register-dialog"
    >
      <el-form :model="regForm" :rules="regRules" ref="regFormRef" label-width="80px" size="large">
        <el-form-item label="用户名" prop="username">
          <el-input v-model="regForm.username" placeholder="请输入用户名" clearable>
            <template #prefix><el-icon><User /></el-icon></template>
          </el-input>
        </el-form-item>
        <el-form-item label="邮箱" prop="email">
          <el-input v-model="regForm.email" placeholder="请输入邮箱" clearable>
            <template #prefix><el-icon><Message /></el-icon></template>
          </el-input>
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input v-model="regForm.password" type="password" placeholder="至少6位密码" show-password>
            <template #prefix><el-icon><Lock /></el-icon></template>
          </el-input>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showRegister = false">取消</el-button>
        <el-button type="primary" :loading="regLoading" @click="handleRegister">注册</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { authApi } from '../api/index.js'
import { ElMessage } from 'element-plus'
/* 新增：Element Plus 图标组件 */
import { User, Lock, Message, Promotion, Check, InfoFilled } from '@element-plus/icons-vue'

const router = useRouter()
const formRef = ref(null)
const regFormRef = ref(null)
const loading = ref(false)
const regLoading = ref(false)
const showRegister = ref(false)

/* 新增：登录身份切换（用户 / 管理员） */
const loginType = ref('user')

const form = reactive({ username: '', password: '' })
const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

const regForm = reactive({ username: '', email: '', password: '' })
const regRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 2, max: 50, message: '长度在 2 到 50 个字符', trigger: 'blur' },
    {
      pattern: /^[\u4e00-\u9fa5a-zA-Z0-9_-]+$/,
      message: '仅支持中文、字母、数字、下划线和连字符',
      trigger: 'blur',
    },
  ],
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '请输入正确的邮箱', trigger: 'blur' },
  ],
  password: [{ required: true, min: 6, message: '至少6位密码', trigger: 'blur' }],
}

/* 新增：加载前端用户/管理员数据文件（public/data/users.json） */
async function loadUsersData() {
  const res = await fetch('/data/users.json')
  return res.json()
}

/* 新增：写入登录态（统一 token、username、role） */
function setLoginState(username, role, token) {
  localStorage.setItem('token', token)
  localStorage.setItem('username', username)
  localStorage.setItem('role', role)
}

/* 新增：同步后端鉴权，获取真实 JWT
 * 修复：本地 users.json 登录写入的伪 token 无法通过后端 JWT 鉴权，
 * 导致 /api/interview 等接口 401。本地校验通过后，自动向后端注册（若不存在）并登录，
 * 拿到后端签发的标准 JWT，替换伪 token。
 */
async function syncBackendAuth(account) {
  // 后端 register 要求 password ≥ 6 位，不足则补齐（仅用于后端同步，不影响前端校验）
  const backendPwd = account.password.length < 6
    ? account.password.padEnd(6, '0')
    : account.password
  // 1. 先尝试登录（账号已存在于后端时直接命中）
  try {
    const { data } = await authApi.login({ username: account.username, password: backendPwd })
    return data.access_token
  } catch (e) {
    if (e.response?.status !== 401) throw e
  }
  // 2. 登录失败（账号不存在）→ 注册后再登录
  try {
    await authApi.register({
      username: account.username,
      email: account.email,
      password: backendPwd,
    })
  } catch (e) {
    // 注册失败：若为用户名/邮箱已存在则忽略，继续登录；其他错误抛出
    if (e.response?.status !== 400) throw e
  }
  const { data } = await authApi.login({ username: account.username, password: backendPwd })
  return data.access_token
}

async function handleLogin() {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  loading.value = true
  try {
    const userData = await loadUsersData()

    if (loginType.value === 'admin') {
      // 管理员登录：仅校验前端预置 admins 数据（不开放注册）
      const admin = userData.admins.find(
        (a) => a.username === form.username && a.password === form.password
      )
      if (!admin) {
        ElMessage.error('管理员账号或密码错误')
        loading.value = false
        return
      }
      // 同步后端拿真实 JWT（管理员账号同步注册到后端，role 仍以前端为准）
      let token
      try {
        token = await syncBackendAuth(admin)
      } catch (e) {
        // 后端不可用时降级为伪 token，保证公司浏览等只读功能可用
        token = 'admin_' + Date.now()
        ElMessage.warning('后端服务连接失败，面试功能暂不可用')
      }
      setLoginState(admin.username, 'admin', token)
      ElMessage.success('管理员登录成功')
      router.push('/companies')
    } else {
      // 用户登录：先匹配前端预置用户，不匹配则 fallback 后端 API（保留原有流程）
      const localUser = userData.users.find(
        (u) => u.username === form.username && u.password === form.password
      )
      if (localUser) {
        // 同步后端拿真实 JWT，确保面试等接口鉴权通过
        let token
        try {
          token = await syncBackendAuth(localUser)
        } catch (e) {
          token = 'user_' + Date.now()
          ElMessage.warning('后端服务连接失败，面试功能暂不可用')
        }
        setLoginState(localUser.username, 'user', token)
        ElMessage.success('登录成功')
        router.push('/companies')
        return
      }
      // fallback：后端 API 鉴权（原有流程，不破坏）
      const { data } = await authApi.login(form)
      setLoginState(data.user.username, 'user', data.access_token)
      ElMessage.success('登录成功')
      router.push('/companies')
    }
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '登录失败')
  } finally {
    loading.value = false
  }
}

async function handleRegister() {
  const valid = await regFormRef.value.validate().catch(() => false)
  if (!valid) return
  regLoading.value = true
  try {
    await authApi.register(regForm)
    ElMessage.success('注册成功，请登录')
    showRegister.value = false
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '注册失败')
  } finally {
    regLoading.value = false
  }
}
</script>

<style scoped>
/* ============================================================
   新增美化样式：求职向商务浅蓝主题
   主色 #409EFF，圆角 8px，柔和阴影
   ============================================================ */

.login-container {
  display: flex;
  justify-content: stretch;
  align-items: stretch;
  min-height: 100vh;
  background: #f5f7fa;
}

/* ---------- 左侧品牌区 ---------- */
.login-brand {
  flex: 1 1 55%;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: 56px 64px;
  background: linear-gradient(135deg, #409EFF 0%, #1f7ae0 60%, #0f5fb8 100%);
  color: #ffffff;
  position: relative;
  overflow: hidden;
}

.login-brand::before {
  content: '';
  position: absolute;
  top: -120px;
  right: -120px;
  width: 360px;
  height: 360px;
  background: rgba(255, 255, 255, 0.08);
  border-radius: 50%;
}

.login-brand::after {
  content: '';
  position: absolute;
  bottom: -160px;
  left: -100px;
  width: 320px;
  height: 320px;
  background: rgba(255, 255, 255, 0.06);
  border-radius: 50%;
}

.brand-inner {
  position: relative;
  z-index: 1;
  margin-top: 40px;
}

.brand-logo {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 20px;
  font-weight: 600;
}

.brand-name {
  letter-spacing: 1px;
}

.brand-title {
  font-size: 40px;
  font-weight: 700;
  line-height: 1.3;
  margin: 56px 0 20px;
  letter-spacing: 1px;
}

.brand-desc {
  font-size: 15px;
  line-height: 1.8;
  color: rgba(255, 255, 255, 0.85);
  margin-bottom: 36px;
  max-width: 420px;
}

.brand-features {
  list-style: none;
  padding: 0;
  margin: 0;
}

.brand-features li {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 14px;
  padding: 10px 0;
  color: rgba(255, 255, 255, 0.92);
}

.brand-features .el-icon {
  background: rgba(255, 255, 255, 0.2);
  border-radius: 50%;
  padding: 3px;
  font-size: 12px;
}

.brand-footer {
  position: relative;
  z-index: 1;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.6);
}

/* ---------- 右侧表单区 ---------- */
.login-panel {
  flex: 1 1 45%;
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 24px;
  background: #ffffff;
}

.login-card {
  width: 100%;
  max-width: 400px;
  border-radius: 8px;
  border: none;
  box-shadow: 0 4px 24px rgba(64, 158, 255, 0.08);
  padding: 32px 28px;
}

.card-header {
  margin-bottom: 20px;
}

/* 新增：身份切换选项卡样式 */
.login-tabs {
  margin-bottom: 8px;
}
.login-tabs :deep(.el-tabs__header) {
  margin: 0 0 16px;
}
.login-tabs :deep(.el-tabs__item) {
  font-size: 15px;
  height: 42px;
  line-height: 42px;
}
.login-tabs :deep(.el-tabs__item.is-active) {
  color: #409EFF;
}
.login-tabs :deep(.el-tabs__active-bar) {
  background: #409EFF;
}

/* 管理员提示文案 */
.admin-tip {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  color: #909399;
}

.title {
  font-size: 24px;
  font-weight: 600;
  color: #303133;
  margin: 0 0 8px;
}

.subtitle {
  font-size: 13px;
  color: #909399;
  margin: 0;
}

/* ---------- 表单交互：hover/focus 反馈 ---------- */
:deep(.el-input__wrapper) {
  border-radius: 6px;
  padding: 4px 12px;
  transition: all 0.2s ease;
}

:deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px #409EFF inset;
}

:deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px #409EFF inset, 0 2px 8px rgba(64, 158, 255, 0.15);
}

:deep(.el-input__prefix) {
  color: #909399;
  margin-right: 4px;
}

/* ---------- 提交按钮（替代无效的 block 属性） ---------- */
.submit-btn {
  width: 100%;
  border-radius: 6px;
  font-size: 15px;
  letter-spacing: 4px;
  transition: all 0.2s ease;
}

.submit-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(64, 158, 255, 0.3);
}

/* ---------- 底部提示 ---------- */
.tip {
  text-align: center;
  font-size: 13px;
  color: #909399;
  margin: 8px 0 0;
}

/* ---------- 注册弹窗统一风格 ---------- */
.register-dialog :deep(.el-dialog) {
  border-radius: 8px;
  overflow: hidden;
}

.register-dialog :deep(.el-dialog__header) {
  background: #f5f7fa;
  margin: 0;
  padding: 18px 24px;
  border-bottom: 1px solid #ebeef5;
}

.register-dialog :deep(.el-dialog__title) {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

.register-dialog :deep(.el-dialog__body) {
  padding: 28px 24px 8px;
}

.register-dialog :deep(.el-dialog__footer) {
  padding: 12px 24px 20px;
}

.register-dialog :deep(.el-button--primary) {
  border-radius: 6px;
}

/* ---------- 响应式：窄屏隐藏品牌区，保留居中登录 ---------- */
@media (max-width: 992px) {
  .login-brand {
    display: none;
  }
  .login-panel {
    flex: 1 1 100%;
    background: linear-gradient(135deg, #f5f7fa 0%, #e8f1ff 100%);
  }
}
</style>
