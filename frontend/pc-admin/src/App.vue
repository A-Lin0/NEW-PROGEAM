<template>
  <div id="app">
    <el-container>
      <el-header v-if="isLoggedIn" class="app-header">
        <el-menu
          :default-active="activeMenu"
          mode="horizontal"
          router
          class="header-menu"
        >
          <div class="logo">🤖 AI 面试辅导</div>
          <el-menu-item index="/companies">公司信息</el-menu-item>
          <el-menu-item index="/resume">简历优化</el-menu-item>
          <el-menu-item index="/interview">面试模拟</el-menu-item>
          <el-menu-item index="/report">面试复盘</el-menu-item>
          <!-- 新增：用户管理入口，仅管理员可见 -->
          <el-menu-item v-if="isAdmin" index="/users">用户管理</el-menu-item>
          <div class="header-right">
            <el-tag v-if="isAdmin" type="danger" size="small" effect="dark" round>管理员</el-tag>
            <el-button text size="small" @click="goProfile">
              <el-icon><User /></el-icon>
              <span class="username">{{ username }}</span>
            </el-button>
            <el-button type="danger" size="small" @click="logout">退出</el-button>
          </div>
        </el-menu>
      </el-header>
      <el-main>
        <router-view />
      </el-main>
    </el-container>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { User } from '@element-plus/icons-vue'

const router = useRouter()
const route = useRoute()

const isLoggedIn = ref(false)
const username = ref('用户')
/* 新增：管理员角色判断，控制导航与页面权限 */
const isAdmin = ref(false)
const activeMenu = computed(() => route.path)

/* 新增：路由变化时同步登录态与角色（localStorage 非响应式，需手动同步） */
function syncAuthState() {
  isLoggedIn.value = !!localStorage.getItem('token')
  username.value = localStorage.getItem('username') || '用户'
  isAdmin.value = localStorage.getItem('role') === 'admin'
}
syncAuthState()
watch(() => route.path, syncAuthState)

function goProfile() {
  router.push('/profile')
}

function logout() {
  localStorage.removeItem('token')
  localStorage.removeItem('username')
  localStorage.removeItem('role')
  syncAuthState()
  router.push('/login')
}
</script>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif; }

.app-header {
  padding: 0;
  box-shadow: 0 2px 8px rgba(0,0,0,0.1);
  position: sticky;
  top: 0;
  z-index: 100;
}

.header-menu {
  display: flex;
  align-items: center;
}

.logo {
  font-size: 18px;
  font-weight: bold;
  padding: 0 20px;
  color: #409eff;
  white-space: nowrap;
}

.header-right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 12px;
  padding-right: 20px;
}

.username { color: #666; font-size: 14px; }
</style>
