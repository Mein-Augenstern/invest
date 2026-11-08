<!--
  桌面主框架：左侧分组导航 + 顶栏（页面标题 / 用户下拉）+ 内容区。
-->
<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import * as Icons from '@element-plus/icons-vue'
import { ArrowDown } from '@element-plus/icons-vue'
import { NAV, type NavItem } from '@/router'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const groups = computed(() => {
  const order: NavItem['group'][] = ['资产', '交易', '研究', '记录', '系统']
  return order.map((g) => ({ name: g, items: NAV.filter((n) => n.group === g) }))
})

/** 标的详情是钻取页：高亮回「总览」 */
const activePath = computed(() => (route.name === 'instrument' ? '/' : route.path))
const pageTitle = computed(() => (route.meta.title as string) || '')

function iconOf(name: string) {
  return (Icons as Record<string, unknown>)[name]
}

function onCommand(cmd: string) {
  if (cmd === 'logout') {
    auth.logout()
    router.replace({ name: 'login' })
  } else if (cmd === 'settings') {
    router.push('/settings')
  }
}
</script>

<template>
  <el-container class="layout">
    <el-aside width="216px" class="aside">
      <div class="brand">
        <span class="brand-mark">iv</span>
        <span class="brand-name">invest 投研台</span>
      </div>
      <el-menu :default-active="activePath" router class="menu">
        <template v-for="g in groups" :key="g.name">
          <div class="menu-group">{{ g.name }}</div>
          <el-menu-item v-for="item in g.items" :key="item.path" :index="item.path">
            <el-icon><component :is="iconOf(item.icon)" /></el-icon>
            <span>{{ item.title }}</span>
          </el-menu-item>
        </template>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="topbar">
        <div class="topbar-title">{{ pageTitle }}</div>
        <el-dropdown trigger="click" @command="onCommand">
          <span class="user">
            <el-avatar :size="28" class="user-avatar">{{ (auth.member?.nickname || auth.member?.username || '?')[0] }}</el-avatar>
            <span>{{ auth.member?.nickname || auth.member?.username || '未登录' }}</span>
            <span class="muted user-id">#{{ auth.member?.id ?? '—' }}</span>
            <el-icon><ArrowDown /></el-icon>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="settings">设置</el-dropdown-item>
              <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-header>
      <el-main class="main">
        <router-view v-slot="{ Component }">
          <component :is="Component" :key="route.fullPath" />
        </router-view>
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.layout {
  height: 100vh;
}
.aside {
  background: var(--iv-panel);
  border-right: 1px solid var(--iv-border);
  overflow-y: auto;
}
.brand {
  height: 56px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 20px;
  border-bottom: 1px solid var(--iv-border);
}
.brand-mark {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  background: var(--iv-primary);
  color: #fff;
  display: grid;
  place-items: center;
  font-weight: 700;
  font-size: 13px;
}
.brand-name {
  font-weight: 600;
  font-size: 15px;
}
.menu {
  border-right: none;
  padding: 8px 0;
}
.menu-group {
  padding: 14px 20px 6px;
  font-size: 12px;
  color: var(--iv-text-3);
}
.menu :deep(.el-menu-item) {
  height: 40px;
  line-height: 40px;
  margin: 2px 8px;
  border-radius: 6px;
}
.menu :deep(.el-menu-item.is-active) {
  background: var(--el-color-primary-light-9);
  font-weight: 600;
}
.topbar {
  height: 56px;
  background: var(--iv-panel);
  border-bottom: 1px solid var(--iv-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.topbar-title {
  font-weight: 600;
}
.user {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  color: var(--iv-text-2);
}
.user-avatar {
  background: var(--iv-primary);
}
.user-id {
  font-size: 11px;
  margin-left: -4px;
}
.main {
  padding: 20px 24px 32px;
  overflow-y: auto;
}
</style>
