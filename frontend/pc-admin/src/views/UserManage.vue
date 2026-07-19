<template>
  <div class="user-manage">
    <!-- ============ 页面标题区（与公司列表统一风格） ============ -->
    <div class="page-title-bar">
      <div class="title-left">
        <el-icon class="title-icon"><UserFilled /></el-icon>
        <div>
          <h2 class="page-title">用户管理</h2>
          <p class="page-subtitle">查看与编辑已注册用户信息</p>
        </div>
      </div>
      <el-button type="primary" :icon="Plus" @click="openCreate">新增用户</el-button>
    </div>

    <!-- ============ 用户表格 ============ -->
    <el-card shadow="never" class="table-card">
      <el-table :data="pagedData" v-loading="loading" stripe style="width: 100%">
        <el-table-column prop="username" label="用户名" min-width="140">
          <template #default="{ row }">
            <div class="user-cell">
              <el-avatar :size="32" class="user-avatar">{{ row.username?.charAt(0) }}</el-avatar>
              <span>{{ row.username }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="email" label="邮箱" min-width="180" />
        <el-table-column prop="phone" label="手机号" width="140">
          <template #default="{ row }">
            <span>{{ row.phone || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="role" label="角色" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.role === 'admin'" type="danger" effect="dark" round size="small">管理员</el-tag>
            <el-tag v-else type="info" effect="light" round size="small">普通用户</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 'active' ? 'success' : 'warning'" effect="light" round size="small">
              {{ row.status === 'active' ? '正常' : '禁用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="注册时间" width="180" />
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" :icon="Edit" @click="editUser(row)">编辑</el-button>
            <el-popconfirm title="确认删除该用户吗？" @confirm="handleDelete(row.id)">
              <template #reference>
                <el-button size="small" type="danger" :icon="Delete" :disabled="row.role === 'admin'">删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-bar">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :page-sizes="[10, 20, 50]"
          :total="allUsers.length"
          layout="total, sizes, prev, pager, next, jumper"
          background
        />
      </div>
    </el-card>

    <!-- ============ 编辑/新增弹窗 ============ -->
    <el-dialog
      v-model="showDialog"
      :title="editing ? '编辑用户' : '新增用户'"
      width="480px"
      align-center
      class="user-dialog"
    >
      <el-form :model="form" label-width="80px" size="large">
        <el-form-item label="用户名" required>
          <el-input v-model="form.username" placeholder="请输入用户名" :disabled="!!editing" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="form.email" placeholder="请输入邮箱" />
        </el-form-item>
        <el-form-item label="手机号">
          <el-input v-model="form.phone" placeholder="请输入手机号" />
        </el-form-item>
        <el-form-item v-if="!editing" label="密码" required>
          <el-input v-model="form.password" type="password" placeholder="请输入密码" show-password />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="form.role" style="width:100%">
            <el-option label="普通用户" value="user" />
            <el-option label="管理员" value="admin" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="form.status" style="width:100%">
            <el-option label="正常" value="active" />
            <el-option label="禁用" value="disabled" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showDialog = false">取消</el-button>
        <el-button type="primary" @click="handleSave">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { UserFilled, Plus, Edit, Delete } from '@element-plus/icons-vue'

const allUsers = ref([])
const loading = ref(false)
const showDialog = ref(false)
const editing = ref(null)
const currentPage = ref(1)
const pageSize = ref(10)

/* 新增：前端分页 */
const pagedData = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return allUsers.value.slice(start, start + pageSize.value)
})

const form = reactive({
  username: '', email: '', phone: '', password: '',
  role: 'user', status: 'active',
})

/* 新增：从 public/data/users.json 加载用户数据，并与 localStorage 修改合并 */
async function loadUsers() {
  loading.value = true
  try {
    const res = await fetch('/data/users.json')
    const data = await res.json()
    // 读取 localStorage 中的修改（管理员编辑后的数据）
    const localOverrides = JSON.parse(localStorage.getItem('user_overrides') || '{}')
    const localAdded = JSON.parse(localStorage.getItem('user_added') || '[]')
    const localDeleted = JSON.parse(localStorage.getItem('user_deleted') || '[]')

    const admins = data.admins.map((a) => ({
      ...a,
      ...(localOverrides[a.id] || {}),
    }))
    const users = data.users
      .filter((u) => !localDeleted.includes(u.id))
      .map((u) => ({ ...u, ...(localOverrides[u.id] || {}) }))
      .concat(localAdded.filter((a) => !localDeleted.includes(a.id)))

    allUsers.value = [...admins, ...users]
  } catch (e) {
    ElMessage.error('加载用户数据失败')
  } finally {
    loading.value = false
  }
}

function resetForm() {
  Object.assign(form, {
    username: '', email: '', phone: '', password: '',
    role: 'user', status: 'active',
  })
}

function openCreate() {
  editing.value = null
  resetForm()
  showDialog.value = true
}

function editUser(row) {
  editing.value = row.id
  Object.assign(form, {
    username: row.username,
    email: row.email,
    phone: row.phone,
    password: '',
    role: row.role,
    status: row.status,
  })
  showDialog.value = true
}

/* 新增：保存用户（写入 localStorage 持久化） */
function handleSave() {
  if (!form.username) {
    ElMessage.warning('请输入用户名')
    return
  }
  const overrides = JSON.parse(localStorage.getItem('user_overrides') || '{}')
  if (editing.value) {
    // 编辑：写入覆盖
    overrides[editing.value] = {
      email: form.email,
      phone: form.phone,
      role: form.role,
      status: form.status,
    }
    localStorage.setItem('user_overrides', JSON.stringify(overrides))
    ElMessage.success('更新成功')
  } else {
    // 新增：追加到 added 列表
    const added = JSON.parse(localStorage.getItem('user_added') || '[]')
    const newId = 'local_' + Date.now()
    added.push({
      id: newId,
      username: form.username,
      password: form.password,
      email: form.email,
      phone: form.phone,
      role: form.role,
      status: form.status,
      created_at: new Date().toLocaleString('zh-CN'),
    })
    localStorage.setItem('user_added', JSON.stringify(added))
    ElMessage.success('添加成功')
  }
  showDialog.value = false
  resetForm()
  loadUsers()
}

/* 新增：删除用户（写入 localStorage deleted 列表，管理员不可删） */
function handleDelete(id) {
  const target = allUsers.value.find((u) => u.id === id)
  if (target && target.role === 'admin') {
    ElMessage.warning('管理员账号不可删除')
    return
  }
  const deleted = JSON.parse(localStorage.getItem('user_deleted') || '[]')
  deleted.push(id)
  localStorage.setItem('user_deleted', JSON.stringify(deleted))
  ElMessage.success('删除成功')
  loadUsers()
}

onMounted(() => { loadUsers() })
</script>

<style scoped>
/* ============================================================
   新增样式：与公司列表统一商务浅蓝风格
   ============================================================ */

.user-manage {
  padding: 20px;
  max-width: 1600px;
  margin: 0 auto;
}

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

.table-card {
  border-radius: 8px;
  border: none;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.04);
}

.user-cell {
  display: flex;
  align-items: center;
  gap: 10px;
}

.user-avatar {
  background: linear-gradient(135deg, #409eff 0%, #66b1ff 100%);
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  flex-shrink: 0;
}

.pagination-bar {
  display: flex;
  justify-content: flex-end;
  margin-top: 20px;
}

.user-dialog :deep(.el-dialog) {
  border-radius: 8px;
  overflow: hidden;
}

.user-dialog :deep(.el-dialog__header) {
  background: #f5f7fa;
  margin: 0;
  padding: 18px 24px;
  border-bottom: 1px solid #ebeef5;
}
</style>
