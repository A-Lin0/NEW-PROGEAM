import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    redirect: '/companies',
  },
  {
    path: '/login',
    name: 'Login',
    component: () => import('../views/Login.vue'),
    meta: { title: '登录' },
  },
  {
    path: '/companies',
    name: 'CompanyList',
    component: () => import('../views/CompanyList.vue'),
    meta: { title: '公司信息', requiresAuth: true },
  },
  {
    path: '/companies/:id',
    name: 'CompanyDetail',
    component: () => import('../views/CompanyDetail.vue'),
    meta: { title: '公司详情', requiresAuth: true },
  },
  {
    path: '/resume',
    name: 'ResumeOptimize',
    component: () => import('../views/ResumeOptimize.vue'),
    meta: { title: '简历优化', requiresAuth: true },
  },
  {
    path: '/interview',
    name: 'InterviewSim',
    component: () => import('../views/InterviewSim.vue'),
    meta: { title: '面试模拟', requiresAuth: true },
  },
  {
    path: '/report',
    name: 'Report',
    component: () => import('../views/Report.vue'),
    meta: { title: '面试复盘', requiresAuth: true },
  },
  {
    path: '/profile',
    name: 'Profile',
    component: () => import('../views/Profile.vue'),
    meta: { title: '个人中心', requiresAuth: true },
  },
  // 新增：用户管理页面，仅管理员可访问
  {
    path: '/users',
    name: 'UserManage',
    component: () => import('../views/UserManage.vue'),
    meta: { title: '用户管理', requiresAuth: true, requiresAdmin: true },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 导航守卫：新增角色权限校验
router.beforeEach((to, from, next) => {
  document.title = to.meta.title ? `${to.meta.title} - AI面试辅导` : 'AI面试辅导系统'
  const isLoggedIn = !!localStorage.getItem('token')
  const role = localStorage.getItem('role') || 'user'
  // 未登录访问需鉴权页面 -> 登录页
  if (to.meta.requiresAuth && !isLoggedIn) {
    next('/login')
  // 已登录访问登录页 -> 首页
  } else if (to.path === '/login' && isLoggedIn) {
    next('/companies')
  // 越权访问管理员页面 -> 回退到公司列表
  } else if (to.meta.requiresAdmin && role !== 'admin') {
    next('/companies')
  } else {
    next()
  }
})

export default router
