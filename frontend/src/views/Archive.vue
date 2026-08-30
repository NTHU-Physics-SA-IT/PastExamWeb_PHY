<template>
  <div
    class="h-full archive-screen"
    :class="{ 'archive-dark': isDarkTheme }"
    ref="archiveView"
    @toggle-sidebar="toggleSidebar"
  >
    <div class="flex h-full relative">
      <!-- Desktop/Tablet Sidebar -->
      <div class="sidebar hidden md:block" :class="{ collapsed: !sidebarVisible }">
        <div class="sidebar-shell">
          <!-- Fixed search section -->
          <div class="search-section p-3">
            <div class="relative w-full">
              <i class="pi pi-search absolute left-4 top-1/2 -mt-2 text-500"></i>
              <InputText
                id="archive-course-search"
                name="archive-course-search"
                v-model="searchQuery"
                :placeholder="$t('搜尋課程')"
                class="w-full pl-6"
              />
            </div>
          </div>

          <!-- Scrollable content section -->
          <div class="course-list-section p-3 pt-0">
            <div v-if="searchQuery" class="search-results">
              <div v-if="filteredCategories.length === 0" class="p-3 text-center text-500">
                <i class="pi pi-search text-2xl mb-2"></i>
                <div>{{ $t('查無搜尋結果') }}</div>
              </div>
              <div v-for="category in filteredCategories" :key="category.label" class="mb-2">
                <div class="text-sm mb-1" style="color: var(--text-secondary)">
                  {{ category.label }}
                </div>
                <div class="flex flex-col gap-1">
                  <Button
                    v-for="course in category.items"
                    :key="course.label"
                    :class="[
                      'p-button-text search-result-btn text-color',
                      { 'active-course-search-result': selectedCourse === course.id },
                    ]"
                    @click="filterBySubject({ label: course.label, id: course.id })"
                  >
                    <span class="ellipsis">{{ course.label }}</span>
                  </Button>
                </div>
              </div>
            </div>
            <PanelMenu
              v-else
              :model="menuItems"
              :expandedKeys="expandedMenuItems"
              @update:expandedKeys="expandedMenuItems = $event"
              class="w-full"
            />
          </div>

          <!-- Fixed upload section for desktop -->
          <div v-if="isAuthenticatedRef" class="upload-section p-3">
            <div class="upload-actions">
              <Button
                icon="pi pi-cloud-upload"
                :label="$t('上傳考古題')"
                severity="success"
                @click="openUploadDialog"
                class="w-full"
                size="small"
              />
              <Button
                icon="pi pi-sparkles"
                :label="$t('考古許願池')"
                severity="secondary"
                outlined
                @click="wishPoolActive = true"
                class="w-full"
                size="small"
              />
              <Button
                icon="pi pi-list-check"
                :label="$t('我的考古投稿')"
                severity="secondary"
                outlined
                @click="openSubmissionStatus"
                class="w-full"
                size="small"
              />
            </div>
          </div>
        </div>
      </div>

      <!-- Mobile Drawer -->
      <Drawer
        v-if="isMobile"
        :visible="sidebarVisible"
        @update:visible="sidebarVisible = $event"
        :class="['mobile-drawer', { 'mobile-drawer-dark': isDarkTheme }]"
        position="left"
        :style="{ width: 'min(100vw, 26rem)' }"
        :autoFocus="false"
        :pt="{
          mask: {
            class: isDarkTheme
              ? 'mobile-drawer-mask mobile-drawer-mask-dark'
              : 'mobile-drawer-mask',
          },
        }"
      >
        <template #header>
          <div class="flex justify-content-between align-items-center w-full">
            <span class="font-semibold">{{ $t('選單') }}</span>
          </div>
        </template>
        <div class="flex flex-column h-full">
          <!-- Fixed search section -->
          <div class="search-section pb-3">
            <div class="relative w-full">
              <i class="pi pi-search absolute left-4 top-1/2 -mt-2 text-500"></i>
              <InputText
                id="archive-mobile-course-search"
                name="archive-mobile-course-search"
                v-model="searchQuery"
                :placeholder="$t('搜尋課程')"
                class="w-full pl-6"
              />
            </div>
          </div>

          <!-- Scrollable course selection section -->
          <div class="flex-1 overflow-auto">
            <div v-if="searchQuery" class="search-results">
              <div v-if="filteredCategories.length === 0" class="p-3 text-center text-500">
                <i class="pi pi-search text-2xl mb-2"></i>
                <div>{{ $t('查無搜尋結果') }}</div>
              </div>
              <div v-for="category in filteredCategories" :key="category.label" class="mb-2">
                <div class="text-sm mb-1" style="color: var(--text-secondary)">
                  {{ category.label }}
                </div>
                <div class="flex flex-col gap-1">
                  <Button
                    v-for="course in category.items"
                    :key="course.label"
                    :class="[
                      'p-button-text search-result-btn text-color',
                      { 'active-course-search-result': selectedCourse === course.id },
                    ]"
                    @click="
                      () => {
                        filterBySubject({ label: course.label, id: course.id })
                        sidebarVisible = false
                      }
                    "
                  >
                    <span class="ellipsis">{{ course.label }}</span>
                  </Button>
                </div>
              </div>
            </div>
            <PanelMenu v-else :model="mobileMenuItems" multiple class="w-full" />
          </div>

          <div v-if="isAuthenticatedRef" class="upload-section mobile-upload-section">
            <div class="upload-actions">
              <Button
                icon="pi pi-cloud-upload"
                :label="$t('上傳考古題')"
                severity="success"
                @click="openUploadFromMobileMenu"
                class="w-full"
                size="small"
              />
              <Button
                icon="pi pi-sparkles"
                :label="$t('考古許願池')"
                severity="secondary"
                outlined
                @click="openWishPoolFromMobileMenu"
                class="w-full"
                size="small"
              />
              <Button
                icon="pi pi-list-check"
                :label="$t('我的考古投稿')"
                severity="secondary"
                outlined
                @click="openSubmissionStatusFromMobileMenu"
                class="w-full"
                size="small"
              />
            </div>
          </div>
        </div>
      </Drawer>

      <div class="main-content flex-1 h-full overflow-auto">
        <div class="card h-full flex flex-col">
          <WishPool
            v-if="wishPoolActive"
            :coursesList="coursesList"
            :courseCategories="courseCategories"
            @add-wish="showWishDialog = true"
            @help-upload="openWishHelpUpload"
          />
          <template v-else>
            <div v-if="selectedSubject" class="subject-header">
              <div class="subject-heading-row">
                <Tag severity="secondary" class="subject-tag">
                  {{ currentCategoryLabel }}
                </Tag>
                <div class="subject-title-stack">
                  <div class="subject-title">{{ selectedSubject }}</div>
                  <div v-if="currentCourseEnglishName" class="subject-english-name">
                    {{ currentCourseEnglishName }}
                  </div>
                </div>
                <div class="subject-summary">
                  <span class="subject-summary-item">{{
                    $t('共 {count} 份考古題', { count: archiveTotalCount })
                  }}</span>
                  <span class="subject-summary-separator" aria-hidden="true">・</span>
                  <span class="subject-summary-item">{{
                    $t('最新：{year}', { year: latestAcademicTerm })
                  }}</span>
                </div>
              </div>
            </div>
            <Toolbar v-if="selectedSubject" class="archive-filter-bar mx-3 mt-3 mb-2">
              <template #start>
                <div class="archive-filter-shell">
                  <div class="filter-summary">
                    {{
                      $t('目前顯示：{course} · 共 {count} 份考古題', {
                        course: selectedSubject,
                        count: filteredArchiveCount,
                      })
                    }}
                  </div>
                  <div class="archive-filter-controls">
                    <Select
                      inputId="archive-filter-year"
                      name="archive-filter-year"
                      v-model="filters.year"
                      :options="years"
                      optionLabel="name"
                      optionValue="code"
                      :placeholder="$t('學期')"
                      class="filter-select"
                      showClear
                      filter
                    />
                    <Select
                      inputId="archive-filter-professor"
                      name="archive-filter-professor"
                      v-model="filters.professor"
                      :options="professors"
                      optionLabel="name"
                      optionValue="code"
                      :placeholder="$t('教授')"
                      class="filter-select"
                      showClear
                      filter
                    />
                    <Select
                      inputId="archive-filter-type"
                      name="archive-filter-type"
                      v-model="filters.type"
                      :options="archiveTypes"
                      optionLabel="name"
                      optionValue="code"
                      :placeholder="$t('類型')"
                      class="filter-select"
                      showClear
                    />
                    <div class="answer-filter">
                      <Checkbox
                        v-model="filters.hasAnswers"
                        :binary="true"
                        inputId="hasAnswersFilter"
                        name="has-answers-filter"
                      />
                      <label for="hasAnswersFilter">{{ $t('附解答') }}</label>
                    </div>
                  </div>
                </div>
              </template>
            </Toolbar>

            <ProgressSpinner
              v-if="loading"
              class="w-full flex justify-content-center mt-4"
              strokeWidth="4"
            />

            <div v-else>
              <div v-if="selectedSubject">
                <Accordion
                  v-model:value="expandedPanels"
                  multiple
                  class="max-w-[calc(100%-2rem)] mx-auto"
                >
                  <AccordionPanel
                    v-for="group in groupedArchives"
                    :key="group.year"
                    :value="group.year.toString()"
                  >
                    <AccordionHeader>
                      <div class="term-header-content">
                        <span class="term-title">{{ formatAcademicTerm(group.year) }}</span>
                        <span class="term-count">{{
                          $t('共 {count} 份', { count: group.list.length })
                        }}</span>
                      </div>
                    </AccordionHeader>
                    <AccordionContent>
                      <div class="archive-card-grid">
                        <article
                          v-for="data in group.list"
                          :key="data.id"
                          class="archive-record-card"
                        >
                          <div class="archive-record-content">
                            <div class="archive-record-line archive-record-primary-line">
                              <div class="archive-record-title-group">
                                <Tag
                                  :severity="archiveTypeConfig[data.type]?.severity || 'secondary'"
                                  class="exam-type-tag"
                                >
                                  {{ archiveTypeConfig[data.type]?.name || data.type }}
                                </Tag>
                                <h3>{{ data.name }}</h3>
                              </div>
                              <div class="archive-record-actions">
                                <Button
                                  icon="pi pi-eye"
                                  @click="previewArchive(data)"
                                  size="small"
                                  severity="secondary"
                                  :label="$t('預覽')"
                                  outlined
                                  :aria-label="$t('預覽')"
                                  :title="$t('預覽')"
                                  class="archive-action-preview"
                                />
                                <Button
                                  icon="pi pi-download"
                                  @click="downloadArchive(data)"
                                  size="small"
                                  severity="success"
                                  :label="$t('下載')"
                                  :loading="downloadingId === data.id"
                                  :aria-label="$t('下載')"
                                  :title="$t('下載')"
                                  class="archive-action-download"
                                />
                                <Button
                                  v-if="canEditArchive(data)"
                                  icon="pi pi-pencil"
                                  @click="openEditDialog(data)"
                                  size="small"
                                  severity="secondary"
                                  :label="$t('編輯')"
                                  outlined
                                  :aria-label="$t('編輯')"
                                  :title="$t('編輯')"
                                  class="archive-action-edit"
                                />
                                <Button
                                  v-if="canDeleteArchive(data)"
                                  icon="pi pi-trash"
                                  @click="confirmDelete(data)"
                                  size="small"
                                  severity="danger"
                                  :label="$t('刪除')"
                                  outlined
                                  :aria-label="$t('刪除')"
                                  :title="$t('刪除')"
                                  class="archive-action-delete archive-action-danger admin-danger-outline-button danger-outline-button"
                                />
                              </div>
                            </div>
                            <div class="archive-record-line archive-record-meta-line">
                              <span>{{ data.professor }}</span>
                              <span>{{ formatAnswerStatus(data) }}</span>
                              <span>{{
                                $t('{count} 次下載', {
                                  count: formatDownloadCount(data.downloadCount),
                                })
                              }}</span>
                              <span v-if="formatSourceSubmissionIds(data)">
                                {{
                                  $t('投稿編號：{ids}', { ids: formatSourceSubmissionIds(data) })
                                }}
                              </span>
                            </div>
                          </div>
                        </article>
                      </div>
                    </AccordionContent>
                  </AccordionPanel>
                </Accordion>
              </div>
              <div
                v-else
                class="flex flex-column align-items-center justify-content-center h-full"
                style="min-height: calc(100vh - 200px)"
              >
                <i class="pi pi-book text-6xl" style="color: var(--text-secondary)"></i>
                <div class="text-xl font-medium mt-4" style="color: var(--text-secondary)">
                  {{ $t('請從左側選單選擇課程') }}
                </div>
                <div class="text-sm mt-2" style="color: var(--text-secondary)">
                  {{ $t('選擇課程後即可瀏覽相關考古題') }}
                </div>
              </div>
            </div>
          </template>

          <PdfPreviewModal
            :visible="showPreview"
            @update:visible="showPreview = $event"
            :courseId="selectedCourse"
            :archiveId="selectedArchive?.id"
            :previewUrl="selectedArchive?.previewUrl"
            :title="selectedArchive?.name || ''"
            :academicYear="selectedArchive?.year"
            :archiveType="selectedArchive?.type || ''"
            :courseName="selectedSubject || ''"
            :professorName="selectedArchive?.professor || ''"
            :loading="previewLoading"
            :error="previewError"
            :errorMessage="previewErrorMessage"
            @hide="closePreview"
            @error="handlePreviewError"
            @download="handlePreviewDownload"
          />

          <UploadArchiveDialog
            v-model="showUploadDialog"
            :coursesList="coursesList"
            :courseCategories="courseCategories"
            :prefill="wishUploadPrefill"
            :sourceWishId="wishUploadPrefill?.id || null"
            @upload-success="handleUploadSuccess"
          />

          <UploadArchiveDialog
            v-model="showWishDialog"
            mode="wish"
            :coursesList="coursesList"
            :courseCategories="courseCategories"
            @upload-success="handleWishCreated"
          />

          <Dialog
            v-model:visible="showSubmissionStatusDialog"
            :header="$t('我的考古投稿')"
            class="submission-typography-dialog"
            modal
            :draggable="false"
            :style="{ width: '760px', maxWidth: '94vw' }"
          >
            <ProgressSpinner
              v-if="submissionStatusLoading"
              class="w-full flex justify-content-center my-4"
            />
            <div v-else class="submission-status-list">
              <section class="submission-level" aria-labelledby="submission-level-title">
                <div class="submission-level-header">
                  <ContributorLevelBadge
                    id="submission-level-title"
                    :level="submissionLevel.level"
                    :title="localizedSubmissionLevelName(submissionLevel)"
                    size="regular"
                    show-title
                  />
                  <span>{{ submissionLevel.currentExp }} EXP</span>
                </div>
                <div
                  class="submission-level-progress-track"
                  role="progressbar"
                  :aria-label="submissionLevelAriaLabel"
                  :aria-valuemin="0"
                  :aria-valuemax="100"
                  :aria-valuenow="submissionLevel.progressPercent"
                  :title="submissionLevelAriaLabel"
                  :style="submissionLevelProgressStyle"
                >
                  <span
                    class="submission-level-progress-fill"
                    :style="{ width: `${submissionLevel.progressPercent}%` }"
                  ></span>
                </div>
                <div class="submission-level-meta">
                  <span v-if="submissionLevel.isMaxLevel">{{ $t('已達最高等級') }}</span>
                  <span v-else>
                    {{
                      $t('本級 {current} / {range} EXP，距離 Lv. {level} 還差 {remaining} EXP', {
                        current: submissionLevel.progressInLevel,
                        range: submissionLevel.progressRange,
                        level: submissionLevel.level + 1,
                        remaining: submissionLevel.expToNextLevel,
                      })
                    }}
                  </span>
                  <span>{{
                    $t('由已通過與已下架投稿累積（{count} 筆）', {
                      count: submissionLevel.countedSubmissions,
                    })
                  }}</span>
                </div>
              </section>
              <section class="submission-summary" :aria-label="$t('投稿統計')">
                <div class="submission-summary-header">
                  <strong>{{ $t('共 {count} 筆投稿', { count: submissionSummary.total }) }}</strong>
                  <span>{{ $t('不含已刪除') }}</span>
                </div>
                <div
                  class="submission-summary-bar"
                  role="img"
                  :aria-label="submissionSummaryAriaLabel"
                  :title="submissionSummaryAriaLabel"
                >
                  <span
                    v-for="status in submissionSummary.statuses"
                    :key="status.key"
                    class="submission-summary-segment"
                    :style="{ width: `${status.ratio}%`, backgroundColor: status.color }"
                  ></span>
                </div>
                <div v-if="submissionSummary.total === 0" class="submission-summary-empty">
                  {{ $t('目前沒有可統計的投稿') }}
                </div>
                <div v-else class="submission-summary-legend">
                  <div
                    v-for="status in submissionSummary.statuses"
                    :key="`legend-${status.key}`"
                    class="submission-summary-legend-item"
                  >
                    <span
                      class="submission-summary-dot"
                      :style="{ backgroundColor: status.color }"
                      aria-hidden="true"
                    ></span>
                    <span>{{ status.label }}</span>
                    <strong>{{ $t('{count} 筆', { count: status.count }) }}</strong>
                    <span>{{ status.percentage }}</span>
                  </div>
                </div>
              </section>
              <section>
                <h3>{{ $t('考古題投稿紀錄') }}</h3>
                <div v-if="archiveSubmissions.length === 0" class="submission-empty">
                  {{ $t('目前沒有考古題投稿') }}
                </div>
                <article
                  v-for="item in archiveSubmissions"
                  :key="`archive-${item.id}`"
                  class="submission-status-card"
                >
                  <div class="submission-status-head">
                    <div class="submission-status-badges">
                      <Tag
                        :class="[
                          'soft-badge',
                          'submission-status-badge',
                          'my-submission-status-badge',
                          getSubmissionStatusClass(item.status),
                        ]"
                        :severity="getSubmissionSeverity(item.status)"
                      >
                        {{ getSubmissionLabel(item.status) }}
                      </Tag>
                      <Tag
                        v-if="item.is_admin_upload"
                        class="soft-badge soft-badge--admin submission-admin-badge"
                        severity="secondary"
                      >
                        {{ $t('管理員投稿（身分標籤）') }}
                      </Tag>
                    </div>
                    <div class="submission-status-title">
                      <strong>{{ localizedSubmissionCourseName(item) }}</strong>
                      <span>{{ item.name }}</span>
                    </div>
                    <small class="my-submission-id">{{
                      $t('投稿編號：{ids}', { ids: formatMySubmissionId(item) })
                    }}</small>
                  </div>
                  <div class="submission-status-meta">
                    <span
                      :class="[
                        'soft-badge',
                        'submission-meta-chip',
                        'my-submission-type-badge',
                        getArchiveSubmissionKindClass(item),
                      ]"
                    >
                      <i class="pi pi-send"></i>{{ getArchiveSubmissionKind(item) }}
                    </span>
                    <span
                      class="soft-badge soft-badge--type submission-meta-chip my-submission-meta-chip"
                    >
                      <i class="pi pi-calendar"></i>{{ formatAcademicTerm(item.academic_year) }}
                    </span>
                    <span
                      class="soft-badge soft-badge--info submission-meta-chip my-submission-meta-chip"
                    >
                      <i class="pi pi-user"></i>{{ item.professor }}
                    </span>
                  </div>
                  <div v-if="item.requested_category_name" class="submission-status-note">
                    <span class="soft-badge soft-badge--new-course-category">{{
                      $t('新分類')
                    }}</span>
                    <strong>{{ localizedSubmissionCategoryName(item) }}</strong>
                    <small>{{ item.requested_category_key }}</small>
                  </div>
                  <div class="submission-time-meta">
                    <span>
                      <i class="pi pi-clock" aria-hidden="true"></i>
                      {{
                        $t('投稿時間：{time}', { time: formatSubmissionDateTime(item.created_at) })
                      }}
                    </span>
                    <span>
                      <i class="pi pi-check-circle" aria-hidden="true"></i>
                      {{
                        $t('審核時間：{time}', {
                          time: formatSubmissionReviewedAt(item.reviewed_at),
                        })
                      }}
                    </span>
                  </div>
                  <div class="submission-review-note">
                    <span class="submission-review-note-label">{{ $t('審核留言') }}</span>
                    <span class="submission-review-note-divider" aria-hidden="true">｜</span>
                    <strong v-if="shouldShowReviewNote(item)">{{ item.review_note }}</strong>
                    <span v-else class="submission-review-note-empty">{{
                      $t('尚無審核留言')
                    }}</span>
                  </div>
                </article>
              </section>
            </div>
          </Dialog>

          <Dialog
            :visible="showEditDialog"
            @update:visible="showEditDialog = $event"
            :modal="true"
            :draggable="false"
            :closeOnEscape="false"
            :header="$t('編輯考古題')"
            :style="{ width: '600px', maxWidth: '90vw' }"
            :autoFocus="false"
          >
            <div class="flex flex-column">
              <div class="flex flex-column gap-2">
                <label>{{ $t('考試名稱') }}</label>
                <InputText
                  id="archive-edit-name"
                  name="archive-edit-name"
                  v-model="editForm.name"
                  :placeholder="$t('輸入考試名稱')"
                  class="w-full"
                />
              </div>

              <div class="flex flex-column gap-2 mt-3">
                <label>{{ $t('授課教授') }}</label>
                <AutoComplete
                  inputId="archive-edit-professor"
                  name="archive-edit-professor"
                  :modelValue="editForm.professor"
                  @update:modelValue="(val) => (editForm.professor = val)"
                  :suggestions="availableEditProfessors"
                  @complete="searchEditProfessor"
                  @item-select="onEditProfessorSelect"
                  @focus="() => searchEditProfessor({ query: '' })"
                  @click="() => searchEditProfessor({ query: '' })"
                  optionLabel="name"
                  :placeholder="$t('選擇授課教授')"
                  class="w-full"
                  dropdown
                  completeOnFocus
                  :minLength="0"
                  autoHighlight="true"
                >
                  <template #item="{ item }">
                    <div>{{ item.name }}</div>
                  </template>
                </AutoComplete>
              </div>

              <div class="flex flex-column gap-2 mt-3">
                <label>{{ $t('考試年份') }}</label>
                <DatePicker
                  inputId="archive-edit-academic-year"
                  name="archive-edit-academic-year"
                  v-model="editForm.academicYear"
                  @update:modelValue="(val) => (editForm.academicYear = val)"
                  view="year"
                  dateFormat="yy"
                  :showIcon="true"
                  :placeholder="$t('選擇考試年份')"
                  class="w-full"
                  :maxDate="new Date()"
                  :minDate="new Date(2000, 0, 1)"
                />
              </div>

              <div class="flex flex-column gap-2 mt-3">
                <label>{{ $t('考試類型') }}</label>
                <Select
                  inputId="archive-edit-type"
                  name="archive-edit-type"
                  v-model="editForm.type"
                  :options="[
                    { name: $t('期中考'), value: 'midterm' },
                    { name: $t('期末考'), value: 'final' },
                    { name: $t('小考'), value: 'quiz' },
                    { name: $t('其他'), value: 'other' },
                  ]"
                  optionLabel="name"
                  optionValue="value"
                  :placeholder="$t('選擇考試類型')"
                  class="w-full"
                />
              </div>

              <div class="flex align-items-center gap-2 mt-3">
                <Checkbox
                  inputId="archive-edit-has-answers"
                  name="archive-edit-has-answers"
                  v-model="editForm.hasAnswers"
                  :binary="true"
                />
                <label for="archive-edit-has-answers">{{ $t('附解答') }}</label>
              </div>

              <Divider class="mt-3" />

              <div class="flex align-items-center gap-2">
                <Checkbox
                  inputId="archive-edit-should-transfer"
                  name="archive-edit-should-transfer"
                  v-model="editForm.shouldTransfer"
                  :binary="true"
                />
                <label for="archive-edit-should-transfer" class="font-semibold">{{
                  $t('轉移到其他課程')
                }}</label>
              </div>

              <div v-if="editForm.shouldTransfer" class="flex flex-column pl-4 mt-3">
                <div class="flex flex-column gap-2">
                  <label>{{ $t('目標課程類別') }}</label>
                  <Select
                    inputId="archive-edit-target-category"
                    name="archive-edit-target-category"
                    v-model="editForm.targetCategory"
                    :options="categoryOptions"
                    optionLabel="name"
                    optionValue="value"
                    :placeholder="$t('選擇課程類別')"
                    class="w-full"
                  />
                </div>

                <div class="flex flex-column gap-2 mt-3">
                  <label>{{ $t('目標課程名稱') }}</label>
                  <AutoComplete
                    inputId="archive-edit-target-course"
                    name="archive-edit-target-course"
                    v-model="editForm.targetCourse"
                    :suggestions="availableCoursesForTransfer"
                    @complete="searchTargetCourse"
                    @item-select="onTargetCourseSelect"
                    @focus="() => searchTargetCourse({ query: '' })"
                    @click="() => searchTargetCourse({ query: '' })"
                    optionLabel="label"
                    :placeholder="$t('搜尋或輸入目標課程名稱')"
                    class="w-full"
                    :disabled="!editForm.targetCategory"
                    dropdown
                    completeOnFocus
                    :minLength="0"
                    autoHighlight="true"
                  >
                    <template #item="{ item }">
                      <div>{{ item.label }}</div>
                    </template>
                  </AutoComplete>
                </div>
              </div>
            </div>
            <div class="flex pt-6 justify-end gap-2.5">
              <Button
                :label="$t('取消')"
                icon="pi pi-times"
                severity="secondary"
                @click="closeEditDialog"
              />
              <Button
                :label="editForm.shouldTransfer ? $t('儲存並轉移') : $t('儲存')"
                :icon="editForm.shouldTransfer ? 'pi pi-arrow-right-arrow-left' : 'pi pi-check'"
                severity="success"
                @click="handleEdit"
                :loading="editLoading"
              />
            </div>
          </Dialog>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
defineOptions({
  name: 'ArchiveView',
})

import { ref, computed, onMounted, watch, inject, onBeforeUnmount, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { routeLocationKey } from 'vue-router'
import { courseService, archiveService } from '../api'
import PdfPreviewModal from '../components/PdfPreviewModal.vue'
import UploadArchiveDialog from '../components/UploadArchiveDialog.vue'
import WishPool from '../components/WishPool.vue'
import ContributorLevelBadge from '../components/ContributorLevelBadge.vue'
import { getCurrentUser, isAuthenticated } from '../utils/auth'
import { useTheme } from '../utils/useTheme'
import { trackEvent, EVENTS } from '../utils/analytics'
import { isUnauthorizedError } from '../utils/http'
import { formatCourseDisplayName, normalizeCourseSearchText } from '../utils/courseText'
import {
  courseMatchesSearch,
  localizedCategoryLabel,
  localizedCategoryName,
  localizedCourseName,
  localizedSubmissionCategoryName,
  localizedSubmissionCourseName,
} from '../utils/localizedCatalog'
import {
  getContributorLevelPalette,
  loadContributorLevelSettings,
  localizedSubmissionLevelName,
  resolveSubmissionLevel,
} from '../utils/submissionLevel'
import {
  STORAGE_KEYS,
  getLocalJson,
  setLocalJson,
  removeLocalItem,
  setSessionJson,
} from '../utils/storage'

const toast = inject('toast')
const confirm = inject('confirm')
const route = inject(routeLocationKey, { fullPath: '/archive', query: {} })

const { isDarkTheme } = useTheme()
const { t, locale } = useI18n()
loadContributorLevelSettings()
const sidebarVisible = inject('sidebarVisible')

// Check if we're on mobile
const isMobile = ref(false)

const checkDevice = () => {
  const mobile = window.innerWidth < 768
  isMobile.value = mobile
  if (mobile) {
    sidebarVisible.value = false
  }
}

onMounted(() => {
  checkDevice()
  window.addEventListener('resize', checkDevice)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', checkDevice)
  if (searchDebounceTimer) {
    clearTimeout(searchDebounceTimer)
  }
})

// Auth related data
const isAuthenticatedRef = ref(false)
const userData = ref(null)

const archives = ref([])
const loading = ref(true)
const filters = ref({
  year: '',
  professor: '',
  type: '',
  hasAnswers: false,
})

// Track filter changes
watch(
  filters,
  (newFilters, oldFilters) => {
    shouldResetPanels.value = true

    // Only track if at least one filter is active and different from old value
    const hasActiveFilter =
      newFilters.year || newFilters.professor || newFilters.type || newFilters.hasAnswers

    if (hasActiveFilter && oldFilters) {
      const changedFilters = {}
      if (newFilters.year !== oldFilters.year) changedFilters.year = !!newFilters.year
      if (newFilters.professor !== oldFilters.professor)
        changedFilters.professor = !!newFilters.professor
      if (newFilters.type !== oldFilters.type) changedFilters.type = !!newFilters.type
      if (newFilters.hasAnswers !== oldFilters.hasAnswers)
        changedFilters.hasAnswers = newFilters.hasAnswers

      if (Object.keys(changedFilters).length > 0) {
        trackEvent(EVENTS.FILTER_ARCHIVES, {
          activeFilters: {
            year: !!newFilters.year,
            professor: !!newFilters.professor,
            type: !!newFilters.type,
            hasAnswers: newFilters.hasAnswers,
          },
          changedFilters,
        })
      }
    }
  },
  { deep: true }
)

const showPreview = ref(false)
const selectedArchive = ref(null)
const selectedSubject = ref(null)
const selectedCourse = ref(null)
const showUploadDialog = ref(false)
const showWishDialog = ref(false)
const wishPoolActive = ref(false)
const wishUploadPrefill = ref(null)
const showSubmissionStatusDialog = ref(false)
const submissionStatusLoading = ref(false)
const archiveSubmissions = ref([])
const deepLinkReady = ref(false)
const submissionLevel = computed(() => {
  const countedSubmissions = archiveSubmissions.value.filter((submission) =>
    ['approved', 'takedown'].includes(getNormalizedSubmissionStatus(submission?.status))
  ).length
  return {
    ...resolveSubmissionLevel(countedSubmissions),
    countedSubmissions,
  }
})
const submissionLevelAriaLabel = computed(() => {
  const level = submissionLevel.value
  if (level.isMaxLevel) {
    return t('投稿等級最高', {
      level: level.level,
      name: localizedSubmissionLevelName(level),
      exp: level.currentExp,
    })
  }
  return t('投稿等級進度', {
    level: level.level,
    name: localizedSubmissionLevelName(level),
    percent: level.progressPercent,
    current: level.progressInLevel,
    range: level.progressRange,
    remaining: level.expToNextLevel,
  })
})
const submissionLevelProgressStyle = computed(() => {
  const palette = getContributorLevelPalette(submissionLevel.value.level)
  return {
    '--level-progress-bg': palette.bg,
    '--level-progress-border': palette.border,
  }
})
const submissionStatusConfig = [
  { key: 'pending', color: '#d29922' },
  { key: 'approved', color: '#2da44e' },
  { key: 'rejected', color: '#cf222e' },
  { key: 'takedown', color: '#6e7781' },
]
const submissionSummary = computed(() => {
  const counts = new Map(submissionStatusConfig.map(({ key }) => [key, 0]))
  archiveSubmissions.value.forEach((submission) => {
    const status = getNormalizedSubmissionStatus(submission?.status)
    if (status !== 'deleted' && counts.has(status)) counts.set(status, counts.get(status) + 1)
  })
  const total = Array.from(counts.values()).reduce((sum, count) => sum + count, 0)
  return {
    total,
    statuses: submissionStatusConfig
      .map(({ key, color }) => {
        const count = counts.get(key)
        const ratio = total > 0 ? (count / total) * 100 : 0
        return {
          key,
          color,
          count,
          ratio,
          label: getSubmissionLabel(key),
          percentage: `${ratio.toFixed(1)}%`,
        }
      })
      .filter(({ count }) => count > 0),
  }
})
const submissionSummaryAriaLabel = computed(() => {
  if (submissionSummary.value.total === 0) return t('投稿統計：目前沒有可統計的投稿，不含已刪除')
  const details = submissionSummary.value.statuses
    .map((status) =>
      t('投稿統計項目', { label: status.label, count: status.count, percentage: status.percentage })
    )
    .join(t('；'))
  return t('投稿統計摘要', { count: submissionSummary.value.total, details })
})
const uploadFormProfessors = ref([])
const expandedPanels = ref([])
const expandedMenuItems = ref({})
const shouldResetPanels = ref(true)

const fallbackCategories = [
  {
    key: 'fundamental',
    name: '基礎必修',
    name_en: 'Foundation Courses',
    icon: 'pi pi-fw pi-book',
    label: '基礎',
    label_en: 'Foundation',
  },
  {
    key: 'required',
    name: '專業必修',
    name_en: 'Required Major Courses',
    icon: 'pi pi-fw pi-compass',
    label: '必修',
    label_en: 'Required',
  },
  {
    key: 'experience',
    name: '實驗課程',
    name_en: 'Laboratory Courses',
    icon: 'pi pi-fw pi-sparkles',
    label: '實驗',
    label_en: 'Laboratory',
  },
  {
    key: 'optional',
    name: '專業選修',
    name_en: 'Major Electives',
    icon: 'pi pi-fw pi-book',
    label: '選修',
    label_en: 'Elective',
  },
  {
    key: 'graduate',
    name: '研究所',
    name_en: 'Graduate Courses',
    icon: 'pi pi-fw pi-graduation-cap',
    label: '研究所',
    label_en: 'Graduate',
  },
  {
    key: 'math-department',
    name: '戳戳數學系',
    name_en: 'Mathematics Courses',
    icon: 'pi pi-fw pi-calculator',
    label: '數學',
    label_en: 'Mathematics',
  },
]

const courseCategories = ref([...fallbackCategories])
const coursesList = ref({})
const categoryMap = computed(() =>
  courseCategories.value.reduce((acc, category) => {
    acc[category.key] = category
    return acc
  }, {})
)

const archiveTypeConfig = computed(() => ({
  midterm: {
    name: t('期中考'),
    severity: 'secondary',
  },
  final: {
    name: t('期末考'),
    severity: 'secondary',
  },
  quiz: {
    name: t('小考'),
    severity: 'secondary',
  },
  other: {
    name: t('其他'),
    severity: 'secondary',
  },
}))

const years = ref([])
const professors = ref([])
const archiveTypes = ref([])

const searchQuery = ref('')

// Track search query changes with debounce
let searchDebounceTimer = null
watch(searchQuery, (newValue) => {
  if (searchDebounceTimer) {
    clearTimeout(searchDebounceTimer)
  }

  if (newValue && newValue.trim().length > 0) {
    searchDebounceTimer = setTimeout(() => {
      trackEvent(EVENTS.SEARCH_COURSE, {
        query: newValue,
        queryLength: newValue.length,
      })
    }, 1000) // 1 second debounce
  }
})

const ISSUE_CONTEXT_STORAGE_KEY = STORAGE_KEYS.session.ISSUE_CONTEXT

function persistIssueContext() {
  try {
    if (typeof window === 'undefined') return

    const selectedSubjectStored = getLocalJson(STORAGE_KEYS.local.SELECTED_SUBJECT)

    const payload = {
      page: 'archive',
      timestamp: new Date().toISOString(),
      course: {
        id: selectedCourse.value ?? selectedSubjectStored?.id ?? null,
        name: selectedSubject.value ?? selectedSubjectStored?.label ?? null,
      },
      filters: {
        year: filters.value?.year || null,
        professor: filters.value?.professor || null,
        type: filters.value?.type || null,
        hasAnswers: Boolean(filters.value?.hasAnswers),
        searchQuery: searchQuery.value || null,
      },
      preview: {
        open: Boolean(showPreview.value),
        archiveId: selectedArchive.value?.id ?? null,
        name: selectedArchive.value?.name ?? null,
        year: selectedArchive.value?.year ?? null,
        professor: selectedArchive.value?.professor ?? null,
        type: selectedArchive.value?.type ?? null,
        hasAnswers: selectedArchive.value?.hasAnswers ?? null,
      },
    }

    setSessionJson(ISSUE_CONTEXT_STORAGE_KEY, payload)
  } catch {
    // ignore
  }
}

watch(
  () => [
    selectedCourse.value,
    selectedSubject.value,
    showPreview.value,
    selectedArchive.value?.id,
    filters.value?.year,
    filters.value?.professor,
    filters.value?.type,
    filters.value?.hasAnswers,
    searchQuery.value,
  ],
  () => persistIssueContext(),
  { immediate: true }
)

const menuItems = computed(() => {
  if (!coursesList.value) return []

  return courseCategories.value.map((category) => ({
    key: category.key,
    label: localizedCategoryName(category),
    icon: category.icon || 'pi pi-fw pi-book',
    items: (coursesList.value[category.key] || []).map((course) => ({
      label: localizedCourseName(course),
      course,
      class: selectedCourse.value === course.id ? 'active-course-menu-item' : undefined,
      command: () => filterBySubject({ label: localizedCourseName(course), id: course.id }),
    })),
  }))
})

const filteredCategories = computed(() => {
  if (!searchQuery.value) {
    return []
  }

  const query = normalizeCourseSearchText(searchQuery.value)
  const filtered = []

  menuItems.value.forEach((category) => {
    const filteredItems = category.items.filter((item) => courseMatchesSearch(item.course, query))

    if (filteredItems.length > 0) {
      filtered.push({
        ...category,
        items: filteredItems.map((item) => {
          return {
            label: item.label,
            id: item.course?.id,
          }
        }),
      })
    }
  })

  return filtered
})

function getCategoryKeyForCourse(courseId) {
  for (const [categoryKey, courses] of Object.entries(coursesList.value)) {
    if (courses.some((course) => course.id === courseId)) {
      return categoryKey
    }
  }
  return null
}

const groupedArchives = computed(() => {
  if (!archives.value) return []

  const filteredArchives = archives.value.filter((archive) => {
    if (filters.value.year && archive.year.toString() !== filters.value.year) return false
    if (filters.value.professor && archive.professor !== filters.value.professor) return false
    if (filters.value.type && archive.type !== filters.value.type) return false
    if (filters.value.hasAnswers && !archive.hasAnswers) return false
    return true
  })

  const groups = {}
  filteredArchives.forEach((archive) => {
    if (!groups[archive.year]) {
      groups[archive.year] = {
        year: archive.year,
        list: [],
      }
    }
    groups[archive.year].list.push(archive)
  })

  Object.values(groups).forEach((group) => {
    group.list.sort((a, b) => {
      // Define exam type priority
      const typePriority = {
        midterm: 1,
        final: 2,
        quiz: 3,
        other: 4,
      }

      const aPriority = typePriority[a.type] || 4
      const bPriority = typePriority[b.type] || 4

      if (aPriority !== bPriority) {
        return aPriority - bPriority
      }

      return a.name.localeCompare(b.name, 'en')
    })
  })

  return Object.values(groups).sort((a, b) => b.year - a.year)
})

const archiveTotalCount = computed(() => archives.value.length)

const filteredArchiveCount = computed(() =>
  groupedArchives.value.reduce((total, group) => total + group.list.length, 0)
)

const latestAcademicTerm = computed(() => {
  const latestYear = archives.value
    .map((archive) => Number(archive.year))
    .filter(Boolean)
    .sort((a, b) => b - a)[0]

  return latestYear ? formatAcademicTerm(latestYear) : t('尚無資料')
})

function formatAcademicTerm(value) {
  const numericValue = Number(value)
  if (!numericValue) return ''
  if (numericValue >= 1000 && numericValue < 2000) {
    const year = Math.floor(numericValue / 10)
    const semester = numericValue % 10
    return t(semester === 1 ? '{year}上學期' : '{year}下學期', { year })
  }
  return t('{year} 年', { year: numericValue })
}

function formatSourceSubmissionIds(archive) {
  const ids = Array.isArray(archive?.sourceSubmissionIds)
    ? archive.sourceSubmissionIds.filter((id) => id !== null && id !== undefined)
    : []
  if (!ids.length) return ''
  return ids.map((id) => `#${id}`).join(', ')
}

async function fetchCourses() {
  try {
    loading.value = true
    const [categoriesResponse, coursesResponse] = await Promise.all([
      courseService.listCategories(),
      courseService.listCourses(),
    ])
    const categories =
      Array.isArray(categoriesResponse.data) && categoriesResponse.data.length
        ? categoriesResponse.data
        : fallbackCategories

    // Only update coursesList if the data has actually changed to prevent unnecessary re-renders
    const rawCourses =
      coursesResponse.data && typeof coursesResponse.data === 'object' ? coursesResponse.data : {}
    const newData = {}
    for (const [categoryKey, courses] of Object.entries(rawCourses)) {
      newData[categoryKey] = (Array.isArray(courses) ? courses : []).map((course) => ({
        ...course,
        name: formatCourseDisplayName(course?.name),
      }))
    }
    const currentData = coursesList.value
    const hasChanged = JSON.stringify(currentData) !== JSON.stringify(newData)

    courseCategories.value = categories.map((category, index) => ({
      key: category.key,
      name: category.name,
      name_en: category.name_en,
      label: category.label || category.name,
      label_en: category.label_en,
      icon: category.icon || 'pi pi-fw pi-book',
      order_index: category.order_index ?? index,
    }))

    if (hasChanged) {
      coursesList.value = newData
    }
  } catch (error) {
    console.error('Error fetching courses:', error)
    if (isUnauthorizedError(error)) {
      return
    }
    toast.add({
      severity: 'error',
      summary: t('載入失敗'),
      detail: t('無法載入課程資料'),
      life: 3000,
    })
  } finally {
    loading.value = false
  }
}

function getSubmissionLabel(status) {
  const labels = {
    pending: t('待審核'),
    approved: t('已通過'),
    rejected: t('未通過'),
    deleted: t('已刪除'),
    takedown: t('已下架'),
    PENDING: t('待審核'),
    APPROVED: t('已通過'),
    REJECTED: t('未通過'),
    DELETED: t('已刪除'),
    TAKEDOWN: t('已下架'),
  }
  return labels[status] || status
}

function getNormalizedSubmissionStatus(status) {
  return String(status || '').toLowerCase()
}

function getSubmissionSeverity(status) {
  const normalized = getNormalizedSubmissionStatus(status)
  if (normalized === 'approved') return 'success'
  if (normalized === 'rejected') return 'danger'
  if (normalized === 'deleted') return 'danger'
  if (normalized === 'takedown') return 'secondary'
  return 'warning'
}

function getSubmissionStatusClass(status) {
  const normalized = getNormalizedSubmissionStatus(status)
  if (normalized === 'approved') return 'submission-status-approved'
  if (normalized === 'rejected') return 'submission-status-rejected'
  if (normalized === 'deleted') return 'submission-status-deleted'
  if (normalized === 'takedown') return 'submission-status-takedown'
  return 'submission-status-pending'
}

function getArchiveSubmissionKind(item) {
  if (item?.requested_category_key) return t('新分類 + 新課程')
  if (item?.requested_course_name) return t('新課程申請')
  return t('既有課程投稿')
}

function getArchiveSubmissionKindClass(item) {
  if (item?.requested_category_key) return 'soft-badge--new-course-category'
  if (item?.requested_course_name) return 'soft-badge--new-course'
  return 'soft-badge--type'
}

function formatMySubmissionId(item) {
  const id = item?.submission_id ?? item?.submissionId ?? item?.id ?? item?.source_submission_id
  return id !== null && id !== undefined && id !== '' ? `#${id}` : '—'
}

function formatSubmissionDateTime(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  const parts = new Intl.DateTimeFormat('zh-TW', {
    timeZone: 'Asia/Taipei',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(date)
  const values = Object.fromEntries(parts.map(({ type, value: partValue }) => [type, partValue]))
  return `${values.year}/${values.month}/${values.day} ${values.hour}:${values.minute}`
}

function formatSubmissionReviewedAt(value) {
  return value ? formatSubmissionDateTime(value) : t('尚未審核')
}

function isBoilerplateReviewNote(note) {
  const normalized = String(note || '')
    .trim()
    .toLowerCase()
  return (
    !normalized ||
    normalized === '管理員上傳' ||
    normalized === 'admin upload' ||
    normalized.startsWith('takedown_target:')
  )
}

function shouldShowReviewNote(item) {
  return Boolean(item?.review_note) && !isBoilerplateReviewNote(item.review_note)
}

async function loadSubmissionStatus() {
  submissionStatusLoading.value = true
  try {
    const archiveResponse = await archiveService.listMySubmissions()
    archiveSubmissions.value = Array.isArray(archiveResponse.data) ? archiveResponse.data : []
  } catch (error) {
    console.error('Load submission status error:', error)
    if (isUnauthorizedError(error)) return
    toast.add({
      severity: 'error',
      summary: t('載入失敗'),
      detail: t('無法載入投稿狀態'),
      life: 3000,
    })
  } finally {
    submissionStatusLoading.value = false
  }
}

async function openSubmissionStatus() {
  showSubmissionStatusDialog.value = true
  await loadSubmissionStatus()
}

async function openRequestedSource() {
  if (!deepLinkReady.value) return
  if (String(route.query.showSubmissionStatus || '') === '1') {
    await openSubmissionStatus()
    return
  }
  const requestedCourseId = Number(route.query.courseId)
  const requestedArchiveId = Number(route.query.archiveId)
  if (!requestedCourseId || !requestedArchiveId) return
  const course = Object.values(coursesList.value)
    .flat()
    .find((item) => Number(item.id) === requestedCourseId)
  if (!course) return
  selectedCourse.value = requestedCourseId
  selectedSubject.value = localizedCourseName(course)
  await fetchArchives()
  const archive = archives.value.find((item) => Number(item.id) === requestedArchiveId)
  if (archive) await previewArchive(archive)
}

function openUploadFromMobileMenu() {
  sidebarVisible.value = false
  openUploadDialog()
}

function openUploadDialog() {
  wishUploadPrefill.value = null
  showUploadDialog.value = true
}

function openWishPoolFromMobileMenu() {
  sidebarVisible.value = false
  wishPoolActive.value = true
}

function openWishHelpUpload(wish) {
  wishUploadPrefill.value = wish
  showUploadDialog.value = true
}

async function openSubmissionStatusFromMobileMenu() {
  sidebarVisible.value = false
  await openSubmissionStatus()
}

function filterBySubject(course) {
  wishPoolActive.value = false
  trackEvent(EVENTS.SELECT_COURSE, {
    courseName: course.label,
    courseId: course.id,
  })

  selectedSubject.value = course.label
  selectedCourse.value = course.id
  filters.value.professor = ''
  filters.value.year = ''
  filters.value.type = ''
  expandedPanels.value = []
  shouldResetPanels.value = true

  const categoryKey = getCategoryKeyForCourse(course.id)
  if (categoryKey) {
    expandedMenuItems.value = { [categoryKey]: true }
    // console.log("Expanding category:", categoryKey, expandedMenuItems.value);
  }

  setLocalJson(STORAGE_KEYS.local.SELECTED_SUBJECT, { label: course.label, id: course.id })

  fetchArchives()
}

async function fetchArchives() {
  try {
    loading.value = true
    const response = await courseService.getCourseArchives(selectedCourse.value)
    const archiveRows = Array.isArray(response.data) ? response.data : []
    if (!Array.isArray(response.data)) {
      throw new Error('Archive list response is not an array')
    }
    archives.value = archiveRows.filter(isVisibleArchiveRow).map((archive) => ({
      id: archive.id,
      year: archive.academic_year || '',
      name: archive.name || t('未命名考古題'),
      type: archive.archive_type || 'other',
      professor: archive.professor || '—',
      hasAnswers: Boolean(archive.has_answers),
      subject: selectedSubject.value,
      uploader_id: archive.uploader_id || null,
      downloadCount: Number(archive.download_count || 0),
      sourceSubmissionIds: Array.isArray(archive.source_submission_ids)
        ? archive.source_submission_ids
        : [],
    }))

    const uniqueYears = new Set()
    const uniqueProfessors = new Set()
    const uniqueTypes = new Set()

    archives.value.forEach((archive) => {
      if (archive.year) uniqueYears.add(archive.year.toString())
      if (archive.professor) uniqueProfessors.add(archive.professor)
      if (archive.type) uniqueTypes.add(archive.type)
    })

    years.value = Array.from(uniqueYears)
      .sort((a, b) => b - a)
      .map((year) => ({
        name: formatAcademicTerm(year),
        code: year,
      }))

    professors.value = Array.from(uniqueProfessors)
      .sort()
      .map((professor) => ({
        name: professor,
        code: professor,
      }))

    archiveTypes.value = Array.from(uniqueTypes)
      .sort()
      .map((type) => ({
        name: archiveTypeConfig.value[type]?.name || type,
        code: type,
      }))
  } catch (error) {
    console.error('Error fetching archives:', error)
    archives.value = []
    years.value = []
    professors.value = []
    archiveTypes.value = []
    if (isUnauthorizedError(error)) {
      return
    }
    toast.add({
      severity: 'error',
      summary: t('載入失敗'),
      detail: t('無法載入考古題資料'),
      life: 3000,
    })
  } finally {
    loading.value = false
  }
}

const downloadingId = ref(null)

function isVisibleArchiveRow(archive) {
  const status = String(archive?.status || archive?.state || '').toLowerCase()
  return (
    archive &&
    archive.id !== null &&
    archive.id !== undefined &&
    !archive.deleted_at &&
    !archive.deletedAt &&
    !archive.is_deleted &&
    !['deleted', 'removed', 'trashed'].includes(status)
  )
}

async function syncArchiveDownloadCount(archiveId) {
  if (!selectedCourse.value) return

  const previousExpandedPanels = [...expandedPanels.value]
  const resetRequested = shouldResetPanels.value

  try {
    const response = await courseService.getCourseArchives(selectedCourse.value)
    const serverRows = Array.isArray(response.data) ? response.data : []
    const serverMap = new Map(serverRows.filter(isVisibleArchiveRow).map((item) => [item.id, item]))

    archives.value = archives.value.map((archive) => {
      const serverArchive = serverMap.get(archive.id)
      if (!serverArchive || serverArchive.download_count === archive.downloadCount) {
        return archive
      }
      return {
        ...archive,
        downloadCount: serverArchive.download_count,
      }
    })

    const serverArchive = serverMap.get(archiveId)
    if (serverArchive && selectedArchive.value?.id === archiveId) {
      selectedArchive.value = {
        ...selectedArchive.value,
        downloadCount: serverArchive.download_count,
      }
    }

    if (!resetRequested) {
      const availableYears = Array.from(
        new Set(
          archives.value
            .map((item) =>
              item.year !== undefined && item.year !== null ? item.year.toString() : null
            )
            .filter((year) => year !== null)
        )
      )

      const preservedPanels = previousExpandedPanels.filter((year) => availableYears.includes(year))
      expandedPanels.value = preservedPanels
    }
  } catch (error) {
    console.error('Sync download count error:', error)
  }
}

function startNativeDownload(url, fileName) {
  const link = document.createElement('a')
  link.href = url
  link.download = fileName
  link.style.display = 'none'
  document.body.appendChild(link)
  link.click()
  link.remove()
}

async function downloadArchive(archive) {
  try {
    downloadingId.value = archive.id

    const { data } = await archiveService.getArchiveDownloadUrl(selectedCourse.value, archive.id)

    const fileName = `${archive.year}_${selectedSubject.value}_${archive.professor}_${archive.name}.pdf`
    startNativeDownload(data.url, fileName)

    trackEvent(EVENTS.DOWNLOAD_ARCHIVE, {
      archiveName: archive.name,
      year: archive.year,
      professor: archive.professor,
      type: archive.type,
      courseName: selectedSubject.value,
      source: 'archive-list',
    })

    toast.add({
      severity: 'success',
      summary: t('已開始下載'),
      detail: t('已開始下載 {file}', { file: fileName }),
      life: 3000,
    })

    await syncArchiveDownloadCount(archive.id)
  } catch (error) {
    console.error('Download error:', error)
    if (isUnauthorizedError(error)) {
      return
    }
    toast.add({
      severity: 'error',
      summary: t('下載失敗'),
      detail:
        error.response?.status === 404 ? t('此筆考古題的 PDF 檔案缺失') : t('無法取得下載連結'),
      life: 3000,
    })
  } finally {
    downloadingId.value = null
  }
}

const previewLoading = ref(false)
const previewError = ref(false)
const previewErrorMessage = ref(t('無法載入預覽'))
let previewRequestId = 0

async function previewArchive(archive) {
  const requestId = ++previewRequestId
  try {
    previewLoading.value = true
    previewError.value = false
    previewErrorMessage.value = t('無法載入預覽')
    showPreview.value = true
    selectedArchive.value = {
      ...archive,
      previewUrl: '',
    }

    const { data } = await archiveService.getArchivePreviewUrl(selectedCourse.value, archive.id)
    if (requestId !== previewRequestId || !showPreview.value) return

    selectedArchive.value = {
      ...archive,
      previewUrl: data.url,
    }

    trackEvent(EVENTS.PREVIEW_ARCHIVE, {
      archiveName: archive.name,
      year: archive.year,
      professor: archive.professor,
      type: archive.type,
      courseName: selectedSubject.value,
    })
  } catch (error) {
    if (requestId !== previewRequestId) return
    console.error('Preview error:', error)
    previewError.value = true
    const isMissingFile = error.response?.status === 404
    previewErrorMessage.value = isMissingFile ? t('檔案缺失') : t('無法載入預覽')
    if (isUnauthorizedError(error)) {
      return
    }
    toast.add({
      severity: 'error',
      summary: t('預覽失敗'),
      detail: isMissingFile ? t('此筆考古題的 PDF 檔案缺失') : t('無法取得預覽連結'),
      life: 3000,
    })
  } finally {
    if (requestId === previewRequestId) {
      previewLoading.value = false
    }
  }
}

function handlePreviewError() {
  previewError.value = true
}

function closePreview() {
  previewRequestId += 1
  showPreview.value = false
  selectedArchive.value = null
  previewError.value = false
}

function getCategoryName(code) {
  return localizedCategoryName(categoryMap.value[code]) || code
}

const availableEditProfessors = ref([])

const categoryOptions = computed(() =>
  courseCategories.value.map((category) => ({
    name: localizedCategoryName(category),
    value: category.key,
  }))
)

watch(
  () => groupedArchives.value,
  (newGroups) => {
    if (!newGroups.length) {
      // Clear expanded panels if no groups available
      expandedPanels.value = []
      shouldResetPanels.value = true
      return
    }

    const availableYears = newGroups.map((group) => group.year.toString())
    const preservedPanels = expandedPanels.value.filter((year) => availableYears.includes(year))

    if (shouldResetPanels.value) {
      // Default to expanding the most recent three years when reset is requested
      expandedPanels.value = newGroups.slice(0, 3).map((group) => group.year.toString())
    } else {
      expandedPanels.value = preservedPanels
    }

    shouldResetPanels.value = false
  },
  { immediate: true }
)

const isAdmin = ref(false)
const showEditDialog = ref(false)
const editForm = ref({
  id: null,
  name: '',
  professor: '',
  type: '',
  hasAnswers: false,
  academicYear: null,
  shouldTransfer: false,
  targetCategory: null,
  targetCourse: null,
  targetCourseId: null,
})

const editLoading = ref(false)

const allAvailableCoursesForTransfer = computed(() => {
  if (!editForm.value.targetCategory || !coursesList.value) {
    return []
  }

  const categoryData = coursesList.value[editForm.value.targetCategory]
  if (!categoryData) {
    return []
  }

  return categoryData
    .filter((course) => course.id !== selectedCourse.value)
    .map((course) => ({
      id: course.id,
      label: localizedCourseName(course),
      searchCourse: course,
    }))
})

const availableCoursesForTransfer = ref([])

const canDeleteArchive = (archive) => {
  const currentUser = getCurrentUser()
  if (!currentUser) return false

  return isAdmin.value || (archive.uploader_id && archive.uploader_id === currentUser.id)
}

const canEditArchive = () => {
  return isAdmin.value
}

const confirmDelete = (archive) => {
  confirm.require({
    message: t('確定要刪除此考古題嗎？'),
    header: t('確認刪除'),
    icon: 'pi pi-exclamation-triangle',
    accept: () => {
      deleteArchive(archive)
    },
  })
}

const deleteArchive = async (archive) => {
  try {
    await archiveService.deleteArchive(selectedCourse.value, archive.id)

    trackEvent(EVENTS.DELETE_ARCHIVE, {
      archiveName: archive.name,
      year: archive.year,
      professor: archive.professor,
      type: archive.type,
      courseName: selectedSubject.value,
    })

    shouldResetPanels.value = true
    await fetchArchives()
    toast.add({
      severity: 'success',
      summary: t('刪除成功'),
      detail: t('考古題已成功刪除'),
      life: 3000,
    })
  } catch (error) {
    console.error('Delete error:', error)
    if (isUnauthorizedError(error)) {
      return
    }
    toast.add({
      severity: 'error',
      summary: t('刪除失敗'),
      detail: t('發生錯誤，請稍後再試'),
      life: 3000,
    })
  }
}

const openEditDialog = async (archive) => {
  try {
    const response = await courseService.getCourseArchives(selectedCourse.value)
    const archiveData = response.data

    const uniqueProfessors = new Set()
    archiveData.forEach((item) => {
      if (item.professor) uniqueProfessors.add(item.professor)
    })

    uploadFormProfessors.value = Array.from(uniqueProfessors)
      .sort()
      .map((professor) => ({
        name: professor,
        code: professor,
      }))

    editForm.value = {
      id: archive.id,
      name: archive.name,
      professor: archive.professor,
      type: archive.type,
      hasAnswers: archive.hasAnswers,
      academicYear: archive.year ? new Date(parseInt(archive.year), 0, 1) : null,
      shouldTransfer: false,
      targetCategory: null,
      targetCourse: null,
      targetCourseId: null,
    }

    availableEditProfessors.value = uploadFormProfessors.value

    trackEvent(EVENTS.EDIT_ARCHIVE, {
      action: 'open-dialog',
      archiveName: archive.name,
      year: archive.year,
    })

    showEditDialog.value = true
  } catch (error) {
    console.error('Error fetching professors:', error)
    if (isUnauthorizedError(error)) {
      return
    }
    toast.add({
      severity: 'error',
      summary: t('載入失敗'),
      detail: t('無法載入教授清單'),
      life: 3000,
    })
  }
}

const handleEdit = async () => {
  if (editForm.value.shouldTransfer && !editForm.value.targetCourseId) {
    toast.add({
      severity: 'error',
      summary: t('轉移失敗'),
      detail: t('請從現有課程清單選擇目標課程。'),
      life: 4000,
    })
    return
  }
  try {
    editLoading.value = true

    await archiveService.updateArchive(selectedCourse.value, editForm.value.id, {
      name: editForm.value.name,
      professor: editForm.value.professor,
      archive_type: editForm.value.type,
      has_answers: editForm.value.hasAnswers,
      academic_year: editForm.value.academicYear ? editForm.value.academicYear.getFullYear() : null,
      ...(editForm.value.shouldTransfer ? { target_course_id: editForm.value.targetCourseId } : {}),
    })

    trackEvent(EVENTS.EDIT_ARCHIVE, {
      action: 'submit',
      transferred: editForm.value.shouldTransfer,
      targetCategory: editForm.value.shouldTransfer ? editForm.value.targetCategory : null,
    })

    shouldResetPanels.value = true
    await fetchArchives()

    // If transfer was performed, refresh the course list to show the new course
    if (editForm.value.shouldTransfer) {
      await fetchCourses()
    }

    closeEditDialog()

    const successMessage = editForm.value.shouldTransfer
      ? t('考古題已更新並轉移到新課程')
      : t('考古題資訊已更新')

    toast.add({
      severity: 'success',
      summary: t('更新成功'),
      detail: successMessage,
      life: 3000,
    })
  } catch (error) {
    console.error('Update error:', error)
    if (isUnauthorizedError(error)) {
      return
    }
    const detail = error?.response?.data?.detail
    const approvedMoveErrorCodes = new Set([
      'archive_move_target_course_not_found',
      'course_lifecycle_conflict',
    ])
    const errorMessage =
      detail &&
      typeof detail === 'object' &&
      approvedMoveErrorCodes.has(detail.code) &&
      typeof detail.message === 'string'
        ? t(detail.message)
        : t('發生錯誤，請稍後再試')
    toast.add({
      severity: 'error',
      summary: t('更新失敗'),
      detail: errorMessage,
      life: 3000,
    })
  } finally {
    editLoading.value = false
  }
}

onMounted(async () => {
  const user = getCurrentUser()
  isAdmin.value = user?.is_admin || false
  checkAuthentication()
  await fetchCourses()

  const subjectData = getLocalJson(STORAGE_KEYS.local.SELECTED_SUBJECT)
  if (subjectData) {
    try {
      // Verify the course still exists in the current course list
      const normalizedStoredLabel = normalizeCourseSearchText(subjectData.label)
      let matchedCourse = null
      const courseExists = Object.values(coursesList.value).some((category) =>
        category.some((course) => {
          if (
            course.id === subjectData.id &&
            normalizeCourseSearchText(course.name) === normalizedStoredLabel
          ) {
            matchedCourse = course
            return true
          }
          return false
        })
      )

      if (courseExists) {
        selectedSubject.value = matchedCourse
          ? localizedCourseName(matchedCourse)
          : formatCourseDisplayName(subjectData.label)
        selectedCourse.value = subjectData.id

        const categoryKey = getCategoryKeyForCourse(subjectData.id)
        if (categoryKey) {
          expandedMenuItems.value = { [categoryKey]: true }
        }

        await fetchArchives()
      } else {
        removeLocalItem(STORAGE_KEYS.local.SELECTED_SUBJECT)
      }
    } catch (error) {
      console.error('Error parsing saved subject:', error)
      removeLocalItem(STORAGE_KEYS.local.SELECTED_SUBJECT)
    }
  }
  deepLinkReady.value = true
  await openRequestedSource()
})

watch(
  () => route.fullPath,
  () => {
    if (deepLinkReady.value) void openRequestedSource()
  }
)

watch(isDarkTheme, () => {})

async function handleUploadSuccess() {
  trackEvent(EVENTS.UPLOAD_ARCHIVE, {
    courseName: selectedSubject.value,
  })

  await fetchCourses()
  await loadSubmissionStatus()
  shouldResetPanels.value = true
  if (selectedCourse.value) {
    await fetchArchives()
  }
}

function handleWishCreated() {
  showWishDialog.value = false
  wishPoolActive.value = false
  nextTick(() => {
    wishPoolActive.value = true
  })
}

function getCategoryTag(categoryLabel) {
  const category = courseCategories.value.find(
    (cat) => localizedCategoryName(cat) === categoryLabel || cat.name === categoryLabel
  )
  return localizedCategoryLabel(category) || categoryLabel
}

function formatDownloadCount(count) {
  if (count === 0 || count === null || count === undefined) {
    return '0'
  }
  return count.toString()
}

function formatAnswerStatus(archive) {
  return archive?.hasAnswers ? t('含解答') : t('僅題目')
}

function toggleSidebar() {
  trackEvent(EVENTS.TOGGLE_SIDEBAR, { visible: !sidebarVisible.value })
  sidebarVisible.value = !sidebarVisible.value
}

async function handlePreviewDownload(onComplete) {
  if (!selectedArchive.value) return

  try {
    const { data } = await archiveService.getArchiveDownloadUrl(
      selectedCourse.value,
      selectedArchive.value.id
    )

    const fileName = `${selectedArchive.value.year}_${selectedSubject.value}_${selectedArchive.value.professor}_${selectedArchive.value.name}.pdf`
    startNativeDownload(data.url, fileName)

    trackEvent(EVENTS.DOWNLOAD_ARCHIVE, {
      archiveName: selectedArchive.value.name,
      year: selectedArchive.value.year,
      professor: selectedArchive.value.professor,
      type: selectedArchive.value.type,
      courseName: selectedSubject.value,
      source: 'preview-modal',
    })

    toast.add({
      severity: 'success',
      summary: t('已開始下載'),
      detail: t('已開始下載 {file}', { file: fileName }),
      life: 3000,
    })

    await syncArchiveDownloadCount(selectedArchive.value.id)
  } catch (error) {
    console.error('Download error:', error)
    if (isUnauthorizedError(error)) {
      return
    }
    toast.add({
      severity: 'error',
      summary: t('下載失敗'),
      detail:
        error.response?.status === 404 ? t('此筆考古題的 PDF 檔案缺失') : t('無法取得下載連結'),
      life: 3000,
    })
  } finally {
    onComplete()
  }
}

const getCurrentCategory = computed(() => {
  if (!selectedCourse.value) return ''

  for (const [category, courses] of Object.entries(coursesList.value)) {
    const course = courses.find((c) => c.id === selectedCourse.value)
    if (course) return category
  }
  return ''
})

const currentCategoryName = computed(() => getCategoryName(getCurrentCategory.value))
const currentCategoryLabel = computed(() => getCategoryTag(currentCategoryName.value))
const currentCourseEnglishName = computed(() => {
  if (!selectedCourse.value) return ''

  for (const courses of Object.values(coursesList.value)) {
    const course = courses.find((item) => item.id === selectedCourse.value)
    if (course && locale.value !== 'en') return (course.name_en || '').trim()
  }
  return ''
})

watch(locale, () => {
  if (!selectedCourse.value) return
  for (const courses of Object.values(coursesList.value)) {
    const course = courses.find((item) => item.id === selectedCourse.value)
    if (course) {
      selectedSubject.value = localizedCourseName(course)
      break
    }
  }
})

const searchEditProfessor = (event) => {
  const query = event?.query?.toLowerCase() || ''
  const filteredProfessors = uploadFormProfessors.value
    .filter((professor) => professor.name.toLowerCase().includes(query))
    .sort((a, b) => a.name.localeCompare(b.name))

  availableEditProfessors.value = filteredProfessors
}

const onEditProfessorSelect = (event) => {
  if (event.value && typeof event.value === 'object') {
    editForm.value.professor = event.value.name
  }
}

const closeEditDialog = () => {
  showEditDialog.value = false
  editForm.value = {
    id: null,
    name: '',
    professor: '',
    type: '',
    hasAnswers: false,
    academicYear: null,
    shouldTransfer: false,
    targetCategory: null,
    targetCourse: null,
    targetCourseId: null,
  }
}

const searchTargetCourse = (event) => {
  const query = normalizeCourseSearchText(event?.query || '')
  const filteredCourses = allAvailableCoursesForTransfer.value.filter((course) =>
    courseMatchesSearch(course.searchCourse, query)
  )

  availableCoursesForTransfer.value = filteredCourses
}

const onTargetCourseSelect = (event) => {
  if (event.value && typeof event.value === 'object') {
    editForm.value.targetCourse = event.value.label
    editForm.value.targetCourseId = event.value.id
  } else if (typeof event.value === 'string') {
    // User typed a new course name
    editForm.value.targetCourse = event.value
    editForm.value.targetCourseId = null
  }
}

// Handle direct input of course name
watch(
  () => editForm.value.targetCourse,
  (newValue) => {
    if (typeof newValue === 'string' && newValue) {
      // Check if it's an existing course
      const existingCourse = allAvailableCoursesForTransfer.value.find(
        (course) => normalizeCourseSearchText(course.label) === normalizeCourseSearchText(newValue)
      )
      if (existingCourse) {
        editForm.value.targetCourseId = existingCourse.id
      } else {
        editForm.value.targetCourseId = null
      }
    }
  }
)

watch(
  () => editForm.value.targetCategory,
  () => {
    editForm.value.targetCourseId = null
    editForm.value.targetCourse = null
    availableCoursesForTransfer.value = allAvailableCoursesForTransfer.value
  }
)

const checkAuthentication = () => {
  isAuthenticatedRef.value = isAuthenticated()
  if (isAuthenticatedRef.value) {
    const user = getCurrentUser()
    if (user) {
      userData.value = user
    } else {
      isAuthenticatedRef.value = false
      userData.value = null
    }
  } else {
    isAuthenticatedRef.value = false
    userData.value = null
  }
}

const mobileMenuItems = computed(() => {
  return menuItems.value.map((item) => ({
    ...item,
    items: item.items?.map((subItem) => ({
      ...subItem,
      command: () => {
        subItem.command()
        sidebarVisible.value = false
      },
    })),
  }))
})
</script>

<style scoped>
.card {
  position: relative;
  z-index: 1;
  background: var(--bg-primary);
}

.archive-screen,
.archive-screen > .flex {
  width: 100%;
  max-width: 100%;
  min-width: 0;
  overflow-x: hidden;
}

:deep(.p-sidebar),
:deep(.p-drawer) {
  padding: 0;
  background-color: var(--bg-primary);
  z-index: 2;
  border-right: 1px solid var(--border-color);
  max-width: 100vw;
}

:deep(.p-sidebar-header),
:deep(.p-drawer-header) {
  padding: 1rem;
  border-bottom: 1px solid var(--border-color);
  background-color: var(--bg-primary);
}

:deep(.p-sidebar-content),
:deep(.p-drawer-content) {
  padding: 1rem;
  background-color: var(--bg-primary);
}

:deep(.p-accordioncontent),
:deep(.p-accordioncontent-wrapper),
:deep(.p-accordioncontent-content) {
  width: 100%;
  max-width: 100%;
  min-width: 0;
  overflow-x: hidden;
}

:deep(.p-input-icon-left) {
  width: 100%;
}

:deep(.p-input-icon-left i) {
  left: 0.75rem;
}

:deep(.p-input-icon-left input) {
  padding-left: 2.5rem;
  background: var(--bg-primary);
  border-color: var(--border-color);
  color: var(--text-color);
}

:deep(.p-input-icon-left input:focus) {
  border-color: var(--primary-color);
  box-shadow: 0 0 0 1px var(--primary-color);
}

.sidebar {
  width: 318px;
  min-width: 0;
  max-width: min(318px, 100vw);
  background: #e4eee9;
  border: 0;
  border-right: 1px solid #c7d8d0;
  transition: width 0.2s ease-in-out;
  overflow: hidden;
  position: relative;
  z-index: 1;
  height: calc(100% - 0.25rem);
  margin-left: 0.25rem;
  margin-bottom: 0.25rem;
  display: flex;
  flex-direction: column;
  box-shadow: none;
}

.archive-dark .sidebar {
  background: #0e1b18;
  border-right-color: #22342f;
}

.upload-section {
  flex-shrink: 0;
  border-top: 1px solid #c7d8d0;
  background: #d8e8e0;
}

.upload-actions {
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
}

.upload-section :deep(.p-button) {
  min-height: 2.25rem;
  font-size: var(--app-font-size-xs) !important;
}

.upload-section :deep(.p-button-label) {
  font-size: inherit !important;
  line-height: 1.25;
}

.upload-section :deep(.p-button-icon) {
  font-size: calc(var(--app-font-size-xs) * 1.05) !important;
}

.archive-dark .upload-section {
  background: #0b1714;
  border-top-color: #22342f;
}

.sidebar-shell {
  width: 100%;
  opacity: 1;
  white-space: normal;
  height: 100%;
  transition: opacity 0.2s ease-in-out;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.sidebar .search-section {
  flex-shrink: 0;
}

.course-list-section {
  flex: 1 1 auto;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
}

.sidebar.collapsed {
  width: 0;
  min-width: 0;
  margin-left: 0;
  margin-bottom: 0;
  height: 100%;
  border-right: none;
}

.sidebar.collapsed .sidebar-shell {
  opacity: 0;
  pointer-events: none;
}

.main-content {
  flex: 1 1 0%;
  min-width: 0;
  max-width: 100%;
  background: transparent;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.subject-header {
  container-name: course-header;
  container-type: inline-size;
  border-bottom: 1px solid var(--border-color);
  background: #eef6f2;
  position: relative;
  z-index: 1;
  padding: 0.9rem 1.35rem;
}

.archive-dark .subject-header {
  background: #14211d;
}

.subject-heading-row {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) max-content;
  align-items: stretch;
  gap: 0.65rem 1rem;
}

.subject-title-stack {
  display: flex;
  flex-direction: column;
  min-width: 0;
  justify-content: center;
}

.subject-tag {
  flex: 0 0 auto;
  align-self: center;
}

.subject-title {
  color: var(--text-primary);
  font-size: clamp(1.25rem, 2vw, 1.75rem);
  font-weight: 800;
  line-height: 1.12;
  overflow-wrap: anywhere;
}

.subject-summary {
  display: inline-flex;
  align-self: center;
  align-items: center;
  justify-content: flex-end;
  justify-self: end;
  gap: 0.35rem;
  color: var(--text-secondary);
  font-size: var(--app-font-size-sm);
  font-weight: 650;
  text-align: right;
  white-space: nowrap;
}

.subject-summary-item {
  white-space: nowrap;
}

.subject-english-name {
  margin-top: 0.2rem;
  color: var(--text-secondary);
  font-size: var(--app-font-size-sm);
  line-height: 1.35;
}

@container course-header (max-width: 32rem) {
  .subject-summary {
    flex-direction: column;
    align-items: flex-end;
    gap: 0.12rem;
  }

  .subject-summary-separator {
    display: none;
  }
}

.archive-filter-bar {
  container-name: archive-filters;
  container-type: inline-size;
  border: 1px solid #d7e4df !important;
  border-radius: 8px;
  background: rgba(247, 251, 249, 0.84) !important;
  box-shadow: none;
  padding: 0.65rem 0.8rem !important;
}

.archive-filter-bar :deep(.p-toolbar-start) {
  width: 100%;
}

.archive-filter-shell {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  width: 100%;
  align-items: center;
  gap: 0.85rem;
}

.filter-summary {
  min-width: 0;
  color: var(--text-secondary);
  font-size: var(--app-font-size-sm);
  font-weight: 650;
}

.archive-filter-controls {
  display: grid;
  grid-template-columns: repeat(3, minmax(8rem, 10rem)) auto;
  min-width: 0;
  align-items: center;
  gap: 0.5rem;
}

.filter-select {
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
}

.archive-filter-controls :deep(.p-select),
.archive-filter-controls :deep(.p-select-label) {
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
}

.archive-filter-controls :deep(.p-select) {
  min-height: 2.35rem;
}

.answer-filter {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  min-height: 2.35rem;
  padding: 0 0.25rem;
  color: var(--text-secondary);
  font-size: var(--app-font-size-sm);
  font-weight: 650;
}

@container archive-filters (max-width: 52rem) {
  .archive-filter-shell {
    grid-template-columns: minmax(0, 1fr);
    align-items: stretch;
  }

  .archive-filter-controls {
    grid-template-columns: repeat(3, minmax(0, 1fr)) auto;
    width: 100%;
  }
}

@container archive-filters (max-width: 34rem) {
  .archive-filter-controls {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .answer-filter {
    justify-content: flex-start;
  }
}

.ellipsis {
  display: inline-block;
  max-width: 90%;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: middle;
}

.search-result-btn {
  width: 100%;
  justify-content: flex-start;
  text-align: left;
  padding: 0.5rem;
  border-radius: 4px;
}

.active-course-search-result {
  background: #dcebe4 !important;
  box-shadow: inset 3px 0 0 #176a5a;
  color: #17382f !important;
  font-weight: 800;
}

:deep(.p-panelmenu) {
  display: grid;
  gap: 0.7rem;
}

:deep(.p-panelmenu-panel) {
  overflow: hidden;
  border: 1px solid #cadbd4;
  border-radius: 8px;
  background: #f8fbfa;
}

.archive-dark :deep(.p-panelmenu-panel) {
  border-color: #22342f;
  background: #121b18;
}

:deep(.p-panelmenu-header-content),
:deep(.p-panelmenu-content) {
  border: 0;
  background: transparent;
}

:deep(.p-panelmenu-header-link) {
  padding: 0.85rem 1rem;
  font-size: var(--app-font-size-base) !important;
  font-weight: 800;
  line-height: 1.35;
}

:deep(.p-panelmenu-item-link) {
  border-radius: 7px;
  margin: 0.15rem 0.45rem;
  padding: 0.55rem 0.75rem;
  font-size: var(--app-font-size-sm) !important;
  line-height: 1.35;
  white-space: normal;
}

:deep(.active-course-menu-item .p-panelmenu-item-link),
:deep(.active-course-menu-item > .p-panelmenu-item-link) {
  background: #dcebe4;
  box-shadow: inset 3px 0 0 #176a5a;
  color: #17382f;
  font-weight: 800;
}

.archive-dark :deep(.active-course-menu-item .p-panelmenu-item-link),
.archive-dark :deep(.active-course-menu-item > .p-panelmenu-item-link) {
  background: #172c26;
  color: #edf8f3;
  box-shadow: inset 3px 0 0 #49b692;
}

:deep(.p-accordion) {
  display: grid;
  gap: 0.85rem;
}

:deep(.p-accordionpanel) {
  overflow: hidden;
  border: 1px solid var(--border-color);
  border-left: 4px solid #176a5a;
  border-radius: 8px;
  background: #fbfdfc;
}

:deep(.p-accordionheader) {
  padding: 0.82rem 1rem;
  border: 0;
  background: #f0f7f4;
  font-size: var(--app-font-size-base);
  font-weight: 800;
}

:deep(.p-accordioncontent-content) {
  padding: 0.75rem;
  background: transparent;
}

.term-header-content {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}

.term-title {
  color: var(--text-primary);
  font-weight: 850;
}

.term-count {
  color: #60776f;
  font-size: calc(var(--app-font-size-base) * 0.86);
  font-weight: 750;
}

.archive-card-grid {
  display: grid;
  gap: 0.5rem;
}

.archive-record-card {
  padding: 0.65rem 0.75rem;
  border: 1px solid #d8e4df;
  border-left: 3px solid #6da48f;
  border-radius: 8px;
  background: #ffffff;
}

.archive-dark .archive-record-card {
  background: #0d1a17;
  border-color: #22342f;
  border-left-color: #35d39a;
}

.archive-record-content {
  display: grid;
  gap: 0.38rem;
  min-width: 0;
}

.archive-record-line,
.archive-record-title-group,
.archive-record-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
}

.archive-record-primary-line {
  justify-content: space-between;
  gap: 0.75rem;
}

.archive-record-title-group {
  flex: 1 1 16rem;
  min-width: 0;
  gap: 0.55rem;
}

.archive-record-card h3 {
  min-width: 0;
  margin: 0;
  color: var(--text-primary);
  font-size: var(--app-font-size-base);
  font-weight: 800;
  line-height: 1.28;
  overflow-wrap: anywhere;
}

.exam-type-tag {
  background: #edf5f1 !important;
  border-color: #c5d8d0 !important;
  color: #1d5f52 !important;
  font-weight: 800;
}

.archive-record-meta-line {
  gap: 0.35rem 0.65rem;
  color: var(--text-secondary);
  font-size: calc(var(--app-font-size-base) * 0.86);
  font-weight: 560;
}

.archive-record-meta-line span + span::before {
  content: '';
  display: inline-block;
  width: 0.2rem;
  height: 0.2rem;
  margin-right: 0.65rem;
  border-radius: 50%;
  vertical-align: middle;
  background: #91a9a0;
}

.archive-record-actions {
  flex: 0 0 auto;
  justify-content: flex-end;
  gap: 0.35rem;
}

.archive-record-actions :deep(.p-button) {
  min-height: 2.05rem;
  padding-top: 0.36rem;
  padding-bottom: 0.36rem;
  font-size: var(--app-font-size-sm) !important;
}

.archive-record-actions :deep(.archive-action-icon.p-button) {
  width: 2.05rem;
  padding-right: 0;
  padding-left: 0;
}

.archive-record-actions :deep(.archive-action-edit.p-button) {
  color: #426b61;
  border-color: #c5d8d0;
  background: #fbfdfc;
}

.archive-dark .archive-filter-bar {
  border-color: #22342f !important;
  background: rgba(18, 31, 27, 0.86) !important;
}

.archive-dark :deep(.p-accordionpanel) {
  border-left-color: #49b692;
  background: #0f1a17;
}

.archive-dark :deep(.p-accordionheader) {
  background: #14231f;
}

.archive-dark .term-count {
  color: #9db8ae;
}

.archive-dark .exam-type-tag {
  background: #172c26 !important;
  border-color: #29483f !important;
  color: #9ee8c7 !important;
}

.archive-dark .archive-record-actions :deep(.archive-action-edit.p-button) {
  color: #b4cbc3;
  border-color: #29483f;
  background: #0f1a17;
}

@media (max-width: 1199px) {
  .subject-header {
    padding: 0.75rem 1rem;
  }

  .subject-title {
    font-size: clamp(1.12rem, 2.4vw, 1.5rem);
  }

  .subject-summary,
  .subject-english-name {
    font-size: calc(var(--app-font-size-base) * 0.84);
  }

  .archive-filter-bar {
    margin: 0.75rem 0.75rem 0.55rem !important;
    padding: 0.55rem 0.65rem !important;
  }

  .filter-summary {
    font-size: calc(var(--app-font-size-base) * 0.84);
    line-height: 1.35;
  }

  .archive-filter-controls {
    gap: 0.45rem;
  }

  .archive-filter-controls :deep(.p-select) {
    min-height: 2.25rem;
  }

  .archive-filter-controls :deep(.p-select-label) {
    padding-top: 0.42rem;
    padding-bottom: 0.42rem;
    font-size: calc(var(--app-font-size-base) * 0.88);
  }

  .answer-filter {
    min-height: 2.25rem;
    justify-content: center;
    padding: 0 0.45rem;
    font-size: calc(var(--app-font-size-base) * 0.86);
  }

  :deep(.p-accordion) {
    gap: 0.65rem;
    max-width: calc(100% - 1.5rem);
  }

  :deep(.p-accordionpanel) {
    border-left-width: 3px;
  }

  :deep(.p-accordionheader) {
    padding: 0.68rem 0.78rem;
    font-size: var(--app-control-font-size);
  }

  :deep(.p-accordioncontent-content) {
    padding: 0.55rem;
  }

  .archive-record-card {
    padding: 0.55rem 0.62rem;
  }

  .archive-record-card h3 {
    font-size: calc(var(--app-font-size-base) * 0.98);
  }

  .archive-record-meta-line {
    font-size: var(--app-badge-font-size);
  }

  .archive-record-actions :deep(.p-button) {
    min-height: 1.95rem;
    padding-top: 0.3rem;
    padding-bottom: 0.3rem;
  }
}

@media (min-width: 1025px) and (max-width: 1199px) {
  .sidebar {
    width: 280px;
    max-width: 280px;
  }

  .archive-record-title-group {
    flex-basis: 13rem;
  }
}

@media (min-width: 768px) and (max-width: 1024px) {
  .sidebar {
    width: 258px;
    max-width: 258px;
  }

  .search-section,
  .course-list-section,
  .upload-section {
    padding-left: 0.75rem !important;
    padding-right: 0.75rem !important;
  }
}

@media (max-width: 767px) {
  .subject-header {
    padding: 0.62rem 0.8rem;
  }

  .subject-title {
    font-size: 1.22rem;
  }

  .subject-summary {
    font-size: calc(var(--app-font-size-base) * 0.8);
    line-height: 1.35;
  }

  .archive-filter-bar {
    margin: 0.55rem 0.55rem 0.45rem !important;
    padding: 0.48rem 0.52rem !important;
  }

  .filter-summary {
    font-size: calc(var(--app-font-size-base) * 0.8);
  }

  .archive-filter-controls {
    gap: 0.4rem;
  }

  .archive-filter-controls :deep(.p-select) {
    min-height: 2.08rem;
  }

  .archive-filter-controls :deep(.p-select-label) {
    padding: 0.34rem 0.55rem;
    font-size: var(--app-badge-font-size);
  }

  .archive-filter-controls :deep(.p-select-dropdown) {
    width: 2rem;
  }

  .answer-filter {
    min-height: 2.08rem;
    font-size: var(--app-badge-font-size);
    line-height: 1;
  }

  .answer-filter :deep(.p-checkbox) {
    width: 1rem;
    height: 1rem;
  }

  .answer-filter :deep(.p-checkbox-box) {
    width: 1rem;
    height: 1rem;
  }

  :deep(.p-accordion) {
    gap: 0.52rem;
    max-width: calc(100% - 1.1rem);
  }

  :deep(.p-accordionheader) {
    padding: 0.58rem 0.65rem;
    font-size: var(--app-font-size-sm);
  }

  .term-count {
    font-size: var(--app-font-size-xs);
  }

  :deep(.p-accordioncontent-content) {
    padding: 0.45rem;
  }
}

@media (max-width: 640px) {
  .archive-card-grid {
    gap: 0.42rem;
  }

  .archive-record-content {
    gap: 0.3rem;
  }

  .archive-record-primary-line {
    display: contents;
  }

  .archive-record-title-group {
    order: 1;
    gap: 0.45rem;
  }

  .archive-record-meta-line {
    order: 2;
    gap: 0.26rem 0.52rem;
    font-size: calc(var(--app-font-size-base) * 0.79);
    line-height: 1.45;
  }

  .archive-record-meta-line span + span::before {
    width: 0.18rem;
    height: 0.18rem;
    margin-right: 0.52rem;
  }

  .archive-record-actions {
    order: 3;
    width: 100%;
    justify-content: flex-start;
    gap: 0.36rem;
    margin-top: 0.08rem;
  }

  .archive-record-actions :deep(.p-button) {
    min-height: 1.92rem;
    padding: 0.28rem 0.55rem;
    font-size: calc(var(--app-font-size-base) * 0.8);
  }

  .archive-record-actions :deep(.archive-action-icon.p-button) {
    width: 2rem;
    flex: 0 0 2rem;
  }
}

@media (max-width: 480px) {
  .answer-filter {
    justify-content: flex-start;
    padding-left: 0.12rem;
  }

  .archive-record-card {
    padding: 0.5rem 0.55rem;
  }

  .archive-record-card h3 {
    font-size: var(--app-control-font-size);
  }

  .exam-type-tag {
    max-width: 5.5rem;
  }

  .archive-record-actions :deep(.archive-action-preview.p-button),
  .archive-record-actions :deep(.archive-action-download.p-button),
  .archive-record-actions :deep(.archive-action-edit.p-button),
  .archive-record-actions :deep(.archive-action-delete.p-button) {
    flex: 1 1 0;
    min-width: 0;
    padding-right: 0.45rem;
    padding-left: 0.45rem;
  }

  .archive-record-actions :deep(.p-button-label) {
    display: none;
  }

  .archive-record-actions :deep(.p-button-icon) {
    margin: 0;
  }
}

.search-results .text-sm {
  font-size: var(--app-font-size-sm);
}

/* Mobile sidebar specific styles */
.mobile-drawer {
  display: none;
}

@media (max-width: 768px) {
  .mobile-drawer {
    display: block;
  }
}

:deep(.mobile-drawer.p-drawer),
:deep(.mobile-drawer .p-sidebar),
:deep(.mobile-drawer .p-drawer) {
  z-index: 1000;
  width: min(100vw, 26rem) !important;
  max-width: 100vw;
  background: #f5f8f1;
  border-right: 1px solid rgba(88, 126, 106, 0.22);
}

:global(.mobile-drawer.p-drawer),
:global(.mobile-drawer .p-drawer),
:global(.mobile-drawer .p-sidebar) {
  width: min(100vw, 26rem) !important;
  max-width: 100vw;
  background: #f5f8f1 !important;
  color: #17382f !important;
  border-right: 1px solid rgba(88, 126, 106, 0.22);
  box-shadow: 0 1.5rem 3.5rem rgba(42, 68, 54, 0.18);
}

:global(.mobile-drawer.mobile-drawer-dark.p-drawer),
:global(.mobile-drawer.mobile-drawer-dark .p-drawer),
:global(.mobile-drawer.mobile-drawer-dark .p-sidebar) {
  background: #101916 !important;
  color: rgba(239, 247, 238, 0.94) !important;
  border-right-color: rgba(214, 230, 223, 0.16);
  box-shadow: 0 1.5rem 3.5rem rgba(0, 0, 0, 0.38);
}

:global(.mobile-drawer-mask) {
  background: rgba(31, 54, 45, 0.2) !important;
  backdrop-filter: blur(2px);
}

:global(.mobile-drawer-mask-dark) {
  background: rgba(2, 8, 7, 0.54) !important;
}

:deep(.mobile-drawer .p-sidebar-content),
:deep(.mobile-drawer .p-drawer-content) {
  padding: 0.9rem;
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow-x: hidden;
  background:
    radial-gradient(circle at 78% 8%, rgba(202, 179, 111, 0.14), transparent 9rem),
    linear-gradient(180deg, #fbfaf3 0%, #eef6f1 100%);
}

:global(.mobile-drawer .p-drawer-content),
:global(.mobile-drawer .p-sidebar-content) {
  padding: 0.9rem !important;
  overflow-x: hidden;
  background:
    radial-gradient(circle at 78% 8%, rgba(202, 179, 111, 0.14), transparent 9rem),
    linear-gradient(180deg, #fbfaf3 0%, #eef6f1 100%) !important;
}

:global(.mobile-drawer.mobile-drawer-dark .p-drawer-content),
:global(.mobile-drawer.mobile-drawer-dark .p-sidebar-content) {
  background:
    radial-gradient(circle at 78% 8%, rgba(202, 179, 111, 0.12), transparent 9rem),
    linear-gradient(180deg, #101916 0%, #0b1512 100%) !important;
}

:deep(.mobile-drawer .p-sidebar-header),
:deep(.mobile-drawer .p-drawer-header) {
  padding: 1rem;
  border-bottom: 1px solid rgba(88, 126, 106, 0.2);
  background-color: #fbfaf3;
  position: relative;
}

:global(.mobile-drawer .p-drawer-header),
:global(.mobile-drawer .p-sidebar-header) {
  background: #fbfaf3 !important;
  border-bottom: 1px solid rgba(88, 126, 106, 0.2);
  color: #17382f !important;
}

:global(.mobile-drawer.mobile-drawer-dark .p-drawer-header),
:global(.mobile-drawer.mobile-drawer-dark .p-sidebar-header) {
  background: #101916 !important;
  border-bottom-color: rgba(214, 230, 223, 0.16);
  color: rgba(239, 247, 238, 0.94) !important;
}

:deep(.mobile-drawer .p-sidebar-close),
:deep(.mobile-drawer .p-drawer-close-button) {
  position: absolute;
  top: 50%;
  right: 1rem;
  transform: translateY(-50%);
  width: 2rem;
  height: 2rem;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.58);
  border: 1px solid rgba(88, 126, 106, 0.24);
  color: #17382f;
  cursor: pointer;
  transition: all 0.2s;
}

:deep(.mobile-drawer .p-sidebar-close:hover),
:deep(.mobile-drawer .p-drawer-close-button:hover) {
  background: rgba(225, 238, 229, 0.86);
}

:global(.mobile-drawer.mobile-drawer-dark .p-drawer-close-button),
:global(.mobile-drawer.mobile-drawer-dark .p-sidebar-close) {
  background: rgba(214, 230, 223, 0.06);
  border-color: rgba(214, 230, 223, 0.16);
  color: rgba(239, 247, 238, 0.94);
}

:global(.mobile-drawer.mobile-drawer-dark .p-drawer-close-button:hover),
:global(.mobile-drawer.mobile-drawer-dark .p-sidebar-close:hover) {
  background: rgba(214, 230, 223, 0.12);
}

.mobile-upload-section {
  margin: 0 -0.9rem -0.9rem;
  padding: 0.9rem;
  padding-bottom: max(0.9rem, env(safe-area-inset-bottom));
}

:global(.mobile-drawer.mobile-drawer-dark .mobile-upload-section) {
  background: #0b1714 !important;
  border-top: 1px solid #22342f !important;
  box-shadow: 0 -1px 0 rgba(214, 230, 223, 0.04);
}

:global(
  .mobile-drawer.mobile-drawer-dark
    .mobile-upload-section
    .p-button.p-button-secondary.p-button-outlined
) {
  background: rgba(214, 230, 223, 0.06) !important;
  border-color: rgba(214, 230, 223, 0.28) !important;
  color: rgba(239, 247, 238, 0.92) !important;
}

:global(
  .mobile-drawer.mobile-drawer-dark
    .mobile-upload-section
    .p-button.p-button-secondary.p-button-outlined:hover
) {
  background: rgba(214, 230, 223, 0.12) !important;
  border-color: rgba(214, 230, 223, 0.4) !important;
  color: #f4fbf4 !important;
}

/* Ensure proper mobile responsiveness */
@media (max-width: 768px) {
  .main-content {
    width: 100%;
    min-width: 0;
    overflow-x: hidden;
  }

  /* Dialog font size adjustments for mobile */
  :deep(.p-dialog .p-dialog-content) {
    font-size: 0.875rem;
  }

  :deep(.p-dialog .p-dialog-header) {
    font-size: 1rem;
  }

  :deep(.p-dialog label) {
    font-size: 0.875rem;
  }

  :deep(.p-dialog .p-inputtext) {
    font-size: 0.875rem;
  }

  :deep(.p-dialog .p-button) {
    font-size: 0.875rem;
    padding: 0.5rem 0.75rem;
  }

  :deep(.p-dialog .p-dropdown-label),
  :deep(.p-dialog .p-autocomplete-input),
  :deep(.p-dialog .p-calendar-input) {
    font-size: 0.875rem;
  }

  :deep(.p-dialog .p-checkbox-label) {
    font-size: 0.875rem;
  }

  /* Table responsive design for mobile */
  :deep(.p-accordioncontent-content .p-datatable) {
    font-size: 0.75rem;
    width: 100%;
    max-width: 100%;
  }

  :deep(.p-accordioncontent-content .p-datatable-table-container) {
    width: 100%;
    max-width: 100%;
    overflow-x: auto;
  }

  :deep(.p-datatable-table) {
    font-size: 0.75rem;
    min-width: 600px;
    width: 100%;
  }

  :deep(.p-datatable .p-datatable-thead > tr > th) {
    font-size: 0.75rem;
    padding: 0.5rem 0.25rem;
    white-space: nowrap;
  }

  :deep(.p-datatable .p-datatable-tbody > tr > td) {
    font-size: 0.75rem;
    padding: 0.5rem 0.25rem;
    white-space: nowrap;
  }

  :deep(.p-datatable .p-button) {
    font-size: 0.75rem;
    padding: 0.25rem 0.5rem;
    white-space: nowrap;
  }

  :deep(.p-tag) {
    font-size: 0.625rem;
    padding: 0.125rem 0.375rem;
    white-space: nowrap;
  }

  /* Make table container scrollable on mobile */
  :deep(.p-accordion-content) {
    padding: 0.5rem;
    overflow-x: auto;
  }

  /* Adjust button groups for mobile */
  :deep(.p-datatable .p-column-header-content) {
    justify-content: center;
  }

  /* Ensure buttons don't wrap */
  :deep(.p-datatable .flex.gap-2\.5) {
    flex-wrap: nowrap;
    gap: 0.25rem;
  }

  /* Accordion adjustments for mobile */
  :deep(.p-accordion .p-accordion-header) {
    font-size: 0.875rem;
  }

  :deep(.p-accordion .p-accordion-content) {
    padding: 0.5rem;
  }
}

@media (max-width: 768px) {
  :deep(.mobile-drawer .p-panelmenu),
  :deep(.mobile-drawer .p-panelmenu-panel),
  :deep(.mobile-drawer .p-panelmenu-header-content),
  :deep(.mobile-drawer .p-panelmenu-header),
  :deep(.mobile-drawer .p-panelmenu-item-content),
  :deep(.mobile-drawer .p-panelmenu-content) {
    width: 100%;
    max-width: 100%;
    overflow: hidden;
    border-color: rgba(88, 126, 106, 0.2);
    background: #f8fbf6 !important;
  }

  :global(.mobile-drawer .p-panelmenu),
  :global(.mobile-drawer .p-panelmenu-panel),
  :global(.mobile-drawer .p-panelmenu-header),
  :global(.mobile-drawer .p-panelmenu-header-content),
  :global(.mobile-drawer .p-panelmenu-item-content),
  :global(.mobile-drawer .p-panelmenu-content) {
    width: 100%;
    max-width: 100%;
    overflow: hidden;
    border-color: rgba(88, 126, 106, 0.2) !important;
    background: #f8fbf6 !important;
  }

  :deep(.mobile-drawer .p-panelmenu-panel) {
    margin-bottom: 0.75rem;
    border-radius: 8px;
  }

  :global(.mobile-drawer .p-panelmenu-panel) {
    margin-bottom: 0.75rem;
    border-radius: 8px;
    box-shadow: none !important;
  }

  :deep(.mobile-drawer .p-panelmenu-header-link),
  :deep(.mobile-drawer .p-panelmenu-item-link) {
    min-height: 3rem;
    color: #17382f !important;
    background: #f8fbf6 !important;
  }

  :global(.mobile-drawer .p-panelmenu-header-link),
  :global(.mobile-drawer .p-panelmenu-item-link) {
    min-height: 3rem;
    color: #17382f !important;
    background: #f8fbf6 !important;
  }

  :deep(.mobile-drawer .p-panelmenu-header-link:hover),
  :deep(.mobile-drawer .p-panelmenu-item-link:hover) {
    background: #edf6f1 !important;
  }

  :deep(.mobile-drawer .p-panelmenu-header-label),
  :deep(.mobile-drawer .p-panelmenu-item-label),
  :deep(.mobile-drawer .p-panelmenu-header-icon),
  :deep(.mobile-drawer .p-panelmenu-submenu-icon) {
    color: #17382f !important;
  }

  :global(.mobile-drawer .p-panelmenu-header-label),
  :global(.mobile-drawer .p-panelmenu-item-label),
  :global(.mobile-drawer .p-panelmenu-header-icon),
  :global(.mobile-drawer .p-panelmenu-submenu-icon),
  :global(.mobile-drawer .p-panelmenu-item-icon) {
    color: #17382f !important;
  }

  :deep(.mobile-drawer .p-inputtext) {
    min-height: 3rem;
    background: rgba(255, 255, 255, 0.82);
    color: #17382f;
    border-color: rgba(88, 126, 106, 0.24);
  }

  :global(.mobile-drawer.mobile-drawer-dark .p-panelmenu),
  :global(.mobile-drawer.mobile-drawer-dark .p-panelmenu-panel),
  :global(.mobile-drawer.mobile-drawer-dark .p-panelmenu-header),
  :global(.mobile-drawer.mobile-drawer-dark .p-panelmenu-header-content),
  :global(.mobile-drawer.mobile-drawer-dark .p-panelmenu-item-content),
  :global(.mobile-drawer.mobile-drawer-dark .p-panelmenu-content) {
    border-color: rgba(214, 230, 223, 0.16) !important;
    background: #111816 !important;
  }

  :global(.mobile-drawer.mobile-drawer-dark .p-panelmenu-header-link),
  :global(.mobile-drawer.mobile-drawer-dark .p-panelmenu-item-link) {
    color: rgba(239, 247, 238, 0.92) !important;
    background: #111816 !important;
  }

  :global(.mobile-drawer.mobile-drawer-dark .p-panelmenu-header-link:hover),
  :global(.mobile-drawer.mobile-drawer-dark .p-panelmenu-item-link:hover) {
    background: #172522 !important;
  }

  :global(.mobile-drawer.mobile-drawer-dark .p-panelmenu-header-label),
  :global(.mobile-drawer.mobile-drawer-dark .p-panelmenu-item-label),
  :global(.mobile-drawer.mobile-drawer-dark .p-panelmenu-header-icon),
  :global(.mobile-drawer.mobile-drawer-dark .p-panelmenu-submenu-icon),
  :global(.mobile-drawer.mobile-drawer-dark .p-panelmenu-item-icon) {
    color: rgba(239, 247, 238, 0.92) !important;
  }

  :global(.mobile-drawer.mobile-drawer-dark .p-inputtext) {
    background: #080a0b !important;
    color: rgba(239, 247, 238, 0.94) !important;
    border-color: rgba(214, 230, 223, 0.22) !important;
  }

  .upload-section,
  .admin-section {
    padding-bottom: max(1rem, env(safe-area-inset-bottom));
  }
}

/* Desktop table overflow handling */
@media (min-width: 769px) {
  :deep(.p-accordioncontent-content .p-datatable) {
    width: 100%;
    max-width: 100%;
  }

  :deep(.p-accordioncontent-content .p-datatable-table-container) {
    width: 100%;
    max-width: 100%;
    overflow-x: auto;
  }

  :deep(.p-datatable-table) {
    min-width: 800px;
    width: 100%;
  }

  :deep(.p-datatable .p-datatable-thead > tr > th),
  :deep(.p-datatable .p-datatable-tbody > tr > td) {
    white-space: nowrap;
  }

  :deep(.p-datatable .p-button) {
    white-space: nowrap;
  }

  :deep(.p-tag) {
    white-space: nowrap;
  }

  /* Make accordion content scrollable on desktop too */
  :deep(.p-accordion-content) {
    overflow-x: auto;
  }

  /* Ensure buttons don't wrap on desktop */
  :deep(.p-datatable .flex.gap-2\.5) {
    flex-wrap: nowrap;
    gap: 0.5rem;
  }
}

/* Search section styles */
.search-section {
  flex-shrink: 0;
}

/* Scrollable content styles */
.sidebar .search-results,
.mobile-drawer .search-results {
  padding: 0.5rem;
}

.sidebar .search-results {
  white-space: nowrap;
  overflow: hidden;
}

.sidebar .search-results .p-button {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sidebar :deep(.p-panelmenu) {
  white-space: nowrap;
}

.sidebar :deep(.p-panelmenu .p-panelmenu-content) {
  overflow: hidden;
}

.admin-section {
  flex-shrink: 0;
}

.submission-level {
  margin-bottom: 0.75rem;
  padding: 0.75rem 0.9rem;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  background: color-mix(in srgb, var(--bg-secondary) 88%, var(--primary-color) 12%);
  overflow: hidden;
}

.submission-level-header,
.submission-level-meta {
  display: flex;
  justify-content: space-between;
  gap: 0.75rem 1rem;
}

.submission-level-header {
  align-items: baseline;
  margin-bottom: 0.5rem;
}

.submission-level-header span,
.submission-level-meta {
  color: var(--text-secondary);
  font-size: var(--app-font-size-sm);
}

.submission-level-progress-track {
  position: relative;
  width: 100%;
  height: 0.75rem;
  box-sizing: border-box;
  overflow: hidden;
  padding: 2px;
  border: 1px solid var(--level-progress-border);
  border-radius: 999px;
  background: color-mix(in srgb, var(--border-color) 82%, var(--bg-primary) 18%);
}

.submission-level-progress-fill {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--level-progress-bg);
  box-shadow: inset 0 0 0 1px var(--level-progress-border);
}

.submission-level-meta {
  flex-wrap: wrap;
  margin-top: 0.45rem;
  line-height: 1.35;
}

.submission-summary {
  margin-bottom: 1.25rem;
  padding: 1rem;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  background: var(--bg-secondary);
  overflow: hidden;
}

.submission-summary-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.7rem;
}

.submission-summary-header strong {
  font-size: var(--app-font-size-base);
}

.submission-summary-header > span,
.submission-summary-empty {
  color: var(--text-secondary);
  font-size: var(--app-font-size-sm);
}

.submission-summary-bar {
  display: flex;
  width: 100%;
  height: 0.65rem;
  overflow: hidden;
  border-radius: 999px;
  background: color-mix(in srgb, var(--border-color) 70%, transparent);
}

.submission-summary-segment {
  flex: 0 0 auto;
  height: 100%;
}

.submission-summary-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 0.65rem 1.25rem;
  margin-top: 0.85rem;
}

.submission-summary-legend-item {
  display: flex;
  align-items: center;
  gap: 0.38rem;
  min-width: 0;
  white-space: nowrap;
  font-size: var(--app-font-size-sm);
}

.submission-summary-dot {
  width: 0.65rem;
  height: 0.65rem;
  flex: 0 0 auto;
  border-radius: 50%;
}

.submission-summary-empty {
  margin-top: 0.75rem;
}

.submission-status-list h3 {
  margin: 0 0 0.75rem;
  font-size: var(--app-font-size-lg);
}

.submission-empty {
  color: var(--text-secondary);
  padding: 1rem;
  border: 1px solid var(--border-color);
  border-radius: 8px;
}

.submission-status-card {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  padding: 1rem;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-secondary);
}

.submission-status-card + .submission-status-card {
  margin-top: 0.75rem;
}

.submission-status-head {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: flex-start;
  gap: 0.75rem;
}

.submission-status-badges {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem;
  max-width: 12rem;
}

.submission-status-title {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  min-width: 0;
}

.submission-status-title strong {
  font-size: var(--app-font-size-base);
  line-height: 1.3;
  overflow-wrap: anywhere;
}

.submission-status-title span {
  color: var(--text-secondary);
  overflow-wrap: anywhere;
}

.my-submission-id {
  align-self: start;
  color: var(--text-secondary);
  font-size: var(--app-font-size-sm);
  font-weight: 600;
  line-height: 1.35;
  overflow-wrap: anywhere;
  text-align: right;
}

.submission-status-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.submission-time-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem 1.25rem;
  color: var(--text-secondary);
  font-size: var(--app-font-size-sm);
  line-height: 1.4;
}

.submission-time-meta span {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  min-width: 0;
  overflow-wrap: anywhere;
}

:deep(.my-submission-status-badge.soft-badge) {
  min-height: 1.72rem !important;
  padding: 0.22rem 0.62rem !important;
  font-size: var(--app-badge-font-size) !important;
  font-weight: 650 !important;
  line-height: 1.25 !important;
}

:deep(.submission-admin-badge.soft-badge),
:deep(.submission-meta-chip.soft-badge),
:deep(.my-submission-type-badge.soft-badge) {
  font-size: var(--app-badge-font-size) !important;
  line-height: 1.25 !important;
}

:deep(.submission-status-badge.soft-badge .pi),
:deep(.submission-admin-badge.soft-badge .pi),
:deep(.submission-meta-chip.soft-badge .pi) {
  font-size: 0.95em !important;
}

.submission-status-note {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.45rem 0.6rem;
  border-radius: 8px;
  color: var(--text-color);
  background: color-mix(in srgb, var(--bg-primary) 82%, var(--border-color));
  border: 1px solid var(--border-color);
}

.submission-meta-chip {
  max-width: 100%;
}

.submission-status-note {
  align-self: flex-start;
}

.submission-status-note span:not(.soft-badge) {
  color: var(--text-secondary);
}

.submission-status-note small {
  color: var(--text-secondary);
}

.submission-review-note {
  display: flex;
  align-items: flex-start;
  gap: 0.35rem;
  padding-top: 0.65rem;
  border-top: 1px solid var(--border-color);
  color: var(--text-secondary);
  font-size: var(--app-font-size-sm);
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.submission-review-note-label {
  flex: 0 0 auto;
  color: var(--text-color);
  font-weight: 650;
}

.submission-review-note strong {
  min-width: 0;
  color: var(--text-color);
  font-weight: 500;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.submission-review-note-empty {
  min-width: 0;
}

@media (max-width: 767px) {
  .submission-level-header,
  .submission-level-meta {
    align-items: flex-start;
    flex-direction: column;
    gap: 0.2rem;
  }

  .submission-summary-header {
    align-items: flex-start;
    flex-direction: column;
    gap: 0.25rem;
  }

  .submission-summary-legend {
    flex-direction: column;
    gap: 0.55rem;
  }

  .submission-summary-legend-item {
    white-space: normal;
    overflow-wrap: anywhere;
  }

  .submission-time-meta {
    flex-direction: column;
  }

  .submission-status-head {
    grid-template-columns: minmax(0, 1fr);
    gap: 0.5rem;
  }

  .submission-status-badges {
    max-width: none;
  }

  .my-submission-id {
    text-align: left;
  }

  .submission-review-note {
    flex-direction: column;
    gap: 0.15rem;
  }

  .submission-review-note-divider {
    display: none;
  }
}
</style>
