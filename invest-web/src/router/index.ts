/**
 * 路由：登录页公开，其余挂在 AppLayout 下并受 token 门禁（S10 AC-1）。
 * 页面均懒加载；meta.title 供顶栏与浏览器标题使用，meta.group 决定侧边栏分组。
 */
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { hasToken } from '@/api/config'
import { onUnauthorized } from '@/api/client'
import AppLayout from '@/layouts/AppLayout.vue'

export interface NavItem {
  path: string
  title: string
  group: '资产' | '交易' | '研究' | '记录' | '系统'
  icon: string
}

/** 侧边栏菜单（顺序即展示顺序）；标的详情为钻取页，不进菜单 */
export const NAV: NavItem[] = [
  { path: '/', title: '总览', group: '资产', icon: 'Odometer' },
  { path: '/summary', title: '统计', group: '资产', icon: 'TrendCharts' },
  { path: '/annual', title: '年度复盘', group: '资产', icon: 'Calendar' },
  { path: '/trades', title: '流水', group: '交易', icon: 'Tickets' },
  { path: '/instruments', title: '标的管理', group: '交易', icon: 'Collection' },
  { path: '/ocr', title: '截图识别', group: '交易', icon: 'Picture' },
  { path: '/signals', title: '信号', group: '研究', icon: 'Bell' },
  { path: '/valuation', title: '指数估值', group: '研究', icon: 'DataLine' },
  { path: '/backtest', title: '策略回测', group: '研究', icon: 'Histogram' },
  { path: '/report', title: '周报', group: '研究', icon: 'Document' },
  { path: '/diary', title: '投资日记', group: '记录', icon: 'EditPen' },
  { path: '/settings', title: '设置', group: '系统', icon: 'Setting' },
]

const routes: RouteRecordRaw[] = [
  { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue'), meta: { public: true, title: '登录' } },
  {
    path: '/',
    component: AppLayout,
    children: [
      { path: '', name: 'overview', component: () => import('@/views/OverviewView.vue'), meta: { title: '总览' } },
      { path: 'instrument/:id', name: 'instrument', component: () => import('@/views/InstrumentView.vue'), meta: { title: '标的详情' } },
      { path: 'instrument-preview/:code', name: 'instrument-preview', component: () => import('@/views/InstrumentPreview.vue'), meta: { title: '标的预览' } },
      { path: 'trades', name: 'trades', component: () => import('@/views/TradesView.vue'), meta: { title: '流水' } },
      { path: 'summary', name: 'summary', component: () => import('@/views/SummaryView.vue'), meta: { title: '统计' } },
      { path: 'signals', name: 'signals', component: () => import('@/views/SignalsView.vue'), meta: { title: '信号' } },
      { path: 'backtest', name: 'backtest', component: () => import('@/views/BacktestView.vue'), meta: { title: '策略回测' } },
      { path: 'report', name: 'report', component: () => import('@/views/ReportView.vue'), meta: { title: '周报' } },
      { path: 'valuation', name: 'valuation', component: () => import('@/views/ValuationView.vue'), meta: { title: '指数估值' } },
      { path: 'diary', name: 'diary', component: () => import('@/views/DiaryView.vue'), meta: { title: '投资日记' } },
      { path: 'annual', name: 'annual', component: () => import('@/views/AnnualView.vue'), meta: { title: '年度复盘' } },
      { path: 'instruments', name: 'instruments', component: () => import('@/views/InstrumentsView.vue'), meta: { title: '标的管理' } },
      { path: 'ocr', name: 'ocr', component: () => import('@/views/OcrView.vue'), meta: { title: '截图识别' } },
      { path: 'settings', name: 'settings', component: () => import('@/views/SettingsView.vue'), meta: { title: '设置' } },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

router.beforeEach((to) => {
  if (!to.meta.public && !hasToken()) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  // 注意：有 token 时也放行到 /login——LoginView onMounted 会清除旧凭据，
  // 让用户以干净状态登录（切账号场景）。如果在这里重定向回 /，旧 token
  // 永远不会被清除，导致「登录 A 却看到 B 数据」的残留会话 bug
  // （2026-11-09 实证：路由守卫先于组件挂载执行，LoginView 的 clearToken
  //   因提前重定向而永远不会运行）
  return true
})

router.afterEach((to) => {
  document.title = `${(to.meta.title as string) || 'invest'} · invest 个人投研台`
})

// 任意请求 401：client 已清 token，这里带回跳地址送回登录页
onUnauthorized(() => {
  const current = router.currentRoute.value
  if (current.name !== 'login') {
    router.replace({ name: 'login', query: { redirect: current.fullPath, expired: '1' } })
  }
})
