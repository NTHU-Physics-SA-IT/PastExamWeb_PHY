<template>
  <main class="nthu-dev-login">
    <header>
      <p class="nthu-dev-login__eyebrow">Development only</p>
      <h1>NTHU OAuth Local QA</h1>
      <p>
        選擇固定測試身分，接著會走正式的 OAuth callback、access policy、Redis handoff 與 JWT
        exchange 流程。
      </p>
    </header>

    <Message v-if="errorMessage" severity="error" :closable="false">{{ errorMessage }}</Message>
    <ProgressSpinner v-else-if="loading" aria-label="載入測試身分" />
    <section v-else class="nthu-dev-login__grid" aria-label="NTHU OAuth 固定測試身分">
      <article v-for="profile in profiles" :key="profile.key" class="nthu-dev-login__card">
        <div>
          <span class="nthu-dev-login__status" :class="{ 'is-inactive': !profile.inschool }">
            {{ profile.inschool ? '在校' : '非在校' }}
          </span>
          <h2>{{ profile.label }}</h2>
          <p>{{ profile.name }}</p>
        </div>
        <dl>
          <div>
            <dt>userid</dt>
            <dd>{{ profile.userid || '—' }}</dd>
          </div>
          <div>
            <dt>系所</dt>
            <dd>{{ profile.department_name || '—' }}</dd>
          </div>
        </dl>
        <Button label="以此測試身分登入" icon="pi pi-sign-in" @click="startLogin(profile.key)" />
      </article>
    </section>
  </main>
</template>

<script setup>
import { onMounted, ref } from 'vue'

import { authService } from '../api'

const profiles = ref([])
const loading = ref(true)
const errorMessage = ref('')

onMounted(async () => {
  try {
    const data = await authService.getNthuDevProfiles()
    if (!Array.isArray(data?.profiles) || data.profiles.length !== 7) {
      throw new TypeError('Invalid NTHU development profile catalog')
    }
    profiles.value = data.profiles
  } catch (error) {
    console.error('Failed to load NTHU development profiles:', error)
    errorMessage.value = '無法載入 NTHU OAuth 測試身分。請確認 development mock 已明確啟用。'
  } finally {
    loading.value = false
  }
})

const startLogin = (profileKey) => authService.nthuDevLogin(profileKey)
</script>

<style scoped>
.nthu-dev-login {
  width: min(100% - 2rem, 1100px);
  margin: 0 auto;
  padding: 2rem 0 3rem;
}

.nthu-dev-login header {
  margin-bottom: 1.25rem;
}

.nthu-dev-login h1,
.nthu-dev-login h2,
.nthu-dev-login p {
  margin-top: 0;
}

.nthu-dev-login__eyebrow,
.nthu-dev-login__status {
  color: var(--primary-color);
  font-weight: 700;
}

.nthu-dev-login__grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 15rem), 1fr));
  gap: 1rem;
}

.nthu-dev-login__card {
  display: grid;
  gap: 1rem;
  min-width: 0;
  padding: 1rem;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: var(--bg-secondary);
}

.nthu-dev-login__status.is-inactive {
  color: var(--p-red-500);
}

.nthu-dev-login__card dl,
.nthu-dev-login__card dl div {
  display: grid;
  gap: 0.25rem;
  margin: 0;
}

.nthu-dev-login__card dl {
  gap: 0.65rem;
}

.nthu-dev-login__card dt {
  color: var(--text-secondary);
  font-size: 0.85rem;
}

.nthu-dev-login__card dd {
  min-width: 0;
  margin: 0;
  overflow-wrap: anywhere;
}
</style>
