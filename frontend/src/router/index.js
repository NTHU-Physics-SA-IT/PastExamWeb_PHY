import { createRouter, createWebHistory } from 'vue-router'
import { getCurrentUser, isAuthenticated } from '../utils/auth.js'
import { applyRouteSeo, DEFAULT_DESCRIPTION } from '../utils/seo'
import { i18n } from '../i18n'

const routes = [
  {
    path: '/',
    name: 'Home',
    component: () => import(/* webpackChunkName: "home" */ '../views/Home.vue'),
    meta: {
      requiresGuest: true,
      seo: {
        title: '清大物理考古系統',
        description: DEFAULT_DESCRIPTION,
        canonicalPath: '/',
        robots: 'index, follow',
      },
    },
  },
  {
    path: '/courses',
    name: 'PublicCourses',
    component: () => import(/* webpackChunkName: "public-courses" */ '../views/PublicCourses.vue'),
    meta: {
      seo: {
        title: '清大物理考古題課程目錄',
        description: '瀏覽清大物理相關課程已公開收錄的歷屆考題資訊。',
        canonicalPath: '/courses',
        robots: 'index, follow',
      },
    },
  },
  {
    path: '/courses/:courseId',
    name: 'PublicCourse',
    component: () => import(/* webpackChunkName: "public-course" */ '../views/PublicCourse.vue'),
    meta: {
      seo: {
        title: '清大物理課程考古題',
        description: '查看課程的公開考古題學年度、授課教師、考試類型與解答資訊。',
        robots: 'noindex, follow',
      },
    },
  },
  {
    path: '/archive',
    name: 'Archive',
    component: () => import(/* webpackChunkName: "archive" */ '../views/Archive.vue'),
    meta: {
      requiresAuth: true,
      seo: {
        title: '考古題資料庫',
        canonicalPath: '/archive',
        robots: 'noindex, nofollow',
      },
    },
  },
  {
    path: '/admin',
    name: 'Admin',
    component: () => import(/* webpackChunkName: "admin" */ '../views/Admin.vue'),
    meta: {
      requiresAuth: true,
      requiresAdmin: true,
      seo: {
        title: '管理後台',
        canonicalPath: '/admin',
        robots: 'noindex, nofollow',
      },
    },
  },
  {
    path: '/personal-settings',
    name: 'PersonalSettings',
    component: () =>
      import(/* webpackChunkName: "personal-settings" */ '../views/PersonalSettings.vue'),
    meta: {
      requiresAuth: true,
      seo: {
        title: '個人化設定',
        canonicalPath: '/personal-settings',
        robots: 'noindex, nofollow',
      },
    },
  },
  {
    path: '/login/callback',
    name: 'LoginCallback',
    component: () => import(/* webpackChunkName: "login-callback" */ '../views/LoginCallback.vue'),
    meta: {
      requiresGuest: true,
      seo: {
        title: '登入處理中',
        canonicalPath: '/login/callback',
        robots: 'noindex, nofollow',
      },
    },
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    component: () => import(/* webpackChunkName: "not-found" */ '../views/NotFound.vue'),
    meta: {
      seo: {
        title: '找不到頁面',
        description: '此頁面不存在或已被移除。',
        robots: 'noindex, nofollow',
      },
    },
  },
]

if (import.meta.env.DEV && import.meta.env.VITE_NTHU_DEV_MOCK_ENABLED === 'true') {
  routes.splice(routes.length - 1, 0, {
    path: '/dev/nthu-login',
    name: 'NthuDevLogin',
    component: () => import('../views/NthuDevLogin.vue'),
    meta: {
      requiresGuest: true,
      seo: {
        title: 'NTHU OAuth Local QA',
        canonicalPath: '/dev/nthu-login',
        robots: 'noindex, nofollow',
      },
    },
  })
}

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to, from, next) => {
  const isLoggedIn = isAuthenticated()
  const currentUser = getCurrentUser()

  if (to.meta.requiresAuth && !isLoggedIn) {
    next({ name: 'Home' })
  } else if (to.meta.requiresGuest && isLoggedIn) {
    next({ name: 'Archive' })
  } else if (to.meta.requiresAdmin && (!currentUser || !currentUser.is_admin)) {
    next({ name: 'Archive' })
  } else {
    next()
  }
})

const applyLocalizedRouteSeo = (route) => {
  const seo = route.meta?.seo
  applyRouteSeo(
    seo
      ? {
          ...route,
          meta: {
            ...route.meta,
            seo: {
              ...seo,
              title: seo.title ? i18n.global.t(seo.title) : seo.title,
              description: seo.description ? i18n.global.t(seo.description) : seo.description,
            },
          },
        }
      : route
  )
}

router.afterEach(applyLocalizedRouteSeo)

if (typeof window !== 'undefined') {
  window.addEventListener('pastexam:locale-changed', () =>
    applyLocalizedRouteSeo(router.currentRoute.value)
  )
}

export default router
