import { createRouter, createWebHistory } from 'vue-router'
import { decodeToken, getCurrentUser, isAuthenticated, setToken } from '../utils/auth.js'
import { STORAGE_KEYS, removeSessionItem } from '../utils/storage'
import { applyRouteSeo } from '../utils/seo'

const routes = [
  {
    path: '/',
    name: 'Home',
    component: () =>
      import(
        /* webpackChunkName: "home" */
        '../views/Home.vue'
      ),
    meta: {
      requiresGuest: true,
      seo: {
        title:
          '清大考古題｜清大物理系歷屆考題與解答｜PhysArchive',
        description:
          '清大物理考古題整理平台，收錄普通物理、電磁學、理論力學、量子物理等課程的歷屆考題、解答與課程資料。',
        canonicalPath: '/',
        robots: 'index, follow',
      },
    },
  },
  {
    path: '/courses',
    name: 'PublicCourses',
    component: () =>
      import(
        /* webpackChunkName: "public-courses" */
        '../views/PublicCourses.vue'
      ),
    meta: {
      seo: {
        title:
          '清大物理考古題課程目錄｜PhysArchive',
        description:
          '瀏覽清大物理系各課程的歷屆考古題、考試類型、授課教師與是否附解答。',
        canonicalPath: '/courses',
        robots: 'index, follow',
      },
    },
  },
  {
    path: '/courses/:courseId',
    name: 'PublicCourse',
    component: () =>
      import(
        /* webpackChunkName: "public-course" */
        '../views/PublicCourse.vue'
      ),
    meta: {
      seo: {
        title:
          '清大物理課程考古題｜PhysArchive',
        description:
          '瀏覽清大物理系課程的歷屆考古題、授課教師、考試類型與解答收錄資訊。',
        robots: 'index, follow',
      },
    },
  },
  {
    path: '/archive',
    name: 'Archive',
    component: () =>
      import(
        /* webpackChunkName: "archive" */
        '../views/Archive.vue'
      ),
    meta: {
      requiresAuth: true,
      seo: {
        title:
          '考古題資料庫｜PhysArchive',
        description:
          '登入後瀏覽及管理清大物理考古題。',
        canonicalPath: '/archive',
        robots: 'noindex, nofollow',
      },
    },
  },
  {
    path: '/admin',
    name: 'Admin',
    component: () =>
      import(
        /* webpackChunkName: "admin" */
        '../views/Admin.vue'
      ),
    meta: {
      requiresAuth: true,
      requiresAdmin: true,
      seo: {
        title:
          '管理後台｜PhysArchive',
        canonicalPath: '/admin',
        robots: 'noindex, nofollow',
      },
    },
  },
  {
    path: '/personal-settings',
    name: 'PersonalSettings',
    component: () =>
      import(
        /* webpackChunkName: "personal-settings" */
        '../views/PersonalSettings.vue'
      ),
    meta: {
      requiresAuth: true,
      seo: {
        title:
          '個人化設定｜PhysArchive',
        canonicalPath: '/personal-settings',
        robots: 'noindex, nofollow',
      },
    },
  },
  {
    path: '/login/callback',
    name: 'LoginCallback',
    component: () =>
      import(
        /* webpackChunkName: "login-callback" */
        '../views/LoginCallback.vue'
      ),
    meta: {
      requiresGuest: true,
      seo: {
        title:
          '登入處理中｜PhysArchive',
        canonicalPath: '/login/callback',
        robots: 'noindex, nofollow',
      },
    },
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    component: () =>
      import(
        /* webpackChunkName: "not-found" */
        '../views/NotFound.vue'
      ),
    meta: {
      seo: {
        title:
          '找不到頁面｜PhysArchive',
        description:
          '此頁面不存在或已被移除。',
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
  if (to.name === 'LoginCallback' && to.query?.token) {
    const token = Array.isArray(to.query.token) ? to.query.token[0] : to.query.token
    const decoded = decodeToken(token)
    const nowInSeconds = Math.floor(Date.now() / 1000)

    if (decoded?.exp && decoded.exp > nowInSeconds) {
      removeSessionItem(STORAGE_KEYS.session.NOTIFICATION_LOGIN_CHECKED)
      setToken(token)
      next({ name: 'Archive', replace: true })
      return
    }

    removeSessionItem(STORAGE_KEYS.session.AUTH_TOKEN)
    removeSessionItem(STORAGE_KEYS.session.NOTIFICATION_LOGIN_CHECKED)
    next({ name: 'Home', replace: true })
    return
  }

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
