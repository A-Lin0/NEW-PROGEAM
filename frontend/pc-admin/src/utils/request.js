/**
 * 统一 Axios 请求封装
 * - 请求拦截器：自动携带 Authorization
 * - 响应拦截器：统一错误提示（ElMessage），401 自动清除 token 并跳转登录页
 * 说明：后端直接返回业务数据（无 code/message 外层包装），此处按 HTTP 状态码处理
 */
import axios from 'axios'
import { ElMessage } from 'element-plus'

const request = axios.create({
  // 使用相对路径，由 Vite 代理转发至后端 http://localhost:8000
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

// 请求拦截：注入 token
request.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

// 响应拦截：统一错误处理
request.interceptors.response.use(
  (response) => response,
  (error) => {
    // 优先使用后端返回的 detail 文案
    const detail = error.response?.data?.detail
    const status = error.response?.status

    if (status === 401) {
      // token 失效：清除并跳转登录
      localStorage.removeItem('token')
      localStorage.removeItem('username')
      ElMessage.error(detail || '登录已过期，请重新登录')
      // 避免在登录页重复跳转
      if (window.location.pathname !== '/login') {
        window.location.href = '/login'
      }
    } else if (status === 422) {
      // 参数校验错误：展示后端 detail
      const msg = Array.isArray(detail)
        ? detail.map((d) => d.msg || JSON.stringify(d)).join('；')
        : detail || '请求参数有误'
      ElMessage.error(msg)
    } else if (status && status >= 400) {
      ElMessage.error(detail || `请求失败（${status}）`)
    } else {
      ElMessage.error(error.message || '网络异常')
    }
    return Promise.reject(error)
  }
)

export default request
