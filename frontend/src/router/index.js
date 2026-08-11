import { createRouter, createWebHistory } from 'vue-router'
import { getCurrentUser, isAuthenticated } from '../utils/auth.js'
import { applyRouteSeo } from '../utils/seo'

const routes = [
  {
    path: '/',
    name: 'Home',
    component: () => import(/* webpackChunkName: "home" */ '../views/Home.vue'),
    meta: {
      requiresGuest: true,
      seo: {
        title: '清大物理考古題與歷屆考題｜PhysArchive',
        description: '清大物理考古系統整理清華大學物理相關課程的歷屆考題、解答與課程資訊。',
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
        title: '清大物理考古題課程目錄｜PhysArchive',
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
        title: '清大物理課程考古題｜PhysArchive',
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
        title: '考古題資料庫｜PhysArchive',
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
        title: '管理後台｜PhysArchive',
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
        title: '個人化設定｜PhysArchive',
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
        title: '登入處理中｜PhysArchive',
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
        title: '找不到頁面｜PhysArchive',
        description: '此頁面不存在或已被移除。',
        robots: 'noindex, nofollow',
      },
    },
  },
]

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

router.afterEach((to) => {
  applyRouteSeo(to)
})

export default router
