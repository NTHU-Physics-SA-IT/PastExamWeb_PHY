<template>
  <div class="not-found h-full flex align-items-center justify-content-center">
    <div class="text-center px-4 w-full max-w-md" :style="{ color: 'var(--text-secondary)' }">
      <Card class="border-round shadow-2" :style="{ backgroundColor: 'var(--bg-secondary)' }">
        <template #title>
          <div class="text-center">
            <div class="not-found-code text-red-400 mb-2">404</div>
            <div class="text-red-400 text-xl font-medium">{{ $t('頁面不存在') }}</div>
          </div>
        </template>
        <template #content>
          <p class="mb-4" :style="{ color: 'var(--text-secondary)' }">
            {{ $t('抱歉，我們找不到您要找的頁面。請確認網址是否正確或返回首頁。') }}
          </p>
          <Button
            :label="$t('返回首頁')"
            icon="pi pi-home"
            @click="goToHome"
            class="p-button-secondary"
          />
        </template>
      </Card>
    </div>
  </div>
</template>

<script>
export default {
  methods: {
    goToHome() {
      this.$router.push('/')
    },
  },
}
</script>

<style scoped>
.not-found {
  min-width: 0;
  overflow-x: hidden;
  background: var(--bg-primary);
}

.not-found-code {
  font-size: 3rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  line-height: 1;
}

:deep(.p-card) {
  background-color: var(--bg-secondary);
  color: var(--text-primary);
}

:deep(.p-card .p-card-title) {
  text-align: center;
}

:deep(.p-card .p-card-content) {
  padding-bottom: 0;
  text-align: center;
}
</style>
