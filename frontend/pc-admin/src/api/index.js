import request from '../utils/request.js'

// 复用统一封装的 axios 实例（含 token 注入与 401 拦截）
const api = request

// ---- API 方法 ----
export const authApi = {
  login: (data) => api.post('/api/auth/login', data),
  register: (data) => api.post('/api/auth/register', data),
  me: () => api.get('/api/auth/me'),
}

export const companyApi = {
  list: (params) => api.get('/api/companies/', { params }),
  get: (id) => api.get(`/api/companies/${id}`),
  create: (data) => api.post('/api/companies/', data),
  update: (id, data) => api.put(`/api/companies/${id}`, data),
  delete: (id) => api.delete(`/api/companies/${id}`),
  smartSearch: (data) => api.post('/api/companies/smart-search', data),
}

export const resumeApi = {
  list: () => api.get('/api/resume/'),
  get: (id) => api.get(`/api/resume/${id}`),
  create: (data) => api.post('/api/resume/', data),
  update: (id, data) => api.put(`/api/resume/${id}`, data),
  delete: (id) => api.delete(`/api/resume/${id}`),
  optimize: (data) => api.post('/api/resume/optimize', data),
  analyze: (data) => api.post('/api/resume/analyze', data),
}

export const interviewApi = {
  // 修复：路径补齐尾斜杠，避免 FastAPI 307 重定向导致 Authorization header 丢失 → 403
  start: (data) => api.post('/api/interview/', data),
  list: () => api.get('/api/interview/'),
  get: (id) => api.get(`/api/interview/${id}`),
  chat: (id, data) => api.post(`/api/interview/${id}/chat`, data),
  command: (id, data) => api.post(`/api/interview/${id}/command`, data),
}

export const reviewApi = {
  get: (id) => api.get(`/api/review/${id}`),
  generate: (id) => api.post(`/api/review/${id}/generate`),
  list: () => api.get('/api/review/'),
  delete: (id) => api.delete(`/api/review/${id}`),
  // 新增：获取面试对话历史
  getConversation: (id) => api.get(`/api/review/${id}/conversation`),
}

/* 新增：智能问答接口（RAG 语义检索） */
export const retrieverApi = {
  qa: (data) => api.post('/api/retrieve/qa', data),
}

export default api
