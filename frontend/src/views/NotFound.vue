<template>
  <div class="not-found h-full flex align-items-center justify-content-center">
    <div class="not-found-panel text-center px-4 w-full max-w-md">
      <Card class="not-found-card border-round shadow-2">
        <template #title>
          <div class="not-found-heading text-center">
            <div class="not-found-code mb-2">404</div>
            <div class="not-found-title text-xl font-medium">
              {{ $t('頁面不存在') }}
            </div>
          </div>
        </template>
        <template #content>
          <p class="not-found-message mb-4">
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

.not-found-panel,
.not-found-message {
  color: var(--text-secondary);
}

.not-found-code,
.not-found-title {
  color: #f87171;
}

.not-found-code {
  font-size: 3rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  line-height: 1;
}

:deep(.not-found-card) {
  background-color: var(--bg-secondary);
  color: var(--text-primary);
}

:deep(.not-found-card .p-card-title) {
  text-align: center;
}

:deep(.not-found-card .p-card-content) {
  padding-bottom: 0;
  text-align: center;
}
</style>

<style>
html[data-effective-theme='christmas'] .not-found {
  background: transparent;
}

html[data-effective-theme='christmas'] .not-found .not-found-panel {
  color: #f5eedc;
}

html[data-effective-theme='christmas'] .not-found .not-found-card {
  border: 1px solid rgba(222, 199, 142, 0.46);
  border-left: 0.25rem solid #793941;
  background: #3e5f72;
  color: #f8f2e8;
}

html[data-effective-theme='christmas'] .not-found .not-found-card .p-card-title {
  padding: 0.9rem;
  border-bottom: 1px solid rgba(222, 199, 142, 0.38);
  border-radius: 0.45rem;
  background: #293f52;
}

html[data-effective-theme='christmas'] .not-found :is(.not-found-code, .not-found-title) {
  color: #f8f2e8;
}

html[data-effective-theme='christmas'] .not-found .not-found-message {
  color: #f5eedc;
}
</style>
