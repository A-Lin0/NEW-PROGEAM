import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 说明：main.js 已通过 app.use(ElementPlus) 全量注册组件与样式，
//       各 .vue 文件中也已手动 import { ElMessage } from 'element-plus'，
//       因此不再使用 unplugin-auto-import / unplugin-vue-components 按需导入，
//       避免全量注册与按需导入并存导致组件重复解析、属性透传异常
export default defineConfig({
  plugins: [
    vue(),
  ],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
