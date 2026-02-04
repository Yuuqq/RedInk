<template>
  <div id="app" class="app-shell" :class="{ 'nav-open': navOpen }">
    <!-- Top bar (glass) -->
    <header class="app-topbar" role="banner">
      <div class="app-topbar-inner">
        <div class="app-topbar-left">
          <button class="topbar-tool app-topbar-menu" type="button" aria-label="打开菜单" @click="toggleNav">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="3" y1="6" x2="21" y2="6"></line>
              <line x1="3" y1="12" x2="21" y2="12"></line>
              <line x1="3" y1="18" x2="21" y2="18"></line>
            </svg>
          </button>

          <RouterLink to="/" class="app-topbar-brand" aria-label="CSS Lab 首页" @click="closeNav">
            <img class="app-topbar-logo" src="/logo.svg" alt="CSS Lab" />
            <span class="app-topbar-title">CSS Lab</span>
          </RouterLink>
        </div>

        <div class="app-topbar-center" aria-hidden="false">
          <nav class="app-topnav" aria-label="主导航">
            <RouterLink to="/" class="topnav-item" active-class="active">创作</RouterLink>
            <RouterLink to="/history" class="topnav-item" active-class="active">历史</RouterLink>
            <RouterLink to="/settings" class="topnav-item" active-class="active">设置</RouterLink>
            <RouterLink to="/admin" class="topnav-item" active-class="active">管理</RouterLink>
          </nav>
        </div>

        <div class="app-topbar-tools" aria-label="快捷操作">
          <RouterLink class="topbar-tool" to="/settings" aria-label="打开设置" title="设置">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="3"></circle>
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V22a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H2a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V2a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9c0 .66.26 1.3.73 1.77.47.47 1.11.73 1.77.73H22a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
            </svg>
          </RouterLink>
          <RouterLink class="topbar-tool" to="/admin" aria-label="打开管理面板" title="管理">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M12 2l7 4v6c0 5-3 9-7 10-4-1-7-5-7-10V6l7-4z"></path>
              <path d="M12 8v4"></path>
              <path d="M12 16h.01"></path>
            </svg>
          </RouterLink>
        </div>
      </div>
    </header>

    <!-- Backdrop + menu sheet (mobile) -->
    <button
      v-if="navOpen"
      class="app-backdrop"
      type="button"
      aria-label="关闭菜单"
      @click="closeNav"
    />
    <div class="app-drawer" aria-label="主导航（菜单）" :aria-hidden="!navOpen">
      <div class="app-drawer-inner">
        <RouterLink to="/" class="drawer-item" active-class="active" @click="closeNav">创作中心</RouterLink>
        <RouterLink to="/history" class="drawer-item" active-class="active" @click="closeNav">历史记录</RouterLink>
        <RouterLink to="/settings" class="drawer-item" active-class="active" @click="closeNav">系统设置</RouterLink>
        <RouterLink to="/admin" class="drawer-item" active-class="active" @click="closeNav">管理面板</RouterLink>
      </div>
    </div>

    <!-- Main -->
    <main class="app-main" @click="closeNavOnMobile">
      <RouterView v-slot="{ Component, route }">
        <component :is="Component" />

        <footer v-if="route.path !== '/'" class="global-footer">
          <div class="footer-content">
            <div class="footer-text">© 2026 CSS Lab</div>
            <div class="footer-license">
              Licensed under
              <a href="https://creativecommons.org/licenses/by-nc-sa/4.0/" target="_blank" rel="noopener noreferrer">
                CC BY-NC-SA 4.0
              </a>
            </div>
          </div>
        </footer>
      </RouterView>
    </main>
  </div>
</template>

<script setup lang="ts">
import { RouterView, RouterLink } from 'vue-router'
import { onMounted, ref } from 'vue'
import { setupAutoSave } from './stores/generator'

const navOpen = ref(false)

const toggleNav = () => {
  navOpen.value = !navOpen.value
}

const closeNav = () => {
  navOpen.value = false
}

const closeNavOnMobile = () => {
  if (window.matchMedia('(max-width: 900px)').matches) {
    navOpen.value = false
  }
}

// 启用自动保存到 localStorage
onMounted(() => {
  setupAutoSave()
})
</script>
