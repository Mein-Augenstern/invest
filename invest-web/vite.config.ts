import { fileURLToPath, URL } from 'node:url'
import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发期 /api 代理目标：默认 ECS 自托管后端（token 门禁，登录页输入）；
// 本机联调可设 INVEST_DEV_API=http://127.0.0.1:8790
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = env.INVEST_DEV_API || 'http://47.92.235.34'
  return {
    plugins: [vue()],
    define: {
      // API 基址经 define 注入（import.meta.env 的可选链访问不被可靠内联，
      // 2026-11-08 实证：产物含值但运行时取空 → 登录打到静态站 405）
      __API_BASE__: JSON.stringify(env.VITE_API_BASE || process.env.VITE_API_BASE || ''),
    },
    resolve: {
      alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
    },
    server: {
      port: 5175,
      proxy: {
        '/api': { target, changeOrigin: true },
      },
    },
    build: {
      chunkSizeWarningLimit: 1500,
      rollupOptions: {
        output: {
          // 大依赖单独分包，业务代码变更不使其缓存失效
          manualChunks: {
            echarts: ['echarts'],
            'element-plus': ['element-plus', '@element-plus/icons-vue'],
            vue: ['vue', 'vue-router', 'pinia'],
          },
        },
      },
    },
    test: {
      environment: 'jsdom',
      include: ['tests/**/*.spec.ts'],
    },
  }
})
