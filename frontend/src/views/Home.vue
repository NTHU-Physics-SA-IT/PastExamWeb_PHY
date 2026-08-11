<template>
  <main class="physics-home" :class="{ 'physics-home-dark': isDarkTheme }">
    <div class="physics-board" aria-hidden="true">
      <svg class="spacetime-mesh" viewBox="0 0 1200 760" preserveAspectRatio="xMidYMid slice">
        <defs>
          <radialGradient id="gravity-well" cx="70%" cy="44%" r="42%">
            <stop offset="0%" stop-color="#aed1b8" stop-opacity="0.35" />
            <stop offset="45%" stop-color="#588770" stop-opacity="0.12" />
            <stop offset="100%" stop-color="#588770" stop-opacity="0" />
          </radialGradient>
        </defs>
        <rect width="1200" height="760" fill="url(#gravity-well)" />
        <g class="mesh-lines">
          <path d="M30 70 C260 115 470 140 650 110 C850 76 1015 70 1170 116" />
          <path d="M10 160 C260 215 488 228 680 192 C864 158 1010 164 1190 230" />
          <path d="M0 255 C260 315 510 322 710 272 C882 230 1026 254 1200 335" />
          <path d="M0 360 C270 410 540 416 740 346 C910 288 1042 346 1200 442" />
          <path d="M0 470 C260 510 540 520 735 448 C910 388 1060 468 1200 560" />
          <path d="M20 590 C278 610 548 622 720 560 C900 496 1060 585 1180 690" />
          <path d="M120 0 C170 180 190 330 160 500 C140 610 160 700 210 760" />
          <path d="M275 0 C320 178 334 330 300 490 C274 612 302 702 365 760" />
          <path d="M440 0 C482 180 492 328 452 482 C420 608 468 702 535 760" />
          <path d="M615 0 C648 184 650 332 604 478 C564 606 618 700 695 760" />
          <path d="M790 0 C812 185 800 330 748 475 C702 606 766 702 860 760" />
          <path d="M960 0 C962 186 930 330 872 482 C824 608 900 704 1030 760" />
        </g>
        <g class="geodesics">
          <path d="M220 680 C390 498 526 408 704 392 C872 376 1010 270 1130 78" />
          <path d="M445 52 C584 202 642 332 622 456 C604 576 668 670 806 730" />
        </g>
        <circle class="mass-core" cx="760" cy="380" r="92" />
      </svg>

      <div ref="formulaCloud" class="formula-cloud">
        <div
          v-for="(formula, index) in renderedFormulaCards"
          :key="formula.name"
          class="theory-card"
          :class="`formula-${index + 1}`"
        >
          <span class="formula-local-body">
            <span class="formula-expression" v-html="formula.rendered" />
          </span>
        </div>
      </div>
    </div>

    <section class="hero-shell">
      <div class="hero-copy">
        <p class="eyebrow">PHY Archive</p>
        <div class="hero-title-lockup">
          <h1><span class="title-line">清大物理</span><span class="title-line">考古系統</span></h1>
          <p class="title-campus"><span></span>NTHU PHYSICS<span></span></p>
        </div>
        <p class="subtitle">書卷沒有，考古這有</p>
        <div class="hero-actions">
          <Button
            icon="pi pi-building-columns"
            label="清華校務系統登入"
            size="large"
            @click="startNthuLogin"
          />
          <Button icon="pi pi-sign-in" label="本地帳號登入" size="large" @click="openLogin" />
          <Button
            icon="pi pi-book"
            label="瀏覽公開課程目錄"
            size="large"
            severity="secondary"
            outlined
            @click="openCatalog"
          />
        </div>
      </div>
    </section>

    <section class="dashboard-strip">
      <article
        v-for="(stat, index) in statistics"
        :key="stat.key"
        class="stat-card"
        :class="{ 'animate-fade-in': statsLoaded }"
        :style="{ animationDelay: `${index * 0.08}s` }"
      >
        <div class="stat-icon">
          <i :class="stat.icon"></i>
        </div>
        <div>
          <p>{{ stat.label }}</p>
          <strong>{{ animatedValues[stat.key] }}</strong>
        </div>
      </article>
    </section>
  </main>
</template>

<script setup>
defineOptions({
  name: 'HomeView',
})

import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useTheme } from '../utils/useTheme'
import { statisticsService } from '../api'
import { renderToString } from 'katex'
import { useFormulaPhysics } from '../composables/useFormulaPhysics'
import { DEFAULT_DESCRIPTION, SITE_URL, setSeo } from '../utils/seo'
import 'katex/dist/katex.min.css'

const { isDarkTheme } = useTheme()
const router = useRouter()
const formulaCloud = ref(null)

useFormulaPhysics(formulaCloud)

const statisticsData = ref({
  totalUsers: 0,
  totalDownloads: 0,
  onlineUsers: 0,
  totalArchives: 0,
  totalCourses: 0,
  activeToday: 0,
})

const animatedValues = ref({
  totalUsers: 0,
  totalDownloads: 0,
  onlineUsers: 0,
  totalArchives: 0,
  totalCourses: 0,
  activeToday: 0,
})

const statsLoaded = ref(false)

const statistics = computed(() => [
  {
    key: 'totalArchives',
    label: '考古題',
    icon: 'pi pi-file-pdf',
  },
  {
    key: 'totalCourses',
    label: '課程',
    icon: 'pi pi-book',
  },
  {
    key: 'totalDownloads',
    label: '下載',
    icon: 'pi pi-download',
  },
  {
    key: 'totalUsers',
    label: '使用者',
    icon: 'pi pi-users',
  },
  {
    key: 'activeToday',
    label: '今日活躍',
    icon: 'pi pi-chart-line',
  },
  {
    key: 'onlineUsers',
    label: '在線',
    icon: 'pi pi-circle-fill',
  },
])

const formulaCards = [
  {
    name: 'Euler-Lagrange',
    latex: String.raw`\frac{d}{dt}\left(\frac{\partial L}{\partial \dot{q}_i}\right) - \frac{\partial L}{\partial q_i} = 0`,
  },
  {
    name: 'Hamilton',
    latex: String.raw`\dot{q}_i = \frac{\partial H}{\partial p_i},\; \dot{p}_i = -\frac{\partial H}{\partial q_i}`,
  },
  {
    name: 'Hamilton-Jacobi',
    latex: String.raw`H\left(q, \frac{\partial S}{\partial q}, t\right) + \frac{\partial S}{\partial t} = 0`,
  },
  {
    name: 'Noether',
    latex: String.raw`\partial_\mu j^\mu = 0`,
  },
  {
    name: 'Virial',
    latex: String.raw`2\langle T \rangle = \langle \mathbf{r} \cdot \nabla V \rangle`,
  },
  {
    name: 'Maxwell',
    latex: String.raw`\nabla\cdot \mathbf{E} = \frac{\rho}{\varepsilon_0}`,
  },
  {
    name: 'Lorentz Force',
    latex: String.raw`\frac{dp_\mu}{d\tau} = qF_{\mu\nu}u^\nu`,
  },
  {
    name: 'Lienard-Wiechert',
    latex: String.raw`\nabla\times\mathbf{B} = \mu_0 \mathbf{J} + \mu_0\varepsilon_0 \frac{\partial \mathbf{E}}{\partial t}`,
  },
  {
    name: 'Poynting',
    latex: String.raw`\frac{\partial u}{\partial t} + \nabla\cdot\mathbf{S} = -\mathbf{J}\cdot\mathbf{E}`,
  },
  {
    name: 'Jefimenko',
    latex: String.raw`\mathbf{E}(\mathbf{r},t)=\int\left(\frac{\rho}{R^2}+\frac{\dot{\rho}}{cR}-\frac{\dot{\mathbf{J}}}{c^2R}\right)\, d^3\mathbf{r}^{\prime}`,
  },
  {
    name: 'TDSE',
    latex: String.raw`i\hbar\frac{\partial \psi}{\partial t} = \hat{H}\psi`,
  },
  {
    name: 'TISE',
    latex: String.raw`\hat{H}\psi_n = E_n\psi_n`,
  },
  {
    name: 'Heisenberg',
    latex: String.raw`\frac{dA}{dt} = \frac{i}{\hbar}[H,A] + \frac{\partial A}{\partial t}`,
  },
  {
    name: 'Ehrenfest',
    latex: String.raw`\frac{d\langle p \rangle}{dt} = -\langle \nabla V \rangle`,
  },
  {
    name: 'Lippmann-Schwinger',
    latex: String.raw`|\psi_\pm\rangle = |\phi\rangle + G^0_\pm V|\psi_\pm\rangle`,
  },
  {
    name: 'Boltzmann',
    latex: String.raw`\frac{\partial f}{\partial t} + \mathbf{v}\cdot\nabla f + \mathbf{F}\cdot\nabla_p f = C[f]`,
  },
  {
    name: 'Fokker-Planck',
    latex: String.raw`\partial_t P = -\partial_i(A_i P) + \frac{1}{2}\partial_i\partial_j(B_{ij}P)`,
  },
  {
    name: 'Langevin',
    latex: String.raw`m\ddot{x} + \gamma \dot{x} + \nabla V = \xi(t)`,
  },
  {
    name: 'Einstein Field',
    latex: String.raw`R_{\mu\nu} - \frac{1}{2}R g_{\mu\nu} = \frac{8\pi G}{c^4}T_{\mu\nu}`,
  },
  {
    name: 'Dirac',
    latex: String.raw`(i\gamma^\mu\partial_\mu - mc)\psi = 0`,
  },
  {
    name: 'Maxwell Dual',
    latex: String.raw`\partial_\mu F^{\mu\nu} = \mu_0 J^\nu`,
  },
  {
    name: 'Path Integral',
    latex: String.raw`Z = \int \mathcal{D}\phi\, e^{iS[\phi]/\hbar}`,
  },
]
const renderedFormulaCards = computed(() =>
  formulaCards.map((formula) => {
    try {
      return {
        ...formula,
        rendered: renderToString(formula.latex, {
          displayMode: false,
          throwOnError: false,
          strict: false,
        }),
      }
    } catch {
      return {
        ...formula,
        rendered: formula.latex,
      }
    }
  })
)

onMounted(async () => {
  applyHomeSeo()
  await fetchStatistics()
})

function openLogin() {
  window.__pastexam?.openLoginModal?.()
}

function startNthuLogin() {
  window.__pastexam?.startNthuLogin?.()
}

function openCatalog() {
  router.push({ name: 'PublicCourses' })
}

function applyHomeSeo() {
  setSeo({
    title: '清大物理考古題與歷屆考題｜PhysArchive',
    description: DEFAULT_DESCRIPTION,
    canonicalPath: '/',
    robots: 'index, follow',
    jsonLd: [
      {
        '@type': 'WebSite',
        '@id': `${SITE_URL}/#website`,
        name: '清大物理考古系統',
        alternateName: 'PhysArchive',
        url: `${SITE_URL}/`,
        inLanguage: 'zh-TW',
        publisher: { '@id': `${SITE_URL}/#organization` },
      },
      {
        '@type': 'Organization',
        '@id': `${SITE_URL}/#organization`,
        name: '清大物理系系學會資訊組',
        url: `${SITE_URL}/`,
        logo: {
          '@type': 'ImageObject',
          url: `${SITE_URL}/physics-symbol.png`,
        },
        sameAs: ['https://github.com/NTHU-Physics-SA-IT/PastExamWeb_PHY'],
      },
    ],
  })
}

async function fetchStatistics() {
  try {
    const response = await statisticsService.getSystemStatistics()

    if (response.data && response.data.data) {
      statisticsData.value = response.data.data
      animateCounters()
      statsLoaded.value = true
      return
    }

    throw new Error('Invalid API response format')
  } catch (error) {
    console.error('Error fetching statistics:', error)
    animatedValues.value = {
      totalUsers: '--',
      totalDownloads: '--',
      onlineUsers: '--',
      totalArchives: '--',
      totalCourses: '--',
      activeToday: '--',
    }
    statsLoaded.value = true
  }
}

function animateCounters() {
  Object.keys(statisticsData.value).forEach((key) => {
    animatedValues.value[key] = formatNumber(statisticsData.value[key])
  })
}

function formatNumber(num) {
  if (Number.isNaN(num) || num === null || num === undefined) {
    return '--'
  }
  return Number(num).toLocaleString('zh-TW')
}
</script>

<style scoped>
.physics-home {
  position: relative;
  min-height: 100%;
  overflow: hidden auto;
  color: var(--text-primary);
  background:
    radial-gradient(circle at 20% 16%, rgba(82, 128, 86, 0.1), transparent 28rem),
    linear-gradient(135deg, #f6faf5 0%, #eef4ef 58%, #f2f0e7 100%);
}

.physics-home-dark {
  background:
    radial-gradient(circle at 20% 16%, rgba(83, 150, 98, 0.12), transparent 34rem),
    linear-gradient(135deg, #101610 0%, #13201a 58%, #171b15 100%);
}

.physics-home:not(.physics-home-dark) {
  background:
    radial-gradient(circle at 74% 38%, rgba(188, 205, 178, 0.42), transparent 30rem),
    radial-gradient(circle at 20% 14%, rgba(112, 158, 133, 0.2), transparent 24rem),
    linear-gradient(135deg, #f7f3e8 0%, #edf4ec 48%, #dfeade 100%);
}

.hero-shell {
  min-height: calc(100vh - var(--navbar-height));
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  width: min(1180px, calc(100% - 2rem));
  margin: 0 auto;
  padding: clamp(2rem, 7vh, 5rem) 0;
}

.hero-copy {
  position: relative;
  z-index: 1;
  width: min(100%, 44rem);
  max-width: 44rem;
  padding: clamp(1rem, 2vw, 1.5rem) 0;
}

.eyebrow {
  margin: 0 0 0.95rem;
  color: #8fd8cb;
  font-size: 0.86rem;
  font-weight: 650;
  letter-spacing: 0;
  text-transform: uppercase;
}

.physics-home-dark .eyebrow {
  color: #9be0d4;
}

.physics-home:not(.physics-home-dark) .eyebrow {
  color: #3d7c6e;
}

h1 {
  margin: 0;
  color: #edf7ed;
  font-size: clamp(2.85rem, 4.4vw, 4.85rem);
  font-weight: 780;
  line-height: 1.04;
  letter-spacing: 0.08em;
  text-shadow: 0 1.2rem 3rem rgba(0, 0, 0, 0.22);
  word-break: keep-all;
  overflow-wrap: normal;
}

.physics-home:not(.physics-home-dark) h1 {
  color: #183a31;
  text-shadow: 0 1rem 2.6rem rgba(82, 109, 91, 0.16);
}

.title-line {
  display: inline;
}

.hero-title-lockup {
  display: inline-grid;
  gap: 0.62rem;
}

.title-roman {
  margin: 0;
  color: rgba(202, 179, 111, 0.94);
  font-size: clamp(0.88rem, 1.25vw, 1.08rem);
  font-weight: 760;
  letter-spacing: 0.34em;
  line-height: 1.1;
  text-transform: uppercase;
}

.title-campus {
  display: grid;
  grid-template-columns: minmax(2.5rem, 1fr) auto minmax(2.5rem, 1fr);
  align-items: center;
  gap: 1rem;
  width: min(100%, 38rem);
  margin: 0;
  color: rgba(202, 179, 111, 0.98);
  font-size: clamp(0.9rem, 1.1vw, 1.05rem);
  font-weight: 760;
  letter-spacing: 0.5em;
  text-indent: 0.5em;
}

.title-campus span {
  display: block;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(202, 179, 111, 0.8));
}

.title-campus span:last-child {
  background: linear-gradient(90deg, rgba(202, 179, 111, 0.8), transparent);
}

.subtitle {
  max-width: 36rem;
  margin: 1.2rem 0 0;
  color: rgba(222, 232, 224, 0.78);
  font-size: clamp(0.98rem, 1.15vw, 1.08rem);
  line-height: 1.78;
}

.physics-home:not(.physics-home-dark) .subtitle {
  color: rgba(33, 58, 50, 0.78);
}

.hero-actions :deep(.p-button.p-button-secondary.p-button-outlined) {
  color: rgba(232, 240, 226, 0.86);
  border-color: rgba(214, 230, 223, 0.62);
  background: rgba(10, 20, 18, 0.18);
}

.physics-home:not(.physics-home-dark)
  .hero-actions
  :deep(.p-button.p-button-secondary.p-button-outlined) {
  color: #1c4c42;
  border-color: rgba(58, 111, 93, 0.36);
  background: rgba(249, 247, 238, 0.52);
}

.hero-actions :deep(.p-button.p-button-secondary.p-button-outlined:hover) {
  color: #f5fbf6;
  border-color: rgba(238, 246, 239, 0.82);
  background: rgba(214, 230, 223, 0.1);
}

.physics-home:not(.physics-home-dark)
  .hero-actions
  :deep(.p-button.p-button-secondary.p-button-outlined:hover) {
  color: #123a31;
  border-color: rgba(58, 111, 93, 0.5);
  background: rgba(232, 240, 224, 0.75);
}

.hero-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  margin-top: 2rem;
}

.physics-board {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 100%;
  min-height: 42rem;
  overflow: hidden;
  background:
    radial-gradient(circle at 68% 46%, rgba(140, 180, 147, 0.18), transparent 20rem),
    radial-gradient(circle at 24% 20%, rgba(72, 123, 103, 0.1), transparent 20rem),
    linear-gradient(135deg, rgba(12, 28, 25, 0.98), rgba(13, 20, 21, 0.98));
  pointer-events: none;
  z-index: 0;
}

.physics-home:not(.physics-home-dark) .physics-board {
  background:
    radial-gradient(circle at 68% 44%, rgba(177, 198, 168, 0.34), transparent 22rem),
    radial-gradient(circle at 24% 20%, rgba(91, 142, 118, 0.14), transparent 24rem),
    linear-gradient(135deg, rgba(248, 244, 232, 0.94), rgba(232, 241, 232, 0.92));
}

.physics-board::before {
  content: '';
  position: absolute;
  inset: 0;
  background:
    radial-gradient(circle at 70% 44%, rgba(218, 230, 205, 0.08), transparent 8rem),
    linear-gradient(115deg, transparent 0 42%, rgba(225, 236, 221, 0.028) 44%, transparent 48%),
    linear-gradient(
      90deg,
      rgba(8, 18, 16, 0.1),
      rgba(8, 18, 16, 0.58) 26%,
      rgba(8, 18, 16, 0.12) 62%,
      rgba(8, 18, 16, 0.02)
    );
  pointer-events: none;
  z-index: 3;
  animation: fieldGlow 10s ease-in-out infinite alternate;
}

.physics-home:not(.physics-home-dark) .physics-board::before {
  background:
    radial-gradient(circle at 70% 44%, rgba(196, 166, 92, 0.14), transparent 10rem),
    linear-gradient(115deg, transparent 0 42%, rgba(54, 105, 88, 0.055) 44%, transparent 48%),
    linear-gradient(
      90deg,
      rgba(250, 246, 234, 0.38),
      rgba(247, 244, 231, 0.66) 28%,
      rgba(233, 241, 230, 0.32) 62%,
      rgba(233, 241, 230, 0.1)
    );
}

.physics-board::after {
  content: '';
  position: absolute;
  inset: 0;
  background:
    radial-gradient(
      circle at 68% 46%,
      transparent 0 13rem,
      rgba(7, 16, 14, 0.1) 18rem,
      transparent 31rem
    ),
    linear-gradient(0deg, rgba(8, 18, 16, 0.32), transparent 40%);
  pointer-events: none;
  z-index: 4;
  animation: gravityVignette 12s ease-in-out infinite alternate;
}

.physics-home:not(.physics-home-dark) .physics-board::after {
  background:
    radial-gradient(
      circle at 68% 46%,
      transparent 0 13rem,
      rgba(82, 115, 94, 0.08) 18rem,
      transparent 31rem
    ),
    linear-gradient(0deg, rgba(247, 242, 228, 0.46), transparent 42%);
}

.formula-cloud::before {
  content: '';
  position: absolute;
  top: -18%;
  left: -24%;
  width: 46%;
  height: 145%;
  background: linear-gradient(
    90deg,
    transparent,
    rgba(172, 219, 205, 0.085),
    rgba(202, 179, 111, 0.095),
    transparent
  );
  filter: blur(16px);
  transform: skewX(-16deg);
  animation: spectralSweep 5.2s linear infinite;
}

.physics-home:not(.physics-home-dark) .formula-cloud::before {
  background: linear-gradient(
    90deg,
    transparent,
    rgba(67, 124, 103, 0.075),
    rgba(190, 159, 78, 0.11),
    transparent
  );
}

.spacetime-mesh {
  position: absolute;
  inset: -10% -14% -10% -14%;
  width: 128%;
  height: 120%;
  opacity: 0.68;
  z-index: 1;
  transform-origin: 68% 46%;
  animation: spacetimeDrift 6.8s ease-in-out infinite alternate;
}

.mesh-lines path {
  fill: none;
  stroke: rgba(198, 223, 205, 0.23);
  stroke-width: 1.35;
  vector-effect: non-scaling-stroke;
  animation: meshBreathing 5.5s ease-in-out infinite alternate;
}

.physics-home:not(.physics-home-dark) .mesh-lines path {
  stroke: rgba(56, 103, 84, 0.25);
}

.geodesics path {
  fill: none;
  stroke: rgba(202, 179, 111, 0.58);
  stroke-width: 2.8;
  stroke-linecap: round;
  stroke-dasharray: 22 18;
  vector-effect: non-scaling-stroke;
  animation: geodesicFlow 3.8s linear infinite;
}

.physics-home:not(.physics-home-dark) .geodesics path {
  stroke: rgba(174, 139, 54, 0.5);
}

.mass-core {
  fill: rgba(232, 238, 218, 0.09);
  stroke: rgba(221, 237, 210, 0.18);
  stroke-width: 1.2;
  vector-effect: non-scaling-stroke;
  transform-origin: 760px 380px;
  animation: massPulse 3.2s ease-in-out infinite;
}

.physics-home:not(.physics-home-dark) .mass-core {
  fill: rgba(64, 113, 91, 0.08);
  stroke: rgba(74, 122, 98, 0.18);
}

.formula-cloud {
  position: absolute;
  inset: -8% -12%;
  z-index: 2;
  animation: formulaFieldDrift 6.6s ease-in-out infinite alternate;
}

.formula-cloud.formula-physics-active .formula-local-body {
  will-change: transform;
}

.theory-card {
  position: absolute;
  display: inline-flex;
  max-width: min(30rem, 40vw);
  min-width: max-content;
  color: rgba(232, 240, 226, 0.25);
  font-family: 'Times New Roman', Georgia, serif;
  font-style: italic;
  letter-spacing: 0.01em;
  text-align: left;
  overflow: visible;
  transform: rotate(var(--tilt, 0deg));
  white-space: nowrap;
  pointer-events: none;
  animation: var(--formula-motion, formulaOrbitA) var(--float-duration, 8s) ease-in-out infinite;
  animation-delay: var(--float-delay, 0s);
}

.physics-home:not(.physics-home-dark) .theory-card {
  color: rgba(44, 82, 68, 0.2);
}

.formula-local-body {
  display: inline-flex;
  transform-origin: center;
}

.formula-expression {
  display: inline-flex;
  font-size: var(--formula-font-size, clamp(0.9rem, 1.02vw, 1.1rem));
  line-height: 1.2;
  text-shadow:
    0 0 1rem rgba(168, 204, 181, 0.1),
    0 0 0.2rem rgba(255, 255, 255, 0.08);
  color: inherit;
  width: max-content;
  white-space: nowrap;
  margin: 0;
}

.formula-expression :deep(.katex) {
  color: inherit;
  font-size: 1em;
  line-height: 1.2;
  text-shadow: inherit;
  display: inline-block;
}

.formula-expression :deep(.katex .katex-html) {
  white-space: nowrap;
}

.physics-home:not(.physics-home-dark) .formula-expression {
  color: rgba(39, 73, 63, 0.85);
  text-shadow:
    0 0 0.95rem rgba(186, 168, 113, 0.1),
    0 0 0.2rem rgba(255, 255, 255, 0.1);
  font-style: italic;
}

.formula-1 {
  top: 11%;
  left: 16%;
  --tilt: -13deg;
  --formula-font-size: 0.96rem;
  --formula-alpha: 0.32;
  --float-delay: -1s;
  --float-duration: 7.5s;
  --formula-motion: formulaOrbitA;
}

.formula-2 {
  top: 16%;
  left: 64%;
  --formula-font-size: 0.95rem;
  --formula-alpha: 0.3;
  --tilt: 8deg;
  --float-delay: -7s;
  --float-duration: 8.6s;
  --formula-motion: formulaOrbitB;
}

.formula-3 {
  top: 23%;
  left: 73%;
  --formula-font-size: 0.9rem;
  --formula-alpha: 0.28;
  --tilt: -9deg;
  --float-delay: -4s;
  --float-duration: 9.2s;
  --formula-motion: formulaOrbitC;
}

.formula-4 {
  top: 9%;
  left: 24%;
  --formula-font-size: 0.86rem;
  --formula-alpha: 0.26;
  --tilt: -5deg;
  --float-delay: -10s;
  --float-duration: 7.8s;
  --formula-motion: formulaOrbitB;
}

.formula-5 {
  top: 18%;
  left: 8%;
  --formula-font-size: 0.92rem;
  --formula-alpha: 0.25;
  --tilt: 17deg;
  --float-delay: -13s;
  --float-duration: 8.2s;
  --formula-motion: formulaOrbitA;
}

.formula-6 {
  top: 30%;
  left: 22%;
  --formula-font-size: 0.86rem;
  --formula-alpha: 0.22;
  --tilt: -24deg;
  --float-delay: -5s;
  --float-duration: 9.8s;
  --formula-motion: formulaOrbitC;
}

.formula-7 {
  top: 21%;
  left: 36%;
  --formula-font-size: 0.83rem;
  --formula-alpha: 0.22;
  --tilt: 4deg;
  --float-delay: -9s;
  --float-duration: 8.4s;
  --formula-motion: formulaOrbitC;
}

.formula-8 {
  top: 68%;
  left: 60%;
  --formula-font-size: 0.85rem;
  --formula-alpha: 0.2;
  --tilt: 22deg;
  --float-delay: -2s;
  --float-duration: 7.4s;
  --formula-motion: formulaOrbitB;
}

.formula-9 {
  top: 64%;
  left: 38%;
  --formula-font-size: 0.84rem;
  --formula-alpha: 0.23;
  --tilt: -18deg;
  --float-delay: -12s;
  --float-duration: 9.4s;
  --formula-motion: formulaOrbitA;
}

.formula-10 {
  top: 82%;
  left: 26%;
  --formula-font-size: 0.76rem;
  --formula-alpha: 0.14;
  --tilt: -13deg;
  --float-delay: -6s;
  --float-duration: 8.8s;
  --formula-motion: formulaOrbitC;
}

.formula-11 {
  top: 25%;
  left: 48%;
  --formula-font-size: 0.9rem;
  --formula-alpha: 0.26;
  --tilt: 12deg;
  --float-delay: -15s;
  --float-duration: 7.9s;
  --formula-motion: formulaOrbitA;
}

.formula-12 {
  top: 33%;
  left: 14%;
  --formula-font-size: 0.8rem;
  --formula-alpha: 0.21;
  --tilt: 0deg;
  --float-delay: -3s;
  --float-duration: 8.5s;
  --formula-motion: formulaOrbitB;
}

.formula-13 {
  top: 65%;
  left: 49%;
  --formula-font-size: 0.88rem;
  --formula-alpha: 0.22;
  --tilt: -5deg;
  --float-delay: -11s;
  --float-duration: 9s;
  --formula-motion: formulaOrbitC;
}

.formula-14 {
  top: 52%;
  left: 57%;
  --formula-font-size: 0.85rem;
  --formula-alpha: 0.23;
  --tilt: 8deg;
  --float-delay: -8s;
  --float-duration: 7.7s;
  --formula-motion: formulaOrbitB;
}

.formula-15 {
  display: none;
  top: 89%;
  left: 16%;
  --formula-font-size: 0.8rem;
  --formula-alpha: 0.2;
  --tilt: 12deg;
  --float-delay: -14s;
  --float-duration: 8.9s;
  --formula-motion: formulaOrbitA;
}

.formula-16 {
  top: 43%;
  left: 63%;
  --formula-font-size: 0.84rem;
  --formula-alpha: 0.22;
  --tilt: -9deg;
  --float-delay: -4s;
  --float-duration: 9.6s;
  --formula-motion: formulaOrbitC;
}

.formula-17 {
  top: 74%;
  left: 38%;
  --formula-font-size: 0.82rem;
  --formula-alpha: 0.22;
  --tilt: 22deg;
  --float-delay: -16s;
  --float-duration: 7.6s;
  --formula-motion: formulaOrbitB;
}

.formula-18 {
  top: 72%;
  left: 34%;
  --formula-font-size: 0.83rem;
  --formula-alpha: 0.21;
  --tilt: -13deg;
  --float-delay: -7s;
  --float-duration: 9.1s;
  --formula-motion: formulaOrbitA;
}

.formula-19 {
  top: 37%;
  left: 59%;
  color: rgba(242, 238, 216, 0.34);
  --formula-font-size: 0.93rem;
  --formula-alpha: 0.27;
  --tilt: -18deg;
  --float-delay: -18s;
  --float-duration: 8s;
  --formula-motion: formulaOrbitC;
}

.physics-home:not(.physics-home-dark) .formula-19 {
  color: rgba(83, 111, 75, 0.3);
}

.formula-20 {
  top: 69%;
  left: 74%;
  --formula-font-size: 0.82rem;
  --formula-alpha: 0.21;
  --tilt: 4deg;
  --float-delay: -5s;
  --float-duration: 8.7s;
  --formula-motion: formulaOrbitA;
}

.formula-21 {
  top: 62%;
  left: 68%;
  --formula-font-size: 0.88rem;
  --formula-alpha: 0.2;
  --tilt: -24deg;
  --float-delay: -4.5s;
  --float-duration: 8.2s;
  --formula-motion: formulaOrbitB;
}

.formula-22 {
  top: 48%;
  left: 78%;
  --tilt: 17deg;
  --formula-font-size: 0.86rem;
  --formula-alpha: 0.23;
  --float-delay: -9.2s;
  --float-duration: 9s;
  --formula-motion: formulaOrbitC;
}

@media (max-width: 1360px) {
  .formula-1,
  .formula-2,
  .formula-3 {
    right: auto;
    --formula-font-size: 0.88rem;
  }

  .formula-1 {
    top: 12%;
    left: 18%;
  }

  .formula-2 {
    top: 18%;
    left: 64%;
  }

  .formula-3 {
    top: 24%;
    left: 74%;
  }

  .formula-7 {
    left: 34%;
    top: 14%;
    right: auto;
  }

  .formula-6 {
    top: 32%;
    left: 20%;
  }

  .formula-18 {
    left: 26%;
    right: auto;
    top: 75%;
    --formula-font-size: 0.82rem;
  }

  .formula-8 {
    left: 61%;
    top: 70%;
    --formula-font-size: 0.8rem;
    --formula-alpha: 0.18;
  }

  .formula-10 {
    left: 22%;
    top: 84%;
    --formula-font-size: 0.76rem;
    --formula-alpha: 0.16;
  }

  .formula-20 {
    left: 74%;
    right: auto;
    top: 70%;
    --formula-font-size: 0.78rem;
    --formula-alpha: 0.18;
  }

  .formula-21 {
    left: 69%;
    right: auto;
    top: 62%;
    --formula-font-size: 0.8rem;
    --formula-alpha: 0.18;
  }

  .formula-22 {
    left: 79%;
    right: auto;
    top: 46%;
    --formula-font-size: 0.82rem;
    --formula-alpha: 0.2;
  }

  .formula-9 {
    --formula-alpha: 0.26;
    --formula-font-size: 0.84rem;
  }

  .formula-3 {
    --formula-font-size: 0.86rem;
  }
}

.dashboard-strip {
  display: grid;
  grid-template-columns: 1fr;
  gap: 0.55rem;
  width: min(17.5rem, calc(100% - 2rem));
  margin: 0;
  position: absolute;
  top: clamp(8.5rem, 20vh, 14rem);
  right: max(1rem, calc((100% - 1180px) / 2));
  z-index: 2;
}

.dashboard-strip::before {
  content: 'Archive Metrics';
  color: rgba(202, 179, 111, 0.72);
  font-size: 0.68rem;
  font-weight: 760;
  letter-spacing: 0.26em;
  line-height: 1;
  text-transform: uppercase;
}

.physics-home:not(.physics-home-dark) .dashboard-strip::before {
  color: rgba(137, 108, 43, 0.78);
}

@media (min-width: 1181px) {
  .hero-shell {
    width: min(1280px, calc(100% - clamp(3rem, 8vw, 10rem)));
  }

  .dashboard-strip {
    width: min(18.25rem, calc(100% - 2rem));
    top: 50%;
    right: max(clamp(2rem, 7vw, 7rem), calc((100% - 1280px) / 2));
    transform: translateY(-45%);
  }
}

@media (min-width: 1200px) and (max-width: 1500px) {
  .formula-10 {
    top: 80%;
    left: 23%;
    --formula-font-size: 0.74rem;
    --formula-alpha: 0.13;
  }

  .formula-17 {
    top: 85%;
    left: 62%;
    --formula-font-size: 0.78rem;
    --formula-alpha: 0.18;
  }

  .formula-20 {
    top: 78%;
    left: 52%;
  }

  .formula-18 {
    top: 72%;
    left: 30%;
    --formula-font-size: 0.79rem;
    --formula-alpha: 0.17;
  }
}

@media (min-width: 1100px) and (max-width: 1300px) {
  .hero-copy {
    margin-left: clamp(2rem, 3.2vw, 3.3rem);
  }
}

@media (min-width: 1300px) and (max-width: 1450px) {
  .hero-copy {
    margin-left: clamp(2.5rem, 3.1vw, 3.8rem);
  }
}

@media (min-width: 1360px) and (max-width: 1500px) {
  .hero-copy {
    margin-left: 3.6vw;
    transform: translateX(0.18rem);
  }
}

@media (min-width: 1450px) and (max-width: 1650px) {
  .formula-8 {
    top: 63%;
    left: 55%;
    --formula-font-size: 0.8rem;
    --formula-alpha: 0.17;
  }

  .formula-10 {
    top: 80%;
    left: 23%;
    --formula-font-size: 0.74rem;
    --formula-alpha: 0.13;
  }

  .formula-17 {
    top: 85%;
    left: 62%;
    --formula-font-size: 0.78rem;
    --formula-alpha: 0.18;
  }

  .formula-18 {
    top: 72%;
    left: 30%;
    --formula-font-size: 0.79rem;
    --formula-alpha: 0.17;
  }

  .formula-20 {
    top: 78%;
    left: 52%;
    --formula-font-size: 0.76rem;
    --formula-alpha: 0.16;
  }

  .formula-21 {
    display: none;
  }

  .formula-22 {
    top: 50%;
    left: 64%;
    --formula-font-size: 0.78rem;
    --formula-alpha: 0.13;
  }
}

@media (min-width: 1650px) {
  .formula-10 {
    top: 84%;
    left: 21%;
    --formula-font-size: 0.74rem;
    --formula-alpha: 0.12;
  }

  .formula-17 {
    top: 58%;
    left: 58%;
    --formula-font-size: 0.8rem;
    --formula-alpha: 0.17;
  }

  .formula-18 {
    top: 66%;
    left: 49%;
    --formula-font-size: 0.8rem;
    --formula-alpha: 0.17;
  }

  .formula-8 {
    top: 64%;
    left: 53%;
    --formula-font-size: 0.8rem;
    --formula-alpha: 0.18;
  }

  .formula-20 {
    top: 72%;
    left: 55%;
    --formula-font-size: 0.76rem;
    --formula-alpha: 0.16;
  }

  .formula-21 {
    display: none;
  }

  .formula-22 {
    top: 50%;
    left: 67%;
    --formula-font-size: 0.78rem;
    --formula-alpha: 0.13;
  }
}

@media (min-width: 1650px) and (max-width: 1900px) {
  .formula-8 {
    top: 80%;
    left: 60%;
    --formula-font-size: 0.79rem;
    --formula-alpha: 0.16;
  }

  .formula-13 {
    top: 66%;
    left: 41%;
    --formula-font-size: 0.82rem;
    --formula-alpha: 0.18;
  }

  .formula-18 {
    top: 84%;
    left: 30%;
    --formula-font-size: 0.74rem;
    --formula-alpha: 0.16;
  }

  .formula-14 {
    top: 57%;
    left: 65%;
    --formula-font-size: 0.82rem;
    --formula-alpha: 0.18;
  }
}

@media (min-width: 1900px) {
  .formula-8 {
    top: 74%;
    left: 52%;
    --formula-font-size: 0.82rem;
    --formula-alpha: 0.17;
  }

  .formula-13 {
    top: 64%;
    left: 43%;
    --formula-font-size: 0.84rem;
    --formula-alpha: 0.17;
  }

  .formula-18 {
    top: 87%;
    left: 30%;
    --formula-font-size: 0.74rem;
    --formula-alpha: 0.16;
  }

  .formula-20 {
    top: 90%;
    left: 62%;
    --formula-font-size: 0.76rem;
    --formula-alpha: 0.16;
  }
}

.stat-card {
  display: flex;
  align-items: center;
  gap: 0.8rem;
  min-height: 4.4rem;
  padding: 0.78rem 0.9rem;
  border: 1px solid rgba(128, 166, 151, 0.14);
  border-left: 3px solid rgba(202, 179, 111, 0.62);
  border-radius: 0.3rem;
  background:
    linear-gradient(90deg, rgba(202, 179, 111, 0.08), transparent 44%), rgba(7, 18, 17, 0.62);
  box-shadow: none;
  backdrop-filter: blur(16px);
  opacity: 0;
  transform: translateY(12px);
}

.physics-home:not(.physics-home-dark) .stat-card {
  border-color: rgba(85, 125, 108, 0.2);
  border-left-color: rgba(184, 145, 54, 0.62);
  background:
    linear-gradient(90deg, rgba(190, 159, 78, 0.13), transparent 46%), rgba(250, 248, 240, 0.72);
  box-shadow: 0 1.4rem 3.6rem rgba(68, 92, 78, 0.12);
}

.physics-home-dark .stat-card {
  background:
    linear-gradient(90deg, rgba(202, 179, 111, 0.08), transparent 44%), rgba(7, 18, 17, 0.62);
  border-color: rgba(125, 174, 164, 0.16);
  border-left-color: rgba(202, 179, 111, 0.62);
}

.stat-icon {
  display: grid;
  place-items: center;
  width: 2rem;
  aspect-ratio: 1;
  border-radius: 0.25rem;
  color: #c7b06b;
  background: rgba(196, 238, 232, 0.08);
}

.physics-home:not(.physics-home-dark) .stat-icon {
  color: #927333;
  background: rgba(74, 127, 105, 0.1);
}

.stat-card p {
  margin: 0 0 0.2rem;
  color: rgba(229, 238, 229, 0.74);
  font-size: 0.85rem;
}

.physics-home:not(.physics-home-dark) .stat-card p {
  color: rgba(41, 68, 59, 0.72);
}

.stat-card strong {
  color: #f4fbf4;
  font-size: 1.3rem;
}

.physics-home:not(.physics-home-dark) .stat-card strong {
  color: #183a31;
}

.animate-fade-in {
  animation: fadeInUp 0.45s ease forwards;
}

@keyframes fadeInUp {
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes spacetimeDrift {
  from {
    transform: translate3d(-5%, -2.2%, 0) scale(1.03) rotate(-0.9deg);
  }

  to {
    transform: translate3d(5.4%, 2.1%, 0) scale(1.085) rotate(1deg);
  }
}

@keyframes meshBreathing {
  from {
    opacity: 0.66;
  }

  to {
    opacity: 1;
  }
}

@keyframes geodesicFlow {
  from {
    stroke-dashoffset: 0;
  }

  to {
    stroke-dashoffset: -720;
  }
}

@keyframes massPulse {
  0%,
  100% {
    opacity: 0.48;
    transform: scale(0.82);
  }

  50% {
    opacity: 1;
    transform: scale(1.36);
  }
}

@keyframes fieldGlow {
  from {
    opacity: 0.82;
    transform: translate3d(-2%, 0.4%, 0);
  }

  to {
    opacity: 1;
    transform: translate3d(2%, -1.1%, 0);
  }
}

@keyframes gravityVignette {
  from {
    opacity: 0.85;
  }

  to {
    opacity: 1;
  }
}

@keyframes formulaFieldDrift {
  from {
    transform: translate3d(-3.2%, 1.8%, 0);
  }

  to {
    transform: translate3d(3.1%, -1.9%, 0);
  }
}

@keyframes formulaOrbitA {
  0%,
  100% {
    opacity: calc(var(--formula-alpha, 0.2) * 0.6);
    transform: rotate(var(--tilt, 0deg)) translate3d(0, 0, 0);
  }

  33% {
    opacity: calc(var(--formula-alpha, 0.2) * 1.35);
    transform: rotate(var(--tilt, 0deg)) translate3d(2.4rem, -1.45rem, 0);
  }

  66% {
    opacity: calc(var(--formula-alpha, 0.2) * 0.9);
    transform: rotate(var(--tilt, 0deg)) translate3d(-1.7rem, 1.65rem, 0);
  }
}

@keyframes formulaOrbitB {
  0%,
  100% {
    opacity: calc(var(--formula-alpha, 0.2) * 0.64);
    transform: rotate(var(--tilt, 0deg)) translate3d(0, 0, 0);
  }

  38% {
    opacity: calc(var(--formula-alpha, 0.2) * 1.35);
    transform: rotate(var(--tilt, 0deg)) translate3d(-2.6rem, -1.25rem, 0);
  }

  72% {
    opacity: calc(var(--formula-alpha, 0.2) * 0.95);
    transform: rotate(var(--tilt, 0deg)) translate3d(1.9rem, 1.9rem, 0);
  }
}

@keyframes formulaOrbitC {
  0%,
  100% {
    opacity: calc(var(--formula-alpha, 0.2) * 0.58);
    transform: rotate(var(--tilt, 0deg)) translate3d(0, 0, 0);
  }

  50% {
    opacity: calc(var(--formula-alpha, 0.2) * 1.42);
    transform: rotate(var(--tilt, 0deg)) translate3d(0.9rem, -2.6rem, 0);
  }

  78% {
    opacity: calc(var(--formula-alpha, 0.2) * 0.9);
    transform: rotate(var(--tilt, 0deg)) translate3d(-2.2rem, 0.9rem, 0);
  }
}

@keyframes spectralSweep {
  from {
    transform: translateX(-25vw) skewX(-16deg);
  }

  to {
    transform: translateX(150vw) skewX(-16deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .formula-cloud {
    animation-duration: 18s !important;
  }

  .formula-cloud::before {
    animation-duration: 24s !important;
  }

  .theory-card {
    animation: none !important;
    opacity: 1;
  }
}

@media (max-width: 1180px) {
  .hero-shell {
    width: min(100% - 2rem, 42rem);
    min-height: calc(100svh - var(--navbar-height, 72px));
    justify-content: center;
    align-items: center;
    padding-top: clamp(1.9rem, 5vh, 2.6rem);
    padding-bottom: clamp(1.7rem, 4.5vh, 2.3rem);
  }

  .hero-copy {
    width: min(100%, 38rem);
    max-width: none;
    padding-top: 0;
    margin: 0 auto;
    text-align: center;
  }

  .hero-title-lockup,
  .title-campus {
    margin-inline: auto;
  }

  .subtitle {
    width: 100%;
    max-width: none;
  }

  .hero-actions {
    width: min(100%, 24rem);
    justify-content: center;
    margin-left: auto;
    margin-right: auto;
    gap: 0.8rem;
  }

  .hero-actions :deep(.p-button) {
    width: 100%;
  }

  .dashboard-strip {
    position: relative;
    top: auto;
    right: auto;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    width: min(45rem, calc(100% - 2rem));
    margin: 0 auto 2rem;
    transform: none;
  }

  .dashboard-strip::before {
    grid-column: 1 / -1;
  }
}

@media (max-width: 920px) {
  .hero-shell {
    align-items: center;
    padding-top: clamp(2.5rem, 8vh, 5rem);
  }

  .physics-board {
    min-height: 44rem;
  }

  .theory-card {
    max-width: 42vw;
  }

  .formula-7,
  .formula-10,
  .formula-12,
  .formula-15,
  .formula-17,
  .formula-18 {
    display: none;
  }

  .dashboard-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    margin-top: 0;
  }
}

@media (max-width: 768px) {
  .dashboard-strip {
    grid-template-columns: 1fr;
    width: min(100% - 2rem, 32rem);
    gap: 0.85rem;
  }
}

@media (max-width: 560px) {
  .physics-home {
    min-height: 100%;
    overflow-x: hidden;
  }

  .hero-shell {
    width: min(100% - 2rem, 1180px);
    min-height: calc(100svh - var(--navbar-height, 72px));
    padding-top: clamp(2.35rem, 8vh, 4.75rem);
    padding-bottom: clamp(2rem, 6vh, 3.5rem);
    justify-content: center;
    align-items: center;
  }

  .hero-copy {
    width: 100%;
    padding-top: 0.65rem;
    margin: 0 auto;
    text-align: center;
    justify-items: center;
  }

  .eyebrow {
    margin-bottom: 0.9rem;
    font-size: 0.78rem;
  }

  h1 {
    max-width: min(100%, 7.2em);
    font-size: clamp(2rem, 9.7vw, 2.72rem);
    line-height: 1.1;
    letter-spacing: 0.03em;
    margin-inline: auto;
  }

  .title-line {
    display: block;
  }

  .title-roman {
    max-width: min(100%, 18rem);
    font-size: 0.72rem;
    letter-spacing: 0.16em;
    line-height: 1.45;
    margin-inline: auto;
  }

  .title-campus {
    width: min(100%, 18rem);
    gap: 0.55rem;
    font-size: 0.74rem;
    letter-spacing: 0.34em;
    text-indent: 0.34em;
    margin-inline: auto;
    margin-top: 0.25rem;
  }

  .subtitle {
    margin-top: 1.45rem;
    margin-inline: auto;
    width: 100%;
    text-align: center;
    font-size: 0.95rem;
    line-height: 1.6;
  }

  .hero-actions {
    gap: 0.85rem;
    margin-top: 1.8rem;
    width: min(100%, 23rem);
    margin-inline: auto;
  }

  .hero-actions :deep(.p-button) {
    width: 100%;
    justify-content: center;
    min-height: 2.85rem;
    font-size: 0.95rem;
  }

  .physics-board {
    min-height: 100%;
    width: 100%;
    max-width: 100%;
    contain: paint;
  }

  .physics-board::before {
    inset: -4%;
  }

  .spacetime-mesh {
    inset: -14%;
    width: 128%;
    height: 128%;
    opacity: 0.48;
  }

  .formula-cloud {
    inset: -10% -18%;
  }

  .theory-card {
    display: none;
    max-width: 72vw;
    padding: 0.5rem 0.62rem;
  }

  .formula-1,
  .formula-2,
  .formula-4,
  .formula-6,
  .formula-8,
  .formula-11,
  .formula-13,
  .formula-16,
  .formula-19,
  .formula-20,
  .formula-22 {
    display: inline-flex;
    align-items: center;
    width: max-content;
    max-width: min(100%, 72vw);
  }

  .formula-2 {
    top: 9%;
    left: 55%;
    --formula-font-size: 0.7rem;
    --formula-alpha: 0.17;
  }

  .formula-4 {
    top: 20%;
    left: 7%;
    --formula-font-size: 0.7rem;
    --formula-alpha: 0.17;
  }

  .formula-1 {
    top: 54%;
    right: 6%;
    left: auto;
    --formula-font-size: 0.75rem;
    --formula-alpha: 0.2;
  }

  .formula-6 {
    top: 65%;
    left: 7%;
    right: auto;
    --formula-font-size: 0.74rem;
    --formula-alpha: 0.22;
  }

  .formula-8 {
    top: 89%;
    left: 57%;
    --formula-font-size: 0.69rem;
    --formula-alpha: 0.16;
  }

  .formula-11 {
    top: 77%;
    left: 12%;
    --formula-font-size: 0.76rem;
    --formula-alpha: 0.22;
  }

  .formula-13 {
    top: 48%;
    left: 72%;
    --formula-font-size: 0.68rem;
    --formula-alpha: 0.16;
  }

  .formula-16 {
    top: 29%;
    left: 67%;
    --formula-font-size: 0.69rem;
    --formula-alpha: 0.17;
  }

  .formula-19 {
    top: 35%;
    left: 9%;
    --formula-font-size: 0.72rem;
    --formula-alpha: 0.2;
  }

  .formula-20 {
    top: auto;
    bottom: 10%;
    left: 55%;
    right: auto;
    --formula-font-size: 0.72rem;
    --formula-alpha: 0.22;
  }

  .formula-22 {
    top: 78%;
    left: 60%;
    right: auto;
    --formula-font-size: 0.71rem;
    --formula-alpha: 0.2;
  }

  .dashboard-strip {
    grid-template-columns: 1fr;
    width: min(100% - 2rem, 1180px);
    gap: 0.85rem;
    margin: clamp(1.5rem, 5vh, 3rem) auto 1.75rem;
  }

  .dashboard-strip::before {
    margin-bottom: 0.15rem;
  }

  .stat-card {
    min-height: 3.85rem;
    padding: 0.72rem 0.82rem;
  }
}

@media (max-width: 420px) {
  .formula-22 {
    display: none;
  }

  .formula-1 {
    top: 52%;
    right: 4%;
    --formula-font-size: 0.72rem;
  }

  .formula-6 {
    top: 64%;
    left: 6%;
    --formula-font-size: 0.71rem;
  }

  .formula-11 {
    top: 74%;
    left: 12%;
  }

  .formula-19 {
    top: 34%;
    left: 10%;
  }

  .formula-20 {
    top: auto;
    bottom: 7%;
    left: 8%;
  }
}
</style>
