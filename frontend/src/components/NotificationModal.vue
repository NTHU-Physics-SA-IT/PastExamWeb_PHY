<template>
  <Dialog
    :visible="visible && total > 0"
    @update:visible="$emit('update:visible', $event)"
    modal
    :style="{ width: '620px', maxWidth: '92vw' }"
    :draggable="false"
    :blockScroll="true"
    :pt="{ root: { 'aria-label': $t('系統公告與通知'), 'aria-labelledby': null } }"
  >
    <template #header>
      <div class="flex align-items-center gap-2">
        <i class="pi pi-bell text-2xl" />
        <span class="text-xl font-semibold">{{ $t('系統公告與通知') }}</span>
        <Badge :value="total" severity="danger" />
      </div>
    </template>
    <div class="summary-list">
      <section v-if="summary.announcements?.length">
        <h3><i class="pi pi-megaphone mr-2" />{{ $t('公告') }}</h3>
        <article
          v-for="(item, itemIndex) in localizedAnnouncements"
          :key="`a-${item.id}`"
          class="summary-item"
          :class="{ 'summary-item--divided': itemIndex > 0 }"
        >
          <div class="summary-item__body">
            <strong>{{ item.title }}</strong>
            <small>{{ formatTimestamp(item.updated_at || item.created_at) }}</small>
            <p>{{ excerpt(item.body) }}</p>
          </div>
          <Button
            :label="$t('檢視')"
            size="small"
            outlined
            @click="$emit('view-announcement', item.id)"
          />
        </article>
      </section>
      <section v-if="summary.personal_notifications?.length">
        <h3><i class="pi pi-bell mr-2" />{{ $t('個人通知') }}</h3>
        <article
          v-for="(item, itemIndex) in localizedPersonalNotifications"
          :key="`p-${item.id}`"
          class="summary-item"
          :class="{ 'summary-item--divided': itemIndex > 0 }"
        >
          <div class="summary-item__body">
            <strong>{{ item.title }}</strong>
            <small>{{ formatTimestamp(item.created_at) }}</small>
            <p>{{ excerpt(item.message) }}</p>
          </div>
          <Button
            :label="$t('檢視')"
            size="small"
            outlined
            @click="$emit('view-personal', item.id)"
          />
        </article>
      </section>
    </div>
    <template #footer>
      <div class="summary-actions">
        <Button
          :label="$t('稍後再看')"
          severity="secondary"
          text
          @click="$emit('update:visible', false)"
        />
        <Button
          :label="$t('查看全部')"
          severity="secondary"
          outlined
          @click="$emit('open-center')"
        />
        <Button
          :label="$t('全部標記為已讀')"
          icon="pi pi-check-circle"
          @click="$emit('mark-all-read')"
        />
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { computed } from 'vue'
import { localizedPersonalNotification } from '@/utils/personalNotificationPresentation'
import {
  localizedAnnouncementContent,
  localizedAnnouncementTitle,
} from '@/utils/localizedDomainContent'
import { formatExactDateTime24h } from '@/utils/time'
const props = defineProps({ visible: Boolean, summary: { type: Object, required: true } })
defineEmits([
  'update:visible',
  'open-center',
  'mark-all-read',
  'view-announcement',
  'view-personal',
])
const total = computed(() => Number(props.summary?.counts?.total || 0))
const localizedAnnouncements = computed(() =>
  (props.summary?.announcements || []).map((item) => ({
    ...item,
    title: localizedAnnouncementTitle(item),
    body: localizedAnnouncementContent(item),
  }))
)
const localizedPersonalNotifications = computed(() =>
  (props.summary?.personal_notifications || []).map((item) => ({
    ...item,
    ...localizedPersonalNotification(item),
  }))
)
const excerpt = (value) =>
  String(value || '')
    .replace(/[#*_`>\n]/g, ' ')
    .trim()
    .slice(0, 120)
const formatTimestamp = (value) => formatExactDateTime24h(value)
</script>

<style scoped>
.summary-list {
  display: grid;
  gap: 1rem;
  max-height: 55vh;
  overflow-y: auto;
  padding-right: 0.25rem;
}
.summary-list h3 {
  margin: 0 0 0.5rem;
  font-size: 1rem;
}
.summary-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 0.75rem;
  align-items: center;
  padding: 0.75rem;
  border-inline-start: 3px solid var(--primary-color);
  background: var(--surface-ground);
  border-radius: var(--content-border-radius);
}
.summary-item--divided {
  margin-top: 0.6rem;
  border-top: 1px solid var(--border-color);
}
.summary-item__body {
  min-width: 0;
}
.summary-item strong,
.summary-item small {
  display: block;
}
.summary-item small {
  color: var(--text-color-secondary);
  margin-top: 0.2rem;
}
.summary-item p {
  margin: 0.35rem 0 0;
  overflow-wrap: anywhere;
}
.summary-actions {
  display: flex;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 0.5rem;
}
@media (max-width: 480px) {
  .summary-item {
    grid-template-columns: 1fr;
  }
  .summary-item .p-button {
    justify-self: end;
  }
}
</style>
