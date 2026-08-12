<template>
  <main class="personal-settings-page">
    <section class="personal-settings-shell">
      <header class="settings-header">
        <h1>個人化設定</h1>
      </header>

      <div class="settings-layout">
        <aside class="settings-nav" aria-label="個人化設定目錄">
          <button
            v-for="item in navItems"
            :key="item.id"
            type="button"
            class="settings-nav-item"
            :class="[`settings-nav-item--${item.level}`, { active: activeSection === item.id }]"
            @click="scrollToSection(item.id)"
          >
            {{ item.label }}
          </button>
        </aside>

        <div class="settings-content">
          <section id="display-settings" class="settings-group settings-anchor">
            <div class="settings-group-header">
              <h2>顯示設定</h2>
              <p>調整網站閱讀與顯示偏好。</p>
            </div>

            <Card class="settings-section">
              <template #title>顯示設定</template>
              <template #content>
                <div class="settings-form display-settings-form">
                  <div class="display-settings-layout">
                    <div class="display-settings-controls">
                      <div id="font-size-setting" class="field settings-anchor font-size-setting">
                        <div class="font-size-controls">
                          <div class="font-size-control-header">
                            <label id="font-size-label">字體大小</label>
                            <span class="font-size-current">{{ fontSizeDisplayText }}</span>
                          </div>
                          <div class="font-size-slider-row">
                            <Slider
                              v-model="fontSizeScale"
                              :min="fontSizeMin"
                              :max="fontSizeMax"
                              :step="fontSizeStep"
                              class="font-size-slider"
                              aria-labelledby="font-size-label"
                            />
                          </div>
                          <small>偏好值會保存於此裝置，重新整理後仍會保留。</small>
                        </div>
                      </div>

                      <div id="language-setting" class="field settings-anchor language-setting">
                        <label for="language">語言</label>
                        <Select
                          id="language"
                          v-model="displayForm.language"
                          :options="languageOptions"
                          optionLabel="label"
                          optionValue="value"
                          class="w-full"
                        />
                        <small>語言功能目前僅為 UI placeholder，正式英文翻譯表之後才會提供。</small>
                      </div>
                    </div>

                    <div class="preview-sample-column">
                      <p class="preview-sample-label">範例顯示：</p>
                      <div class="font-size-preview">
                        <section class="preview-course-sample" aria-label="字體大小預覽">
                          <div class="preview-course-heading">
                            <Tag severity="secondary" class="subject-tag preview-tag">必修</Tag>
                            <div class="preview-course-title-block">
                              <h3>原子彈製作</h3>
                              <p>共 5 份考古題 · 最新：114下學期</p>
                            </div>
                          </div>
                          <div class="preview-meta-row">
                            <span>奧本海默</span>
                            <span>114下學期</span>
                            <span>期中考 / midterm2</span>
                          </div>

                          <div class="preview-filter-row">
                            <span class="preview-filter-chip">學期</span>
                            <span class="preview-filter-chip">教授：奧本海默</span>
                            <span class="preview-filter-chip">類型</span>
                            <span class="preview-filter-chip preview-filter-chip--check">
                              <i class="pi pi-check-square" aria-hidden="true"></i>
                              附解答
                            </span>
                          </div>

                          <article class="preview-archive-card">
                            <div class="preview-archive-main">
                              <Tag severity="secondary" class="exam-type-tag preview-tag">
                                期中考
                              </Tag>
                              <div>
                                <h4>midterm2</h4>
                                <p>奧本海默 · 考題目 · 0 次下載</p>
                              </div>
                            </div>
                            <div class="preview-actions">
                              <Button icon="pi pi-eye" label="預覽" size="small" outlined />
                              <Button icon="pi pi-download" label="下載" size="small" />
                              <Button
                                icon="pi pi-trash"
                                label="刪除"
                                size="small"
                                severity="danger"
                                outlined
                              />
                            </div>
                          </article>

                          <div class="preview-admin-tags">
                            <Tag class="soft-badge review-status-pending" severity="warning">
                              待審核
                            </Tag>
                            <Tag class="soft-badge submission-status-deleted" severity="danger">
                              已刪除
                            </Tag>
                            <Tag severity="success" class="preview-tag">啟用中</Tag>
                          </div>
                        </section>
                      </div>
                    </div>
                  </div>

                  <p class="autosave-hint">顯示偏好會自動儲存在此裝置。</p>
                </div>
              </template>
            </Card>
          </section>

          <section
            v-if="showAccountSettings"
            id="account-settings"
            class="settings-group settings-anchor"
          >
            <div class="settings-group-header">
              <h2>帳號設定</h2>
              <p>{{ accountSettingsDescription }}</p>
            </div>

            <Card id="profile-setting" class="settings-section settings-anchor">
              <template #title>基本資料</template>
              <template #content>
                <form class="settings-form" @submit.prevent="saveProfile">
                  <div class="field">
                    <label for="display-name">名稱</label>
                    <InputText
                      id="display-name"
                      name="display-name"
                      v-model="profileForm.name"
                      class="w-full"
                      maxlength="15"
                      :disabled="profileLoading || !canEditProfile"
                    />
                    <small v-if="canEditProfile">最多 15 字，會優先作為站內顯示名稱。</small>
                  </div>

                  <div class="field">
                    <label for="email">電子郵件</label>
                    <InputText
                      id="email"
                      name="email"
                      v-model="profileForm.email"
                      class="w-full"
                      readonly
                    />
                  </div>

                  <small v-if="!canEditProfile" class="oauth-profile-helper">
                    此資料由清華校務系統提供，無法在本站修改。
                  </small>

                  <div v-if="canEditProfile" class="form-actions">
                    <Button
                      class="profile-save-button"
                      label="儲存基本資料"
                      icon="pi pi-save"
                      type="submit"
                      :loading="profileSaving"
                      :disabled="profileLoading || !canSaveProfile"
                    />
                  </div>
                </form>
              </template>
            </Card>

            <Card
              v-if="showPasswordSettings"
              id="password-setting"
              class="settings-section settings-anchor"
            >
              <template #title>密碼設定</template>
              <template #content>
                <form class="settings-form" @submit.prevent="savePassword">
                  <div class="field">
                    <label for="current-password">目前密碼</label>
                    <Password
                      inputId="current-password"
                      name="current-password"
                      v-model="passwordForm.currentPassword"
                      class="w-full"
                      inputClass="w-full"
                      toggleMask
                      :feedback="false"
                    />
                  </div>

                  <div class="field">
                    <label for="new-password">新密碼</label>
                    <Password
                      inputId="new-password"
                      name="new-password"
                      v-model="passwordForm.newPassword"
                      class="w-full"
                      inputClass="w-full"
                      toggleMask
                    />
                  </div>

                  <div class="field">
                    <label for="confirm-password">確認新密碼</label>
                    <Password
                      inputId="confirm-password"
                      name="confirm-password"
                      v-model="passwordForm.confirmPassword"
                      class="w-full"
                      inputClass="w-full"
                      toggleMask
                      :feedback="false"
                      :invalid="Boolean(passwordMismatch)"
                    />
                    <small v-if="passwordMismatch" class="field-error">{{
                      passwordMismatch
                    }}</small>
                  </div>

                  <div class="form-actions">
                    <Button
                      label="儲存密碼"
                      icon="pi pi-key"
                      type="submit"
                      :disabled="!canSubmitPassword"
                    />
                  </div>
                </form>
              </template>
            </Card>
          </section>
        </div>
      </div>
    </section>
  </main>
</template>

<script>
import { userService } from '../api'
import { getLocalItem, setLocalItem } from '../utils/storage'
import {
  APP_FONT_BASELINE,
  FONT_SIZE_MAX,
  FONT_SIZE_MIN,
  FONT_SIZE_STEP,
  USER_SCALE_DEFAULT_PERCENT,
  getFontSizePreference,
  setFontSizePreference,
} from '../utils/fontSizePreference'
import { useToast } from 'primevue/usetoast'

const LANGUAGE_KEY = 'personal-settings-language'

export default {
  name: 'PersonalSettings',
  setup() {
    const toast = useToast()

    return {
      toast,
    }
  },
  data() {
    return {
      isLocalAccount: null,
      profileLoaded: false,
      profileLoading: true,
      profileSaving: false,
      originalName: '',
      profileForm: {
        name: '',
        email: '',
      },
      passwordForm: {
        currentPassword: '',
        newPassword: '',
        confirmPassword: '',
      },
      displayForm: {
        fontSize: getFontSizePreference(),
        language: getLocalItem(LANGUAGE_KEY) || 'zh-TW',
      },
      fontSizeScale: getFontSizePreference(),
      fontSizeMin: FONT_SIZE_MIN,
      fontSizeMax: FONT_SIZE_MAX,
      fontSizeStep: FONT_SIZE_STEP,
      activeSection: 'display-settings',
      sectionObserver: null,
      languageOptions: [
        { label: '繁體中文', value: 'zh-TW' },
        { label: 'English', value: 'en' },
      ],
    }
  },
  computed: {
    showAccountSettings() {
      return this.profileLoaded
    },
    canEditProfile() {
      return this.isLocalAccount === true
    },
    showPasswordSettings() {
      return this.isLocalAccount === true
    },
    accountSettingsDescription() {
      return this.isLocalAccount
        ? '管理名稱、電子郵件與密碼。'
        : '查看由清華校務系統提供的帳號資料。'
    },
    navItems() {
      const items = [
        { id: 'display-settings', label: '顯示設定', level: 'group' },
        { id: 'font-size-setting', label: '字體大小', level: 'item' },
        { id: 'language-setting', label: '語言', level: 'item' },
      ]

      if (this.showAccountSettings) {
        items.push(
          { id: 'account-settings', label: '帳號設定', level: 'group' },
          { id: 'profile-setting', label: '基本資料', level: 'item' }
        )
        if (this.showPasswordSettings) {
          items.push({ id: 'password-setting', label: '密碼設定', level: 'item' })
        }
      }

      return items
    },
    fontSizePercent() {
      return Math.round(this.fontSizeScale * APP_FONT_BASELINE)
    },
    fontSizeToneLabel() {
      const defaultDisplayPercent = Math.round(USER_SCALE_DEFAULT_PERCENT * APP_FONT_BASELINE)
      if (this.fontSizePercent < defaultDisplayPercent) {
        return '偏小'
      }
      if (this.fontSizePercent > defaultDisplayPercent) {
        return '偏大'
      }
      return '預設'
    },
    fontSizeDisplayText() {
      return `目前大小：${this.fontSizePercent}%（${this.fontSizeToneLabel}）`
    },
    canSaveProfile() {
      return (
        this.canEditProfile &&
        Boolean(this.profileForm.name.trim()) &&
        this.profileForm.name.trim() !== this.originalName
      )
    },
    passwordMismatch() {
      if (!this.passwordForm.confirmPassword) {
        return ''
      }

      return this.passwordForm.newPassword === this.passwordForm.confirmPassword
        ? ''
        : '兩次輸入的新密碼不一致'
    },
    canSubmitPassword() {
      return (
        Boolean(this.passwordForm.currentPassword) &&
        Boolean(this.passwordForm.newPassword) &&
        Boolean(this.passwordForm.confirmPassword) &&
        !this.passwordMismatch
      )
    },
  },
  watch: {
    fontSizeScale(value) {
      const scale = setFontSizePreference(value)
      this.displayForm.fontSize = scale
    },
    'displayForm.language'(value) {
      // TODO: Wire language preference to i18n after the official English translation table is provided.
      setLocalItem(LANGUAGE_KEY, value)
    },
  },
  async mounted() {
    await this.loadProfile()
    await this.$nextTick()
    this.setupSectionObserver()
  },
  beforeUnmount() {
    this.teardownSectionObserver()
  },
  methods: {
    scrollToSection(sectionId) {
      const target = document.getElementById(sectionId)
      if (!target) {
        return
      }

      target.scrollIntoView({ behavior: 'smooth', block: 'start' })
      this.activeSection = sectionId
    },

    setupSectionObserver() {
      this.teardownSectionObserver()

      if (typeof IntersectionObserver === 'undefined') {
        return
      }

      const targets = this.navItems.map((item) => document.getElementById(item.id)).filter(Boolean)
      const root = document.querySelector('.content-container')

      this.sectionObserver = new IntersectionObserver(
        (entries) => {
          const visible = entries
            .filter((entry) => entry.isIntersecting)
            .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)

          if (visible[0]?.target?.id) {
            this.activeSection = visible[0].target.id
          }
        },
        {
          root,
          rootMargin: '-16% 0px -68% 0px',
          threshold: [0, 0.2, 0.6],
        }
      )

      targets.forEach((target) => this.sectionObserver.observe(target))
    },

    teardownSectionObserver() {
      if (this.sectionObserver) {
        this.sectionObserver.disconnect()
        this.sectionObserver = null
      }
    },

    async loadProfile() {
      this.profileLoading = true
      this.profileLoaded = false
      this.isLocalAccount = null

      try {
        const { data } = await userService.getMe()
        this.isLocalAccount = data?.is_local === true
        const displayName = (data?.nickname || data?.name || '').trim()
        this.originalName = displayName
        this.profileForm.name = displayName
        this.profileForm.email = (data?.email || this.profileForm.email || '').trim()
        this.profileLoaded = true
      } catch (error) {
        console.error('Load profile failed:', error)
      } finally {
        this.profileLoading = false
      }
    },

    async saveProfile() {
      if (!this.canEditProfile) {
        return
      }

      const nextName = this.profileForm.name.trim()
      if (!nextName || nextName === this.originalName) {
        return
      }

      this.profileSaving = true
      try {
        const { data } = await userService.updateMyNickname(nextName)
        const savedName = (data?.nickname || data?.name || nextName).trim()
        this.originalName = savedName
        this.profileForm.name = savedName
        this.profileForm.email = (data?.email || this.profileForm.email || '').trim()
        this.toast.add({
          severity: 'success',
          summary: '儲存成功',
          detail: '基本資料已更新',
          life: 2500,
        })
      } catch (error) {
        console.error('Save profile failed:', error)
        const detail = error?.response?.data?.detail
        this.toast.add({
          severity: 'error',
          summary: '更新失敗',
          detail:
            typeof detail === 'string' && detail.trim() ? detail : '無法更新基本資料，請稍後再試',
          life: 3000,
        })
      } finally {
        this.profileSaving = false
      }
    },

    savePassword() {
      if (!this.canSubmitPassword) {
        return
      }

      // TODO: Connect to a password update API when the backend endpoint is available.
      console.info('Password update is a UI placeholder until the backend API is ready.')
      this.passwordForm = {
        currentPassword: '',
        newPassword: '',
        confirmPassword: '',
      }
      this.toast.add({
        severity: 'info',
        summary: '尚未送出',
        detail: '密碼 API 尚未接入，已先保留前端表單。',
        life: 3000,
      })
    },
  },
}
</script>

<style scoped>
.personal-settings-page {
  min-height: 100%;
  background: var(--bg-primary);
  color: var(--text-primary);
}

.personal-settings-shell {
  width: min(100%, 1040px);
  margin: 0 auto;
  padding: 2.25rem 1.5rem 3.5rem;
}

.settings-header {
  margin-bottom: 1.25rem;
}

h1 {
  margin: 0;
  color: var(--text-primary);
  font-size: calc(var(--app-font-size-base) * 1.75);
  font-weight: 760;
  letter-spacing: 0;
}

.settings-layout {
  display: grid;
  grid-template-columns: minmax(13rem, 0.26fr) minmax(0, 1fr);
  gap: clamp(1rem, 2.2vw, 2rem);
  align-items: start;
}

.settings-nav {
  position: sticky;
  top: 1rem;
  display: grid;
  gap: 0.2rem;
  padding: 0.35rem;
  border: 1px solid color-mix(in srgb, var(--border-color) 82%, transparent);
  border-radius: 8px;
  background: color-mix(in srgb, var(--bg-secondary) 82%, transparent);
}

.settings-nav-item {
  width: 100%;
  min-height: 2.1em;
  padding: 0.35rem 0.6rem;
  border: 0;
  border-radius: 6px;
  color: var(--text-secondary);
  background: transparent;
  font: inherit;
  font-size: var(--app-font-size-sm);
  line-height: 1.35;
  text-align: left;
  cursor: pointer;
  overflow-wrap: normal;
  word-break: keep-all;
}

.settings-nav-item:hover,
.settings-nav-item.active {
  color: var(--text-primary);
  background: color-mix(in srgb, var(--text-primary) 9%, transparent);
}

.settings-nav-item.active {
  box-shadow: inset 3px 0 0 color-mix(in srgb, var(--title-gradient-start) 72%, transparent);
}

.settings-nav-item--item {
  padding-left: 1.25rem;
  font-size: calc(var(--app-font-size-base) * 0.86);
}

.settings-content {
  min-width: 0;
}

.settings-anchor {
  scroll-margin-top: 1rem;
}

.settings-group {
  padding-top: 0.5rem;
}

.settings-group + .settings-group {
  margin-top: 2rem;
  padding-top: 2rem;
  border-top: 1px solid var(--border-color);
}

.settings-group-header {
  max-width: 640px;
  margin-bottom: 0.85rem;
}

.settings-group-header h2 {
  margin: 0;
  color: var(--text-primary);
  font-size: calc(var(--app-font-size-base) * 1.18);
  font-weight: 760;
  letter-spacing: 0;
}

.settings-group-header p {
  margin: 0.35rem 0 0;
  color: var(--text-secondary);
  font-size: var(--app-font-size-base);
  line-height: 1.6;
}

.settings-section {
  border: 1px solid color-mix(in srgb, var(--border-color) 82%, transparent);
  border-radius: 8px;
  background: color-mix(in srgb, var(--bg-secondary) 92%, var(--bg-primary));
  box-shadow: 0 10px 28px rgba(15, 23, 42, 0.04);
}

.settings-section :deep(.p-card-body) {
  padding: 1.15rem;
}

.settings-section :deep(.p-card-title) {
  color: var(--text-primary);
  font-size: calc(var(--app-font-size-base) * 1.03);
  font-weight: 740;
  letter-spacing: 0;
}

#display-settings .settings-section :deep(.p-card-title) {
  display: flex;
  align-items: center;
  min-height: 28px;
  line-height: 28px;
}

.settings-section :deep(.p-card-content) {
  padding-top: 0.9rem;
}

.settings-section + .settings-section {
  margin-top: 1.25rem;
}

.settings-form {
  display: grid;
  gap: 1.25rem;
  width: min(100%, 640px);
}

.display-settings-form {
  width: 100%;
  container-type: inline-size;
}

.display-settings-layout,
.settings-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1rem;
}

.display-settings-layout {
  grid-template-columns: minmax(18rem, 0.9fr) minmax(20rem, 1.1fr);
  align-items: start;
  gap: 1rem 1.15rem;
}

.display-settings-controls {
  display: grid;
  gap: 0.95rem;
  min-width: 0;
}

.field {
  display: grid;
  gap: 0.45rem;
  margin: 0;
}

.font-size-setting {
  min-width: 0;
}

.language-setting {
  min-width: 0;
}

.font-size-controls {
  display: grid;
  grid-template-rows: 88px 36px auto;
  gap: 8px;
  min-width: 0;
}

.font-size-control-header {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 4px;
  align-items: start;
  min-height: 0;
  overflow: visible;
}

.font-size-control-header label {
  min-width: max-content;
  white-space: nowrap;
  line-height: 1.25;
}

.font-size-slider-row {
  display: flex;
  align-items: center;
  width: 100%;
  height: 36px;
  min-height: 36px;
  min-width: min(100%, 14rem);
}

.font-size-slider {
  width: 100%;
  min-height: 1rem;
  min-width: min(100%, 14rem);
  flex: 1 1 auto;
  align-self: center;
}

.font-size-slider.p-slider,
.font-size-slider :deep(.p-slider) {
  align-self: center;
  width: 100%;
}

.font-size-slider.p-slider {
  height: 4px !important;
  min-height: 4px !important;
  margin: 0;
}

.font-size-slider :deep(.p-slider-range) {
  top: 0 !important;
  height: 4px !important;
}

.font-size-controls > small {
  display: block;
  line-height: 1.35;
}

.font-size-current {
  color: var(--text-primary);
  font-weight: 700;
  line-height: 1.25;
  justify-self: start;
  text-align: left;
  max-width: 100%;
  overflow-wrap: normal;
  word-break: keep-all;
}

.preview-sample-column {
  display: grid;
  gap: 0.45rem;
  min-width: 0;
}

.preview-sample-label {
  margin: 0;
  color: var(--text-secondary);
  font-size: var(--app-font-size-sm);
  font-weight: 650;
  line-height: 1.35;
}

.font-size-preview {
  display: grid;
  gap: 0.65em;
  padding: 1rem;
  border: 1px solid color-mix(in srgb, var(--border-color) 82%, transparent);
  border-radius: 8px;
  background: color-mix(in srgb, var(--bg-primary) 72%, var(--bg-secondary));
  font-size: 1rem;
  box-shadow: inset 0 1px 0 color-mix(in srgb, #ffffff 22%, transparent);
  min-width: 0;
}

.preview-course-sample {
  display: grid;
  gap: 0.75em;
  min-width: 0;
}

.preview-course-heading {
  display: flex;
  gap: 0.6em;
  align-items: flex-start;
  min-width: 0;
}

.preview-course-title-block {
  min-width: 0;
}

.font-size-preview h3,
.font-size-preview h4 {
  margin: 0;
  color: var(--text-primary);
  font-size: 1.08em;
  font-weight: 760;
  letter-spacing: 0;
  line-height: 1.25;
}

.font-size-preview p {
  margin: 0;
  color: var(--text-secondary);
  line-height: 1.5;
}

.preview-meta-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35em 0.65em;
  color: var(--text-secondary);
  font-size: 0.82em;
  font-weight: 650;
  line-height: 1.35;
}

.preview-meta-row span + span::before {
  content: '';
  display: inline-block;
  width: 0.22em;
  height: 0.22em;
  margin-right: 0.65em;
  border-radius: 50%;
  vertical-align: middle;
  background: color-mix(in srgb, var(--text-secondary) 65%, transparent);
}

.preview-filter-row,
.preview-actions,
.preview-admin-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45em;
  min-width: 0;
}

.preview-filter-chip {
  display: inline-flex;
  gap: 0.35em;
  align-items: center;
  min-height: 1.9em;
  padding: 0.28em 0.62em;
  border: 1px solid color-mix(in srgb, var(--border-color) 88%, transparent);
  border-radius: 6px;
  color: var(--text-primary);
  background: color-mix(in srgb, var(--bg-secondary) 78%, transparent);
  font-size: 0.88em;
  line-height: 1.25;
}

.preview-archive-card {
  display: grid;
  gap: 0.65em;
  padding: 0.75em;
  border: 1px solid color-mix(in srgb, var(--border-color) 78%, transparent);
  border-radius: 8px;
  background: color-mix(in srgb, var(--bg-secondary) 68%, transparent);
}

.preview-archive-main {
  display: flex;
  gap: 0.55em;
  align-items: flex-start;
  min-width: 0;
}

.font-size-preview :deep(.p-button) {
  min-height: 2.25em;
  padding: 0.42em 0.68em;
  font-size: 0.88em;
  line-height: 1.25;
}

.font-size-preview :deep(.p-button-label),
.font-size-preview :deep(.p-button-icon) {
  font-size: inherit;
  line-height: 1;
}

.font-size-preview :deep(.pi) {
  font-size: 1em;
}

.font-size-preview :deep(.p-tag),
.font-size-preview .preview-tag,
.font-size-preview .soft-badge {
  min-height: 1.65em !important;
  padding: 0.22em 0.55em !important;
  font-size: 0.82em !important;
  line-height: 1.2 !important;
  white-space: normal;
}

.autosave-hint {
  margin: 0;
  color: var(--text-secondary);
  font-size: var(--app-font-size-sm);
  line-height: 1.5;
}

label {
  color: var(--text-primary);
  font-weight: 650;
}

small {
  color: var(--text-secondary);
}

.field-error {
  color: #dc2626;
}

.dark .field-error {
  color: #fca5a5;
}

.form-actions {
  display: flex;
  justify-content: flex-start;
}

.oauth-profile-helper {
  display: block;
  line-height: 1.5;
}

@media (max-width: 980px) {
  .settings-layout {
    display: grid;
    grid-template-columns: 1fr;
    gap: 1rem;
  }

  .settings-nav {
    position: static;
    display: flex;
    gap: 0.35rem;
    padding: 0.35rem;
    overflow-x: auto;
  }

  .settings-nav-item {
    width: auto;
    flex: 0 0 auto;
    white-space: normal;
    min-height: 2.35em;
  }

  .settings-nav-item.active {
    box-shadow: inset 0 -3px 0 color-mix(in srgb, var(--title-gradient-start) 72%, transparent);
  }

  .settings-nav-item--item {
    padding-left: 0.6rem;
  }
}

@container (max-width: 680px) {
  .display-settings-layout {
    grid-template-columns: 1fr;
  }

  .font-size-controls {
    grid-template-rows: 96px 36px auto;
  }
}

@media (max-width: 640px) {
  .personal-settings-shell {
    padding: 1.25rem 0.75rem 2rem;
  }

  .form-actions {
    justify-content: stretch;
  }

  .display-settings-layout,
  .settings-grid {
    grid-template-columns: 1fr;
  }

  .font-size-slider-row {
    min-width: 100%;
  }

  .font-size-controls {
    grid-template-rows: 104px 36px auto;
  }

  .form-actions :deep(.p-button) {
    width: 100%;
  }
}
</style>
