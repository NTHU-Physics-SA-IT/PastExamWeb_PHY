<template>
  <div class="h-full px-2 md:px-4 admin-container">
    <div class="card h-full flex flex-col">
      <Tabs :value="currentTab" class="flex-1" @update:value="handleTabChange">
        <TabList>
          <Tab value="3">審核中心</Tab>
          <Tab value="0">課程管理</Tab>
          <Tab value="2">公告管理</Tab>
          <Tab value="1">使用者管理</Tab>
          <Tab value="5">回報管理</Tab>
          <Tab value="4">垃圾桶</Tab>
        </TabList>
        <TabPanels>
          <TabPanel value="0">
            <div class="p-2 md:p-4">
              <Message v-if="courseLoadError" severity="error" :closable="false" class="mb-4">
                <div class="flex flex-wrap align-items-center justify-content-between gap-3">
                  <span>{{ courseLoadError }}</span>
                  <Button
                    label="重新載入"
                    icon="pi pi-refresh"
                    severity="danger"
                    outlined
                    size="small"
                    :loading="coursesLoading"
                    @click="loadCourses"
                  />
                </div>
              </Message>
              <section class="admin-section mb-5">
                <div class="admin-toolbar admin-toolbar--course admin-toolbar--section mb-3">
                  <div>
                    <h3 class="m-0">課程分類</h3>
                    <p class="m-0 text-sm text-500">管理左側分類順序、分類名稱與科目標籤</p>
                  </div>
                  <div class="admin-toolbar__actions">
                    <Button
                      class="admin-toolbar__button"
                      label="新增分類"
                      icon="pi pi-plus"
                      severity="success"
                      outlined
                      @click="openCreateCategoryDialog"
                    />
                  </div>
                </div>
                <DataTable
                  v-if="!courseLoadError"
                  :value="courseCategories"
                  class="admin-data-table admin-desktop-data-table category-management-table"
                  tableStyle="min-width: 44rem"
                  responsiveLayout="stack"
                  breakpoint="1023px"
                >
                  <Column header="順序" style="width: 12rem">
                    <template #body="{ data }">
                      <div class="mobile-card-order flex align-items-center gap-2">
                        <span class="text-sm text-500 w-2rem">{{
                          getCategoryPosition(data) + 1
                        }}</span>
                        <Button
                          icon="pi pi-arrow-up"
                          severity="secondary"
                          text
                          rounded
                          size="small"
                          :disabled="!canMoveCategory(data, -1) || categoryOrderLoading"
                          @click="moveCategory(data, -1)"
                        />
                        <Button
                          icon="pi pi-arrow-down"
                          severity="secondary"
                          text
                          rounded
                          size="small"
                          :disabled="!canMoveCategory(data, 1) || categoryOrderLoading"
                          @click="moveCategory(data, 1)"
                        />
                      </div>
                    </template>
                  </Column>
                  <Column field="name" header="分類名稱">
                    <template #body="{ data }">
                      <span class="category-name-desktop">{{ data.name }}</span>
                      <span class="category-name-mobile">
                        <span class="category-mobile-header">
                          <span class="category-mobile-title">{{ data.name }}</span>
                          <span class="category-key-mobile">
                            <span class="mobile-field-label">Key</span>
                            <span class="mobile-field-value">{{ data.key }}</span>
                          </span>
                        </span>
                      </span>
                    </template>
                  </Column>
                  <Column field="label" header="科目標籤">
                    <template #body="{ data }">
                      <Tag severity="secondary" :class="getCategoryBadgeClass(data)">
                        {{ data.label || data.name }}
                      </Tag>
                    </template>
                  </Column>
                  <Column field="key" header="Key">
                    <template #body="{ data }">
                      <span class="category-key-desktop">{{ data.key }}</span>
                    </template>
                  </Column>
                  <Column field="is_active" header="狀態" style="width: 8rem">
                    <template #body="{ data }">
                      <Tag :severity="data.is_active ? 'success' : 'secondary'">
                        {{ data.is_active ? '啟用中' : '已停用' }}
                      </Tag>
                    </template>
                  </Column>
                  <Column header="操作" style="width: 20rem">
                    <template #body="{ data }">
                      <div class="admin-card-actions">
                        <Button
                          icon="pi pi-pencil"
                          label="編輯"
                          aria-label="編輯分類"
                          title="編輯分類"
                          size="small"
                          outlined
                          @click="openEditCategoryDialog(data)"
                        />
                        <Button
                          :icon="data.is_active ? 'pi pi-eye-slash' : 'pi pi-check'"
                          :label="data.is_active ? '停用' : '啟用'"
                          :aria-label="data.is_active ? '停用分類' : '啟用分類'"
                          :title="data.is_active ? '停用分類' : '啟用分類'"
                          size="small"
                          :severity="data.is_active ? 'warn' : 'success'"
                          outlined
                          @click="confirmToggleCategory(data)"
                        />
                        <Button
                          class="admin-danger-outline-button"
                          icon="pi pi-trash"
                          label="刪除"
                          aria-label="刪除分類"
                          title="刪除分類"
                          size="small"
                          severity="danger"
                          outlined
                          @click="confirmDeleteCategory(data)"
                        />
                      </div>
                    </template>
                  </Column>
                </DataTable>
                <div
                  v-if="!courseLoadError"
                  class="admin-mobile-list admin-mobile-list--categories"
                >
                  <article
                    v-for="category in courseCategories"
                    :key="category.id"
                    class="admin-mobile-card admin-category-card category-responsive-card"
                  >
                    <section class="category-card-topline">
                      <span class="category-card-order">{{
                        getCategoryPosition(category) + 1
                      }}</span>
                      <Button
                        icon="pi pi-arrow-up"
                        severity="secondary"
                        text
                        rounded
                        size="small"
                        aria-label="上移"
                        title="上移"
                        :disabled="!canMoveCategory(category, -1) || categoryOrderLoading"
                        @click="moveCategory(category, -1)"
                      />
                      <Button
                        icon="pi pi-arrow-down"
                        severity="secondary"
                        text
                        rounded
                        size="small"
                        aria-label="下移"
                        title="下移"
                        :disabled="!canMoveCategory(category, 1) || categoryOrderLoading"
                        @click="moveCategory(category, 1)"
                      />
                      <div class="category-card-top-tags--mobile">
                        <Tag :severity="category.is_active ? 'success' : 'secondary'">
                          {{ category.is_active ? '啟用中' : '已停用' }}
                        </Tag>
                      </div>
                    </section>
                    <section class="category-card-main category-card-main--tablet">
                      <div class="category-card-title-group">
                        <strong class="category-card-title">{{ category.name }}</strong>
                        <Tag severity="secondary" :class="getCategoryBadgeClass(category)">
                          {{ category.label || category.name }}
                        </Tag>
                      </div>
                      <span class="category-card-key">
                        <span class="category-card-key-label">Key</span>
                        <span class="category-card-key-value">{{ category.key }}</span>
                      </span>
                    </section>
                    <section class="category-card-meta category-card-meta--tablet">
                      <Tag :severity="category.is_active ? 'success' : 'secondary'">
                        {{ category.is_active ? '啟用中' : '已停用' }}
                      </Tag>
                    </section>
                    <section class="category-card-main category-card-main--mobile">
                      <div class="category-card-title-group">
                        <strong class="category-card-title">{{ category.name }}</strong>
                        <Tag severity="secondary" :class="getCategoryBadgeClass(category)">
                          {{ category.label || category.name }}
                        </Tag>
                      </div>
                      <span class="category-card-key">
                        <span class="category-card-key-label">Key</span>
                        <span class="category-card-key-value">{{ category.key }}</span>
                      </span>
                    </section>
                    <section
                      class="admin-card-actions admin-mobile-card-actions category-card-actions"
                    >
                      <Button
                        icon="pi pi-pencil"
                        label="編輯"
                        aria-label="編輯分類"
                        title="編輯分類"
                        size="small"
                        outlined
                        @click="openEditCategoryDialog(category)"
                      />
                      <Button
                        :icon="category.is_active ? 'pi pi-eye-slash' : 'pi pi-check'"
                        :label="category.is_active ? '停用' : '啟用'"
                        :aria-label="category.is_active ? '停用分類' : '啟用分類'"
                        :title="category.is_active ? '停用分類' : '啟用分類'"
                        size="small"
                        :severity="category.is_active ? 'warn' : 'success'"
                        outlined
                        @click="confirmToggleCategory(category)"
                      />
                      <Button
                        class="admin-danger-outline-button"
                        icon="pi pi-trash"
                        label="刪除"
                        aria-label="刪除分類"
                        title="刪除分類"
                        size="small"
                        severity="danger"
                        outlined
                        @click="confirmDeleteCategory(category)"
                      />
                    </section>
                  </article>
                </div>
              </section>

              <div class="admin-toolbar admin-toolbar--course mb-4">
                <div class="admin-toolbar__filters">
                  <div class="admin-toolbar__search relative w-full md:w-auto">
                    <i class="pi pi-search search-icon"></i>
                    <InputText
                      id="admin-course-search"
                      name="admin-course-search"
                      v-model="searchQuery"
                      placeholder="搜尋課程"
                      class="w-full pl-6"
                    />
                  </div>
                  <Select
                    inputId="admin-course-category-filter"
                    name="admin-course-category-filter"
                    v-model="filterCategory"
                    :options="categoryOptions"
                    optionLabel="name"
                    optionValue="value"
                    placeholder="篩選分類"
                    showClear
                    class="admin-toolbar__select w-full md:w-14rem"
                  />
                </div>
                <div class="admin-toolbar__actions">
                  <Button
                    label="新增課程"
                    icon="pi pi-plus"
                    severity="success"
                    @click="openCreateDialog"
                    class="admin-toolbar__button w-full md:w-auto"
                  />
                </div>
              </div>

              <ProgressSpinner
                v-if="coursesLoading"
                class="w-full flex justify-content-center mt-4"
                strokeWidth="4"
              />
              <DataTable
                v-else-if="!courseLoadError"
                :value="filteredCourses"
                class="admin-data-table admin-desktop-data-table course-management-table"
                paginator
                :first="courseFirst"
                :rows="courseRows"
                :rowsPerPageOptions="ADMIN_PAGE_SIZE_OPTIONS"
                paginatorTemplate="FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink RowsPerPageDropdown CurrentPageReport"
                currentPageReportTemplate="第 {currentPage} / {totalPages} 頁，共 {totalRecords} 筆"
                tableStyle="min-width: 50rem"
                scrollable
                scrollHeight="65vh"
                responsiveLayout="stack"
                breakpoint="1023px"
                @page="handleCoursePage"
              >
                <Column header="順序" style="width: 18%">
                  <template #body="{ data }">
                    <div class="mobile-card-order flex align-items-center gap-2">
                      <span class="text-sm text-500 w-2rem">
                        {{ getCoursePosition(data) + 1 }}
                      </span>
                      <Button
                        icon="pi pi-arrow-up"
                        severity="secondary"
                        text
                        rounded
                        size="small"
                        aria-label="上移"
                        :disabled="!canMoveCourse(data, -1) || courseOrderLoading"
                        @click="moveCourse(data, -1)"
                      />
                      <Button
                        icon="pi pi-arrow-down"
                        severity="secondary"
                        text
                        rounded
                        size="small"
                        aria-label="下移"
                        :disabled="!canMoveCourse(data, 1) || courseOrderLoading"
                        @click="moveCourse(data, 1)"
                      />
                    </div>
                  </template>
                </Column>
                <Column field="name" header="課程名稱" style="width: 32%">
                  <template #body="{ data }">
                    <span class="mobile-primary-text">{{ data.name }}</span>
                  </template>
                </Column>
                <Column field="category" header="分類" style="width: 22%">
                  <template #body="{ data }">
                    <Tag
                      severity="secondary"
                      :class="['text-sm', getCategoryBadgeClass(data.category)]"
                    >
                      {{ getCategoryName(data.category) }}
                    </Tag>
                  </template>
                </Column>
                <Column header="操作" style="width: 18%">
                  <template #body="{ data }">
                    <div class="admin-card-actions">
                      <Button
                        icon="pi pi-pencil"
                        severity="warning"
                        size="small"
                        @click="openEditDialog(data)"
                        label="編輯"
                        aria-label="編輯課程"
                        title="編輯課程"
                      />
                      <Button
                        class="admin-danger-solid-button"
                        icon="pi pi-trash"
                        severity="danger"
                        size="small"
                        @click="confirmDeleteCourse(data)"
                        label="刪除"
                        aria-label="刪除課程"
                        title="刪除課程"
                      />
                    </div>
                  </template>
                </Column>
              </DataTable>
              <div
                v-if="!coursesLoading && !courseLoadError"
                class="admin-mobile-list admin-mobile-list--courses"
              >
                <article
                  v-for="course in paginatedCourses"
                  :key="course.id"
                  class="admin-mobile-card admin-course-card admin-tablet-card"
                >
                  <header class="admin-tablet-card-header">
                    <div class="admin-tablet-title-group">
                      <strong class="course-card-title admin-tablet-card-title">{{
                        course.name
                      }}</strong>
                      <div class="admin-tablet-tag-group">
                        <Tag
                          severity="secondary"
                          :class="['course-card-category', getCategoryBadgeClass(course.category)]"
                        >
                          {{ getCategoryName(course.category) }}
                        </Tag>
                      </div>
                    </div>
                  </header>
                  <section class="admin-tablet-metadata">
                    <div class="admin-tablet-metadata-item course-card-order-item">
                      <span class="admin-tablet-metadata-label">順序</span>
                      <span class="course-card-order admin-tablet-metadata-value">{{
                        getCoursePosition(course) + 1
                      }}</span>
                      <div class="course-card-order-actions">
                        <Button
                          icon="pi pi-arrow-up"
                          severity="secondary"
                          text
                          rounded
                          size="small"
                          aria-label="上移"
                          title="上移"
                          :disabled="!canMoveCourse(course, -1) || courseOrderLoading"
                          @click="moveCourse(course, -1)"
                        />
                        <Button
                          icon="pi pi-arrow-down"
                          severity="secondary"
                          text
                          rounded
                          size="small"
                          aria-label="下移"
                          title="下移"
                          :disabled="!canMoveCourse(course, 1) || courseOrderLoading"
                          @click="moveCourse(course, 1)"
                        />
                      </div>
                    </div>
                  </section>
                  <section
                    class="admin-card-actions admin-mobile-card-actions course-card-actions admin-tablet-actions"
                  >
                    <Button
                      icon="pi pi-pencil"
                      severity="warning"
                      size="small"
                      @click="openEditDialog(course)"
                      label="編輯"
                      aria-label="編輯課程"
                      title="編輯課程"
                    />
                    <Button
                      class="admin-danger-solid-button"
                      icon="pi pi-trash"
                      severity="danger"
                      size="small"
                      @click="confirmDeleteCourse(course)"
                      label="刪除"
                      aria-label="刪除課程"
                      title="刪除課程"
                    />
                  </section>
                </article>
                <Paginator
                  :first="courseFirst"
                  :rows="courseRows"
                  :totalRecords="filteredCourses.length"
                  :rowsPerPageOptions="ADMIN_PAGE_SIZE_OPTIONS"
                  :pageLinkSize="1"
                  template="FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink RowsPerPageDropdown CurrentPageReport"
                  currentPageReportTemplate="第 {currentPage} / {totalPages} 頁，共 {totalRecords} 筆"
                  aria-label="課程管理分頁"
                  class="admin-mobile-paginator"
                  @page="handleCoursePage"
                />
              </div>
            </div>
          </TabPanel>

          <TabPanel value="1">
            <div class="p-2 md:p-4">
              <section
                class="user-insights admin-insights-card"
                aria-labelledby="user-insights-title"
              >
                <div class="user-insights__heading">
                  <div>
                    <h3 id="user-insights-title">使用者統計圖表</h3>
                    <p>
                      {{
                        userInsightsView === 'level'
                          ? userInsightsViewLabel
                          : loginDistributionDescription
                      }}
                    </p>
                  </div>
                  <div class="user-insights__actions">
                    <div
                      class="user-insights__switch user-insights__switch--three"
                      role="group"
                      aria-label="切換使用者統計圖表"
                    >
                      <button
                        type="button"
                        class="user-insights__switch-option user-insights__switch-option--primary"
                        :class="{ 'is-active': userInsightsView === 'login-hour' }"
                        :aria-pressed="userInsightsView === 'login-hour'"
                        @click="userInsightsView = 'login-hour'"
                      >
                        最近在線時間分布
                      </button>
                      <button
                        type="button"
                        class="user-insights__switch-option user-insights__switch-option--secondary"
                        :class="{ 'is-active': userInsightsView === 'login-date' }"
                        :aria-pressed="userInsightsView === 'login-date'"
                        @click="userInsightsView = 'login-date'"
                      >
                        最近在線日期分布
                      </button>
                      <button
                        type="button"
                        class="user-insights__switch-option user-insights__switch-option--wide"
                        :class="{ 'is-active': userInsightsView === 'level' }"
                        :aria-pressed="userInsightsView === 'level'"
                        @click="userInsightsView = 'level'"
                      >
                        投稿等級分布
                      </button>
                    </div>
                    <button
                      type="button"
                      class="user-insights__toggle section-collapse-toggle"
                      :aria-expanded="isUserChartsExpanded"
                      aria-controls="user-insights-content"
                      :aria-label="
                        isUserChartsExpanded ? '收合使用者統計圖表' : '展開使用者統計圖表'
                      "
                      @click="isUserChartsExpanded = !isUserChartsExpanded"
                    >
                      <span>{{ isUserChartsExpanded ? '收合' : '展開' }}</span>
                      <i
                        class="pi"
                        :class="isUserChartsExpanded ? 'pi-chevron-up' : 'pi-chevron-down'"
                        aria-hidden="true"
                      ></i>
                    </button>
                  </div>
                </div>

                <div v-show="isUserChartsExpanded" id="user-insights-content">
                  <Message
                    v-if="
                      userStatsLoadError || (userInsightsView !== 'level' && onlineStatisticsError)
                    "
                    severity="error"
                    :closable="false"
                    class="user-insights__load-error"
                  >
                    <div class="flex flex-wrap align-items-center justify-content-between gap-3">
                      <span>{{ userStatsLoadError || onlineStatisticsError }}</span>
                      <Button
                        label="重新載入"
                        icon="pi pi-refresh"
                        severity="danger"
                        outlined
                        size="small"
                        :loading="usersLoading || onlineStatisticsLoading"
                        @click="reloadUserStatistics"
                      />
                    </div>
                  </Message>
                  <div v-else-if="userInsightsView !== 'level'" class="user-insights__panel">
                    <div class="chart-summary-control-row">
                      <div
                        v-if="onlineStatisticsSummary"
                        class="chart-summary-group"
                        aria-label="同時在線人數摘要"
                      >
                        <span class="chart-summary-item">
                          <span>目前在線</span>
                          <strong>{{ onlineStatisticsSummary.current }} 人</strong>
                        </span>
                        <span class="chart-summary-item">
                          <span>區間峰值</span>
                          <strong>{{ onlineStatisticsSummary.peak }} 人</strong>
                        </span>
                        <span class="chart-summary-item">
                          <span>區間平均</span>
                          <strong>{{ onlineStatisticsSummary.average }} 人</strong>
                        </span>
                      </div>
                      <div class="chart-control-stack">
                        <div
                          class="user-insights__range"
                          role="group"
                          aria-label="最近在線統計範圍"
                        >
                          <button
                            v-for="option in loginRangeOptions"
                            :key="option"
                            type="button"
                            :class="{ 'is-active': activeLoginRange === option }"
                            :aria-pressed="activeLoginRange === option"
                            @click="setActiveLoginRange(option)"
                          >
                            {{ option }} {{ loginRangeUnit }}
                          </button>
                        </div>
                        <span class="chart-timezone-label">
                          統計時區：{{ PRODUCT_TIME_ZONE_LABEL }}
                        </span>
                      </div>
                    </div>
                    <div
                      v-if="onlineStatistics?.history_started_at"
                      class="user-login-column-chart"
                      role="img"
                      :aria-label="loginChartData.ariaLabel"
                    >
                      <div class="user-login-column-chart__y-axis" aria-hidden="true">
                        <span v-for="tick in loginChartData.yTicks" :key="`y-${tick}`">
                          {{ tick }}
                        </span>
                      </div>
                      <div class="user-login-column-chart__plot">
                        <div class="user-login-column-chart__grid" aria-hidden="true">
                          <span
                            v-for="tick in loginChartData.yTicks"
                            :key="`grid-${tick}`"
                            :style="{ bottom: `${(tick / loginChartData.yMax) * 100}%` }"
                          ></span>
                        </div>
                        <div
                          class="user-login-column-chart__bars"
                          :style="{ '--login-chart-columns': loginChartData.buckets.length }"
                        >
                          <div
                            v-for="bucket in loginChartData.buckets"
                            :key="bucket.key"
                            class="user-login-column-chart__item"
                            tabindex="0"
                            :aria-label="
                              bucket.has_data
                                ? `${bucket.fullLabel}，${bucket.count} 人在線`
                                : `${bucket.fullLabel}，尚無歷史資料`
                            "
                          >
                            <span
                              class="user-login-column-chart__bar"
                              :class="{ 'has-value': bucket.count > 0 }"
                              :style="{
                                height: `${(bucket.count / loginChartData.yMax) * 100}%`,
                              }"
                            ></span>
                            <span class="user-login-column-chart__tooltip" role="tooltip">
                              {{
                                bucket.has_data
                                  ? `${bucket.fullLabel}：${bucket.count} 人在線`
                                  : `${bucket.fullLabel}：尚無歷史資料`
                              }}
                            </span>
                          </div>
                        </div>
                        <div
                          ref="userStatisticsChartElement"
                          class="user-login-column-chart__x-axis"
                          :style="{ '--login-chart-columns': loginChartData.buckets.length }"
                          aria-hidden="true"
                        >
                          <span
                            v-for="bucket in loginChartData.buckets"
                            :key="`label-${bucket.key}`"
                            :class="{ 'is-multiline': bucket.isMultiline }"
                          >
                            <template v-if="bucket.showLabel">
                              <span v-for="line in bucket.labelLines" :key="line">{{ line }}</span>
                            </template>
                          </span>
                        </div>
                      </div>
                    </div>
                    <div v-else class="user-insights__empty" role="status">
                      在線歷史資料將從此功能啟用後開始累積。
                    </div>
                  </div>

                  <div v-else class="user-insights__panel">
                    <p class="user-insights__description">
                      依完整使用者集合統計，不受目前搜尋、分頁或等級篩選影響。
                    </p>
                    <div class="user-level-chart" aria-label="投稿等級分布">
                      <div
                        v-for="stat in contributorLevelDistribution"
                        :key="`chart-level-${stat.level}`"
                        class="user-level-chart__row"
                        :style="{
                          '--chart-level-color': stat.palette.bg,
                          '--chart-level-border': stat.palette.border,
                        }"
                      >
                        <ContributorLevelBadge
                          :level="stat.level"
                          :title="stat.name"
                          size="compact"
                        />
                        <span class="user-level-chart__name">{{ stat.name }}</span>
                        <div class="user-level-chart__track">
                          <span
                            class="user-level-chart__fill"
                            :style="{ width: `${stat.percentage}%` }"
                          ></span>
                        </div>
                        <strong>{{ stat.count }} 人</strong>
                        <span>{{ stat.percentage.toFixed(1) }}%</span>
                      </div>
                    </div>
                  </div>
                </div>
              </section>

              <section
                class="contributor-level-insights admin-insights-card"
                aria-labelledby="contributor-level-insights-title"
              >
                <div class="contributor-level-insights__heading">
                  <div>
                    <h3 id="contributor-level-insights-title">投稿等級選單與設定</h3>
                    <p>選擇等級以篩選使用者，或調整等級設定</p>
                  </div>
                  <div class="contributor-level-insights__actions">
                    <Button
                      v-if="selectedContributorLevels.length"
                      label="清除選取"
                      icon="pi pi-filter-slash"
                      severity="secondary"
                      size="small"
                      outlined
                      @click="clearContributorLevelFilter"
                    />
                    <Button
                      label="等級設定"
                      icon="pi pi-cog"
                      severity="secondary"
                      size="small"
                      outlined
                      class="contributor-level-settings-button"
                      @click="openContributorLevelSettingsDialog"
                    />
                    <button
                      type="button"
                      class="contributor-level-toggle section-collapse-toggle"
                      :aria-expanded="isLevelStatsExpanded"
                      aria-controls="contributor-level-stats-grid"
                      :aria-label="
                        isLevelStatsExpanded ? '收合投稿等級選單與設定' : '展開投稿等級選單與設定'
                      "
                      @click="isLevelStatsExpanded = !isLevelStatsExpanded"
                    >
                      <span>{{ isLevelStatsExpanded ? '收合' : '展開' }}</span>
                      <i
                        class="pi"
                        :class="isLevelStatsExpanded ? 'pi-chevron-up' : 'pi-chevron-down'"
                        aria-hidden="true"
                      ></i>
                    </button>
                  </div>
                </div>
                <div
                  v-show="isLevelStatsExpanded"
                  id="contributor-level-stats-grid"
                  class="contributor-level-insights__grid"
                >
                  <button
                    v-for="level in SUBMISSION_LEVELS"
                    :key="level.level"
                    type="button"
                    class="contributor-level-stat"
                    :class="{
                      'is-active': isContributorLevelSelected(level.level),
                    }"
                    :aria-pressed="isContributorLevelSelected(level.level)"
                    :title="level.name"
                    @click="toggleContributorLevel(level.level)"
                  >
                    <ContributorLevelBadge
                      :level="level.level"
                      :title="level.name"
                      size="compact"
                    />
                    <span class="contributor-level-stat__name">{{ level.name }}</span>
                  </button>
                </div>
              </section>

              <div class="admin-toolbar admin-toolbar--users mb-4">
                <div class="admin-toolbar__filters">
                  <div class="admin-toolbar__search relative w-full md:w-auto">
                    <i class="pi pi-search search-icon"></i>
                    <InputText
                      id="admin-user-search"
                      name="admin-user-search"
                      v-model="userSearchQuery"
                      placeholder="搜尋使用者"
                      class="w-full pl-6"
                    />
                  </div>
                  <Select
                    inputId="admin-user-type-filter"
                    name="admin-user-type-filter"
                    v-model="filterUserType"
                    :options="userTypeFilterOptions"
                    optionLabel="name"
                    optionValue="value"
                    placeholder="篩選類型"
                    showClear
                    class="admin-toolbar__select w-full md:w-14rem"
                  />
                </div>
                <div class="admin-toolbar__actions">
                  <Button
                    label="新增使用者"
                    icon="pi pi-plus"
                    severity="success"
                    @click="openCreateUserDialog"
                    class="admin-toolbar__button w-full md:w-auto"
                  />
                </div>
              </div>

              <ProgressSpinner
                v-if="usersLoading"
                class="w-full flex justify-content-center mt-4"
                strokeWidth="4"
              />
              <DataTable
                v-else
                :value="sortedUsers"
                class="admin-data-table admin-desktop-data-table user-management-table"
                paginator
                :first="userFirst"
                :rows="userRows"
                :rowsPerPageOptions="ADMIN_PAGE_SIZE_OPTIONS"
                paginatorTemplate="FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink RowsPerPageDropdown CurrentPageReport"
                currentPageReportTemplate="第 {currentPage} / {totalPages} 頁，共 {totalRecords} 筆"
                tableStyle="min-width: 62rem"
                scrollable
                scrollHeight="65vh"
                responsiveLayout="stack"
                breakpoint="1023px"
                :multiSortMeta="userSortMeta"
                sortMode="multiple"
                removableSort
                @page="handleUserPage"
                @sort="handleUserSort"
              >
                <Column
                  field="contributor_level"
                  header="投稿等級"
                  sortable
                  style="width: 7.5rem; min-width: 7.5rem; max-width: 7.5rem"
                >
                  <template #body="{ data }">
                    <span class="user-table-contributor-level">
                      Lv. {{ data.contributorLevel.level }}
                    </span>
                  </template>
                </Column>
                <Column header="使用者名稱" sortable style="width: 15%">
                  <template #body="{ data }">
                    <span class="mobile-primary-text admin-desktop-cell">{{ data.name }}</span>
                    <div class="admin-mobile-card admin-user-mobile-card">
                      <div class="admin-card-primary">
                        <strong class="admin-card-title">{{ data.name }}</strong>
                        <span class="admin-card-email">{{ data.email }}</span>
                      </div>
                      <div class="admin-card-meta">
                        <ContributorLevelBadge
                          :level="data.contributorLevel.level"
                          :title="data.contributorLevel.name"
                          size="compact"
                          show-title
                        />
                        <Tag :severity="data.is_admin ? 'success' : 'secondary'" class="text-sm">
                          {{ data.is_admin ? '是' : '否' }}
                        </Tag>
                        <Tag :severity="data.is_local ? 'info' : 'warning'" class="text-sm">
                          {{ data.is_local ? '本地帳號' : '外部帳號' }}
                        </Tag>
                        <span class="admin-card-meta-text">
                          {{ data.last_login ? formatDateTime(data.last_login) : '從未登入' }}
                        </span>
                      </div>
                    </div>
                  </template>
                </Column>
                <Column header="電子郵件" sortable style="width: 20%">
                  <template #body="{ data }">
                    <span class="mobile-long-text admin-desktop-cell">{{ data.email }}</span>
                  </template>
                </Column>
                <Column field="is_admin" header="管理員權限" sortable style="width: 15%">
                  <template #body="{ data }">
                    <Tag :severity="data.is_admin ? 'success' : 'secondary'" class="text-sm">
                      {{ data.is_admin ? '是' : '否' }}
                    </Tag>
                  </template>
                </Column>
                <Column field="is_local" header="帳號類型" sortable style="width: 15%">
                  <template #body="{ data }">
                    <Tag :severity="data.is_local ? 'info' : 'warning'" class="text-sm">
                      {{ data.is_local ? '本地帳號' : '外部帳號' }}
                    </Tag>
                  </template>
                </Column>
                <Column field="last_login" header="最近登入" sortable style="width: 15%">
                  <template #body="{ data }">
                    <span v-if="data.last_login" class="text-sm">
                      {{ formatDateTime(data.last_login) }}
                    </span>
                    <span v-else class="text-sm text-500"> 從未登入 </span>
                  </template>
                </Column>
                <Column field="is_online" header="上線狀態" sortable style="width: 16%">
                  <template #body="{ data }">
                    <span class="user-online-badge" :class="getOnlineStatusDotClass(data)">
                      <i class="pi pi-circle-fill"></i>
                      <span>{{ getOnlineStatusLabel(data) }}</span>
                    </span>
                  </template>
                </Column>
                <Column header="操作" style="width: 28%; min-width: 21rem">
                  <template #body="{ data }">
                    <div class="user-management-table-actions">
                      <Button
                        icon="pi pi-eye"
                        severity="secondary"
                        size="small"
                        @click="openUserDataStats(data)"
                        label="查看"
                        aria-label="查看使用者資料統計"
                        title="查看使用者資料統計"
                      />
                      <Button
                        icon="pi pi-pencil"
                        severity="warning"
                        size="small"
                        @click="openEditUserDialog(data)"
                        label="編輯"
                        aria-label="編輯使用者"
                        title="編輯使用者"
                      />
                      <Button
                        icon="pi pi-key"
                        severity="info"
                        size="small"
                        @click="openResetPasswordDialog(data)"
                        label="重設密碼"
                        aria-label="重設使用者密碼"
                        :title="data.is_local ? '重設密碼' : NON_LOCAL_PASSWORD_RESET_HINT"
                        :disabled="!data.is_local"
                      />
                      <Button
                        class="admin-danger-solid-button"
                        icon="pi pi-trash"
                        severity="danger"
                        size="small"
                        @click="confirmDeleteUser(data)"
                        label="刪除"
                        aria-label="刪除使用者"
                        title="刪除使用者"
                        :disabled="data.id === currentUserId"
                      />
                    </div>
                  </template>
                </Column>
              </DataTable>
              <div v-if="!usersLoading" class="admin-mobile-list admin-mobile-list--users">
                <article
                  v-for="user in paginatedUsers"
                  :key="user.id"
                  class="admin-mobile-card admin-user-card admin-tablet-card"
                >
                  <header class="admin-tablet-card-header">
                    <div class="admin-tablet-title-group user-card-title-group">
                      <span class="mobile-user-level-tag">Lv{{ user.contributorLevel.level }}</span>
                      <strong class="admin-card-title admin-tablet-card-title">{{
                        user.name
                      }}</strong>
                      <div class="admin-tablet-tag-group user-role-tag-group">
                        <Tag :severity="user.is_admin ? 'success' : 'secondary'" class="text-sm">
                          {{ user.is_admin ? '管理員' : '一般使用者' }}
                        </Tag>
                      </div>
                    </div>
                    <span class="user-online-badge" :class="getOnlineStatusDotClass(user)">
                      <i class="pi pi-circle-fill"></i>
                      <span>{{ getOnlineStatusLabel(user) }}</span>
                    </span>
                  </header>
                  <section class="admin-tablet-metadata">
                    <div class="admin-tablet-metadata-item admin-tablet-metadata-item--wide">
                      <span class="admin-tablet-metadata-label">Email</span>
                      <span class="admin-card-email admin-tablet-metadata-value">{{
                        user.email
                      }}</span>
                    </div>
                    <div class="admin-tablet-metadata-item">
                      <span class="admin-tablet-metadata-label">帳號類型</span>
                      <span class="admin-tablet-metadata-value">{{
                        user.is_local ? '本地帳號' : '外部帳號'
                      }}</span>
                    </div>
                    <div class="admin-tablet-metadata-item">
                      <span class="admin-tablet-metadata-label">最後登入</span>
                      <span class="admin-tablet-metadata-value">
                        {{ user.last_login ? formatDateTime(user.last_login) : '從未登入' }}
                      </span>
                    </div>
                  </section>
                  <section
                    class="admin-card-actions admin-mobile-card-actions user-management-card-actions admin-tablet-actions"
                  >
                    <Button
                      icon="pi pi-eye"
                      severity="secondary"
                      size="small"
                      @click="openUserDataStats(user)"
                      label="查看"
                      aria-label="查看使用者資料統計"
                      title="查看使用者資料統計"
                    />
                    <Button
                      icon="pi pi-pencil"
                      severity="warning"
                      size="small"
                      @click="openEditUserDialog(user)"
                      label="編輯"
                      aria-label="編輯使用者"
                      title="編輯使用者"
                    />
                    <Button
                      icon="pi pi-key"
                      severity="info"
                      size="small"
                      @click="openResetPasswordDialog(user)"
                      label="重設密碼"
                      aria-label="重設使用者密碼"
                      :title="user.is_local ? '重設密碼' : NON_LOCAL_PASSWORD_RESET_HINT"
                      :disabled="!user.is_local"
                    />
                    <Button
                      class="admin-danger-solid-button"
                      icon="pi pi-trash"
                      severity="danger"
                      size="small"
                      @click="confirmDeleteUser(user)"
                      label="刪除"
                      aria-label="刪除使用者"
                      title="刪除使用者"
                      :disabled="user.id === currentUserId"
                    />
                  </section>
                </article>
                <Paginator
                  :first="userFirst"
                  :rows="userRows"
                  :totalRecords="sortedUsers.length"
                  :rowsPerPageOptions="ADMIN_PAGE_SIZE_OPTIONS"
                  :pageLinkSize="1"
                  template="FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink RowsPerPageDropdown CurrentPageReport"
                  currentPageReportTemplate="第 {currentPage} / {totalPages} 頁，共 {totalRecords} 筆"
                  aria-label="使用者管理分頁"
                  class="admin-mobile-paginator"
                  @page="handleUserPage"
                />
              </div>
            </div>
          </TabPanel>

          <TabPanel value="2">
            <div class="p-2 md:p-4">
              <div class="admin-toolbar admin-toolbar--announcement mb-4">
                <div class="admin-toolbar__filters">
                  <div class="admin-toolbar__search relative w-full md:w-auto">
                    <i class="pi pi-search search-icon"></i>
                    <InputText
                      id="admin-notification-search"
                      name="admin-notification-search"
                      v-model="notificationSearchQuery"
                      placeholder="搜尋公告"
                      class="w-full pl-6"
                    />
                  </div>
                  <Select
                    inputId="admin-notification-severity-filter"
                    name="admin-notification-severity-filter"
                    v-model="notificationSeverityFilter"
                    :options="notificationSeverityFilterOptions"
                    optionLabel="label"
                    optionValue="value"
                    placeholder="篩選重要程度"
                    showClear
                    class="admin-toolbar__select w-full md:w-14rem"
                  />
                </div>
                <div class="admin-toolbar__actions">
                  <Button
                    label="新增公告"
                    icon="pi pi-plus"
                    severity="success"
                    @click="openNotificationCreateDialog"
                    class="admin-toolbar__button w-full md:w-auto"
                  />
                </div>
              </div>

              <ProgressSpinner
                v-if="notificationsLoading"
                class="w-full flex justify-content-center mt-4"
                strokeWidth="4"
              />
              <DataTable
                v-else
                :value="sortedNotifications"
                class="admin-data-table admin-desktop-data-table notification-management-table"
                paginator
                :first="notificationFirst"
                :rows="notificationRows"
                :rowsPerPageOptions="ADMIN_PAGE_SIZE_OPTIONS"
                paginatorTemplate="FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink RowsPerPageDropdown CurrentPageReport"
                currentPageReportTemplate="第 {currentPage} / {totalPages} 頁，共 {totalRecords} 筆"
                tableStyle="min-width: 50rem"
                scrollable
                scrollHeight="65vh"
                responsiveLayout="stack"
                breakpoint="1023px"
                sortMode="multiple"
                :multiSortMeta="notificationSortMeta"
                removableSort
                @page="handleNotificationPage"
                @sort="handleNotificationSort"
              >
                <Column field="title" header="標題" sortable style="width: 26%">
                  <template #body="{ data }">
                    <span class="mobile-primary-text admin-desktop-cell">{{ data.title }}</span>
                    <div class="admin-mobile-card admin-announcement-mobile-card">
                      <div class="admin-card-primary">
                        <strong class="admin-card-title">{{ data.title }}</strong>
                      </div>
                      <div class="admin-card-meta">
                        <Tag :severity="getNotificationSeverity(data.severity)">
                          {{ getNotificationSeverityLabel(data.severity) }}
                        </Tag>
                        <Tag :severity="data.is_active ? 'success' : 'secondary'">
                          {{ data.is_active ? '啟用中' : '已停用' }}
                        </Tag>
                        <Tag :severity="isNotificationEffective(data) ? 'success' : 'secondary'">
                          {{ isNotificationEffective(data) ? '生效中' : '未生效' }}
                        </Tag>
                        <div class="notification-mobile-update">
                          <span class="notification-mobile-update__label">最近更新</span>
                          <span
                            class="notification-mobile-update__actor"
                            :title="getNotificationUpdaterLabel(data)"
                            >{{ getNotificationUpdaterLabel(data) }}・</span
                          >
                          <time
                            class="notification-mobile-update__time"
                            :datetime="data.updated_at || data.created_at"
                          >
                            {{ formatAdminActorTime(data.updated_at || data.created_at) }}
                          </time>
                        </div>
                      </div>
                    </div>
                  </template>
                </Column>
                <Column field="severity" header="重要程度" sortable style="width: 12%">
                  <template #body="{ data }">
                    <Tag :severity="getNotificationSeverity(data.severity)">
                      {{ getNotificationSeverityLabel(data.severity) }}
                    </Tag>
                  </template>
                </Column>
                <Column
                  field="is_active"
                  sortField="is_active"
                  header="啟用中"
                  sortable
                  style="width: 12%"
                >
                  <template #body="{ data }">
                    <Tag :severity="data.is_active ? 'success' : 'secondary'">
                      {{ data.is_active ? '啟用中' : '已停用' }}
                    </Tag>
                  </template>
                </Column>
                <Column header="生效中" sortField="effectiveOrder" sortable style="width: 12%">
                  <template #body="{ data }">
                    <Tag :severity="isNotificationEffective(data) ? 'success' : 'secondary'">
                      {{ isNotificationEffective(data) ? '生效中' : '未生效' }}
                    </Tag>
                  </template>
                </Column>
                <Column
                  field="updated_at"
                  sortField="updated_at"
                  header="最近更新"
                  sortable
                  style="width: 11rem; min-width: 11rem"
                >
                  <template #body="{ data }">
                    <div class="admin-actor-time admin-actor-time--notification">
                      <span
                        class="admin-actor-time__name"
                        :title="getNotificationUpdaterLabel(data)"
                      >
                        {{ getNotificationUpdaterLabel(data) }}
                      </span>
                      <time
                        class="admin-actor-time__time"
                        :datetime="data.updated_at || data.created_at"
                      >
                        {{ formatAdminActorTime(data.updated_at || data.created_at) }}
                      </time>
                    </div>
                  </template>
                </Column>
                <Column header="操作" style="width: 20%">
                  <template #body="{ data }">
                    <div class="admin-card-actions">
                      <Button
                        icon="pi pi-pencil"
                        severity="warning"
                        size="small"
                        @click="openNotificationEditDialog(data)"
                        label="編輯"
                        aria-label="編輯公告"
                        title="編輯公告"
                      />
                      <Button
                        class="admin-danger-solid-button"
                        icon="pi pi-trash"
                        severity="danger"
                        size="small"
                        @click="confirmDeleteNotification(data)"
                        label="刪除"
                        aria-label="刪除公告"
                        title="刪除公告"
                      />
                    </div>
                  </template>
                </Column>
              </DataTable>
              <div
                v-if="!notificationsLoading"
                class="admin-mobile-list admin-mobile-list--notifications"
              >
                <article
                  v-for="notification in paginatedNotifications"
                  :key="notification.id"
                  class="admin-mobile-card admin-announcement-card admin-tablet-card"
                >
                  <header class="admin-tablet-card-header">
                    <div class="admin-tablet-title-group announcement-card-title-group">
                      <strong class="admin-card-title admin-tablet-card-title">{{
                        notification.title
                      }}</strong>
                      <div class="admin-tablet-tag-group announcement-type-tag-group">
                        <Tag :severity="getNotificationSeverity(notification.severity)">
                          {{ getNotificationSeverityLabel(notification.severity) }}
                        </Tag>
                      </div>
                    </div>
                    <div class="admin-tablet-status-group">
                      <Tag :severity="notification.is_active ? 'success' : 'secondary'">
                        {{ notification.is_active ? '啟用中' : '已停用' }}
                      </Tag>
                      <Tag
                        :severity="isNotificationEffective(notification) ? 'success' : 'secondary'"
                      >
                        {{ isNotificationEffective(notification) ? '生效中' : '未生效' }}
                      </Tag>
                    </div>
                  </header>
                  <section class="admin-tablet-metadata">
                    <div class="admin-tablet-metadata-item admin-tablet-metadata-item--wide">
                      <span class="admin-tablet-metadata-label">最近更新</span>
                      <div class="notification-mobile-update__value">
                        <span
                          class="notification-mobile-update__actor"
                          :title="getNotificationUpdaterLabel(notification)"
                          >{{ getNotificationUpdaterLabel(notification) }}・</span
                        >
                        <time
                          class="notification-mobile-update__time"
                          :datetime="notification.updated_at || notification.created_at"
                        >
                          {{
                            formatAdminActorTime(notification.updated_at || notification.created_at)
                          }}
                        </time>
                      </div>
                    </div>
                  </section>
                  <section
                    class="admin-card-actions admin-mobile-card-actions announcement-mobile-actions admin-tablet-actions"
                  >
                    <Button
                      icon="pi pi-pencil"
                      severity="warning"
                      size="small"
                      @click="openNotificationEditDialog(notification)"
                      label="編輯"
                      aria-label="編輯公告"
                      title="編輯公告"
                    />
                    <Button
                      class="admin-danger-solid-button"
                      icon="pi pi-trash"
                      severity="danger"
                      size="small"
                      @click="confirmDeleteNotification(notification)"
                      label="刪除"
                      aria-label="刪除公告"
                      title="刪除公告"
                    />
                  </section>
                </article>
                <Paginator
                  :first="notificationFirst"
                  :rows="notificationRows"
                  :totalRecords="sortedNotifications.length"
                  :rowsPerPageOptions="ADMIN_PAGE_SIZE_OPTIONS"
                  :pageLinkSize="1"
                  template="FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink RowsPerPageDropdown CurrentPageReport"
                  currentPageReportTemplate="第 {currentPage} / {totalPages} 頁，共 {totalRecords} 筆"
                  aria-label="公告管理分頁"
                  class="admin-mobile-paginator"
                  @page="handleNotificationPage"
                />
              </div>
            </div>
          </TabPanel>

          <TabPanel value="3">
            <div class="p-2 md:p-4 review-center">
              <section
                class="user-insights admin-insights-card review-submission-insights"
                aria-labelledby="review-submission-insights-title"
              >
                <div class="user-insights__heading">
                  <div>
                    <h3 id="review-submission-insights-title">投稿統計圖表</h3>
                    <p>{{ reviewSubmissionDescription }}</p>
                  </div>
                  <div class="user-insights__actions">
                    <div
                      class="user-insights__switch user-insights__switch--two"
                      role="group"
                      aria-label="切換投稿統計圖表"
                    >
                      <button
                        type="button"
                        class="user-insights__switch-option"
                        :class="{ 'is-active': reviewSubmissionView === 'time' }"
                        :aria-pressed="reviewSubmissionView === 'time'"
                        @click="reviewSubmissionView = 'time'"
                      >
                        最近投稿時間分布
                      </button>
                      <button
                        type="button"
                        class="user-insights__switch-option"
                        :class="{ 'is-active': reviewSubmissionView === 'date' }"
                        :aria-pressed="reviewSubmissionView === 'date'"
                        @click="reviewSubmissionView = 'date'"
                      >
                        最近投稿日期分布
                      </button>
                    </div>
                    <button
                      type="button"
                      class="user-insights__toggle section-collapse-toggle"
                      :aria-expanded="isReviewSubmissionChartExpanded"
                      aria-controls="review-submission-insights-content"
                      :aria-label="
                        isReviewSubmissionChartExpanded ? '收合投稿統計圖表' : '展開投稿統計圖表'
                      "
                      @click="isReviewSubmissionChartExpanded = !isReviewSubmissionChartExpanded"
                    >
                      <span>{{ isReviewSubmissionChartExpanded ? '收合' : '展開' }}</span>
                      <i
                        class="pi"
                        :class="
                          isReviewSubmissionChartExpanded ? 'pi-chevron-up' : 'pi-chevron-down'
                        "
                        aria-hidden="true"
                      ></i>
                    </button>
                  </div>
                </div>

                <div
                  v-show="isReviewSubmissionChartExpanded"
                  id="review-submission-insights-content"
                >
                  <Message
                    v-if="reviewSubmissionStatisticsError"
                    severity="error"
                    :closable="false"
                    class="user-insights__load-error"
                  >
                    <div class="flex flex-wrap align-items-center justify-content-between gap-3">
                      <span>{{ reviewSubmissionStatisticsError }}</span>
                      <Button
                        label="重新載入"
                        icon="pi pi-refresh"
                        severity="danger"
                        outlined
                        size="small"
                        :loading="reviewSubmissionStatisticsLoading"
                        @click="loadReviewSubmissionStatistics"
                      />
                    </div>
                  </Message>
                  <div
                    v-else-if="reviewSubmissionStatisticsLoading"
                    class="user-insights__empty"
                    role="status"
                  >
                    投稿統計載入中…
                  </div>
                  <div v-else-if="reviewSubmissionStatistics" class="user-insights__panel">
                    <div class="chart-summary-control-row">
                      <div class="chart-summary-group" aria-label="投稿統計摘要">
                        <span class="chart-summary-item">
                          <span>區間投稿</span>
                          <strong>{{ reviewSubmissionStatistics.summary.total }} 筆</strong>
                        </span>
                        <span class="chart-summary-item">
                          <span>區間峰值</span>
                          <strong>{{ reviewSubmissionStatistics.summary.peak }} 筆</strong>
                        </span>
                        <span class="chart-summary-item">
                          <span>區間平均</span>
                          <strong
                            >{{ reviewSubmissionStatistics.summary.average.toFixed(1) }} 筆</strong
                          >
                        </span>
                      </div>
                      <div class="chart-control-stack">
                        <div class="user-insights__range" role="group" aria-label="投稿統計範圍">
                          <button
                            v-for="option in reviewSubmissionRangeOptions"
                            :key="option"
                            type="button"
                            :class="{ 'is-active': activeReviewSubmissionRange === option }"
                            :aria-pressed="activeReviewSubmissionRange === option"
                            @click="setActiveReviewSubmissionRange(option)"
                          >
                            {{ option }} {{ reviewSubmissionRangeUnit }}
                          </button>
                        </div>
                        <span class="chart-timezone-label">
                          統計時區：{{ PRODUCT_TIME_ZONE_LABEL }}
                        </span>
                      </div>
                    </div>
                    <div
                      class="user-login-column-chart"
                      role="img"
                      :aria-label="reviewSubmissionChartData.ariaLabel"
                    >
                      <div class="user-login-column-chart__y-axis" aria-hidden="true">
                        <span
                          v-for="tick in reviewSubmissionChartData.yTicks"
                          :key="`review-y-${tick}`"
                        >
                          {{ tick }}
                        </span>
                      </div>
                      <div class="user-login-column-chart__plot">
                        <div class="user-login-column-chart__grid" aria-hidden="true">
                          <span
                            v-for="tick in reviewSubmissionChartData.yTicks"
                            :key="`review-grid-${tick}`"
                            :style="{
                              bottom: `${(tick / reviewSubmissionChartData.yMax) * 100}%`,
                            }"
                          ></span>
                        </div>
                        <div
                          class="user-login-column-chart__bars"
                          :style="{
                            '--login-chart-columns': reviewSubmissionChartData.buckets.length,
                          }"
                        >
                          <div
                            v-for="bucket in reviewSubmissionChartData.buckets"
                            :key="bucket.key"
                            class="user-login-column-chart__item"
                            tabindex="0"
                            :aria-label="`${bucket.fullLabel}，投稿 ${bucket.count} 筆`"
                          >
                            <span
                              class="user-login-column-chart__bar"
                              :class="{ 'has-value': bucket.count > 0 }"
                              :style="{
                                height: `${(bucket.count / reviewSubmissionChartData.yMax) * 100}%`,
                              }"
                            ></span>
                            <span class="user-login-column-chart__tooltip" role="tooltip">
                              {{ bucket.fullLabel }}：投稿 {{ bucket.count }} 筆
                            </span>
                          </div>
                        </div>
                        <div
                          ref="reviewSubmissionChartElement"
                          class="user-login-column-chart__x-axis"
                          :style="{
                            '--login-chart-columns': reviewSubmissionChartData.buckets.length,
                          }"
                          aria-hidden="true"
                        >
                          <span
                            v-for="bucket in reviewSubmissionChartData.buckets"
                            :key="`review-label-${bucket.key}`"
                            :class="{ 'is-multiline': bucket.isMultiline }"
                          >
                            <template v-if="bucket.showLabel">
                              <span v-for="line in bucket.labelLines" :key="line">{{ line }}</span>
                            </template>
                          </span>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </section>
              <div v-if="reviewLoadError" class="review-load-error">
                {{ reviewLoadError }}
              </div>
              <div class="review-search-toolbar admin-toolbar admin-toolbar--review">
                <div class="search-container admin-toolbar__filters">
                  <div class="admin-toolbar__search relative w-full md:w-24rem">
                    <i class="pi pi-search search-icon"></i>
                    <InputText
                      id="admin-review-search"
                      name="admin-review-search"
                      v-model="reviewSearchQuery"
                      placeholder="搜尋投稿編號、標題、課程、投稿者…"
                      class="w-full pl-6"
                    />
                  </div>
                  <Select
                    inputId="admin-review-status-filter"
                    name="admin-review-status-filter"
                    v-model="reviewStatusFilter"
                    :options="reviewStatusOptions"
                    optionLabel="name"
                    optionValue="value"
                    placeholder="篩選審核狀態"
                    showClear
                    class="review-status-filter admin-toolbar__select w-full md:w-14rem"
                  />
                </div>
                <div class="admin-toolbar__actions">
                  <Button
                    class="review-refresh-button admin-toolbar__button"
                    icon="pi pi-refresh"
                    label="重新整理"
                    outlined
                    @click="reloadReviewCenter"
                  />
                </div>
              </div>
              <div class="review-section">
                <div class="review-section-header">
                  <h3>新課程 / 新分類考古申請</h3>
                </div>
                <DataTable
                  :value="newCourseArchiveRequests"
                  :loading="reviewLoading"
                  class="admin-data-table review-request-table review-request-table--new"
                  paginator
                  :rows="newSubmissionRows"
                  :rowsPerPageOptions="[5, 10, 15, 25, 50]"
                  :first="newSubmissionFirst"
                  paginatorTemplate="FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink RowsPerPageDropdown CurrentPageReport"
                  currentPageReportTemplate="第 {currentPage} / {totalPages} 頁，共 {totalRecords} 筆"
                  @page="handleNewSubmissionPage"
                  tableStyle="min-width: 72rem"
                  responsiveLayout="stack"
                  breakpoint="1023px"
                >
                  <template #empty>
                    <div class="review-empty-state">沒有符合搜尋條件的投稿。</div>
                  </template>
                  <Column>
                    <template #header>
                      <button
                        type="button"
                        class="review-sort-header"
                        @click="toggleReviewSort('new', 'kind')"
                      >
                        投稿類型
                        <i
                          class="review-sort-icon"
                          :class="getReviewSortHeaderIcon('new', 'kind')"
                          aria-hidden="true"
                        ></i>
                      </button>
                    </template>
                    <template #body="{ data }">
                      <div class="review-submission-type-cell">
                        <Tag
                          :class="[
                            'soft-badge',
                            'review-card-chip',
                            'review-desktop-submission-type-tag',
                            getArchiveSubmissionKindClass(data),
                          ]"
                          :severity="getArchiveSubmissionKindSeverity(data)"
                        >
                          <span
                            v-if="data.requested_category_key"
                            class="submission-type-combined-label"
                            aria-label="新分類＋新課程"
                          >
                            <span class="submission-type-combined-label__category">新分類</span>
                            <span
                              class="submission-type-combined-label__separator"
                              aria-hidden="true"
                              >＋</span
                            >
                            <span class="submission-type-combined-label__course">新課程</span>
                          </span>
                          <span v-else>{{ getArchiveSubmissionKind(data) }}</span>
                        </Tag>
                      </div>
                    </template>
                  </Column>
                  <Column field="subject">
                    <template #header>
                      <button
                        type="button"
                        class="review-sort-header"
                        @click="toggleReviewSort('new', 'subject')"
                      >
                        課程
                        <i
                          class="review-sort-icon"
                          :class="getReviewSortHeaderIcon('new', 'subject')"
                          aria-hidden="true"
                        ></i>
                      </button>
                    </template>
                    <template #body="{ data }">
                      <div
                        class="mobile-primary-text review-card-title review-course-cell review-desktop-course-cell"
                      >
                        <div class="review-desktop-course-cell__name">{{ data.subject }}</div>
                        <div
                          v-if="data.is_admin_upload"
                          class="review-desktop-course-cell__admin-row"
                        >
                          <Tag
                            class="soft-badge soft-badge--admin review-admin-upload-chip review-course-cell__admin-tag"
                            severity="info"
                          >
                            管理員投稿
                          </Tag>
                        </div>
                      </div>
                      <div class="review-mobile-card-header">
                        <div class="review-mobile-card-title-block">
                          <div class="review-mobile-card-course-name">
                            {{ getReviewMobileCourseName(data) }}
                          </div>
                          <div class="review-mobile-type-badges">
                            <Tag
                              :class="[
                                'soft-badge',
                                'review-card-chip',
                                'review-mobile-card-type-badge',
                                getArchiveSubmissionKindClass(data),
                              ]"
                              :severity="getArchiveSubmissionKindSeverity(data)"
                            >
                              {{ getArchiveSubmissionKind(data) }}
                            </Tag>
                            <Tag
                              v-if="data.is_admin_upload"
                              class="soft-badge soft-badge--admin review-admin-upload-chip"
                              severity="info"
                            >
                              管理員投稿
                            </Tag>
                          </div>
                        </div>
                        <Tag
                          :class="[
                            'soft-badge',
                            'review-card-chip',
                            'review-status-chip',
                            'review-mobile-card-status-badge',
                            getSubmissionStatusClass(data.status),
                          ]"
                          :severity="getSubmissionSeverity(data.status)"
                        >
                          {{ getSubmissionLabel(data.status) }}
                        </Tag>
                      </div>
                      <div class="review-mobile-summary">
                        <div v-if="data.name" class="review-mobile-exam-name">{{ data.name }}</div>
                        <div class="review-mobile-info-grid">
                          <div
                            v-if="data.id !== null && data.id !== undefined"
                            class="review-mobile-info-item"
                          >
                            <span class="review-mobile-info-label">投稿編號</span>
                            <span class="review-mobile-info-value">{{
                              formatSubmissionLabel(data)
                            }}</span>
                          </div>
                          <div class="review-mobile-info-item">
                            <span class="review-mobile-info-label">申請時間</span>
                            <span class="review-mobile-info-value">{{
                              formatReviewSubmissionTime(data)
                            }}</span>
                          </div>
                          <div v-if="data.academic_year" class="review-mobile-info-item">
                            <span class="review-mobile-info-label">學期</span>
                            <span class="review-mobile-info-value">{{
                              formatAcademicTerm(data.academic_year)
                            }}</span>
                          </div>
                          <div v-if="data.professor" class="review-mobile-info-item">
                            <span class="review-mobile-info-label">授課教師</span>
                            <span class="review-mobile-info-value">{{ data.professor }}</span>
                          </div>
                          <div class="review-mobile-info-item">
                            <span class="review-mobile-info-label">審核人</span>
                            <span class="review-mobile-info-value">{{
                              formatReviewReviewer(data)
                            }}</span>
                          </div>
                          <div class="review-mobile-info-item">
                            <span class="review-mobile-info-label">審核時間</span>
                            <span class="review-mobile-info-value">{{
                              formatReviewReviewedTime(data)
                            }}</span>
                          </div>
                        </div>
                      </div>
                    </template>
                  </Column>
                  <Column field="academic_year">
                    <template #header>
                      <button
                        type="button"
                        class="review-sort-header"
                        @click="toggleReviewSort('new', 'academic_year')"
                      >
                        學期
                        <i
                          class="review-sort-icon"
                          :class="getReviewSortHeaderIcon('new', 'academic_year')"
                          aria-hidden="true"
                        ></i>
                      </button>
                    </template>
                    <template #body="{ data }">
                      <span class="review-card-meta-text">{{
                        formatAcademicTerm(data.academic_year)
                      }}</span>
                    </template>
                  </Column>
                  <Column field="professor">
                    <template #header>
                      <button
                        type="button"
                        class="review-sort-header"
                        @click="toggleReviewSort('new', 'professor')"
                      >
                        授課教師
                        <i
                          class="review-sort-icon"
                          :class="getReviewSortHeaderIcon('new', 'professor')"
                          aria-hidden="true"
                        ></i>
                      </button>
                    </template>
                    <template #body="{ data }">
                      <span class="mobile-metadata-text review-card-meta-text">{{
                        data.professor
                      }}</span>
                    </template>
                  </Column>
                  <Column field="name">
                    <template #header>
                      <button
                        type="button"
                        class="review-sort-header"
                        @click="toggleReviewSort('new', 'name')"
                      >
                        考試名稱
                        <i
                          class="review-sort-icon"
                          :class="getReviewSortHeaderIcon('new', 'name')"
                          aria-hidden="true"
                        ></i>
                      </button>
                    </template>
                    <template #body="{ data }">
                      <span class="mobile-metadata-text review-card-meta-text">{{
                        data.name
                      }}</span>
                      <small class="text-xs text-500"
                        >投稿編號：{{ formatSubmissionLabel(data) }}</small
                      >
                    </template>
                  </Column>
                  <Column style="width: 10.5rem; min-width: 10.5rem">
                    <template #header>
                      <button
                        type="button"
                        class="review-sort-header"
                        @click="toggleReviewSort('new', 'submitted_at')"
                      >
                        申請
                        <i
                          class="review-sort-icon"
                          :class="getReviewSortHeaderIcon('new', 'submitted_at')"
                          aria-hidden="true"
                        ></i>
                      </button>
                    </template>
                    <template #body="{ data }">
                      <div class="admin-actor-time">
                        <span class="admin-actor-time__name" :title="getReviewRequesterLabel(data)">
                          {{ getReviewRequesterLabel(data) }}
                        </span>
                        <time
                          v-if="getReviewSubmissionTimeValue(data)"
                          class="admin-actor-time__time"
                          :datetime="getReviewSubmissionTimeValue(data)"
                        >
                          {{ formatAdminActorTime(getReviewSubmissionTimeValue(data)) }}
                        </time>
                        <span v-else class="admin-actor-time__time">—</span>
                      </div>
                    </template>
                  </Column>
                  <Column
                    field="status"
                    headerClass="admin-desktop-status-column"
                    bodyClass="admin-desktop-status-column"
                    style="width: 6rem; min-width: 6rem"
                  >
                    <template #header>
                      <button
                        type="button"
                        class="review-sort-header"
                        @click="toggleReviewSort('new', 'status')"
                      >
                        狀態
                        <i
                          class="review-sort-icon"
                          :class="getReviewSortHeaderIcon('new', 'status')"
                          aria-hidden="true"
                        ></i>
                      </button>
                    </template>
                    <template #body="{ data }">
                      <div class="admin-desktop-status-cell">
                        <Tag
                          :class="[
                            'soft-badge',
                            'review-card-chip',
                            'review-status-chip',
                            'admin-desktop-status-tag',
                            getSubmissionStatusClass(data.status),
                          ]"
                          :severity="getSubmissionSeverity(data.status)"
                        >
                          <span
                            class="admin-desktop-status-label"
                            :aria-label="getSubmissionLabel(data.status)"
                          >
                            <span
                              v-for="(character, index) in Array.from(
                                getSubmissionLabel(data.status)
                              )"
                              :key="`${character}-${index}`"
                              aria-hidden="true"
                              >{{ character }}</span
                            >
                          </span>
                        </Tag>
                      </div>
                    </template>
                  </Column>
                  <Column style="width: 10.5rem; min-width: 10.5rem">
                    <template #header>
                      <button
                        type="button"
                        class="review-sort-header"
                        @click="toggleReviewSort('new', 'reviewed_at')"
                      >
                        審核
                        <i
                          class="review-sort-icon"
                          :class="getReviewSortHeaderIcon('new', 'reviewed_at')"
                          aria-hidden="true"
                        ></i>
                      </button>
                    </template>
                    <template #body="{ data }">
                      <div class="admin-actor-time">
                        <span
                          class="admin-actor-time__name"
                          :title="getReviewReviewerDisplay(data)"
                        >
                          {{ getReviewReviewerDisplay(data) }}
                        </span>
                        <time
                          v-if="getReviewReviewedAt(data)"
                          class="admin-actor-time__time"
                          :datetime="getReviewReviewedAt(data)"
                        >
                          {{ formatAdminActorTime(getReviewReviewedAt(data)) }}
                        </time>
                        <span v-else class="admin-actor-time__time">—</span>
                      </div>
                    </template>
                  </Column>
                  <Column header="操作">
                    <template #body="{ data }">
                      <div class="review-row-action-area">
                        <div class="admin-card-actions review-card-actions">
                          <Button
                            class="review-action-button"
                            label="查看/編輯"
                            icon="pi pi-search"
                            aria-label="查看/編輯"
                            title="查看/編輯"
                            size="small"
                            severity="secondary"
                            outlined
                            @click="openArchiveRequestDialog(data)"
                          />
                          <Button
                            v-for="action in getReviewRowActions(data)"
                            :key="action.key"
                            :label="action.label"
                            :icon="action.icon"
                            :aria-label="action.label"
                            :title="action.label"
                            :class="[
                              'review-action-button',
                              {
                                'review-action-button--reject': action.key === 'reject',
                                'review-action-button--delete': action.key === 'delete',
                                'review-action-reject': action.key === 'reject',
                                'admin-danger-solid-button': action.key === 'reject',
                                'admin-danger-outline-button': action.key === 'delete',
                                'review-action-delete': action.key === 'delete',
                              },
                            ]"
                            size="small"
                            :severity="action.severity"
                            :outlined="action.outlined"
                            :text="action.text"
                            @click="runReviewRowAction(data, action.key)"
                          />
                        </div>
                        <div
                          v-if="getReviewTrashNote(data)"
                          :class="['review-card-action-note', getReviewTrashNoteClass(data)]"
                          :title="getReviewTrashNote(data, true)"
                        >
                          <i :class="getReviewTrashNoteIcon(data)" aria-hidden="true"></i>
                          <span class="review-card-action-note__text">{{
                            getReviewTrashNote(data)
                          }}</span>
                        </div>
                      </div>
                    </template>
                  </Column>
                </DataTable>
              </div>

              <div class="review-section mt-5">
                <div class="review-section-header">
                  <h3>既有課程考古申請</h3>
                </div>
                <DataTable
                  :value="existingCourseArchiveRequests"
                  :loading="reviewLoading"
                  class="admin-data-table review-request-table"
                  paginator
                  :rows="existingSubmissionRows"
                  :rowsPerPageOptions="[5, 10, 15, 25, 50]"
                  :first="existingSubmissionFirst"
                  paginatorTemplate="FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink RowsPerPageDropdown CurrentPageReport"
                  currentPageReportTemplate="第 {currentPage} / {totalPages} 頁，共 {totalRecords} 筆"
                  @page="handleExistingSubmissionPage"
                  tableStyle="min-width: 72rem"
                  responsiveLayout="stack"
                  breakpoint="1023px"
                >
                  <template #empty>
                    <div class="review-empty-state">沒有符合搜尋條件的投稿。</div>
                  </template>
                  <Column field="subject">
                    <template #header>
                      <button
                        type="button"
                        class="review-sort-header"
                        @click="toggleReviewSort('existing', 'subject')"
                      >
                        課程
                        <i
                          class="review-sort-icon"
                          :class="getReviewSortHeaderIcon('existing', 'subject')"
                          aria-hidden="true"
                        ></i>
                      </button>
                    </template>
                    <template #body="{ data }">
                      <div
                        class="mobile-primary-text review-card-title review-course-cell review-desktop-course-cell"
                      >
                        <div class="review-desktop-course-cell__name">{{ data.subject }}</div>
                        <div
                          v-if="data.is_admin_upload"
                          class="review-desktop-course-cell__admin-row"
                        >
                          <Tag
                            class="soft-badge soft-badge--admin review-admin-upload-chip review-course-cell__admin-tag"
                            severity="info"
                          >
                            管理員投稿
                          </Tag>
                        </div>
                      </div>
                      <div class="review-mobile-card-header">
                        <div class="review-mobile-card-title-block">
                          <div class="review-mobile-card-course-name">
                            {{ getReviewMobileCourseName(data) }}
                          </div>
                          <div v-if="data.is_admin_upload" class="review-mobile-type-badges">
                            <Tag
                              class="soft-badge soft-badge--admin review-admin-upload-chip"
                              severity="info"
                            >
                              管理員投稿
                            </Tag>
                          </div>
                        </div>
                        <Tag
                          :class="[
                            'soft-badge',
                            'review-card-chip',
                            'review-status-chip',
                            'review-mobile-card-status-badge',
                            getSubmissionStatusClass(data.status),
                          ]"
                          :severity="getSubmissionSeverity(data.status)"
                        >
                          {{ getSubmissionLabel(data.status) }}
                        </Tag>
                      </div>
                      <div class="review-mobile-summary">
                        <div v-if="data.name" class="review-mobile-exam-name">{{ data.name }}</div>
                        <div class="review-mobile-info-grid">
                          <div
                            v-if="data.id !== null && data.id !== undefined"
                            class="review-mobile-info-item"
                          >
                            <span class="review-mobile-info-label">投稿編號</span>
                            <span class="review-mobile-info-value">{{
                              formatSubmissionLabel(data)
                            }}</span>
                          </div>
                          <div class="review-mobile-info-item">
                            <span class="review-mobile-info-label">投稿時間</span>
                            <span class="review-mobile-info-value">{{
                              formatReviewSubmissionTime(data)
                            }}</span>
                          </div>
                          <div v-if="data.academic_year" class="review-mobile-info-item">
                            <span class="review-mobile-info-label">學期</span>
                            <span class="review-mobile-info-value">{{
                              formatAcademicTerm(data.academic_year)
                            }}</span>
                          </div>
                          <div v-if="data.professor" class="review-mobile-info-item">
                            <span class="review-mobile-info-label">授課教師</span>
                            <span class="review-mobile-info-value">{{ data.professor }}</span>
                          </div>
                          <div class="review-mobile-info-item">
                            <span class="review-mobile-info-label">審核人</span>
                            <span class="review-mobile-info-value">{{
                              formatReviewReviewer(data)
                            }}</span>
                          </div>
                          <div class="review-mobile-info-item">
                            <span class="review-mobile-info-label">審核時間</span>
                            <span class="review-mobile-info-value">{{
                              formatReviewReviewedTime(data)
                            }}</span>
                          </div>
                        </div>
                      </div>
                    </template>
                  </Column>
                  <Column field="academic_year">
                    <template #header>
                      <button
                        type="button"
                        class="review-sort-header"
                        @click="toggleReviewSort('existing', 'academic_year')"
                      >
                        學期
                        <i
                          class="review-sort-icon"
                          :class="getReviewSortHeaderIcon('existing', 'academic_year')"
                          aria-hidden="true"
                        ></i>
                      </button>
                    </template>
                    <template #body="{ data }">
                      <span class="review-card-meta-text">{{
                        formatAcademicTerm(data.academic_year)
                      }}</span>
                    </template>
                  </Column>
                  <Column field="professor">
                    <template #header>
                      <button
                        type="button"
                        class="review-sort-header"
                        @click="toggleReviewSort('existing', 'professor')"
                      >
                        授課教師
                        <i
                          class="review-sort-icon"
                          :class="getReviewSortHeaderIcon('existing', 'professor')"
                          aria-hidden="true"
                        ></i>
                      </button>
                    </template>
                    <template #body="{ data }">
                      <span class="mobile-metadata-text review-card-meta-text">{{
                        data.professor
                      }}</span>
                    </template>
                  </Column>
                  <Column field="name">
                    <template #header>
                      <button
                        type="button"
                        class="review-sort-header"
                        @click="toggleReviewSort('existing', 'name')"
                      >
                        考試名稱
                        <i
                          class="review-sort-icon"
                          :class="getReviewSortHeaderIcon('existing', 'name')"
                          aria-hidden="true"
                        ></i>
                      </button>
                    </template>
                    <template #body="{ data }">
                      <span class="mobile-metadata-text review-card-meta-text">{{
                        data.name
                      }}</span>
                      <small class="text-xs text-500"
                        >投稿編號：{{ formatSubmissionLabel(data) }}</small
                      >
                    </template>
                  </Column>
                  <Column style="width: 10.5rem; min-width: 10.5rem">
                    <template #header>
                      <button
                        type="button"
                        class="review-sort-header"
                        @click="toggleReviewSort('existing', 'submitted_at')"
                      >
                        投稿
                        <i
                          class="review-sort-icon"
                          :class="getReviewSortHeaderIcon('existing', 'submitted_at')"
                          aria-hidden="true"
                        ></i>
                      </button>
                    </template>
                    <template #body="{ data }">
                      <div class="admin-actor-time">
                        <span class="admin-actor-time__name" :title="getReviewRequesterLabel(data)">
                          {{ getReviewRequesterLabel(data) }}
                        </span>
                        <time
                          v-if="getReviewSubmissionTimeValue(data)"
                          class="admin-actor-time__time"
                          :datetime="getReviewSubmissionTimeValue(data)"
                        >
                          {{ formatAdminActorTime(getReviewSubmissionTimeValue(data)) }}
                        </time>
                        <span v-else class="admin-actor-time__time">—</span>
                      </div>
                    </template>
                  </Column>
                  <Column
                    field="status"
                    headerClass="admin-desktop-status-column"
                    bodyClass="admin-desktop-status-column"
                    style="width: 6rem; min-width: 6rem"
                  >
                    <template #header>
                      <button
                        type="button"
                        class="review-sort-header"
                        @click="toggleReviewSort('existing', 'status')"
                      >
                        狀態
                        <i
                          class="review-sort-icon"
                          :class="getReviewSortHeaderIcon('existing', 'status')"
                          aria-hidden="true"
                        ></i>
                      </button>
                    </template>
                    <template #body="{ data }">
                      <div class="admin-desktop-status-cell">
                        <Tag
                          :class="[
                            'soft-badge',
                            'review-card-chip',
                            'review-status-chip',
                            'admin-desktop-status-tag',
                            getSubmissionStatusClass(data.status),
                          ]"
                          :severity="getSubmissionSeverity(data.status)"
                        >
                          <span
                            class="admin-desktop-status-label"
                            :aria-label="getSubmissionLabel(data.status)"
                          >
                            <span
                              v-for="(character, index) in Array.from(
                                getSubmissionLabel(data.status)
                              )"
                              :key="`${character}-${index}`"
                              aria-hidden="true"
                              >{{ character }}</span
                            >
                          </span>
                        </Tag>
                      </div>
                    </template>
                  </Column>
                  <Column style="width: 10.5rem; min-width: 10.5rem">
                    <template #header>
                      <button
                        type="button"
                        class="review-sort-header"
                        @click="toggleReviewSort('existing', 'reviewed_at')"
                      >
                        審核
                        <i
                          class="review-sort-icon"
                          :class="getReviewSortHeaderIcon('existing', 'reviewed_at')"
                          aria-hidden="true"
                        ></i>
                      </button>
                    </template>
                    <template #body="{ data }">
                      <div class="admin-actor-time">
                        <span
                          class="admin-actor-time__name"
                          :title="getReviewReviewerDisplay(data)"
                        >
                          {{ getReviewReviewerDisplay(data) }}
                        </span>
                        <time
                          v-if="getReviewReviewedAt(data)"
                          class="admin-actor-time__time"
                          :datetime="getReviewReviewedAt(data)"
                        >
                          {{ formatAdminActorTime(getReviewReviewedAt(data)) }}
                        </time>
                        <span v-else class="admin-actor-time__time">—</span>
                      </div>
                    </template>
                  </Column>
                  <Column header="操作">
                    <template #body="{ data }">
                      <div class="review-row-action-area">
                        <div class="admin-card-actions review-card-actions">
                          <Button
                            class="review-action-button"
                            label="查看/編輯"
                            icon="pi pi-search"
                            aria-label="查看/編輯"
                            title="查看/編輯"
                            size="small"
                            severity="secondary"
                            outlined
                            @click="openArchiveRequestDialog(data)"
                          />
                          <Button
                            v-for="action in getReviewRowActions(data)"
                            :key="action.key"
                            :label="action.label"
                            :icon="action.icon"
                            :aria-label="action.label"
                            :title="action.label"
                            :class="[
                              'review-action-button',
                              {
                                'review-action-button--reject': action.key === 'reject',
                                'review-action-button--delete': action.key === 'delete',
                                'review-action-reject': action.key === 'reject',
                                'admin-danger-solid-button': action.key === 'reject',
                                'admin-danger-outline-button': action.key === 'delete',
                                'review-action-delete': action.key === 'delete',
                              },
                            ]"
                            size="small"
                            :severity="action.severity"
                            :outlined="action.outlined"
                            :text="action.text"
                            @click="runReviewRowAction(data, action.key)"
                          />
                        </div>
                        <div
                          v-if="getReviewTrashNote(data)"
                          :class="['review-card-action-note', getReviewTrashNoteClass(data)]"
                          :title="getReviewTrashNote(data, true)"
                        >
                          <i :class="getReviewTrashNoteIcon(data)" aria-hidden="true"></i>
                          <span class="review-card-action-note__text">{{
                            getReviewTrashNote(data)
                          }}</span>
                        </div>
                      </div>
                    </template>
                  </Column>
                </DataTable>
              </div>
            </div>
          </TabPanel>

          <TabPanel value="5">
            <div class="p-2 md:p-4">
              <ReportManagementPanel />
            </div>
          </TabPanel>

          <TabPanel value="4">
            <div class="p-2 md:p-4 trash-center">
              <div class="admin-toolbar admin-toolbar--trash-shell mb-4">
                <div>
                  <h3 class="m-0">垃圾桶</h3>
                  <p class="m-0 text-sm text-500">還原或永久刪除管理中心已刪除項目</p>
                </div>
                <div class="admin-toolbar admin-toolbar--trash">
                  <div class="admin-toolbar__filters admin-toolbar__filters--trash">
                    <Select
                      inputId="admin-trash-filter"
                      name="admin-trash-filter"
                      v-model="trashFilterType"
                      :options="trashFilterOptions"
                      optionLabel="label"
                      optionValue="value"
                      placeholder="篩選項目類型"
                      showClear
                      class="admin-toolbar__select admin-toolbar__select--trash w-full md:w-12rem"
                      @change="loadTrashItems"
                    />
                  </div>
                  <div class="admin-toolbar__actions admin-toolbar__actions--trash">
                    <Button
                      class="admin-toolbar__button"
                      icon="pi pi-refresh"
                      label="重新整理"
                      outlined
                      @click="loadTrashItems"
                    />
                    <Button
                      class="admin-toolbar__button"
                      icon="pi pi-sitemap"
                      :label="getTrashRelationButtonLabel()"
                      outlined
                      :disabled="!isTrashRelationHierarchyFilterOnly"
                      :severity="isTrashRelationHierarchyEnabled ? 'primary' : 'secondary'"
                      :title="
                        isTrashRelationHierarchyFilterOnly ? '' : '相關性顯示僅適用於「全部」篩選。'
                      "
                      @click="toggleTrashRelationHierarchy"
                    />
                    <Button
                      class="admin-toolbar__button"
                      icon="pi pi-info-circle"
                      label="依賴與阻擋說明"
                      outlined
                      aria-label="依賴與阻擋說明"
                      title="依賴與阻擋說明"
                      @click="showTrashDependencyHelpDialog = true"
                    />
                    <Button
                      class="admin-toolbar__button admin-toolbar__button--danger"
                      icon="pi pi-times-circle"
                      label="清空目前範圍"
                      severity="danger"
                      outlined
                      :disabled="!trashItems.length || trashLoading"
                      @click="confirmBulkDeleteTrash"
                    />
                  </div>
                </div>
              </div>

              <DataTable
                :value="paginatedTrashItems"
                :loading="trashLoading"
                class="admin-data-table trash-table"
                tableStyle="min-width: 72rem"
                responsiveLayout="stack"
                breakpoint="1023px"
                :rowClass="getTrashRowClass"
              >
                <Column field="deleted_at" style="width: 10.5rem; min-width: 10.5rem">
                  <template #header>
                    <button
                      type="button"
                      class="review-sort-header"
                      @click="toggleTrashSort('deleted_at')"
                    >
                      刪除
                      <i
                        class="review-sort-icon"
                        :class="getTrashSortHeaderIcon('deleted_at')"
                        aria-hidden="true"
                      ></i>
                    </button>
                  </template>
                  <template #body="{ data }">
                    <div class="admin-actor-time">
                      <span class="admin-actor-time__name" :title="getTrashDeletedByLabel(data)">
                        {{ getTrashDeletedByLabel(data) }}
                      </span>
                      <time class="admin-actor-time__time" :datetime="data.deleted_at">
                        {{ formatAdminActorTime(data.deleted_at) }}
                      </time>
                    </div>
                  </template>
                </Column>
                <Column field="item_type">
                  <template #header>
                    <button
                      type="button"
                      class="review-sort-header"
                      @click="toggleTrashSort('type')"
                    >
                      類型
                      <i
                        class="review-sort-icon"
                        :class="getTrashSortHeaderIcon('type')"
                        aria-hidden="true"
                      ></i>
                    </button>
                  </template>
                  <template #body="{ data }">
                    <Tag class="soft-badge soft-badge--type trash-type-chip" severity="secondary">
                      {{ getTrashTypeLabel(data.item_type) }}
                    </Tag>
                  </template>
                </Column>
                <Column
                  field="display_name"
                  headerClass="trash-name-column"
                  bodyClass="trash-name-column"
                  style="width: clamp(14rem, 18vw, 18rem); max-width: 18rem"
                >
                  <template #header>
                    <button
                      type="button"
                      class="review-sort-header"
                      @click="toggleTrashSort('name')"
                    >
                      名稱
                      <i
                        class="review-sort-icon"
                        :class="getTrashSortHeaderIcon('name')"
                        aria-hidden="true"
                      ></i>
                    </button>
                  </template>
                  <template #body="{ data }">
                    <span class="trash-name-cell">
                      <strong
                        class="trash-name-title"
                        :style="{
                          paddingLeft: `${isTrashRelationHierarchyEnabled ? getTrashNameIndent(data) : 0}rem`,
                        }"
                      >
                        <span
                          v-if="isTrashRelationHierarchyEnabled && (data?.trash_depth || 0) > 0"
                          class="trash-tree-prefix"
                          aria-hidden="true"
                        >
                          {{ getTrashTreePrefix(data) }}
                        </span>
                        <span
                          :class="[
                            'trash-name-title__text',
                            { 'trash-user-name': data.item_type === 'user' },
                          ]"
                        >
                          {{ data.display_name }}
                        </span>
                      </strong>
                      <small
                        v-if="data.item_type === 'user' && data.user_email"
                        class="trash-user-email"
                        :title="data.user_email"
                      >
                        {{ data.user_email }}
                      </small>
                      <small v-if="getTrashSubmissionLabel(data)">{{
                        getTrashSubmissionLabel(data)
                      }}</small>
                      <small v-if="getTrashSemesterText(data)">{{
                        getTrashSemesterText(data)
                      }}</small>
                      <small v-if="getTrashContextLine(data)" class="text-secondary">
                        {{ getTrashContextLine(data) }}
                      </small>
                      <small
                        v-for="detail in getTrashReportDetails(data)"
                        :key="detail.label"
                        class="text-secondary"
                      >
                        {{ detail.label }}：{{ detail.value }}
                      </small>
                    </span>
                  </template>
                </Column>
                <Column
                  field="status"
                  headerClass="admin-desktop-status-column"
                  bodyClass="admin-desktop-status-column"
                  style="width: 6rem; min-width: 6rem"
                >
                  <template #header>
                    <button
                      type="button"
                      class="review-sort-header"
                      @click="toggleTrashSort('status')"
                    >
                      狀態
                      <i
                        class="review-sort-icon"
                        :class="getTrashSortHeaderIcon('status')"
                        aria-hidden="true"
                      ></i>
                    </button>
                  </template>
                  <template #body="{ data }">
                    <div class="admin-desktop-status-cell">
                      <Tag
                        :class="[
                          'soft-badge',
                          'review-status-chip',
                          'admin-desktop-status-tag',
                          getTrashStatusClass(data.status, data.item_type),
                        ]"
                        :severity="getTrashStatusSeverity(data.status, data.item_type)"
                      >
                        <span
                          class="admin-desktop-status-label"
                          :aria-label="getTrashStatusLabel(data.status, data.item_type)"
                        >
                          <span
                            v-for="(character, index) in Array.from(
                              getTrashStatusLabel(data.status, data.item_type)
                            )"
                            :key="`${character}-${index}`"
                            aria-hidden="true"
                            >{{ character }}</span
                          >
                        </span>
                      </Tag>
                    </div>
                  </template>
                </Column>
                <Column
                  header="依賴與阻擋"
                  headerClass="trash-dependencies-column"
                  bodyClass="trash-dependencies-column"
                  style="width: clamp(17rem, 22vw, 23rem); max-width: 23rem"
                >
                  <template #body="{ data }">
                    <div class="trash-dependencies">
                      <Tag
                        v-for="dependency in getTrashDependencies(data)"
                        :key="dependency.key"
                        :severity="getTrashDependencySeverity(dependency)"
                        :class="[
                          'soft-badge',
                          'trash-dependency-chip',
                          getTrashDependencyChipClass(dependency),
                        ]"
                      >
                        {{ dependency.label }}
                      </Tag>
                      <span
                        v-if="!getTrashDependencies(data).length"
                        class="soft-badge trash-dependency-chip trash-dependency-chip--clear"
                        >無阻擋</span
                      >
                    </div>
                  </template>
                </Column>
                <Column header="操作">
                  <template #body="{ data }">
                    <div class="admin-card-actions">
                      <Button
                        v-if="canRestoreTrashItem(data)"
                        icon="pi pi-undo"
                        label="還原"
                        size="small"
                        severity="success"
                        outlined
                        @click="confirmRestoreTrashItem(data)"
                      />
                      <Button
                        v-if="canPermanentDeleteTrashItem(data)"
                        class="trash-action-button trash-action-button--delete trash-action-permanent-delete admin-danger-outline-button"
                        icon="pi pi-trash"
                        label="永久刪除"
                        aria-label="永久刪除"
                        title="永久刪除"
                        size="small"
                        severity="danger"
                        outlined
                        @click="confirmPermanentDeleteTrashItem(data)"
                      />
                      <span
                        v-if="!canRestoreTrashItem(data) && !canPermanentDeleteTrashItem(data)"
                        class="text-xs text-500"
                      >
                        目前無可用操作
                      </span>
                    </div>
                  </template>
                </Column>
              </DataTable>

              <div v-if="!trashLoading" class="trash-mobile-list">
                <article
                  v-for="data in paginatedTrashItems"
                  :key="getTrashItemKey(data)"
                  :class="['trash-mobile-card', getTrashRowClass(data)]"
                >
                  <header class="trash-mobile-card-header">
                    <div class="trash-mobile-card-title-block">
                      <strong
                        :class="[
                          'trash-mobile-card-title',
                          { 'trash-user-name': data.item_type === 'user' },
                        ]"
                      >
                        <span
                          v-if="isTrashRelationHierarchyEnabled && (data?.trash_depth || 0) > 0"
                          class="trash-tree-prefix"
                          aria-hidden="true"
                        >
                          {{ getTrashTreePrefix(data) }}
                        </span>
                        {{ data.display_name }}
                      </strong>
                      <small
                        v-if="data.item_type === 'user' && data.user_email"
                        class="trash-user-email"
                        :title="data.user_email"
                      >
                        {{ data.user_email }}
                      </small>
                    </div>
                    <div class="trash-mobile-card-badges">
                      <Tag
                        class="soft-badge soft-badge--type trash-type-chip trash-mobile-type-badge"
                        severity="secondary"
                      >
                        {{ getTrashTypeLabel(data.item_type) }}
                      </Tag>
                      <Tag
                        :class="[
                          'soft-badge',
                          'review-status-chip',
                          'trash-mobile-status',
                          getTrashStatusClass(data.status, data.item_type),
                        ]"
                        :severity="getTrashStatusSeverity(data.status, data.item_type)"
                      >
                        {{ getTrashStatusLabel(data.status, data.item_type) }}
                      </Tag>
                    </div>
                  </header>

                  <div class="trash-mobile-info-grid">
                    <div
                      v-for="metadata in getTrashMobileMetadata(data)"
                      :key="metadata.key"
                      :class="[
                        'trash-mobile-info-item',
                        { 'trash-mobile-info-item--row-start': metadata.startNewRow },
                      ]"
                    >
                      <span class="trash-mobile-info-label">{{ metadata.label }}</span>
                      <span class="trash-mobile-info-value">{{ metadata.value }}</span>
                    </div>
                  </div>

                  <footer class="trash-mobile-card-footer">
                    <div class="trash-mobile-dependencies">
                      <Tag
                        v-for="dependency in getTrashDependencies(data)"
                        :key="dependency.key"
                        :severity="getTrashDependencySeverity(dependency)"
                        :class="[
                          'soft-badge',
                          'trash-dependency-chip',
                          getTrashDependencyChipClass(dependency),
                        ]"
                      >
                        {{ dependency.label }}
                      </Tag>
                      <span
                        v-if="!getTrashDependencies(data).length"
                        class="soft-badge trash-dependency-chip trash-dependency-chip--clear"
                        >無阻擋</span
                      >
                    </div>

                    <section class="trash-mobile-card-actions">
                      <Button
                        v-if="canRestoreTrashItem(data)"
                        icon="pi pi-undo"
                        label="還原"
                        aria-label="還原"
                        title="還原"
                        size="small"
                        severity="success"
                        outlined
                        @click="confirmRestoreTrashItem(data)"
                      />
                      <Button
                        v-if="canPermanentDeleteTrashItem(data)"
                        class="trash-action-button trash-action-button--delete trash-action-permanent-delete admin-danger-outline-button"
                        icon="pi pi-trash"
                        label="永久刪除"
                        aria-label="永久刪除"
                        title="永久刪除"
                        size="small"
                        severity="danger"
                        outlined
                        @click="confirmPermanentDeleteTrashItem(data)"
                      />
                      <span
                        v-if="!canRestoreTrashItem(data) && !canPermanentDeleteTrashItem(data)"
                        class="text-xs text-500"
                      >
                        目前無可用操作
                      </span>
                    </section>
                  </footer>
                </article>
              </div>
              <Paginator
                v-if="!trashLoading && sortedTrashItems.length"
                :first="trashFirst"
                :rows="trashRowsPerPage"
                :totalRecords="sortedTrashItems.length"
                :rowsPerPageOptions="ADMIN_PAGE_SIZE_OPTIONS"
                template="FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink RowsPerPageDropdown CurrentPageReport"
                currentPageReportTemplate="第 {currentPage} / {totalPages} 頁，共 {totalRecords} 筆"
                class="trash-paginator"
                @page="handleTrashPageChange"
              />
            </div>
          </TabPanel>
        </TabPanels>
      </Tabs>

      <Dialog
        :visible="showCourseDialog"
        @update:visible="showCourseDialog = $event"
        :modal="true"
        :draggable="false"
        :closeOnEscape="false"
        :header="editingCourse ? '編輯課程' : '新增課程'"
        :style="{ width: '450px', maxWidth: '90vw' }"
        :autoFocus="false"
      >
        <div class="flex flex-column gap-4">
          <div class="flex flex-column gap-2">
            <label>課程名稱</label>
            <InputText
              id="admin-course-name"
              name="admin-course-name"
              v-model="courseForm.name"
              placeholder="輸入課程名稱"
              class="w-full"
              :class="{ 'p-invalid': courseFormErrors.name }"
            />
            <small v-if="courseFormErrors.name" class="p-error">
              {{ courseFormErrors.name }}
            </small>
          </div>

          <div class="flex flex-column gap-2">
            <label>分類</label>
            <Select
              inputId="admin-course-category"
              name="admin-course-category"
              v-model="courseForm.category"
              :options="categoryOptions"
              optionLabel="name"
              optionValue="value"
              placeholder="選擇分類"
              class="w-full"
              :class="{ 'p-invalid': courseFormErrors.category }"
            />
            <small v-if="courseFormErrors.category" class="p-error">
              {{ courseFormErrors.category }}
            </small>
          </div>
        </div>

        <div class="flex pt-6 justify-end gap-2.5">
          <Button label="取消" icon="pi pi-times" severity="secondary" @click="closeCourseDialog" />
          <Button
            :label="editingCourse ? '更新' : '新增'"
            :icon="editingCourse ? 'pi pi-check' : 'pi pi-plus'"
            severity="success"
            @click="saveCourse"
            :loading="saveLoading"
          />
        </div>
      </Dialog>

      <Dialog
        :visible="showCategoryDialog"
        @update:visible="showCategoryDialog = $event"
        :modal="true"
        :draggable="false"
        :header="editingCategory ? '編輯課程分類' : '新增課程分類'"
        :style="{ width: '480px', maxWidth: '92vw' }"
        :autoFocus="false"
      >
        <div class="flex flex-column gap-4">
          <div class="flex flex-column gap-2">
            <label>分類 Key</label>
            <InputText
              id="admin-category-key"
              name="admin-category-key"
              v-model="categoryForm.key"
              placeholder="例如 advanced-physics"
              class="w-full"
              :class="{ 'p-invalid': categoryFormErrors.key }"
            />
            <small v-if="categoryFormErrors.key" class="p-error">{{
              categoryFormErrors.key
            }}</small>
          </div>
          <div class="flex flex-column gap-2">
            <label>顯示名稱</label>
            <InputText
              id="admin-category-name"
              name="admin-category-name"
              v-model="categoryForm.name"
              placeholder="例如 進階物理"
              class="w-full"
              :class="{ 'p-invalid': categoryFormErrors.name }"
            />
            <small v-if="categoryFormErrors.name" class="p-error">{{
              categoryFormErrors.name
            }}</small>
          </div>
          <div class="flex flex-column gap-2">
            <label>科目旁小標籤</label>
            <InputText
              id="admin-category-label"
              name="admin-category-label"
              v-model="categoryForm.label"
              placeholder="例如 進階"
              class="w-full"
            />
          </div>
          <div class="flex flex-column gap-2">
            <label>PrimeIcons class</label>
            <InputText
              id="admin-category-icon"
              name="admin-category-icon"
              v-model="categoryForm.icon"
              placeholder="pi pi-fw pi-book"
              class="w-full"
            />
          </div>
          <div class="flex flex-column gap-2">
            <label>分類標籤顏色</label>
            <div class="category-color-options" role="radiogroup" aria-label="分類標籤顏色">
              <button
                v-for="option in categoryBadgeColorOptions"
                :key="option.value"
                type="button"
                class="category-color-option"
                :class="[
                  getCategoryBadgeClass({ badge_color: option.value }),
                  { 'is-selected': categoryForm.badge_color === option.value },
                ]"
                role="radio"
                :aria-checked="categoryForm.badge_color === option.value"
                @click="categoryForm.badge_color = option.value"
              >
                {{ option.label }}
              </button>
            </div>
            <div class="category-badge-preview">
              <span>預覽</span>
              <Tag severity="secondary" :class="getCategoryBadgeClass(categoryForm)">
                {{ categoryForm.label || categoryForm.name || '分類標籤' }}
              </Tag>
            </div>
          </div>
        </div>

        <div class="flex pt-6 justify-end gap-2.5">
          <Button
            label="取消"
            icon="pi pi-times"
            severity="secondary"
            @click="closeCategoryDialog"
          />
          <Button
            :label="editingCategory ? '更新' : '新增'"
            :icon="editingCategory ? 'pi pi-check' : 'pi pi-plus'"
            severity="success"
            :loading="categorySaveLoading"
            @click="saveCategory"
          />
        </div>
      </Dialog>

      <Dialog
        v-model:visible="showArchiveRequestDialog"
        header="考古題投稿詳情"
        class="submission-typography-dialog"
        modal
        :draggable="false"
        :style="{ width: '760px', maxWidth: '96vw' }"
        @hide="clearArchiveRequesterStats"
      >
        <div class="request-summary mb-4">
          <div class="request-summary__header">
            <Tag
              :class="[
                'soft-badge',
                'review-card-chip',
                getArchiveSubmissionKindClass(selectedArchiveRequest),
              ]"
              :severity="getArchiveSubmissionKindSeverity(selectedArchiveRequest)"
            >
              {{ getArchiveSubmissionKind(selectedArchiveRequest) }}
            </Tag>
            <small class="request-summary__id text-500">
              投稿編號：{{ formatSubmissionLabel(selectedArchiveRequest) }}
            </small>
          </div>
          <p
            v-if="selectedArchiveRequest?.requested_course_name"
            class="request-summary__description"
          >
            這筆投稿通過後會建立或使用新課程「{{ selectedArchiveRequest.requested_course_name }}」。
          </p>
          <p v-else class="request-summary__description">這筆投稿會掛到既有課程。</p>
        </div>
        <Message
          v-if="archiveRequestReadonlyMessage"
          severity="info"
          :closable="false"
          class="mb-4"
        >
          {{ archiveRequestReadonlyMessage }}
        </Message>
        <div class="grid">
          <template v-if="archiveRequestEditForm.requested_category_key">
            <div class="col-12 md:col-6 flex flex-column gap-2">
              <label>申請分類 Key</label>
              <InputText
                id="admin-review-requested-category-key"
                name="admin-review-requested-category-key"
                v-model="archiveRequestEditForm.requested_category_key"
                :disabled="!canEditSelectedArchiveRequest"
              />
            </div>
            <div class="col-12 md:col-6 flex flex-column gap-2">
              <label>申請分類名稱</label>
              <InputText
                id="admin-review-requested-category-name"
                name="admin-review-requested-category-name"
                v-model="archiveRequestEditForm.requested_category_name"
                :disabled="!canEditSelectedArchiveRequest"
              />
            </div>
            <div class="col-12 md:col-6 flex flex-column gap-2">
              <label>科目旁小標籤</label>
              <InputText
                id="admin-review-requested-category-label"
                name="admin-review-requested-category-label"
                v-model="archiveRequestEditForm.requested_category_label"
                :disabled="!canEditSelectedArchiveRequest"
              />
            </div>
          </template>
          <div
            v-if="archiveRequestEditForm.requested_course_name"
            class="col-12 md:col-6 flex flex-column gap-2"
          >
            <label>申請課程名稱</label>
            <InputText
              id="admin-review-requested-course-name"
              name="admin-review-requested-course-name"
              v-model="archiveRequestEditForm.requested_course_name"
              :disabled="!canEditSelectedArchiveRequest"
            />
          </div>
          <div class="col-12 md:col-6 flex flex-column gap-2">
            <label>課程</label>
            <InputText
              id="admin-review-subject"
              name="admin-review-subject"
              v-model="archiveRequestEditForm.subject"
              :disabled="!canEditSelectedArchiveRequest"
            />
          </div>
          <div
            v-if="archiveRequestEditForm.requested_category_key"
            class="col-12 md:col-6 flex flex-column gap-2"
          >
            <label>分類 Key</label>
            <InputText
              id="admin-review-category-key"
              name="admin-review-category-key"
              v-model="archiveRequestEditForm.category"
              :disabled="!canEditSelectedArchiveRequest"
            />
          </div>
          <div v-else class="col-12 md:col-6 flex flex-column gap-2">
            <label>分類</label>
            <Select
              inputId="admin-review-category"
              name="admin-review-category"
              v-model="archiveRequestEditForm.category"
              :options="categoryOptions"
              optionLabel="name"
              optionValue="value"
              overlayClass="submission-typography-overlay"
              :disabled="!canEditSelectedArchiveRequest"
            />
          </div>
          <div class="col-12 md:col-6 flex flex-column gap-2">
            <label>考試名稱</label>
            <InputText
              id="admin-review-exam-name"
              name="admin-review-exam-name"
              v-model="archiveRequestEditForm.name"
              :disabled="!canEditSelectedArchiveRequest"
            />
          </div>
          <div class="col-12 md:col-6 flex flex-column gap-2">
            <label>授課教師</label>
            <InputText
              id="admin-review-professor"
              name="admin-review-professor"
              v-model="archiveRequestEditForm.professor"
              :disabled="!canEditSelectedArchiveRequest"
            />
          </div>
          <div class="col-12 md:col-6 flex flex-column gap-2">
            <label>學期代碼</label>
            <InputNumber
              inputId="admin-review-academic-year"
              name="admin-review-academic-year"
              v-model="archiveRequestEditForm.academic_year"
              :disabled="!canEditSelectedArchiveRequest"
              :useGrouping="false"
            />
          </div>
          <div class="col-12 md:col-6 flex flex-column gap-2">
            <label>考試類型</label>
            <Select
              inputId="admin-review-archive-type"
              name="admin-review-archive-type"
              v-model="archiveRequestEditForm.archive_type"
              :options="archiveTypeOptions"
              optionLabel="name"
              optionValue="value"
              overlayClass="submission-typography-overlay"
              :disabled="!canEditSelectedArchiveRequest"
            />
          </div>
          <div class="col-12 flex align-items-center gap-2">
            <Checkbox
              inputId="admin-review-has-answers"
              name="admin-review-has-answers"
              v-model="archiveRequestEditForm.has_answers"
              :binary="true"
              :disabled="!canEditSelectedArchiveRequest"
            />
            <label for="admin-review-has-answers">附解答</label>
          </div>
        </div>

        <div class="mt-4">
          <h4 class="mb-2">同課程同考試比對</h4>
          <div class="comparison-basis mb-2">
            {{ getComparisonBasisText(selectedArchiveRequest) }}
          </div>
          <div v-if="comparisonLoading" class="text-sm text-500">載入中...</div>
          <div v-else-if="comparisonArchives.length === 0" class="text-sm text-500">
            沒有找到同課程、同教師、同學期、同考試名稱的其他投稿。
          </div>
          <div v-else class="submission-detail-comparison">
            <DataTable
              :value="comparisonArchives"
              class="comparison-desktop-table"
              tableStyle="min-width: 36rem"
              responsiveLayout="stack"
              breakpoint="768px"
            >
              <Column header="投稿編號">
                <template #body="{ data }">{{ formatComparisonSubmissionId(data) }}</template>
              </Column>
              <Column field="has_answers" header="解答">
                <template #body="{ data }">{{ data.has_answers ? '有' : '無' }}</template>
              </Column>
              <Column header="狀態">
                <template #body="{ data }">
                  <Tag
                    :class="[
                      'soft-badge',
                      'review-status-chip',
                      getSubmissionStatusClass(data.status),
                    ]"
                    :severity="getSubmissionSeverity(data.status)"
                  >
                    {{ getSubmissionLabel(data.status) }}
                  </Tag>
                </template>
              </Column>
              <Column header="投稿帳號">
                <template #body="{ data }">{{ getRequesterDisplay(data) }}</template>
              </Column>
              <Column header="操作" style="width: 14rem">
                <template #body="{ data }">
                  <div class="comparison-row-actions">
                    <Button
                      label="並排預覽"
                      icon="pi pi-columns"
                      size="small"
                      outlined
                      :loading="comparePreviewLoading && comparePreviewArchive?.id === data.id"
                      @click="openComparePreview(data)"
                    />
                    <Button
                      v-if="canTakedownComparisonItem(data)"
                      label="下架"
                      icon="pi pi-eye-slash"
                      size="small"
                      severity="secondary"
                      outlined
                      @click="confirmTakedownComparisonItem(data)"
                    />
                  </div>
                </template>
              </Column>
            </DataTable>
            <div class="submission-detail-comparison-mobile">
              <article
                v-for="comparison in comparisonArchives"
                :key="`comparison-mobile-${comparison.id}`"
                class="comparison-mobile-card"
              >
                <header class="comparison-mobile-card-header">
                  <div class="comparison-mobile-id">
                    投稿編號 {{ formatComparisonSubmissionId(comparison) }}
                  </div>
                  <Tag
                    :class="[
                      'soft-badge',
                      'review-status-chip',
                      'comparison-mobile-status',
                      getSubmissionStatusClass(comparison.status),
                    ]"
                    :severity="getSubmissionSeverity(comparison.status)"
                  >
                    {{ getSubmissionLabel(comparison.status) }}
                  </Tag>
                </header>
                <div class="comparison-mobile-meta">
                  <div class="comparison-mobile-meta-item">
                    <span class="comparison-mobile-meta-label">附解答</span>
                    <span class="comparison-mobile-meta-value">{{
                      comparison.has_answers ? '有' : '無'
                    }}</span>
                  </div>
                  <div class="comparison-mobile-meta-item">
                    <span class="comparison-mobile-meta-label">投稿者</span>
                    <span class="comparison-mobile-meta-value">{{
                      getRequesterDisplay(comparison)
                    }}</span>
                  </div>
                </div>
                <div class="comparison-mobile-actions">
                  <Button
                    label="並排預覽"
                    icon="pi pi-columns"
                    size="small"
                    outlined
                    :loading="comparePreviewLoading && comparePreviewArchive?.id === comparison.id"
                    @click="openComparePreview(comparison)"
                  />
                  <Button
                    v-if="canTakedownComparisonItem(comparison)"
                    label="下架"
                    icon="pi pi-eye-slash"
                    size="small"
                    severity="secondary"
                    outlined
                    @click="confirmTakedownComparisonItem(comparison)"
                  />
                </div>
              </article>
            </div>
          </div>
        </div>

        <section class="archive-requester-stats mt-4" aria-label="投稿者統計">
          <h4>投稿者統計</h4>
          <div v-if="archiveRequesterStatsLoading" class="text-sm text-500">載入中...</div>
          <Message v-else-if="archiveRequesterStatsError" severity="error" :closable="false">
            {{ archiveRequesterStatsError }}
          </Message>
          <template v-else-if="archiveRequesterStats">
            <div class="archive-requester-stats__identity">
              <div>
                <span>投稿者</span>
                <strong>{{ getRequesterDisplay(selectedArchiveRequest) }}</strong>
              </div>
              <ContributorLevelBadge
                :level="archiveRequesterContributorLevel.level"
                :title="archiveRequesterContributorLevel.name"
                size="compact"
                show-title
              />
              <strong>全部投稿 {{ archiveRequesterStats.total_count }} 筆</strong>
            </div>
            <div class="user-submission-status-cards">
              <div
                v-for="status in archiveRequesterSubmissionStatuses"
                :key="`requester-summary-${status.key}`"
                class="user-submission-status-card"
              >
                <span
                  class="user-submission-status-dot"
                  :style="{ background: status.color }"
                ></span>
                <span>{{ status.label }}</span>
                <strong>{{ status.count }}</strong>
              </div>
            </div>
            <div
              v-if="archiveRequesterStats.total_count > 0"
              class="user-submission-distribution__bar"
              role="img"
              :aria-label="archiveRequesterDistributionLabel"
            >
              <span
                v-for="status in archiveRequesterSubmissionStatuses"
                :key="`requester-bar-${status.key}`"
                :style="{ width: `${status.percentage}%`, background: status.color }"
                :title="`${status.label} ${status.count} 筆（${status.percentage.toFixed(1)}%）`"
              ></span>
            </div>
            <div v-else class="user-insights__empty">此投稿者目前沒有投稿</div>
            <div class="user-submission-distribution__legend">
              <div
                v-for="status in archiveRequesterSubmissionStatuses"
                :key="`requester-legend-${status.key}`"
                class="user-submission-legend-row"
              >
                <span
                  class="user-submission-status-dot"
                  :style="{ background: status.color }"
                ></span>
                <span>{{ status.label }}</span>
                <strong>{{ status.count }} 筆</strong>
                <span>{{ status.percentage.toFixed(1) }}%</span>
              </div>
            </div>
          </template>
        </section>

        <div class="flex justify-end gap-2 mt-4 review-dialog-actions">
          <Button
            class="review-close-action"
            label="關閉"
            icon="pi pi-times"
            aria-label="關閉"
            severity="secondary"
            outlined
            @click="showArchiveRequestDialog = false"
          />
          <Button
            label="預覽 PDF"
            icon="pi pi-eye"
            aria-label="預覽 PDF"
            severity="secondary"
            outlined
            :loading="archiveRequestPreviewLoading"
            @click="previewArchiveRequestFile"
          />
          <Button
            v-if="canEditSelectedArchiveRequest"
            label="儲存修改"
            icon="pi pi-save"
            aria-label="儲存修改"
            :loading="reviewEditLoading"
            @click="saveArchiveRequestEdit"
          />
          <Button
            v-for="action in getReviewRowActions(selectedArchiveRequest)"
            :key="action.key"
            :label="action.label"
            :icon="action.icon"
            :aria-label="action.label"
            :title="action.label"
            :class="[
              'review-action-button',
              {
                'review-action-button--reject': action.key === 'reject',
                'review-action-button--delete': action.key === 'delete',
                'review-action-reject': action.key === 'reject',
                'admin-danger-solid-button': action.key === 'reject',
                'admin-danger-outline-button': action.key === 'delete',
                'review-action-delete': action.key === 'delete',
              },
            ]"
            :severity="action.severity"
            :outlined="action.outlined"
            :text="action.text"
            :disabled="!selectedArchiveRequest"
            @click="runReviewRowAction(selectedArchiveRequest, action.key)"
          />
        </div>
      </Dialog>

      <PdfPreviewModal
        :visible="showArchiveRequestPreview"
        @update:visible="showArchiveRequestPreview = $event"
        :previewUrl="archiveRequestPreviewUrl"
        :title="selectedArchiveRequest?.name || ''"
        :academicYear="formatAcademicTerm(selectedArchiveRequest?.academic_year)"
        :archiveType="selectedArchiveRequest?.archive_type || ''"
        :courseName="selectedArchiveRequest?.subject || ''"
        :professorName="selectedArchiveRequest?.professor || ''"
        :loading="archiveRequestPreviewLoading"
        :error="archiveRequestPreviewError"
        :showDownload="false"
        :showDiscussion="false"
        @hide="closeArchiveRequestPreview"
        @error="handleArchiveRequestPreviewError"
      />

      <Dialog
        v-model:visible="showComparePreview"
        modal
        maximizable
        :draggable="false"
        :style="{ width: 'min(1500px, 96vw)', height: 'min(92vh, 92dvh)' }"
        :contentStyle="{ height: '100%', display: 'flex', flexDirection: 'column' }"
        header="申請考卷與既有考卷比對"
        @hide="closeComparePreview"
      >
        <div v-if="comparePreviewError" class="compare-preview-error">
          <i class="pi pi-exclamation-circle"></i>
          無法載入比對 PDF，請稍後再試。
        </div>
        <div v-else class="compare-preview-grid">
          <section class="compare-preview-pane">
            <header>
              <span>申請考卷</span>
              <strong>{{ selectedArchiveRequest?.name }}</strong>
            </header>
            <iframe
              v-if="compareRequestPreviewUrl"
              :src="compareRequestPreviewUrl"
              title="申請考卷 PDF 預覽"
            ></iframe>
            <ProgressSpinner v-else strokeWidth="4" />
          </section>
          <section class="compare-preview-pane">
            <header>
              <span>既有考卷</span>
              <strong>{{ comparePreviewArchive?.name }}</strong>
            </header>
            <iframe
              v-if="compareArchivePreviewUrl"
              :src="compareArchivePreviewUrl"
              title="既有考卷 PDF 預覽"
            ></iframe>
            <ProgressSpinner v-else strokeWidth="4" />
          </section>
        </div>
      </Dialog>

      <Dialog
        v-model:visible="showContributorLevelSettingsDialog"
        modal
        :draggable="false"
        :closable="!contributorLevelSettingsSaving"
        :closeOnEscape="!contributorLevelSettingsSaving"
        header="投稿等級設定"
        :style="{ width: 'min(860px, 96vw)' }"
        :contentStyle="{ padding: 0, overflow: 'hidden' }"
        @hide="closeContributorLevelSettingsDialog"
      >
        <div class="contributor-level-settings-dialog">
          <p class="contributor-level-settings-help">
            EXP 欄位代表「達到本級所需累積 EXP」。Lv.10 為最高等級，仍保留其累積門檻。
          </p>
          <Message v-if="contributorLevelSettingsError" severity="error" :closable="false">
            {{ contributorLevelSettingsError }}
          </Message>
          <div class="contributor-level-settings-list">
            <article
              v-for="level in contributorLevelSettingsDraft"
              :key="level.level"
              class="contributor-level-settings-row"
            >
              <strong class="contributor-level-settings-number">Lv.{{ level.level }}</strong>
              <ContributorLevelBadge :level="level.level" :title="level.name" size="compact" />
              <label class="contributor-level-settings-field">
                <span>等級名稱</span>
                <InputText v-model="level.name" maxlength="30" class="w-full" />
              </label>
              <label class="contributor-level-settings-field">
                <span>達到本級所需累積 EXP</span>
                <InputNumber
                  v-model="level.minExp"
                  :min="0"
                  :useGrouping="false"
                  :minFractionDigits="0"
                  :maxFractionDigits="0"
                  :disabled="level.level === 1"
                  class="w-full"
                />
              </label>
              <span v-if="level.level === 10" class="contributor-level-settings-max">
                最高等級
              </span>
            </article>
          </div>
        </div>
        <template #footer>
          <div class="contributor-level-settings-footer">
            <Button
              label="還原目前已保存設定"
              severity="secondary"
              text
              :disabled="contributorLevelSettingsSaving"
              @click="resetContributorLevelSettingsDraft"
            />
            <span class="contributor-level-settings-footer-spacer"></span>
            <Button
              label="取消"
              severity="secondary"
              :disabled="contributorLevelSettingsSaving"
              @click="closeContributorLevelSettingsDialog"
            />
            <Button
              label="保存全部設定"
              severity="success"
              :loading="contributorLevelSettingsSaving"
              @click="confirmContributorLevelSettingsSave"
            />
          </div>
        </template>
      </Dialog>

      <Dialog
        v-model:visible="showUserDataStatsDialog"
        modal
        :draggable="false"
        header="使用者資料統計"
        class="submission-typography-dialog user-data-stats-dialog"
        :style="{ width: 'min(760px, 96vw)', maxHeight: '90vh' }"
        :pt="{
          content: { class: 'user-data-stats-dialog__content' },
          footer: { class: 'user-data-stats-dialog__footer' },
        }"
        @hide="closeUserDataStatsDialog"
      >
        <div class="user-submission-dialog">
          <UserOnlineDurationChart
            :userId="selectedUserDataStatsId"
            :active="showUserDataStatsDialog"
          />
          <ProgressSpinner
            v-if="userSubmissionStatsLoading"
            class="w-full flex justify-content-center"
            strokeWidth="4"
          />
          <Message v-else-if="userSubmissionStatsError" severity="error" :closable="false">
            {{ userSubmissionStatsError }}
          </Message>
          <template v-else-if="userSubmissionStats">
            <section class="user-submission-summary" aria-label="使用者投稿摘要">
              <div class="user-submission-summary__identity">
                <div>
                  <span class="user-submission-summary__eyebrow">使用者</span>
                  <h3>{{ userSubmissionStats.name }}</h3>
                </div>
                <ContributorLevelBadge
                  :level="selectedUserContributorLevel.level"
                  :title="selectedUserContributorLevel.name"
                  show-title
                />
              </div>
              <div class="user-submission-summary__exp">
                <strong>{{ userSubmissionStats.contributor_experience }} EXP</strong>
                <span v-if="selectedUserContributorLevel.isMaxLevel">已達最高等級</span>
                <span v-else>
                  距離 Lv.{{ selectedUserContributorLevel.level + 1 }} 還差
                  {{ selectedUserContributorLevel.expToNextLevel }} EXP
                </span>
              </div>
              <div
                class="user-submission-level-progress"
                role="progressbar"
                aria-valuemin="0"
                aria-valuemax="100"
                :aria-valuenow="selectedUserContributorLevel.progressPercent"
                :aria-label="`Lv.${selectedUserContributorLevel.level} 經驗進度 ${selectedUserContributorLevel.progressPercent}%`"
                :style="selectedUserLevelProgressStyle"
              >
                <span :style="{ width: `${selectedUserContributorLevel.progressPercent}%` }"></span>
              </div>
            </section>

            <section class="user-submission-overview" aria-label="投稿狀態總覽">
              <div class="user-submission-total">
                <span>全部投稿</span>
                <strong>{{ userSubmissionStats.total_count }} 筆</strong>
              </div>
              <div class="user-submission-status-cards">
                <div
                  v-for="status in selectedUserSubmissionStatuses"
                  :key="`summary-${status.key}`"
                  class="user-submission-status-card"
                >
                  <span
                    class="user-submission-status-dot"
                    :style="{ background: status.color }"
                  ></span>
                  <span>{{ status.label }}</span>
                  <strong>{{ status.count }}</strong>
                </div>
              </div>
            </section>

            <section class="user-submission-distribution" aria-label="投稿狀態比例">
              <div
                v-if="userSubmissionStats.total_count > 0"
                class="user-submission-distribution__bar"
                role="img"
                :aria-label="selectedUserSubmissionDistributionLabel"
              >
                <span
                  v-for="status in selectedUserSubmissionStatuses"
                  :key="`bar-${status.key}`"
                  :style="{ width: `${status.percentage}%`, background: status.color }"
                  :title="`${status.label} ${status.count} 筆（${status.percentage.toFixed(1)}%）`"
                ></span>
              </div>
              <div v-else class="user-insights__empty">此使用者目前沒有投稿</div>
              <div class="user-submission-distribution__legend">
                <div
                  v-for="status in selectedUserSubmissionStatuses"
                  :key="`legend-${status.key}`"
                  class="user-submission-legend-row"
                >
                  <span
                    class="user-submission-status-dot"
                    :style="{ background: status.color }"
                  ></span>
                  <span>{{ status.label }}</span>
                  <strong>{{ status.count }} 筆</strong>
                  <span>{{ status.percentage.toFixed(1) }}%</span>
                </div>
              </div>
            </section>

            <section
              class="user-submission-records"
              aria-labelledby="user-submission-records-title"
            >
              <div class="user-submission-records__heading">
                <div>
                  <h4 id="user-submission-records-title">此帳號投稿紀錄</h4>
                  <span v-if="normalizedUserSubmissionRecordSearch">
                    符合 {{ filteredUserSubmissionRecords.length }} 筆／共
                    {{ userSubmissionStats.records_total }} 筆
                  </span>
                  <span v-else>共 {{ userSubmissionStats.records_total }} 筆</span>
                </div>
                <div class="user-submission-records__search relative">
                  <i class="pi pi-search search-icon" aria-hidden="true"></i>
                  <InputText
                    id="user-submission-record-search"
                    v-model="userSubmissionRecordSearch"
                    placeholder="搜尋投稿紀錄……"
                    aria-label="搜尋此帳號投稿紀錄"
                    class="w-full pl-6"
                  />
                </div>
              </div>
              <div v-if="paginatedUserSubmissionRecords.length" class="user-submission-record-list">
                <article
                  v-for="record in paginatedUserSubmissionRecords"
                  :key="`user-submission-record-${record.id}`"
                  class="user-submission-record"
                >
                  <header class="user-submission-record__header">
                    <div>
                      <Tag
                        :class="[
                          'soft-badge',
                          'review-status-chip',
                          getSubmissionStatusClass(record.status),
                        ]"
                        :severity="getSubmissionSeverity(record.status)"
                      >
                        {{ getUserSubmissionStatusLabel(record.status) }}
                      </Tag>
                      <span class="user-submission-record__kind">
                        {{ getArchiveSubmissionKind(record) }}
                      </span>
                    </div>
                    <strong>投稿編號：#{{ record.id }}</strong>
                  </header>
                  <div class="user-submission-record__title">
                    <strong>{{ record.course_name || '—' }}</strong>
                    <span>{{ record.exam_name || '—' }}</span>
                  </div>
                  <div class="user-submission-record__meta">
                    <span>學期：{{ formatAcademicTerm(record.academic_year) || '—' }}</span>
                    <span>授課教師：{{ record.professor || '—' }}</span>
                    <span>投稿時間：{{ formatDateTime(record.submitted_at) }}</span>
                    <span>
                      審核時間：{{
                        record.reviewed_at ? formatDateTime(record.reviewed_at) : '尚未審核'
                      }}
                    </span>
                  </div>
                  <div class="user-submission-record__comment">
                    <strong>審核留言</strong>
                    <span>{{ record.review_comment?.trim() || '尚無審核留言' }}</span>
                  </div>
                </article>
              </div>
              <div v-else class="user-insights__empty">
                {{
                  normalizedUserSubmissionRecordSearch
                    ? '找不到符合搜尋條件的投稿紀錄。'
                    : '此帳號目前沒有投稿紀錄'
                }}
              </div>
              <Paginator
                v-if="filteredUserSubmissionRecords.length > userSubmissionRecordRows"
                :first="userSubmissionRecordFirst"
                :rows="userSubmissionRecordRows"
                :totalRecords="filteredUserSubmissionRecords.length"
                :rowsPerPageOptions="[10, 20, 50]"
                template="FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink RowsPerPageDropdown CurrentPageReport"
                currentPageReportTemplate="第 {currentPage} / {totalPages} 頁，共 {totalRecords} 筆"
                aria-label="此帳號投稿紀錄分頁"
                class="user-submission-records__paginator"
                @page="handleUserSubmissionRecordPage"
              />
            </section>
          </template>
        </div>
        <template #footer>
          <Button
            class="user-data-stats-dialog__close"
            label="關閉"
            severity="secondary"
            @click="closeUserDataStatsDialog"
          />
        </template>
      </Dialog>

      <Dialog
        :visible="showUserDialog"
        @update:visible="showUserDialog = $event"
        :modal="true"
        :draggable="false"
        :closeOnEscape="false"
        :header="editingUser ? '編輯使用者' : '新增使用者'"
        :style="{ width: '450px', maxWidth: '90vw' }"
        :autoFocus="false"
      >
        <div class="flex flex-column gap-4">
          <div class="flex flex-column gap-2">
            <label>使用者名稱</label>
            <InputText
              id="admin-user-name"
              name="admin-user-name"
              v-model="userForm.name"
              placeholder="輸入使用者名稱"
              class="w-full"
              :class="{ 'p-invalid': userFormErrors.name }"
            />
            <small v-if="userFormErrors.name" class="p-error">
              {{ userFormErrors.name }}
            </small>
          </div>

          <div class="flex flex-column gap-2">
            <label>電子郵件</label>
            <InputText
              id="admin-user-email"
              name="admin-user-email"
              v-model="userForm.email"
              placeholder="輸入電子郵件"
              class="w-full"
              :class="{ 'p-invalid': userFormErrors.email }"
            />
            <small v-if="userFormErrors.email" class="p-error">
              {{ userFormErrors.email }}
            </small>
          </div>

          <div v-if="!editingUser" class="flex flex-column gap-2">
            <label>密碼</label>
            <Password
              inputId="admin-user-password"
              name="admin-user-password"
              v-model="userForm.password"
              placeholder="輸入密碼"
              class="w-full"
              inputClass="w-full"
              :class="{ 'p-invalid': userFormErrors.password }"
              toggleMask
              :feedback="false"
            />
            <small v-if="userFormErrors.password" class="p-error">
              {{ userFormErrors.password }}
            </small>
          </div>

          <div class="flex align-items-center gap-2">
            <Checkbox
              inputId="admin-user-is-admin"
              name="admin-user-is-admin"
              v-model="userForm.is_admin"
              :binary="true"
            />
            <label for="admin-user-is-admin">管理員權限</label>
          </div>
        </div>

        <div class="flex pt-6 justify-end gap-2.5">
          <Button label="取消" icon="pi pi-times" severity="secondary" @click="closeUserDialog" />
          <Button
            :label="editingUser ? '更新' : '新增'"
            :icon="editingUser ? 'pi pi-check' : 'pi pi-plus'"
            severity="success"
            @click="saveUser"
            :loading="userSaveLoading"
          />
        </div>
      </Dialog>

      <Dialog
        :visible="showResetPasswordDialog"
        @update:visible="showResetPasswordDialog = $event"
        @hide="closeResetPasswordDialog"
        :modal="true"
        :draggable="false"
        :closeOnEscape="false"
        header="重設密碼"
        :style="{ width: '460px', maxWidth: '92vw' }"
        :autoFocus="false"
      >
        <div class="flex flex-column gap-3">
          <div class="flex flex-column gap-1">
            <label class="font-semibold">使用者</label>
            <div class="text-sm">
              {{ getResetPasswordTargetLabel(resetPasswordUser) }}
              <span v-if="resetPasswordUser?.email" class="text-500"
                >（{{ resetPasswordUser.email }}）</span
              >
            </div>
          </div>

          <div class="flex flex-column gap-2">
            <label>新密碼</label>
            <Password
              inputId="admin-reset-new-password"
              name="admin-reset-new-password"
              v-model="resetPasswordForm.newPassword"
              placeholder="輸入新密碼"
              class="w-full"
              inputClass="w-full"
              :class="{ 'p-invalid': resetPasswordFormErrors.newPassword }"
              toggleMask
              :feedback="false"
              :maxlength="128"
            />
            <small v-if="resetPasswordFormErrors.newPassword" class="p-error">
              {{ resetPasswordFormErrors.newPassword }}
            </small>
          </div>

          <div class="flex flex-column gap-2">
            <label>確認新密碼</label>
            <Password
              inputId="admin-reset-confirm-password"
              name="admin-reset-confirm-password"
              v-model="resetPasswordForm.confirmPassword"
              placeholder="再次輸入新密碼"
              class="w-full"
              inputClass="w-full"
              :class="{ 'p-invalid': resetPasswordFormErrors.confirmPassword }"
              toggleMask
              :feedback="false"
              :maxlength="128"
            />
            <small v-if="resetPasswordFormErrors.confirmPassword" class="p-error">
              {{ resetPasswordFormErrors.confirmPassword }}
            </small>
          </div>
        </div>

        <div class="flex pt-6 justify-end gap-2.5">
          <Button
            label="取消"
            icon="pi pi-times"
            severity="secondary"
            @click="closeResetPasswordDialog"
          />
          <Button
            label="確認重設"
            icon="pi pi-key"
            severity="success"
            @click="resetPassword"
            :loading="resetPasswordLoading"
          />
        </div>
      </Dialog>
      <Dialog
        :visible="showNotificationDialog"
        @update:visible="showNotificationDialog = $event"
        :modal="true"
        :draggable="false"
        :closeOnEscape="false"
        :header="editingNotification ? '編輯公告' : '新增公告'"
        :style="{ width: '540px', maxWidth: '92vw' }"
        :autoFocus="false"
      >
        <div class="flex flex-column gap-4">
          <div class="flex flex-column gap-2">
            <label>標題</label>
            <InputText
              id="admin-notification-title"
              name="admin-notification-title"
              v-model="notificationForm.title"
              placeholder="輸入公告標題"
              class="w-full"
              :class="{ 'p-invalid': notificationFormErrors.title }"
            />
            <small v-if="notificationFormErrors.title" class="p-error">
              {{ notificationFormErrors.title }}
            </small>
          </div>

          <div class="flex flex-column md:flex-row gap-3">
            <div class="flex-1 flex flex-column gap-2">
              <label>重要程度</label>
              <Select
                inputId="admin-notification-severity"
                name="admin-notification-severity"
                v-model="notificationForm.severity"
                :options="notificationSeverityOptions"
                optionLabel="label"
                optionValue="value"
                placeholder="選擇重要程度"
                class="w-full"
              />
            </div>
            <div class="flex align-items-center gap-2 mt-3 md:mt-5">
              <ToggleSwitch
                inputId="admin-notification-is-active"
                name="admin-notification-is-active"
                v-model="notificationForm.is_active"
              />
              <label for="admin-notification-is-active" class="m-0 font-medium">啟用公告</label>
            </div>
          </div>

          <div class="flex flex-column gap-2">
            <label>內容</label>
            <Textarea
              id="admin-notification-body"
              name="admin-notification-body"
              v-model="notificationForm.body"
              rows="6"
              autoResize
              class="w-full"
              placeholder="輸入公告內容"
              :class="{ 'p-invalid': notificationFormErrors.body }"
            />
            <small v-if="notificationFormErrors.body" class="p-error">
              {{ notificationFormErrors.body }}
            </small>
          </div>

          <div class="flex flex-column gap-3">
            <div class="flex flex-column gap-2">
              <label>生效時間 (選填)</label>
              <DatePicker
                inputId="admin-notification-starts-at"
                name="admin-notification-starts-at"
                v-model="notificationForm.starts_at"
                showTime
                hourFormat="24"
                :showIcon="true"
                placeholder="選擇生效時間"
                class="w-full"
              />
            </div>
            <div class="flex flex-column gap-2">
              <label>結束時間 (選填)</label>
              <DatePicker
                inputId="admin-notification-ends-at"
                name="admin-notification-ends-at"
                v-model="notificationForm.ends_at"
                showTime
                hourFormat="24"
                :showIcon="true"
                placeholder="選擇結束時間"
                class="w-full"
                :class="{ 'p-invalid': notificationFormErrors.ends_at }"
              />
              <small v-if="notificationFormErrors.ends_at" class="p-error">
                {{ notificationFormErrors.ends_at }}
              </small>
            </div>
          </div>
        </div>

        <div class="flex pt-6 justify-end gap-2.5">
          <Button
            label="取消"
            icon="pi pi-times"
            severity="secondary"
            @click="closeNotificationDialog"
          />
          <Button
            :label="editingNotification ? '更新' : '新增'"
            :icon="editingNotification ? 'pi pi-check' : 'pi pi-plus'"
            severity="success"
            @click="saveNotification"
            :loading="notificationSaveLoading"
          />
        </div>
      </Dialog>

      <Dialog
        v-model:visible="showTrashDependencyHelpDialog"
        :modal="true"
        :draggable="false"
        :closeOnEscape="true"
        header="如何閱讀「依賴與阻擋」"
        :style="{ width: '44rem', maxWidth: '92vw' }"
      >
        <div class="trash-dependency-help">
          <p class="trash-dependency-help-intro">
            這一欄會告訴你：能不能還原、能不能永久刪除，以及哪些資料會一起處理。
          </p>

          <section class="trash-dependency-help-section">
            <h4 class="trash-dependency-help-title">快速判斷</h4>
            <div class="trash-dependency-help-label-grid">
              <article class="trash-dependency-help-label-card">
                <span
                  class="soft-badge trash-dependency-help-chip trash-dependency-chip--restore-blocked"
                  >阻擋還原</span
                >
                <p>現在不能還原。通常要先復原父層，或必要關聯已不存在。</p>
              </article>
              <article class="trash-dependency-help-label-card">
                <span
                  class="soft-badge trash-dependency-help-chip trash-dependency-chip--delete-blocked"
                  >阻擋永久刪除</span
                >
                <p>現在不能永久刪除。通常仍有啟用中的資料依附。</p>
              </article>
              <article class="trash-dependency-help-label-card">
                <span class="soft-badge trash-dependency-help-chip trash-dependency-chip--cascade"
                  >一併永久刪除</span
                >
                <p>刪除此項時，列出的資料會一起永久刪除。</p>
              </article>
              <article class="trash-dependency-help-label-card">
                <span class="soft-badge trash-dependency-help-chip trash-dependency-chip--relation"
                  >關聯</span
                >
                <p>只是提醒資料有關，通常不會直接阻擋。</p>
              </article>
              <article class="trash-dependency-help-label-card">
                <span class="soft-badge trash-dependency-help-chip trash-dependency-chip--clear"
                  >無阻擋</span
                >
                <p>目前沒有影響還原或永久刪除的限制。</p>
              </article>
            </div>
          </section>

          <section class="trash-dependency-help-section">
            <h4 class="trash-dependency-help-title">按鈕規則</h4>
            <div class="trash-dependency-help-rule-list">
              <p><span aria-hidden="true">-</span> 有「阻擋還原」 → 不顯示還原。</p>
              <p><span aria-hidden="true">-</span> 有「阻擋永久刪除」 → 不顯示永久刪除。</p>
              <p>
                <span aria-hidden="true">-</span> 只有「一併永久刪除」或「關聯」 →
                按鈕不會自動隱藏。
              </p>
            </div>
          </section>

          <section class="trash-dependency-help-section">
            <h4 class="trash-dependency-help-title">縮排怎麼看</h4>
            <div class="trash-dependency-help-rule-list">
              <p><span aria-hidden="true">-</span> 只有「已在垃圾桶」的項目會出現在縮排中。</p>
              <p>
                <span aria-hidden="true">-</span>
                只是暫時下架的投稿，仍留在審核中心，不會出現在垃圾桶縮排。
              </p>
            </div>
            <p class="trash-dependency-help-note">
              縮排只代表目前垃圾桶中的父子關係，不代表所有歷史關聯都會出現。
            </p>
          </section>

          <section class="trash-dependency-help-section">
            <h4 class="trash-dependency-help-title">兩種常見流程</h4>
            <div class="trash-dependency-help-flow-grid">
              <article class="trash-dependency-help-flow-card">
                <h5>先刪投稿，再刪課程 / 分類</h5>
                <div
                  class="trash-dependency-help-flow"
                  aria-label="課程分類 到 課程 到 考古題投稿 到 考古題"
                >
                  <span>課程分類</span>
                  <i aria-hidden="true">→</i>
                  <span>課程</span>
                  <i aria-hidden="true">→</i>
                  <span>考古題投稿</span>
                  <i aria-hidden="true">→</i>
                  <span>考古題</span>
                </div>
                <p>
                  投稿已從審核中心按「刪除」，所以投稿本身也是垃圾桶項目。關聯考古題會列在投稿底下。
                </p>
              </article>
              <article class="trash-dependency-help-flow-card">
                <h5>直接刪課程 / 分類</h5>
                <div class="trash-dependency-help-flow" aria-label="課程分類 到 課程 到 考古題">
                  <span>課程分類</span>
                  <i aria-hidden="true">→</i>
                  <span>課程</span>
                  <i aria-hidden="true">→</i>
                  <span>考古題</span>
                </div>
                <p>投稿只是因原課程刪除而暫時下架，仍留在審核中心，所以不會出現在垃圾桶縮排。</p>
                <div class="trash-dependency-help-note">
                  <p>若之後永久刪除此課程，底下考古題會一併永久刪除。</p>
                  <p>相關投稿會進入垃圾桶並標示無法復原。</p>
                  <p>因父層課程與考古題已不存在，投稿會以獨立項目顯示。</p>
                </div>
              </article>
            </div>
          </section>

          <section class="trash-dependency-help-section">
            <h4 class="trash-dependency-help-title">考古題與投稿</h4>
            <div class="trash-dependency-help-rule-list">
              <p>
                <span aria-hidden="true">-</span> 刪除投稿：投稿進垃圾桶，關聯考古題也會被帶入。
              </p>
              <p>
                <span aria-hidden="true">-</span>
                刪除考古題：考古題進垃圾桶，相關投稿通常只會暫時下架。
              </p>
              <p><span aria-hidden="true">-</span> 考古題顯示在投稿底下時，通常要先還原投稿。</p>
            </div>
          </section>

          <section class="trash-dependency-help-section">
            <h4 class="trash-dependency-help-title">課程、分類與留言</h4>
            <div class="trash-dependency-help-rule-list">
              <p>
                <span aria-hidden="true">-</span>
                刪除課程：課程與下轄考古題會進垃圾桶，相關投稿會暫時下架。
              </p>
              <p>
                <span aria-hidden="true">-</span>
                復原課程：只復原因課程刪除而進垃圾桶的考古題；因刪投稿而進垃圾桶的考古題仍需還原投稿。
              </p>
              <p><span aria-hidden="true">-</span> 復原分類：只復原分類本身，不會自動復原課程。</p>
              <p>
                <span aria-hidden="true">-</span>
                留言：不再阻擋考古題永久刪除，會隨考古題一併永久刪除。
              </p>
            </div>
          </section>
        </div>
      </Dialog>
    </div>
  </div>
</template>

<script setup>
defineOptions({
  name: 'AdminView',
})

import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { useConfirm } from 'primevue/useconfirm'
import { useToast } from 'primevue/usetoast'
import { getCurrentUser } from '../utils/auth'
import { isUnauthorizedError } from '../utils/http'
import { formatRelativeOrAbsoluteDateTime } from '../utils/time'
import {
  PRODUCT_TIME_ZONE,
  PRODUCT_TIME_ZONE_LABEL,
  formatProductDateTime,
} from '../utils/productTimezone'
import { buildTemporalTicks, resolveTemporalTickLayout } from '../utils/temporalChart'
import {
  getCourses,
  createCourse,
  updateCourse,
  reorderCourses,
  deleteCourse,
  getUsers,
  getOnlineStatistics,
  getUserSubmissionStats,
  createUser,
  updateUser,
  deleteUser,
  resetUserPassword,
  notificationService,
  courseService,
  archiveService,
} from '../api'
import { trackEvent, EVENTS } from '../utils/analytics'
import { STORAGE_KEYS, getLocalItem, setLocalItem } from '../utils/storage'
import { formatCourseDisplayName, normalizeCourseSearchText } from '../utils/courseText'
import { ADMIN_PAGE_SIZE_OPTIONS } from '../constants/pagination'
import PdfPreviewModal from '../components/PdfPreviewModal.vue'
import ContributorLevelBadge from '../components/ContributorLevelBadge.vue'
import UserOnlineDurationChart from '../components/UserOnlineDurationChart.vue'
import ReportManagementPanel from '../components/admin/ReportManagementPanel.vue'
import {
  SUBMISSION_LEVELS,
  getContributorLevelPalette,
  getContributorLevelSettingsSnapshot,
  loadContributorLevelSettings,
  resolveSubmissionLevel,
  saveContributorLevelSettings,
  validateContributorLevelSettings,
} from '../utils/submissionLevel'

const confirm = useConfirm()
const toast = useToast()

const courses = ref([])
const coursesLoading = ref(false)
const courseLoadError = ref('')
const searchQuery = ref('')
const filterCategory = ref(null)
const courseOrderLoading = ref(false)
const courseFirst = ref(0)
const courseRows = ref(10)

const showCourseDialog = ref(false)
const editingCourse = ref(null)
const saveLoading = ref(false)
const showCategoryDialog = ref(false)
const editingCategory = ref(null)
const categorySaveLoading = ref(false)
const categoryOrderLoading = ref(false)

const courseForm = ref({
  name: '',
  category: '',
})

const courseFormErrors = ref({})
const categoryForm = ref({
  key: '',
  name: '',
  label: '',
  icon: 'pi pi-fw pi-book',
  badge_color: 'slate',
})
const categoryFormErrors = ref({})
const DEFAULT_CATEGORY_BADGE_COLOR = 'slate'
const categoryBadgeColorOptions = [
  { label: '深藍', value: 'navy' },
  { label: '青綠', value: 'teal' },
  { label: '森綠', value: 'forest' },
  { label: '琥珀', value: 'amber' },
  { label: '酒紅', value: 'burgundy' },
  { label: '紫色', value: 'violet' },
  { label: '灰色', value: 'slate' },
  { label: '靛藍', value: 'indigo' },
]
const categoryBadgeColorValues = new Set(categoryBadgeColorOptions.map((option) => option.value))
const legacyCategoryBadgeColorMap = {
  blue: 'navy',
  green: 'forest',
  purple: 'violet',
  rose: 'burgundy',
  gray: 'slate',
}
const users = ref([])
const usersLoading = ref(false)
const userStatsLoadError = ref('')
const userSearchQuery = ref('')
const filterUserType = ref(null)
const selectedContributorLevels = ref([])
const isLevelStatsExpanded = ref(false)
const showContributorLevelSettingsDialog = ref(false)
const contributorLevelSettingsDraft = ref([])
const contributorLevelSettingsError = ref('')
const contributorLevelSettingsSaving = ref(false)
const userFirst = ref(0)
const userRows = ref(10)
const LOGIN_HOUR_RANGE_OPTIONS = [24, 48, 72]
const LOGIN_DATE_RANGE_OPTIONS = [7, 30, 90]
const LOGIN_HOUR_BUCKET_CONFIG = {
  24: { bucketMinutes: 10, bucketCount: 144, labelEvery: 12 },
  48: { bucketMinutes: 20, bucketCount: 144, labelEvery: 18 },
  72: { bucketMinutes: 30, bucketCount: 144, labelEvery: 18 },
}
const LOGIN_DATE_BUCKET_CONFIG = {
  7: { bucketMinutes: 4 * 60, bucketCount: 42, labelEvery: 6 },
  30: { bucketMinutes: 12 * 60, bucketCount: 60, labelEvery: 10 },
  90: { bucketMinutes: 24 * 60, bucketCount: 90, labelEvery: 15 },
}
const userInsightsView = ref('login-hour')
const isUserChartsExpanded = ref(false)
const loginRangeHours = ref(24)
const loginRangeDays = ref(30)
const onlineStatistics = ref(null)
const onlineStatisticsLoading = ref(false)
const onlineStatisticsError = ref('')
const userStatisticsChartElement = ref(null)
const reviewSubmissionChartElement = ref(null)
const userStatisticsChartWidth = ref(Number.POSITIVE_INFINITY)
const reviewSubmissionChartWidth = ref(Number.POSITIVE_INFINITY)
const statisticsFontScale = ref(1)
let statisticsChartResizeObserver = null
let statisticsFontScaleObserver = null
let onlineStatisticsRequestId = 0
let loginStatsRefreshTimer = null
const showUserDataStatsDialog = ref(false)
const selectedUserDataStatsId = ref(null)
const userSubmissionStatsLoading = ref(false)
const userSubmissionStatsError = ref('')
const userSubmissionStats = ref(null)
const userSubmissionRecordSearch = ref('')
const userSubmissionRecordFirst = ref(0)
const userSubmissionRecordRows = ref(10)
let userSubmissionStatsController = null
const archiveRequesterStats = ref(null)
const archiveRequesterStatsLoading = ref(false)
const archiveRequesterStatsError = ref('')
let archiveRequesterStatsController = null

const USER_SUBMISSION_STATUS_CONFIG = [
  { key: 'pending', label: '待審核', color: '#b7791f' },
  { key: 'approved', label: '已通過', color: '#2f855a' },
  { key: 'rejected', label: '未通過', color: '#c2414d' },
  { key: 'takedown', label: '已下架', color: '#64748b' },
  { key: 'deleted', label: '已刪除', color: '#8c2f46' },
]

const getUserSubmissionStatusLabel = (status) => {
  const normalized = String(status || '').toLowerCase()
  return USER_SUBMISSION_STATUS_CONFIG.find((item) => item.key === normalized)?.label || '未知狀態'
}

const userSortMeta = ref([
  { field: 'is_admin', order: -1 },
  { field: 'name', order: 1 },
])
const USER_PASSWORD_MIN_LENGTH = 8
const NON_LOCAL_PASSWORD_RESET_HINT = '此帳號不是本地帳號，無法由系統重設密碼。'

const getResetPasswordTargetLabel = (user) => {
  return user?.name || user?.email || '該使用者'
}

const getOnlineStatusLabel = (user) => {
  if (user?.online_status_label) {
    return user.online_status_label
  }

  if (user?.is_online === true) {
    return '在線'
  }

  if (!user || !user.last_login_at) {
    return '從未登入'
  }

  return '離線'
}

const getOnlineStatusDotClass = (user) => {
  return user?.is_online ? 'user-online-dot--online' : 'user-online-dot--offline'
}

const showUserDialog = ref(false)
const editingUser = ref(null)
const userSaveLoading = ref(false)

const showResetPasswordDialog = ref(false)
const resetPasswordUser = ref(null)
const resetPasswordLoading = ref(false)
const resetPasswordForm = ref({
  newPassword: '',
  confirmPassword: '',
})
const resetPasswordFormErrors = ref({})

const userForm = ref({
  name: '',
  email: '',
  password: '',
  is_admin: false,
})

const userFormErrors = ref({})

const notifications = ref([])
const notificationsLoading = ref(false)
const notificationSearchQuery = ref('')
const notificationSeverityFilter = ref(null)
const notificationFirst = ref(0)
const notificationRows = ref(10)

const notificationSortMeta = ref([
  { field: 'is_active', order: -1 },
  { field: 'effectiveOrder', order: -1 },
  { field: 'updated_at', order: -1 },
])

const notificationSeverityOptions = [
  { label: '一般', value: 'info' },
  { label: '重要', value: 'danger' },
]

const notificationSeverityFilterOptions = notificationSeverityOptions

const showNotificationDialog = ref(false)
const editingNotification = ref(null)
const notificationSaveLoading = ref(false)
const notificationForm = ref({
  title: '',
  body: '',
  severity: 'info',
  is_active: true,
  starts_at: null,
  ends_at: null,
})
const notificationFormErrors = ref({})
const reviewLoading = ref(false)
const reviewLoadError = ref('')
const reviewSubmissionView = ref('time')
const isReviewSubmissionChartExpanded = ref(false)
const reviewSubmissionRangeHours = ref(24)
const reviewSubmissionRangeDays = ref(30)
const reviewSubmissionStatistics = ref(null)
const reviewSubmissionStatisticsLoading = ref(false)
const reviewSubmissionStatisticsError = ref('')
let reviewSubmissionStatisticsRequestId = 0
const reviewSearchQuery = ref('')
const reviewStatusFilter = ref(null)
const newSubmissionFirst = ref(0)
const newSubmissionRows = ref(10)
const existingSubmissionFirst = ref(0)
const existingSubmissionRows = ref(10)
const archiveRequests = ref([])
const trashLoading = ref(false)
const trashItems = ref([])
const showTrashRelationHierarchy = ref(true)
const TRASH_FILTER_ALL_VALUE = 'all'
const trashFilterType = ref(null)
const trashPage = ref(1)
const trashRowsPerPage = ref(10)
const courseCategories = ref([])
const reviewEditLoading = ref(false)
const showArchiveRequestDialog = ref(false)
const selectedArchiveRequest = ref(null)
const comparisonArchives = ref([])
const comparisonLoading = ref(false)
const showArchiveRequestPreview = ref(false)
const archiveRequestPreviewUrl = ref('')
const archiveRequestPreviewLoading = ref(false)
const archiveRequestPreviewError = ref(false)
const showComparePreview = ref(false)
const comparePreviewArchive = ref(null)
const compareRequestPreviewUrl = ref('')
const compareArchivePreviewUrl = ref('')
const comparePreviewLoading = ref(false)
const comparePreviewError = ref(false)
const archiveRequestEditForm = ref({
  subject: '',
  category: '',
  name: '',
  academic_year: null,
  archive_type: '',
  professor: '',
  has_answers: false,
  requested_course_name: '',
  requested_category_key: '',
  requested_category_name: '',
  requested_category_label: '',
  requested_category_icon: '',
})
const archiveTypeOptions = [
  { name: '期中考', value: 'midterm' },
  { name: '期末考', value: 'final' },
  { name: '小考', value: 'quiz' },
  { name: '其他', value: 'other' },
]

const currentUserId = computed(() => getCurrentUser()?.id)
const submissionStatusPriority = {
  pending: 1,
  approved: 2,
  rejected: 3,
  takedown: 4,
  deleted: 5,
}
const reviewStatusOptions = [
  { name: '待審核', value: 'pending' },
  { name: '已通過', value: 'approved' },
  { name: '已退回', value: 'rejected' },
  { name: '已下架', value: 'takedown' },
  { name: '已刪除', value: 'deleted' },
]
const reviewStatusFilterValues = new Set(reviewStatusOptions.map((option) => option.value))
const trashFilterOptions = [
  { label: '考古題', value: 'archive' },
  { label: '考古題投稿', value: 'archive_submission' },
  { label: '課程分類', value: 'course_category' },
  { label: '課程', value: 'course' },
  { label: '公告', value: 'notification' },
  { label: '使用者', value: 'user' },
  { label: '系統問題回報', value: 'system_issue_report' },
  { label: '留言回報', value: 'comment_report' },
  { label: '考古題回報', value: 'archive_report' },
]
const trashTypeLabels = trashFilterOptions.reduce((acc, option) => {
  if (option.value) acc[option.value] = option.label
  return acc
}, {})
const getTrashTypeLabel = (itemType) => trashTypeLabels[itemType] || itemType || '未知'
const isTrashAllFilter = (value) => !value || value === TRASH_FILTER_ALL_VALUE
const getReviewSortDirectionIcon = (direction) =>
  direction === 'asc' ? 'pi pi-sort-amount-up-alt' : 'pi pi-sort-amount-down'
const getReviewSortNeutralIcon = () => 'pi pi-sort-alt'
const getTrashDeletedTimestamp = (item) => {
  const time = new Date(item?.deleted_at || 0).getTime()
  return Number.isNaN(time) ? 0 : time
}
const submissionStatusAliases = {
  pending: 'pending',
  approved: 'approved',
  rejected: 'rejected',
  takedown: 'takedown',
  deleted: 'deleted',
  待審核: 'pending',
  已通過: 'approved',
  已退回: 'rejected',
  未通過: 'rejected',
  已下架: 'takedown',
  已刪除: 'deleted',
}
const reviewSortState = ref({
  new: { key: 'status', direction: 'asc' },
  existing: { key: 'status', direction: 'asc' },
})
const trashSortState = ref({
  key: null,
  direction: 'asc',
})
const showTrashDependencyHelpDialog = ref(false)
const normalizeSubmissionStatus = (status) => {
  const raw = String(status || '').trim()
  const normalized = raw.toLowerCase()
  return submissionStatusAliases[normalized] || submissionStatusAliases[raw] || normalized
}
const getReviewItemStatus = (item) => {
  if (item?.deletedAt || item?.deleted_at) return 'deleted'
  return normalizeSubmissionStatus(item?.status)
}
const getReviewStatusFilterValue = (status) => {
  const raw = String(status || '').trim()
  if (!raw) return ''

  const normalized = normalizeSubmissionStatus(raw)
  return reviewStatusFilterValues.has(normalized) ? normalized : ''
}
const isReadonlyReviewSubmission = (item) => {
  return ['takedown', 'deleted'].includes(getReviewItemStatus(item))
}
const getReadonlyReviewSubmissionMessage = (item) => {
  const status = getReviewItemStatus(item)
  if (status === 'takedown') return '此投稿已下架，僅能查看，不能再編輯內容。'
  if (status === 'deleted') return '此投稿已刪除，僅能查看，請至垃圾桶處理復原或永久刪除。'
  return ''
}
const canEditSelectedArchiveRequest = computed(() => {
  return (
    Boolean(selectedArchiveRequest.value) &&
    !isReadonlyReviewSubmission(selectedArchiveRequest.value)
  )
})
const archiveRequestReadonlyMessage = computed(() => {
  return getReadonlyReviewSubmissionMessage(selectedArchiveRequest.value)
})
const getReviewItemStatusPriority = (item) => {
  return submissionStatusPriority[getReviewItemStatus(item)] || 99
}
const getReviewSubmissionTimeValue = (item) => {
  const value =
    item?.submittedAt ??
    item?.submitted_at ??
    item?.createdAt ??
    item?.created_at ??
    item?.uploadedAt ??
    item?.uploaded_at
  if (!value) return null
  if (typeof value === 'object') {
    return value.raw ?? value.value ?? value.date ?? value.display ?? value.label ?? null
  }
  return value
}
const getReviewTimestamp = (item) => {
  const timeValue = getReviewSubmissionTimeValue(item)
  if (!timeValue) return 0
  const time = new Date(timeValue).getTime()
  return Number.isNaN(time) ? 0 : time
}
const formatReviewSubmissionTime = (item) => {
  const value = getReviewSubmissionTimeValue(item)
  if (!value) return '—'
  if (typeof value === 'object') {
    return value.display || value.label || '—'
  }
  return formatRelativeOrAbsoluteDateTime(value)
}
const getReviewRequesterLabel = (item) => {
  return item?.requester_name || item?.requester_email || '—'
}
const formatReviewReviewer = (item) => {
  return (
    item?.reviewer_name || item?.reviewerName || item?.reviewer_username || item?.reviewer_id || '—'
  )
}
const getReviewReviewedAt = (item) => {
  return item?.reviewed_at || item?.reviewedAt || item?.status_changed_at || null
}
const getReviewReviewerDisplay = (item) => {
  if (!getReviewReviewedAt(item)) return '尚未審核'
  return formatReviewReviewer(item)
}
const formatReviewReviewedTime = (item) => {
  const value = getReviewReviewedAt(item)
  return formatRelativeOrAbsoluteDateTime(value)
}
const getReviewMobileCourseName = (item) => {
  return item?.requested_course_name || item?.requestedCourseName || item?.subject || '—'
}
const getReviewSortValue = (item, key) => {
  if (key === 'status') return getReviewItemStatusPriority(item)
  if (key === 'submitted_at') return getReviewTimestamp(item)
  if (key === 'reviewed_at') {
    const value = getReviewReviewedAt(item)
    if (!value) return null
    const time = new Date(value).getTime()
    return Number.isNaN(time) ? null : time
  }
  if (key === 'academic_year') return Number(item.academic_year) || null
  if (key === 'kind') return getArchiveSubmissionKind(item)
  return String(item?.[key] || '').trim()
}
const isMissingReviewSortValue = (value, key) => {
  return value === null || value === undefined || value === '' || (key === 'status' && value >= 99)
}
const compareReviewSortValues = (a, b, key, direction) => {
  const aValue = getReviewSortValue(a, key)
  const bValue = getReviewSortValue(b, key)
  const aMissing = isMissingReviewSortValue(aValue, key)
  const bMissing = isMissingReviewSortValue(bValue, key)
  if (aMissing && bMissing) return 0
  if (aMissing) return 1
  if (bMissing) return -1
  const directionFactor = direction === 'desc' ? -1 : 1
  if (typeof aValue === 'number' && typeof bValue === 'number') {
    return (aValue - bValue) * directionFactor
  }
  return String(aValue).localeCompare(String(bValue), 'zh-TW') * directionFactor
}
const sortArchiveReviewItems = (items, section) => {
  const { key, direction } = reviewSortState.value[section]
  return [...items].sort((a, b) => {
    const primaryDiff = compareReviewSortValues(a, b, key, direction)
    if (primaryDiff !== 0) return primaryDiff
    if (key === 'submitted_at' || key === 'reviewed_at') {
      const idDiff = (Number(a?.id) || 0) - (Number(b?.id) || 0)
      return direction === 'desc' ? -idDiff : idDiff
    }
    const statusDiff = getReviewItemStatusPriority(a) - getReviewItemStatusPriority(b)
    if (statusDiff !== 0) return statusDiff
    const timeDiff = getReviewTimestamp(b) - getReviewTimestamp(a)
    if (timeDiff !== 0) return timeDiff
    return (Number(b?.id) || 0) - (Number(a?.id) || 0)
  })
}

const normalizeReviewSearchText = (value) => normalizeCourseSearchText(value)

const getReviewSearchHaystack = (item) => {
  const fields = [
    item?.id,
    item?.id ? `#${item.id}` : '',
    item?.name,
    item?.subject,
    item?.course_name,
    item?.course_code,
    item?.category,
    item?.requested_course_name,
    item?.requested_category_key,
    item?.requested_category_name,
    item?.requested_category_label,
    item?.requester_name,
    item?.requester_email,
    item?.professor,
    item?.academic_year,
    formatAcademicTerm(item?.academic_year),
    getSubmissionLabel(item?.status),
    getArchiveSubmissionKind(item),
  ]
  return fields.map(normalizeReviewSearchText).filter(Boolean).join(' ')
}

const filteredArchiveRequests = computed(() => {
  const query = normalizeReviewSearchText(reviewSearchQuery.value)
  const statusFilter = getReviewStatusFilterValue(reviewStatusFilter.value)
  let filtered = archiveRequests.value

  if (query) {
    filtered = filtered.filter((item) => getReviewSearchHaystack(item).includes(query))
  }

  if (!statusFilter) return filtered
  return filtered.filter((item) => getReviewStatusFilterValue(item?.status) === statusFilter)
})

const toggleReviewSort = (section, key) => {
  const current = reviewSortState.value[section]
  reviewSortState.value = {
    ...reviewSortState.value,
    [section]: {
      key,
      direction: current.key === key && current.direction === 'asc' ? 'desc' : 'asc',
    },
  }
}
const getReviewSortIndicator = (section, key) => {
  const current = reviewSortState.value[section]
  if (current.key !== key) return ''
  return getReviewSortDirectionIcon(current.direction)
}
const getTrashSortIndicator = (key) => {
  if (trashSortState.value.key !== key) return getReviewSortNeutralIcon()
  return getReviewSortDirectionIcon(trashSortState.value.direction)
}
const getReviewSortHeaderIcon = (section, key) => {
  return getReviewSortIndicator(section, key) || getReviewSortNeutralIcon()
}
const getTrashSortHeaderIcon = (key) => {
  return getTrashSortIndicator(key) || getReviewSortNeutralIcon()
}
const isTrashRelationHierarchyFilterOnly = computed(() => isTrashAllFilter(trashFilterType.value))
const isTrashRelationHierarchyEnabled = computed(
  () => showTrashRelationHierarchy.value && isTrashRelationHierarchyFilterOnly.value
)
const toggleTrashRelationHierarchy = () => {
  if (!isTrashRelationHierarchyFilterOnly.value) {
    showTrashRelationHierarchy.value = false
    return
  }
  showTrashRelationHierarchy.value = !showTrashRelationHierarchy.value
  if (showTrashRelationHierarchy.value) {
    trashSortState.value = { key: null, direction: 'asc' }
  }
}
const getTrashRelationButtonLabel = () =>
  isTrashRelationHierarchyEnabled.value ? '隱藏相關性' : '相關性顯示'
const newCourseArchiveRequests = computed(() =>
  sortArchiveReviewItems(
    filteredArchiveRequests.value.filter(
      (item) => item.requested_course_name || item.requested_category_key
    ),
    'new'
  )
)
const existingCourseArchiveRequests = computed(() =>
  sortArchiveReviewItems(
    filteredArchiveRequests.value.filter(
      (item) => !item.requested_course_name && !item.requested_category_key
    ),
    'existing'
  )
)
const clampReviewPaginatorFirst = (firstRef, rows, totalItems) => {
  const normalizedRows = Math.max(1, Number(rows) || 10)
  if (totalItems <= 0) {
    firstRef.value = 0
    return
  }
  const maxFirst = Math.max(0, Math.floor((totalItems - 1) / normalizedRows) * normalizedRows)
  if (firstRef.value > maxFirst) {
    firstRef.value = maxFirst
  }
}
const handleNewSubmissionPage = (event = {}) => {
  const first = Math.max(0, Number(event?.first) || 0)
  const rows = Math.max(1, Number(event?.rows) || newSubmissionRows.value || 10)
  newSubmissionRows.value = rows
  newSubmissionFirst.value = first
}
const handleExistingSubmissionPage = (event = {}) => {
  const first = Math.max(0, Number(event?.first) || 0)
  const rows = Math.max(1, Number(event?.rows) || existingSubmissionRows.value || 10)
  existingSubmissionRows.value = rows
  existingSubmissionFirst.value = first
}
const getFilteredTrashRows = () => {
  const filterType = getValidTrashFilterType(trashFilterType.value)
  const rows = Array.isArray(trashItems.value) ? trashItems.value : []
  if (!filterType) {
    return rows
  }
  return rows.filter((item) => item?.item_type === filterType)
}
const getTrashSortValue = (item, key) => {
  if (key === 'deleted_at') return getTrashDeletedTimestamp(item)
  if (key === 'type') return getTrashTypeLabel(item?.item_type)
  if (key === 'name') return String(item?.display_name || '')
  if (key === 'status') return getTrashStatusLabel(item?.status)
  if (key === 'dependencies')
    return getTrashDependencies(item)
      .map((dependency) => dependency.label)
      .join(' ')
  return String(item?.[key] || '')
}
const isMissingTrashSortValue = (value) => value === null || value === undefined || value === ''
const compareTrashSortValues = (a, b) => {
  const { key, direction } = trashSortState.value
  const directionFactor = direction === 'desc' ? -1 : 1
  const aValue = getTrashSortValue(a, key)
  const bValue = getTrashSortValue(b, key)
  const aMissing = isMissingTrashSortValue(aValue)
  const bMissing = isMissingTrashSortValue(bValue)
  if (aMissing && bMissing) return 0
  if (aMissing) return 1
  if (bMissing) return -1
  if (typeof aValue === 'number' && typeof bValue === 'number') {
    return (aValue - bValue) * directionFactor
  }
  return String(aValue).localeCompare(String(bValue), 'zh-TW') * directionFactor
}
const sortTrashItems = (rows) => {
  const sortKey = trashSortState.value.key
  if (!sortKey) {
    return rows
  }
  return [...rows].sort((a, b) => {
    const primaryDiff = compareTrashSortValues(a, b)
    if (primaryDiff !== 0) return primaryDiff
    const idDiff = (Number(a?.id) || 0) - (Number(b?.id) || 0)
    return trashSortState.value.direction === 'desc' ? -idDiff : idDiff
  })
}
const toggleTrashSort = (key) => {
  if (isTrashRelationHierarchyEnabled.value) {
    showTrashRelationHierarchy.value = false
  }
  const current = trashSortState.value
  if (current.key === key) {
    if (current.direction === 'asc') {
      trashSortState.value = { ...current, direction: 'desc' }
      return
    }
    trashSortState.value = { key: null, direction: 'asc' }
    return
  }
  trashSortState.value = {
    key,
    direction: 'asc',
  }
}
const sortedTrashItems = computed(() => {
  const filteredRows = getFilteredTrashRows()
  const sortKey = trashSortState.value.key
  if (isTrashRelationHierarchyEnabled.value) {
    return buildTrashHierarchy(filteredRows, getValidTrashFilterType(trashFilterType.value))
  }
  if (!sortKey) {
    return filteredRows
  }
  return sortTrashItems(filteredRows)
})
const trashTotalPages = computed(() =>
  Math.max(1, Math.ceil(sortedTrashItems.value.length / Math.max(1, trashRowsPerPage.value)))
)
const trashFirst = computed(() => {
  const currentPage = Math.min(Math.max(1, trashPage.value), trashTotalPages.value)
  return (currentPage - 1) * trashRowsPerPage.value
})
const paginatedTrashItems = computed(() => {
  const start = trashFirst.value
  return sortedTrashItems.value.slice(start, start + trashRowsPerPage.value)
})

const clampTrashPage = () => {
  if (trashPage.value > trashTotalPages.value) {
    trashPage.value = trashTotalPages.value
  }
  if (trashPage.value < 1) {
    trashPage.value = 1
  }
}

const handleTrashPageChange = (event = {}) => {
  const nextRows = Math.max(1, Number(event?.rows) || trashRowsPerPage.value || 10)
  const rowsChanged = nextRows !== trashRowsPerPage.value
  trashRowsPerPage.value = nextRows
  trashPage.value = rowsChanged ? 1 : Math.max(1, Number(event?.page) + 1 || 1)
  clampTrashPage()
}

watch(trashFilterType, (nextFilterType) => {
  trashPage.value = 1
  if (!isTrashAllFilter(nextFilterType)) {
    showTrashRelationHierarchy.value = false
    return
  }
  showTrashRelationHierarchy.value = true
  trashSortState.value = { key: null, direction: 'asc' }
})

watch([reviewSearchQuery, reviewStatusFilter], () => {
  newSubmissionFirst.value = 0
  existingSubmissionFirst.value = 0
})

watch([() => newCourseArchiveRequests.value.length, newSubmissionRows], ([count, rows]) => {
  clampReviewPaginatorFirst(newSubmissionFirst, rows, count)
})

watch(
  [() => existingCourseArchiveRequests.value.length, existingSubmissionRows],
  ([count, rows]) => {
    clampReviewPaginatorFirst(existingSubmissionFirst, rows, count)
  }
)

const getTrashItemKey = (item, fallbackIndex = 0) => {
  const type = item?.item_type || 'unknown'
  if (item?.id === null || item?.id === undefined) {
    return `${type}:tmp:${fallbackIndex}`
  }
  return `${type}:${item.id}`
}

const getTrashParentKey = (item) => {
  if (!item?.parent_type || item?.parent_id === null || item?.parent_id === undefined) return null
  return `${item.parent_type}:${item.parent_id}`
}

const getTrashNameIndent = (item) => Math.max(0, Number(item?.trash_depth || 0)) * 1.65

const getTrashTreePrefix = (item) => {
  const depth = Math.max(0, Number(item?.trash_depth || 0))
  if (!depth) return ''
  return `${'│  '.repeat(Math.max(0, depth - 1))}└─`
}

const getTrashRowClass = (item) => {
  if (!isTrashRelationHierarchyEnabled.value) return ''
  const groupIndex = item?.trash_relation_group_index
  const groupSize = Number(item?.trash_relation_group_size || 0)
  if (groupIndex === null || groupIndex === undefined || groupSize <= 1) return ''
  const bandClass =
    Number(groupIndex) % 2 === 0
      ? 'trash-row--relation-group-even'
      : 'trash-row--relation-group-odd'
  return `trash-row--relation-group ${bandClass}`
}

const getValidTrashFilterType = (value) => {
  const validFilterValues = new Set(trashFilterOptions.map((option) => option.value))
  if (isTrashAllFilter(value)) return null
  return validFilterValues.has(value) ? value : null
}

const getTrashFilterApiValue = (value) => getValidTrashFilterType(value)

const buildTrashHierarchy = (items, filterType) => {
  const normalizedFilterType = getValidTrashFilterType(filterType)
  const rowMap = new Map()
  for (const [index, rawItem] of (Array.isArray(items) ? items : []).entries()) {
    if (!rawItem || typeof rawItem !== 'object' || !rawItem.item_type) continue
    const row = {
      ...rawItem,
      _trashRowIndex: index,
      trash_depth: 0,
    }
    const key = getTrashItemKey(row, index)
    const existing = rowMap.get(key)
    if (!existing) {
      rowMap.set(key, row)
      continue
    }
    const dependencies = [...(existing.dependencies || [])]
    for (const dependency of row.dependencies || []) {
      if (!dependencies.includes(dependency)) dependencies.push(dependency)
    }
    rowMap.set(key, {
      ...existing,
      dependencies,
      deleted_at:
        getTrashDeletedTimestamp(row) > getTrashDeletedTimestamp(existing)
          ? row.deleted_at
          : existing.deleted_at,
      deleted_by_id:
        getTrashDeletedTimestamp(row) > getTrashDeletedTimestamp(existing)
          ? row.deleted_by_id
          : existing.deleted_by_id,
      deleted_by_name:
        getTrashDeletedTimestamp(row) > getTrashDeletedTimestamp(existing)
          ? row.deleted_by_name
          : existing.deleted_by_name,
    })
  }
  const rows = [...rowMap.values()]
    .map((item, index) => ({
      ...item,
      _trashRowIndex: item._trashRowIndex ?? index,
      trash_depth: 0,
      trash_relation_group_index: null,
      trash_relation_group_size: 1,
    }))
    .sort((a, b) => getTrashDeletedTimestamp(b) - getTrashDeletedTimestamp(a))

  if (normalizedFilterType !== null && normalizedFilterType !== undefined) {
    return rows
      .sort((a, b) => getTrashDeletedTimestamp(b) - getTrashDeletedTimestamp(a))
      .map((item) => ({
        ...item,
        trash_depth: 0,
        trash_relation_group_index: null,
        trash_relation_group_size: 1,
      }))
  }

  if (!rows.length) return []

  const itemMap = new Map()
  const childrenMap = new Map()
  const roots = []

  for (const row of rows) {
    const key = getTrashItemKey(row, row._trashRowIndex)
    itemMap.set(key, row)
    childrenMap.set(key, [])
  }
  for (const row of rows) {
    const parentKey = getTrashParentKey(row)
    if (parentKey && itemMap.has(parentKey)) {
      childrenMap.get(parentKey)?.push(row)
    } else {
      roots.push(row)
    }
  }

  for (const children of childrenMap.values()) {
    children.sort((a, b) => getTrashDeletedTimestamp(b) - getTrashDeletedTimestamp(a))
  }
  roots.sort((a, b) => getTrashDeletedTimestamp(b) - getTrashDeletedTimestamp(a))

  const visited = new Set()
  const result = []

  const countSubtree = (node, seen = new Set()) => {
    const key = getTrashItemKey(node, node._trashRowIndex)
    if (seen.has(key)) return 0
    seen.add(key)
    const children = childrenMap.get(key) || []
    return 1 + children.reduce((total, child) => total + countSubtree(child, seen), 0)
  }

  const walk = (node, depth, relationGroupIndex = null, relationGroupSize = 1) => {
    const key = getTrashItemKey(node, node._trashRowIndex)
    if (visited.has(key)) return
    visited.add(key)

    result.push({
      ...node,
      trash_depth: depth,
      trash_relation_group_index: relationGroupIndex,
      trash_relation_group_size: relationGroupSize,
    })
    const children = childrenMap.get(key) || []
    for (const child of children) {
      walk(child, depth + 1, relationGroupIndex, relationGroupSize)
    }
  }
  let nextRelationGroupIndex = 0
  for (const root of roots) {
    const relationGroupSize = countSubtree(root)
    const relationGroupIndex = relationGroupSize > 1 ? nextRelationGroupIndex++ : null
    walk(root, 0, relationGroupIndex, relationGroupSize)
  }

  if (!result.length && rows.length) {
    return rows.map((item) => ({
      ...item,
      trash_depth: 0,
      trash_relation_group_index: null,
      trash_relation_group_size: 1,
    }))
  }

  return result
}

watch([() => sortedTrashItems.value.length, trashRowsPerPage], () => {
  clampTrashPage()
})

const getTrashContextLine = (item) => {
  if (!item) return ''
  if (item.item_type === 'archive' && item.course_name) return `課程：${item.course_name}`
  if (item.item_type === 'course' && item.parent_name) return `隸屬分類：${item.parent_name}`
  if (item.item_type === 'archive_submission') {
    if (item.parent_name) return `關聯考古題：${item.parent_name}`
    if (item.course_name) return `課程：${item.course_name}`
  }
  return ''
}

const getSystemIssueReportTypeLabel = (value) =>
  ({
    bug: '程式錯誤',
    enhancement: '功能建議',
    performance: '效能問題',
    'ui-ux': 'UI/UX',
    question: '其他',
  })[value] ||
  value ||
  '—'

const getTrashReportDetails = (item) => {
  if (item?.item_type === 'system_issue_report') {
    return [
      { label: '問題類型', value: getSystemIssueReportTypeLabel(item.report_type) },
      { label: '回報者', value: item.reporter_name || '—' },
      { label: '回報時間', value: item.created_at ? formatAdminActorTime(item.created_at) : '—' },
      { label: '說明', value: '本地摘要' },
    ]
  }
  if (item?.item_type === 'comment_report') {
    return [
      { label: '回報者', value: item.reporter_name || '—' },
      { label: '留言者', value: item.comment_author_name || '—' },
      {
        label: '課程／考古題',
        value: [item.course_name, item.archive_name].filter(Boolean).join(' · ') || '—',
      },
      { label: '回報時間', value: item.created_at ? formatAdminActorTime(item.created_at) : '—' },
    ]
  }
  return []
}

const TAB_STORAGE_KEY = STORAGE_KEYS.local.ADMIN_CURRENT_TAB

const getInitialTab = () => {
  try {
    const savedTab = getLocalItem(TAB_STORAGE_KEY)
    if (savedTab && ['0', '1', '2', '3', '4', '5'].includes(savedTab)) {
      return savedTab
    }
  } catch (e) {
    console.error('Failed to load tab from storage:', e)
  }
  return '0'
}

const currentTab = ref(getInitialTab())

const categoryOptions = computed(() =>
  courseCategories.value
    .filter((category) => !category.deleted_at)
    .map((category) => ({
      name: category.is_active ? category.name : `${category.name}（已停用）`,
      value: category.key,
      label: category.label,
    }))
)
const categoryInfoMap = computed(() =>
  courseCategories.value.reduce((acc, category) => {
    if (!category.deleted_at) {
      acc[category.key] = category
    }
    return acc
  }, {})
)

const userTypeFilterOptions = [
  { name: '管理員', value: true },
  { name: '一般使用者', value: false },
]

const contributorLevelStats = computed(() => {
  const counts = new Map(SUBMISSION_LEVELS.map((level) => [level.level, 0]))
  users.value.forEach((user) => {
    counts.set(user.contributorLevel.level, (counts.get(user.contributorLevel.level) || 0) + 1)
  })
  return SUBMISSION_LEVELS.map((level) => ({
    ...level,
    count: counts.get(level.level) || 0,
  }))
})

const contributorLevelDistribution = computed(() => {
  const total = users.value.length
  return contributorLevelStats.value.map((stat) => ({
    ...stat,
    palette: getContributorLevelPalette(stat.level),
    percentage: total > 0 ? (stat.count / total) * 100 : 0,
  }))
})

const userInsightsViewLabel = computed(() => {
  if (userInsightsView.value === 'login-hour') return '最近在線時間分布'
  if (userInsightsView.value === 'login-date') return '最近在線日期分布'
  return '投稿等級分布'
})

const activeLoginBucketConfig = computed(() =>
  userInsightsView.value === 'login-hour'
    ? LOGIN_HOUR_BUCKET_CONFIG[loginRangeHours.value]
    : LOGIN_DATE_BUCKET_CONFIG[loginRangeDays.value]
)
const loginDistributionDescription = computed(() => {
  const range =
    userInsightsView.value === 'login-hour'
      ? `${loginRangeHours.value} 小時`
      : `${loginRangeDays.value} 日`
  const bucketMinutes = activeLoginBucketConfig.value.bucketMinutes
  const sampling =
    bucketMinutes === 24 * 60
      ? '每日取樣一次'
      : bucketMinutes < 60
        ? `每 ${bucketMinutes} 分鐘取樣一次`
        : `每 ${bucketMinutes / 60} 小時取樣一次`
  return `統計最近 ${range}內，${sampling}的同時在線使用者人數。`
})

const loginRangeOptions = computed(() =>
  userInsightsView.value === 'login-hour' ? LOGIN_HOUR_RANGE_OPTIONS : LOGIN_DATE_RANGE_OPTIONS
)
const activeLoginRange = computed(() =>
  userInsightsView.value === 'login-hour' ? loginRangeHours.value : loginRangeDays.value
)
const loginRangeUnit = computed(() => (userInsightsView.value === 'login-hour' ? '小時' : '日'))
const setActiveLoginRange = (value) => {
  if (userInsightsView.value === 'login-hour') loginRangeHours.value = value
  else loginRangeDays.value = value
  void loadOnlineStatistics()
  if (typeof window !== 'undefined') scheduleLoginStatsRefresh()
}

watch(userInsightsView, (mode) => {
  if (mode === 'login-hour') loginRangeHours.value = 24
  if (mode === 'login-date') loginRangeDays.value = 30
  if (mode !== 'level') void loadOnlineStatistics()
})

const buildIntegerAxis = (buckets) => {
  const maxCount = Math.max(0, ...buckets.map(({ count }) => count))
  const step = Math.max(1, Math.ceil(maxCount / 4))
  const yMax = Math.max(1, Math.ceil(maxCount / step) * step)
  const yTicks = []
  for (let value = 0; value <= yMax; value += step) yTicks.push(value)
  if (yTicks.at(-1) !== yMax) yTicks.push(yMax)
  return { yMax, yTicks: yTicks.reverse() }
}

const activeReviewSubmissionBucketConfig = computed(() =>
  reviewSubmissionView.value === 'time'
    ? LOGIN_HOUR_BUCKET_CONFIG[reviewSubmissionRangeHours.value]
    : LOGIN_DATE_BUCKET_CONFIG[reviewSubmissionRangeDays.value]
)
const reviewSubmissionRangeOptions = computed(() =>
  reviewSubmissionView.value === 'time' ? LOGIN_HOUR_RANGE_OPTIONS : LOGIN_DATE_RANGE_OPTIONS
)
const activeReviewSubmissionRange = computed(() =>
  reviewSubmissionView.value === 'time'
    ? reviewSubmissionRangeHours.value
    : reviewSubmissionRangeDays.value
)
const reviewSubmissionRangeUnit = computed(() =>
  reviewSubmissionView.value === 'time' ? '小時' : '日'
)
const activeReviewSubmissionRangeKey = () =>
  reviewSubmissionView.value === 'time'
    ? `${reviewSubmissionRangeHours.value}h`
    : `${reviewSubmissionRangeDays.value}d`
const reviewSubmissionDescription = computed(() => {
  if (reviewSubmissionView.value === 'time') {
    const bucketMinutes = activeReviewSubmissionBucketConfig.value.bucketMinutes
    return `統計最近 ${reviewSubmissionRangeHours.value} 小時內，每 ${bucketMinutes} 分鐘區間的投稿筆數。`
  }
  const days = reviewSubmissionRangeDays.value
  const bucketMinutes = activeReviewSubmissionBucketConfig.value.bucketMinutes
  if (bucketMinutes === 24 * 60) return `統計最近 ${days} 日內，每日的投稿筆數。`
  return `統計最近 ${days} 日內，每 ${bucketMinutes / 60} 小時區間的投稿筆數。`
})
const reviewSubmissionChartData = computed(() => {
  const source = Array.isArray(reviewSubmissionStatistics.value?.points)
    ? reviewSubmissionStatistics.value.points
    : []
  const config = activeReviewSubmissionBucketConfig.value
  const mode = reviewSubmissionView.value === 'time' ? 'hour' : 'date'
  const tickLayout = resolveTemporalTickLayout({
    baseLabelEvery: config.labelEvery,
    chartWidth: reviewSubmissionChartWidth.value,
    pointCount: source.length,
    mode,
    fontScale: statisticsFontScale.value,
  })
  const ticks = buildTemporalTicks(source, {
    mode,
    ...tickLayout,
  })
  const buckets = source.map((point, index) => ({
    ...point,
    ...ticks[index],
    key: point.start,
    fullLabel: `${formatProductDateTime(new Date(point.start))}–${formatProductDateTime(
      new Date(point.end)
    )}`,
  }))
  return {
    ...buildIntegerAxis(buckets),
    buckets,
    ariaLabel:
      reviewSubmissionView.value === 'time'
        ? `最近 ${reviewSubmissionRangeHours.value} 小時的投稿筆數分布`
        : `最近 ${reviewSubmissionRangeDays.value} 日的投稿筆數分布`,
  }
})

const setActiveReviewSubmissionRange = (value) => {
  if (reviewSubmissionView.value === 'time') reviewSubmissionRangeHours.value = value
  else reviewSubmissionRangeDays.value = value
  void loadReviewSubmissionStatistics()
}

watch(reviewSubmissionView, (mode) => {
  if (mode === 'time') reviewSubmissionRangeHours.value = 24
  else reviewSubmissionRangeDays.value = 30
  void loadReviewSubmissionStatistics()
})

const loginChartData = computed(() => {
  const mode = userInsightsView.value
  const source = Array.isArray(onlineStatistics.value?.points) ? onlineStatistics.value.points : []
  const config = activeLoginBucketConfig.value
  const tickMode = mode === 'login-hour' ? 'hour' : 'date'
  const tickLayout = resolveTemporalTickLayout({
    baseLabelEvery: config.labelEvery,
    chartWidth: userStatisticsChartWidth.value,
    pointCount: source.length,
    mode: tickMode,
    fontScale: statisticsFontScale.value,
  })
  const ticks = buildTemporalTicks(source, {
    mode: tickMode,
    ...tickLayout,
  })
  const buckets = source.map((point, index) => {
    const start = new Date(point.start)
    const end = new Date(point.end)
    return {
      ...point,
      ...ticks[index],
      key: point.at,
      fullLabel: `${formatProductDateTime(new Date(point.at))} 取樣（區間 ${formatProductDateTime(start)}–${formatProductDateTime(end)}）`,
    }
  })
  const axis = buildIntegerAxis(buckets)
  return {
    ...axis,
    bucketMinutes: config.bucketMinutes,
    labels: buckets.map(({ labelLines }) => labelLines),
    counts: buckets.map(({ count }) => count),
    buckets,
    ariaLabel:
      mode === 'login-hour'
        ? `最近 ${loginRangeHours.value} 小時的同時在線人數分布`
        : `最近 ${loginRangeDays.value} 日的同時在線人數分布`,
  }
})

const onlineStatisticsSummary = computed(() =>
  onlineStatistics.value
    ? {
        current: onlineStatistics.value.current_online,
        peak: onlineStatistics.value.peak_online,
        average: Number(onlineStatistics.value.average_online).toFixed(1),
      }
    : null
)

const selectedUserContributorLevel = computed(() =>
  resolveSubmissionLevel(userSubmissionStats.value?.contributor_experience || 0)
)

const selectedUserLevelProgressStyle = computed(() => {
  const palette = getContributorLevelPalette(selectedUserContributorLevel.value.level)
  return {
    '--user-level-color': palette.bg,
    '--user-level-border': palette.border,
  }
})

const buildUserSubmissionStatuses = (stats) => {
  const counts = stats?.status_counts || {}
  const total = stats?.total_count || 0
  return USER_SUBMISSION_STATUS_CONFIG.map((status) => {
    const count = Number(counts[status.key]) || 0
    return {
      ...status,
      count,
      percentage: total > 0 ? (count / total) * 100 : 0,
    }
  })
}

const selectedUserSubmissionStatuses = computed(() =>
  buildUserSubmissionStatuses(userSubmissionStats.value)
)

const archiveRequesterSubmissionStatuses = computed(() =>
  buildUserSubmissionStatuses(archiveRequesterStats.value)
)

const archiveRequesterContributorLevel = computed(() =>
  resolveSubmissionLevel(archiveRequesterStats.value?.contributor_experience || 0)
)

const selectedUserSubmissionDistributionLabel = computed(() =>
  selectedUserSubmissionStatuses.value
    .map((status) => `${status.label} ${status.count} 筆`)
    .join('，')
)

const archiveRequesterDistributionLabel = computed(() =>
  archiveRequesterSubmissionStatuses.value
    .map((status) => `${status.label} ${status.count} 筆`)
    .join('，')
)

const normalizedUserSubmissionRecordSearch = computed(() =>
  normalizeReviewSearchText(userSubmissionRecordSearch.value.trim())
)

const getUserSubmissionRecordSearchHaystack = (record) => {
  const statusLabel = getUserSubmissionStatusLabel(record.status)
  const submissionKind = getArchiveSubmissionKind(record)
  const fields = [
    record.course_name,
    record.exam_name,
    record.professor,
    record.academic_year,
    formatAcademicTerm(record.academic_year),
    record.id,
    record.id ? `#${record.id}` : '',
    record.id ? `投稿編號 ${record.id}` : '',
    record.id ? `投稿編號 #${record.id}` : '',
    record.status,
    statusLabel,
    submissionKind,
    record.review_comment,
  ]
  return fields.map(normalizeReviewSearchText).filter(Boolean).join(' ')
}

const filteredUserSubmissionRecords = computed(() => {
  const records = userSubmissionStats.value?.submission_records || []
  const query = normalizedUserSubmissionRecordSearch.value
  const filtered = query
    ? records.filter((record) => getUserSubmissionRecordSearchHaystack(record).includes(query))
    : records
  return [...filtered].sort((left, right) => {
    const timeDifference =
      new Date(right.submitted_at || 0).getTime() - new Date(left.submitted_at || 0).getTime()
    return timeDifference || Number(right.id || 0) - Number(left.id || 0)
  })
})

const paginatedUserSubmissionRecords = computed(() =>
  filteredUserSubmissionRecords.value.slice(
    userSubmissionRecordFirst.value,
    userSubmissionRecordFirst.value + userSubmissionRecordRows.value
  )
)

const handleUserSubmissionRecordPage = (event) => {
  userSubmissionRecordFirst.value = event.first
  userSubmissionRecordRows.value = event.rows
}

watch(userSubmissionRecordSearch, () => {
  userSubmissionRecordFirst.value = 0
})

const isContributorLevelSelected = (level) => selectedContributorLevels.value.includes(level)

const toggleContributorLevel = (level) => {
  selectedContributorLevels.value = isContributorLevelSelected(level)
    ? selectedContributorLevels.value.filter((selectedLevel) => selectedLevel !== level)
    : [...selectedContributorLevels.value, level].sort((left, right) => left - right)
  userFirst.value = 0
}

const clearContributorLevelFilter = () => {
  selectedContributorLevels.value = []
  userFirst.value = 0
}

const closeUserDataStatsDialog = () => {
  userSubmissionStatsController?.abort()
  userSubmissionStatsController = null
  showUserDataStatsDialog.value = false
  selectedUserDataStatsId.value = null
  userSubmissionStatsLoading.value = false
  userSubmissionStats.value = null
  userSubmissionStatsError.value = ''
  userSubmissionRecordSearch.value = ''
  userSubmissionRecordFirst.value = 0
}

const openUserDataStats = async (user) => {
  userSubmissionStatsController?.abort()
  const controller = new AbortController()
  userSubmissionStatsController = controller
  userSubmissionStats.value = null
  userSubmissionStatsError.value = ''
  userSubmissionRecordSearch.value = ''
  userSubmissionStatsLoading.value = true
  userSubmissionRecordFirst.value = 0
  selectedUserDataStatsId.value = user.id
  showUserDataStatsDialog.value = true

  try {
    const { data } = await getUserSubmissionStats(user.id, {
      includeRecords: true,
      signal: controller.signal,
    })
    if (userSubmissionStatsController === controller) {
      userSubmissionStats.value = data
    }
  } catch (error) {
    if (error?.code === 'ERR_CANCELED') return
    if (userSubmissionStatsController === controller) {
      const statusCode = error?.response?.status
      userSubmissionStatsError.value =
        statusCode === 403
          ? '你沒有權限查看此使用者的投稿統計'
          : statusCode === 404
            ? '找不到此使用者'
            : '投稿統計載入失敗，請稍後再試'
    }
  } finally {
    if (userSubmissionStatsController === controller) {
      userSubmissionStatsLoading.value = false
      userSubmissionStatsController = null
    }
  }
}

const resetContributorLevelSettingsDraft = () => {
  contributorLevelSettingsDraft.value = getContributorLevelSettingsSnapshot()
  contributorLevelSettingsError.value = ''
}

const recalculateUserContributorLevels = () => {
  users.value = users.value.map((user) => {
    const contributorLevel = resolveSubmissionLevel(user.contributor_experience)
    return {
      ...user,
      contributorLevel,
      contributor_level: contributorLevel.level,
    }
  })
}

const openContributorLevelSettingsDialog = async () => {
  contributorLevelSettingsError.value = ''
  await loadContributorLevelSettings({ force: true })
  recalculateUserContributorLevels()
  resetContributorLevelSettingsDraft()
  showContributorLevelSettingsDialog.value = true
}

const closeContributorLevelSettingsDialog = () => {
  if (contributorLevelSettingsSaving.value) return
  showContributorLevelSettingsDialog.value = false
  contributorLevelSettingsError.value = ''
}

const persistContributorLevelSettings = async (settings) => {
  contributorLevelSettingsSaving.value = true
  contributorLevelSettingsError.value = ''
  try {
    await saveContributorLevelSettings(settings)
    recalculateUserContributorLevels()
    userFirst.value = 0
    resetContributorLevelSettingsDraft()
    showContributorLevelSettingsDialog.value = false
    toast.add({
      severity: 'success',
      summary: '設定已保存',
      detail: '投稿等級名稱與累積 EXP 門檻已更新。',
      life: 3000,
    })
  } catch (error) {
    contributorLevelSettingsError.value =
      error?.response?.data?.detail || error?.message || '投稿等級設定保存失敗'
  } finally {
    contributorLevelSettingsSaving.value = false
  }
}

const confirmContributorLevelSettingsSave = () => {
  let normalized
  try {
    normalized = validateContributorLevelSettings(contributorLevelSettingsDraft.value)
    contributorLevelSettingsDraft.value = normalized.map((level) => ({ ...level }))
    contributorLevelSettingsError.value = ''
  } catch (error) {
    contributorLevelSettingsError.value = error?.message || '投稿等級設定格式錯誤'
    return
  }

  confirm.require({
    header: '確認更新投稿等級設定',
    message: '修改等級名稱或 EXP 門檻後，使用者目前顯示的投稿等級可能立即重新計算。',
    icon: 'pi pi-exclamation-triangle',
    rejectLabel: '取消',
    acceptLabel: '確認保存',
    accept: () => persistContributorLevelSettings(normalized),
  })
}

const getCategoryName = (category) => {
  return categoryInfoMap.value[category]?.name || category
}

const getCategoryDisplayLabel = (category) => {
  return categoryInfoMap.value[category]?.label || categoryInfoMap.value[category]?.name || ''
}

const normalizeCategoryBadgeColor = (color) => {
  const value = (color || DEFAULT_CATEGORY_BADGE_COLOR).toString().trim().toLowerCase()
  const mappedValue = legacyCategoryBadgeColorMap[value] || value
  return categoryBadgeColorValues.has(mappedValue) ? mappedValue : DEFAULT_CATEGORY_BADGE_COLOR
}

const getCategoryBadgeColor = (category) => {
  if (typeof category === 'string') {
    return normalizeCategoryBadgeColor(categoryInfoMap.value[category]?.badge_color)
  }
  return normalizeCategoryBadgeColor(category?.badge_color)
}

const getCategoryBadgeClass = (category) => {
  return `category-badge category-badge--${getCategoryBadgeColor(category)}`
}

const categoryOrder = computed(() =>
  courseCategories.value.reduce((acc, category, index) => {
    acc[category.key] = index
    return acc
  }, {})
)

const sortCourses = (courseList) => {
  return [...courseList].sort((a, b) => {
    const categoryDiff =
      (categoryOrder.value[a.category] ?? 999) - (categoryOrder.value[b.category] ?? 999)
    if (categoryDiff !== 0) return categoryDiff
    const orderDiff = (a.order_index ?? 0) - (b.order_index ?? 0)
    if (orderDiff !== 0) return orderDiff
    return (a.id ?? 0) - (b.id ?? 0)
  })
}

const getNotificationSeverity = (severity) => {
  const map = {
    info: 'info',
    success: 'success',
    warning: 'warning',
    danger: 'danger',
  }
  return map[severity] || 'secondary'
}

const getNotificationSeverityLabel = (severity) => {
  const map = {
    info: '一般',
    success: '成功',
    warning: '提醒',
    danger: '重要',
  }
  return map[severity] || '未知'
}

const isNotificationEffective = (notification) => {
  if (!notification || !notification.is_active) {
    return false
  }

  const now = new Date()

  if (notification.starts_at) {
    const startsAt = new Date(notification.starts_at)
    if (!Number.isNaN(startsAt.getTime()) && startsAt > now) {
      return false
    }
  }

  if (notification.ends_at) {
    const endsAt = new Date(notification.ends_at)
    if (!Number.isNaN(endsAt.getTime()) && endsAt < now) {
      return false
    }
  }

  return true
}

const formatAdminActorTime = (value) => formatRelativeOrAbsoluteDateTime(value)

const getNotificationUpdaterLabel = (notification) => {
  const label = String(notification?.updated_by_username || '').trim()
  return label || '—'
}

const getSubmissionLabel = (status) => {
  const labels = {
    pending: '待審核',
    approved: '已通過',
    rejected: '已退回',
    takedown: '已下架',
    deleted: '已刪除',
  }
  return labels[normalizeSubmissionStatus(status)] || '未知狀態'
}

const getSubmissionSeverity = (status) => {
  const normalized = normalizeSubmissionStatus(status)
  if (normalized === 'approved') return 'success'
  if (normalized === 'rejected') return 'danger'
  if (normalized === 'deleted') return 'danger'
  if (normalized === 'takedown') return 'secondary'
  return 'warning'
}

const getSubmissionStatusClass = (status) => {
  const normalized = normalizeSubmissionStatus(status)
  if (normalized === 'approved') return 'review-status-approved'
  if (normalized === 'rejected') return 'review-status-rejected'
  if (normalized === 'takedown') return 'review-status-takedown'
  if (normalized === 'deleted') return 'review-status-deleted'
  return 'review-status-pending'
}

const reviewActionDefinitions = {
  approve: { key: 'approve', label: '通過', icon: 'pi pi-check', severity: 'success' },
  reject: { key: 'reject', label: '退回', icon: 'pi pi-ban', severity: 'danger' },
  takedown: {
    key: 'takedown',
    label: '下架',
    icon: 'pi pi-eye-slash',
    severity: 'secondary',
    outlined: true,
  },
  republish: {
    key: 'republish',
    label: '重新上架',
    icon: 'pi pi-refresh',
    severity: 'success',
    outlined: true,
  },
  delete: { key: 'delete', label: '刪除', icon: 'pi pi-trash', severity: 'danger', outlined: true },
}

const getReviewRowActions = (item) => {
  const status = getReviewItemStatus(item)
  if (status === 'pending') {
    return [
      reviewActionDefinitions.approve,
      reviewActionDefinitions.reject,
      reviewActionDefinitions.delete,
    ]
  }
  if (status === 'approved') {
    return [
      reviewActionDefinitions.takedown,
      reviewActionDefinitions.reject,
      reviewActionDefinitions.delete,
    ]
  }
  if (status === 'takedown' && canShowRepublishReviewSubmission(item)) {
    return [reviewActionDefinitions.republish]
  }
  if (status === 'rejected') {
    return [reviewActionDefinitions.approve, reviewActionDefinitions.delete]
  }
  return []
}

const isCourseTrashLifecycleReason = (reason) => {
  if (!reason) return false
  return reason === 'course_trashed' || reason.startsWith('course_trashed|')
}

const canShowRepublishReviewSubmission = (item) => {
  if (getReviewItemStatus(item) !== 'takedown') return false
  if (!item?.created_archive_id) return false
  if (item?.linked_course_deleted === true || item?.linked_archive_deleted === true) {
    return false
  }
  if (
    isCourseTrashLifecycleReason(item?.lifecycle_reason) ||
    item?.lifecycle_reason === 'archive_trashed' ||
    item?.lifecycle_reason === 'linked_archive_permanently_deleted'
  ) {
    return false
  }
  return true
}

const getReviewTrashNote = (item, fullText = false) => {
  const status = getReviewItemStatus(item)
  if (!['takedown', 'deleted'].includes(status)) return ''
  if (item?.lifecycle_reason === 'linked_archive_permanently_deleted')
    return '無法復原：關聯考古題已永久刪除。'
  if (
    isCourseTrashLifecycleReason(item?.lifecycle_reason) ||
    item?.linked_course_deleted === true
  ) {
    if (status === 'deleted') {
      const shortText = '原課程在垃圾桶，請至垃圾桶處理。'
      const fullTextMessage = '此投稿已刪除；其原課程仍在垃圾桶，請到垃圾桶查看關聯項目。'
      return fullText ? fullTextMessage : shortText
    }
    const shortText = '原課程在垃圾桶，復原後會回到原狀。'
    const fullTextMessage =
      '原課程已在垃圾桶，此投稿暫時下架。請先到垃圾桶復原原課程，復原後會回到原本狀態。'
    return fullText ? fullTextMessage : shortText
  }
  if (item?.lifecycle_reason === 'archive_trashed' || item?.linked_archive_deleted === true) {
    return '關聯考古題在垃圾桶，請先復原考古題。'
  }
  return ''
}

const isReviewTrashWarningNote = (item) => {
  const note = getReviewTrashNote(item)
  return note.includes('無法復原') || note.includes('永久刪除')
}

const getReviewTrashNoteClass = (item) => {
  return isReviewTrashWarningNote(item)
    ? 'review-card-action-note--warning'
    : 'review-card-action-note--info'
}

const getReviewTrashNoteIcon = (item) => {
  return isReviewTrashWarningNote(item) ? 'pi pi-exclamation-circle' : 'pi pi-info-circle'
}

const runReviewRowAction = (item, action) => {
  if (!item?.id) return
  if (isReadonlyReviewSubmission(item) && action !== 'republish') {
    toast.add({
      severity: 'info',
      summary: '僅能查看',
      detail: getReadonlyReviewSubmissionMessage(item) || '此投稿目前不能變更審核狀態。',
      life: 3000,
    })
    return
  }
  if (action === 'delete') {
    confirmDeleteArchiveSubmission(item)
    return
  }
  reviewArchiveSubmission(item, action)
}

const getArchiveSubmissionKind = (item) => {
  if (item?.requested_category_key) return '新分類 + 新課程'
  if (item?.requested_course_name) return '新課程'
  return '考古題投稿'
}

const getArchiveSubmissionKindSeverity = (item) => {
  if (item?.requested_category_key) return 'warning'
  if (item?.requested_course_name) return 'info'
  return 'secondary'
}

const getArchiveSubmissionKindClass = (item) => {
  if (item?.requested_category_key) return 'soft-badge--new-course-category'
  if (item?.requested_course_name) return 'soft-badge--new-course'
  return 'soft-badge--info'
}

const formatAcademicTerm = (value) => {
  const numericValue = Number(value)
  if (!numericValue) return ''
  if (numericValue >= 1000 && numericValue < 2000) {
    const year = Math.floor(numericValue / 10)
    const semester = numericValue % 10
    return `${year}${semester === 1 ? '上' : '下'}學期`
  }
  return `${numericValue} 年`
}

const resetNotificationForm = () => {
  notificationForm.value = {
    title: '',
    body: '',
    severity: 'info',
    is_active: true,
    starts_at: null,
    ends_at: null,
  }
  notificationFormErrors.value = {}
  editingNotification.value = null
}

const toDate = (value) => {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

const filteredCourses = computed(() => {
  let filtered = sortCourses(courses.value)

  if (searchQuery.value) {
    const query = normalizeReviewSearchText(searchQuery.value)
    filtered = filtered.filter((course) => {
      const courseName = normalizeReviewSearchText(course.name)
      const categoryName = normalizeReviewSearchText(getCategoryName(course.category))
      const categoryLabel = normalizeReviewSearchText(getCategoryDisplayLabel(course.category))
      const categoryKey = normalizeReviewSearchText(course.category)
      return (
        courseName.includes(query) ||
        categoryName.includes(query) ||
        categoryLabel.includes(query) ||
        categoryKey.includes(query)
      )
    })
  }

  if (filterCategory.value) {
    filtered = filtered.filter((course) => course.category === filterCategory.value)
  }

  return filtered
})

const paginatedCourses = computed(() =>
  filteredCourses.value.slice(courseFirst.value, courseFirst.value + courseRows.value)
)

const getCategoryCourses = (category) => {
  return sortCourses(courses.value.filter((course) => course.category === category))
}

const getCoursePosition = (course) => {
  return getCategoryCourses(course.category).findIndex((item) => item.id === course.id)
}

const canMoveCourse = (course, direction) => {
  const position = getCoursePosition(course)
  if (position < 0) return false
  const categoryCourses = getCategoryCourses(course.category)
  const nextPosition = position + direction
  return nextPosition >= 0 && nextPosition < categoryCourses.length
}

const getCategoryPosition = (category) => {
  return courseCategories.value.findIndex((item) => item.id === category.id)
}

const canMoveCategory = (category, direction) => {
  const position = getCategoryPosition(category)
  const nextPosition = position + direction
  return position >= 0 && nextPosition >= 0 && nextPosition < courseCategories.value.length
}

const moveCategory = async (category, direction) => {
  if (!canMoveCategory(category, direction)) return

  const currentIndex = getCategoryPosition(category)
  const nextIndex = currentIndex + direction
  const reordered = [...courseCategories.value]
  const [movedCategory] = reordered.splice(currentIndex, 1)
  reordered.splice(nextIndex, 0, movedCategory)

  categoryOrderLoading.value = true
  try {
    await courseService.reorderCategories(reordered.map((item) => item.id))
    courseCategories.value = reordered.map((item, index) => ({ ...item, order_index: index }))
    await loadCourses()
  } catch (error) {
    console.error('更新分類順序失敗:', error)
    if (isUnauthorizedError(error)) return
    toast.add({ severity: 'error', summary: '錯誤', detail: '分類順序更新失敗', life: 3000 })
  } finally {
    categoryOrderLoading.value = false
  }
}

const moveCourse = async (course, direction) => {
  if (!canMoveCourse(course, direction)) return

  const categoryCourses = getCategoryCourses(course.category)
  const currentIndex = categoryCourses.findIndex((item) => item.id === course.id)
  const nextIndex = currentIndex + direction
  const reordered = [...categoryCourses]
  const [movedCourse] = reordered.splice(currentIndex, 1)
  reordered.splice(nextIndex, 0, movedCourse)

  courseOrderLoading.value = true
  try {
    await reorderCourses(
      course.category,
      reordered.map((item) => item.id)
    )
    trackEvent(EVENTS.UPDATE_COURSE, {
      action: 'reorder',
      courseName: course.name,
      category: course.category,
    })
    await loadCourses()
  } catch (error) {
    console.error('更新課程順序失敗:', error)
    if (isUnauthorizedError(error)) {
      return
    }
    toast.add({
      severity: 'error',
      summary: '錯誤',
      detail: '課程順序更新失敗',
      life: 3000,
    })
  } finally {
    courseOrderLoading.value = false
  }
}

const filteredUsers = computed(() => {
  let filtered = users.value

  if (userSearchQuery.value) {
    const query = userSearchQuery.value.toLowerCase()
    filtered = filtered.filter(
      (user) => user.name.toLowerCase().includes(query) || user.email.toLowerCase().includes(query)
    )
  }

  if (filterUserType.value !== null) {
    filtered = filtered.filter((user) => user.is_admin === filterUserType.value)
  }

  if (selectedContributorLevels.value.length > 0) {
    filtered = filtered.filter((user) =>
      selectedContributorLevels.value.includes(user.contributorLevel.level)
    )
  }

  return filtered
})

const sortRecords = (records, sortMeta) => {
  if (!sortMeta.length) return records

  return [...records].sort((left, right) => {
    for (const { field, order } of sortMeta) {
      if (field === 'contributor_level') {
        const leftLevel = Number.isInteger(left.contributor_level) ? left.contributor_level : null
        const rightLevel = Number.isInteger(right.contributor_level)
          ? right.contributor_level
          : null
        if (leftLevel === rightLevel) continue
        if (leftLevel === null) return 1
        if (rightLevel === null) return -1
        return (leftLevel - rightLevel) * order
      }

      const leftValue = left[field]
      const rightValue = right[field]
      if (leftValue === rightValue) continue
      if (leftValue === null || leftValue === undefined) return -1 * order
      if (rightValue === null || rightValue === undefined) return order

      const comparison = String(leftValue).localeCompare(String(rightValue), 'zh-Hant', {
        numeric: true,
        sensitivity: 'base',
      })
      if (comparison !== 0) return comparison * order
    }
    if (sortMeta.some(({ field }) => field === 'contributor_level')) {
      return left.name.localeCompare(right.name, 'zh-Hant', { sensitivity: 'base' })
    }
    return 0
  })
}

const sortedUsers = computed(() => sortRecords(filteredUsers.value, userSortMeta.value))
const paginatedUsers = computed(() =>
  sortedUsers.value.slice(userFirst.value, userFirst.value + userRows.value)
)

const filteredNotifications = computed(() => {
  let filtered = notifications.value

  if (notificationSearchQuery.value) {
    const query = notificationSearchQuery.value.toLowerCase()
    filtered = filtered.filter(
      (notification) =>
        notification.title.toLowerCase().includes(query) ||
        notification.body.toLowerCase().includes(query)
    )
  }

  if (notificationSeverityFilter.value) {
    filtered = filtered.filter(
      (notification) => notification.severity === notificationSeverityFilter.value
    )
  }

  return filtered.map((notification) => {
    const effectiveOrder = isNotificationEffective(notification) ? 1 : 0
    return {
      ...notification,
      effectiveOrder,
    }
  })
})

const sortedNotifications = computed(() =>
  sortRecords(filteredNotifications.value, notificationSortMeta.value)
)
const paginatedNotifications = computed(() =>
  sortedNotifications.value.slice(
    notificationFirst.value,
    notificationFirst.value + notificationRows.value
  )
)

const updatePaginator = (event, firstRef, rowsRef) => {
  rowsRef.value = event.rows
  firstRef.value = Math.max(0, event.first)
}

const handleCoursePage = (event) => updatePaginator(event, courseFirst, courseRows)
const handleUserPage = (event) => updatePaginator(event, userFirst, userRows)
const handleNotificationPage = (event) =>
  updatePaginator(event, notificationFirst, notificationRows)

const handleUserSort = (event) => {
  userSortMeta.value = event.multiSortMeta || []
  userFirst.value = 0
}

const handleNotificationSort = (event) => {
  notificationSortMeta.value = event.multiSortMeta || []
  notificationFirst.value = 0
}

const clampPaginatorFirst = (firstRef, rowsRef, totalRecords) => {
  const lastFirst =
    totalRecords > 0 ? Math.floor((totalRecords - 1) / rowsRef.value) * rowsRef.value : 0
  firstRef.value = Math.min(Math.max(0, firstRef.value), lastFirst)
}

watch([searchQuery, filterCategory], () => {
  courseFirst.value = 0
})
watch([userSearchQuery, filterUserType, selectedContributorLevels], () => {
  userFirst.value = 0
})
watch([notificationSearchQuery, notificationSeverityFilter], () => {
  notificationFirst.value = 0
})
watch([() => filteredCourses.value.length, courseRows], ([totalRecords]) => {
  clampPaginatorFirst(courseFirst, courseRows, totalRecords)
})
watch([() => sortedUsers.value.length, userRows], ([totalRecords]) => {
  clampPaginatorFirst(userFirst, userRows, totalRecords)
})
watch([() => sortedNotifications.value.length, notificationRows], ([totalRecords]) => {
  clampPaginatorFirst(notificationFirst, notificationRows, totalRecords)
})

const loadCategories = async () => {
  try {
    const response = await courseService.listAdminCategories()
    courseCategories.value = Array.isArray(response.data) ? response.data : []
  } catch (error) {
    console.error('載入課程分類失敗:', error)
    if (isUnauthorizedError(error)) return
    toast.add({
      severity: 'error',
      summary: '錯誤',
      detail: '載入課程分類失敗',
      life: 3000,
    })
  }
}

const loadCourses = async () => {
  coursesLoading.value = true
  courseLoadError.value = ''
  try {
    const [categoryResponse, courseResponse] = await Promise.all([
      courseService.listAdminCategories(),
      courseService.getAllCourses(),
    ])
    if (!Array.isArray(categoryResponse.data) || !Array.isArray(courseResponse.data)) {
      throw new TypeError('Invalid course management response')
    }
    courseCategories.value = categoryResponse.data
    const courseList = courseResponse.data
    courses.value = courseList.map((course) => ({
      ...course,
      name: formatCourseDisplayName(course?.name),
    }))
  } catch (error) {
    console.error('載入課程失敗:', error)
    const unauthorized = isUnauthorizedError(error)
    courseLoadError.value = unauthorized
      ? '登入階段已過期，請重新登入後再載入課程資料。'
      : '課程資料載入失敗，請稍後再試或查看伺服器日誌。'
    if (unauthorized) {
      return
    }
    toast.add({
      severity: 'error',
      summary: '錯誤',
      detail: '載入課程失敗',
      life: 3000,
    })
  } finally {
    coursesLoading.value = false
  }
}

const loadUsers = async () => {
  usersLoading.value = true
  userStatsLoadError.value = ''
  try {
    await loadContributorLevelSettings()
    const response = await getUsers()
    if (!Array.isArray(response.data)) {
      throw new TypeError('Invalid users response')
    }
    users.value = response.data.map((user) => {
      const contributorLevel = resolveSubmissionLevel(user.contributor_experience)
      return {
        ...user,
        contributorLevel,
        contributor_level: contributorLevel.level,
      }
    })
  } catch (error) {
    console.error('載入使用者失敗:', error)
    const unauthorized = isUnauthorizedError(error)
    userStatsLoadError.value = unauthorized
      ? '登入階段已過期，請重新登入後再載入使用者統計。'
      : '使用者統計載入失敗，請稍後再試或查看伺服器日誌。'
    if (unauthorized) {
      return
    }
    toast.add({
      severity: 'error',
      summary: '錯誤',
      detail: '載入使用者失敗',
      life: 3000,
    })
  } finally {
    usersLoading.value = false
  }
}

const activeOnlineRangeKey = () =>
  userInsightsView.value === 'login-hour' ? `${loginRangeHours.value}h` : `${loginRangeDays.value}d`

const loadOnlineStatistics = async () => {
  if (userInsightsView.value === 'level') return
  const requestId = ++onlineStatisticsRequestId
  onlineStatisticsLoading.value = true
  onlineStatisticsError.value = ''
  try {
    const expectedRange = activeOnlineRangeKey()
    const expectedConfig = activeLoginBucketConfig.value
    const { data } = await getOnlineStatistics(expectedRange)
    if (requestId !== onlineStatisticsRequestId) return
    if (
      !data ||
      data.range !== expectedRange ||
      data.bucket_minutes !== expectedConfig.bucketMinutes ||
      !Array.isArray(data.points) ||
      data.points.length !== expectedConfig.bucketCount ||
      data.points.some(
        (point) =>
          !point?.start ||
          !point?.end ||
          !point?.at ||
          !Number.isInteger(point?.count) ||
          point.count < 0 ||
          typeof point.has_data !== 'boolean'
      )
    ) {
      throw new TypeError('Invalid online statistics response')
    }
    onlineStatistics.value = data
  } catch (error) {
    if (requestId !== onlineStatisticsRequestId) return
    console.error('載入在線統計失敗:', error)
    onlineStatistics.value = null
    onlineStatisticsError.value = isUnauthorizedError(error)
      ? '登入階段已過期，請重新登入後再載入在線統計。'
      : '在線統計載入失敗，請稍後再試或查看伺服器日誌。'
  } finally {
    if (requestId === onlineStatisticsRequestId) onlineStatisticsLoading.value = false
  }
}

const reloadUserStatistics = async () => {
  await Promise.all([loadUsers(), loadOnlineStatistics()])
}

const loadNotifications = async () => {
  notificationsLoading.value = true
  try {
    const { data } = await notificationService.getAllAdmin()
    notifications.value = Array.isArray(data) ? data : []
  } catch (error) {
    console.error('載入公告失敗:', error)
    if (isUnauthorizedError(error)) {
      return
    }
    toast.add({
      severity: 'error',
      summary: '錯誤',
      detail: '載入公告失敗',
      life: 3000,
    })
  } finally {
    notificationsLoading.value = false
  }
}

const loadReviewItems = async () => {
  reviewLoading.value = true
  reviewLoadError.value = ''
  try {
    const [categoryResponse, allCoursesResponse, archiveResponse] = await Promise.all([
      courseService.listAdminCategories(),
      getCourses(),
      archiveService.listAdminSubmissions(),
    ])
    courseCategories.value = Array.isArray(categoryResponse.data) ? categoryResponse.data : []
    courses.value = Array.isArray(allCoursesResponse.data) ? allCoursesResponse.data : []
    archiveRequests.value = Array.isArray(archiveResponse.data) ? archiveResponse.data : []
  } catch (error) {
    console.error('載入審核資料失敗:', error)
    reviewLoadError.value = '審核資料載入失敗，請稍後再試或查看伺服器日誌。'
    if (isUnauthorizedError(error)) {
      return
    }
    toast.add({
      severity: 'error',
      summary: '錯誤',
      detail: '載入審核資料失敗',
      life: 3000,
    })
  } finally {
    reviewLoading.value = false
  }
}

const loadReviewSubmissionStatistics = async () => {
  const requestId = ++reviewSubmissionStatisticsRequestId
  reviewSubmissionStatisticsLoading.value = true
  reviewSubmissionStatisticsError.value = ''
  try {
    const expectedMode = reviewSubmissionView.value
    const expectedRange = activeReviewSubmissionRangeKey()
    const expectedConfig = activeReviewSubmissionBucketConfig.value
    const { data } = await archiveService.getSubmissionStatistics(expectedRange, expectedMode)
    if (requestId !== reviewSubmissionStatisticsRequestId) return
    const points = data?.points
    const counts = Array.isArray(points) ? points.map(({ count }) => count) : []
    const total = counts.reduce((sum, count) => sum + count, 0)
    const peak = Math.max(0, ...counts)
    const expectedAverage = Number((total / expectedConfig.bucketCount).toFixed(1))
    if (
      data?.mode !== expectedMode ||
      data?.range !== expectedRange ||
      data?.timezone !== PRODUCT_TIME_ZONE ||
      data?.bucket_minutes !== expectedConfig.bucketMinutes ||
      !data?.range_start ||
      !data?.range_end ||
      !Array.isArray(points) ||
      points.length !== expectedConfig.bucketCount ||
      points.some(
        (point) =>
          !point?.start ||
          !point?.end ||
          !Number.isFinite(Date.parse(point.start)) ||
          !Number.isFinite(Date.parse(point.end)) ||
          Date.parse(point.start) >= Date.parse(point.end) ||
          !Number.isInteger(point?.count) ||
          point.count < 0
      ) ||
      !Number.isInteger(data?.summary?.total) ||
      !Number.isInteger(data?.summary?.peak) ||
      typeof data?.summary?.average !== 'number' ||
      data?.summary?.total !== total ||
      data?.summary?.peak !== peak ||
      data?.summary?.average !== expectedAverage
    ) {
      throw new TypeError('Invalid review submission statistics response')
    }
    reviewSubmissionStatistics.value = data
  } catch (error) {
    if (requestId !== reviewSubmissionStatisticsRequestId) return
    console.error('載入投稿統計失敗:', error)
    reviewSubmissionStatistics.value = null
    reviewSubmissionStatisticsError.value = isUnauthorizedError(error)
      ? '登入階段已過期，請重新登入後再載入投稿統計。'
      : '投稿統計載入失敗，請稍後再試或查看伺服器日誌。'
  } finally {
    if (requestId === reviewSubmissionStatisticsRequestId) {
      reviewSubmissionStatisticsLoading.value = false
    }
  }
}

const reloadReviewCenter = async () => {
  await Promise.all([loadReviewItems(), loadReviewSubmissionStatistics()])
}

const loadTrashItems = async () => {
  trashLoading.value = true
  try {
    const filterType = getTrashFilterApiValue(trashFilterType.value)
    const isDefaultFilter = filterType === null
    showTrashRelationHierarchy.value = isDefaultFilter
    if (isDefaultFilter) {
      trashSortState.value = { key: null, direction: 'asc' }
    }
    if (filterType !== trashFilterType.value) {
      trashFilterType.value = filterType
    }
    const { data } = await archiveService.listTrashItems(filterType)
    const items = Array.isArray(data) ? data : Array.isArray(data?.items) ? data.items : []
    trashItems.value = items.filter((item) => item && typeof item === 'object')
  } catch (error) {
    console.error('載入垃圾桶失敗:', error)
    if (isUnauthorizedError(error)) return
    toast.add({
      severity: 'error',
      summary: '錯誤',
      detail: getTrashErrorMessage(error, '垃圾桶載入失敗'),
      life: 3500,
    })
  } finally {
    trashLoading.value = false
  }
}

const formatTrashDeletedAt = (value) => {
  return formatRelativeOrAbsoluteDateTime(value)
}

const getTrashSemesterText = (item) => {
  if (!['archive', 'archive_submission'].includes(item?.item_type)) return ''
  if (!item.academic_term) return '學期：—'
  return `學期：${item.academic_term}`
}

const getTrashSemesterValue = (item) => {
  if (!['archive', 'archive_submission'].includes(item?.item_type)) return ''
  return item?.academic_term || '—'
}

const getTrashStatusLabel = (statusValue, itemType = null) => {
  if (['system_issue_report', 'comment_report', 'archive_report'].includes(itemType)) {
    return '已刪除'
  }
  const normalized = normalizeSubmissionStatus(statusValue || 'deleted')
  const labels = {
    pending: '待審核',
    approved: '已通過',
    rejected: '已退回',
    takedown: '已下架',
    deleted: '已刪除',
  }
  return labels[normalized] || '已刪除'
}

const getTrashStatusSeverity = (statusValue, itemType = null) => {
  if (['system_issue_report', 'comment_report', 'archive_report'].includes(itemType))
    return 'danger'
  const normalized = normalizeSubmissionStatus(statusValue || 'deleted')
  if (normalized === 'approved') return 'success'
  if (normalized === 'pending') return 'warning'
  if (normalized === 'takedown') return 'secondary'
  return 'danger'
}

const getTrashStatusClass = (statusValue, itemType = null) => {
  if (['system_issue_report', 'comment_report', 'archive_report'].includes(itemType)) {
    return 'review-status-deleted'
  }
  return getSubmissionStatusClass(statusValue)
}

const getTrashDeletedByLabel = (item) => {
  return item?.deleted_by_name || (item?.deleted_by_id ? `使用者 #${item.deleted_by_id}` : '—')
}

const getTrashDependencies = (item) => {
  const dependencies = Array.isArray(item?.dependencies) ? item.dependencies.filter(Boolean) : []
  return dependencies
    .map((dependency) => formatTrashDependency(dependency, item?.item_type))
    .filter((item) => item?.label)
    .filter((dependency) => String(dependency?.label || '').trim())
    .sort((a, b) => {
      if (a.restoreBlocking !== b.restoreBlocking) {
        return a.restoreBlocking ? -1 : 1
      }
      if (a.deleteBlocking !== b.deleteBlocking) {
        return a.deleteBlocking ? -1 : 1
      }
      if (a.kindOrder !== b.kindOrder) {
        return a.kindOrder - b.kindOrder
      }
      return a.label.localeCompare(b.label)
    })
}

const canRestoreTrashItem = (item) => {
  if (item?.canRestore === false) return false
  if (item?.canRestore === true) return true
  return !getTrashDependencyHasRestoreBlocker(item)
}

const canPermanentDeleteTrashItem = (item) => {
  if (item?.canPermanentDelete === false) return false
  if (item?.canPermanentDelete === true) return true
  return !getTrashDependencyHasPermanentDeleteBlocker(item)
}

const getTrashDependencyHasRestoreBlocker = (item) => {
  return getTrashDependencies(item).some((dependency) =>
    String(dependency?.label || '').startsWith('阻擋還原：')
  )
}

const getTrashDependencyHasPermanentDeleteBlocker = (item) => {
  return getTrashDependencies(item).some((dependency) =>
    String(dependency?.label || '').startsWith('阻擋永久刪除：')
  )
}

const getTrashDependencySeverity = (dependency) => {
  return dependency?.severity || 'secondary'
}

const getTrashDependencyChipClass = (dependency) => {
  const label = String(dependency?.label || '')
  if (dependency?.restoreBlocking || label.startsWith('阻擋還原：'))
    return 'trash-dependency-chip--restore-blocked'
  if (dependency?.deleteBlocking || label.startsWith('阻擋永久刪除：'))
    return 'trash-dependency-chip--delete-blocked'
  if (label.startsWith('一併永久刪除：')) return 'trash-dependency-chip--cascade'
  if (label === '無阻擋') return 'trash-dependency-chip--clear'
  return 'trash-dependency-chip--relation'
}

const formatSubmissionLabel = (item) => {
  if (!item || item.id === null || item.id === undefined) {
    return '—'
  }
  return `#${item.id}`
}

const getTrashSubmissionLabel = (item) => {
  if (!['archive', 'archive_submission'].includes(item?.item_type)) return ''
  const submissionId =
    item?.source_submission_id || (item?.item_type === 'archive_submission' ? item?.id : null)
  return submissionId ? `投稿編號：#${submissionId}` : '投稿編號：—'
}

const getTrashSubmissionValue = (item) => {
  if (!['archive', 'archive_submission'].includes(item?.item_type)) return ''
  const submissionId =
    item?.source_submission_id || (item?.item_type === 'archive_submission' ? item?.id : null)
  return submissionId ? `#${submissionId}` : '—'
}

const getTrashContextLabel = (item) => {
  const line = getTrashContextLine(item)
  if (!line) return ''
  const separatorIndex = line.indexOf('：')
  return separatorIndex > 0 ? line.slice(0, separatorIndex) : '關聯'
}

const getTrashContextValue = (item) => {
  const line = getTrashContextLine(item)
  if (!line) return ''
  const separatorIndex = line.indexOf('：')
  return separatorIndex > 0 ? line.slice(separatorIndex + 1) : line
}

const getTrashMobileMetadata = (item) => {
  const metadata = []
  const submissionLabel = getTrashSubmissionLabel(item)
  const semesterValue = getTrashSemesterValue(item)
  const contextLine = getTrashContextLine(item)

  if (submissionLabel) {
    metadata.push({ key: 'submission', label: '投稿編號', value: getTrashSubmissionValue(item) })
  }
  if (semesterValue) {
    metadata.push({ key: 'semester', label: '學期', value: semesterValue })
  }
  if (contextLine) {
    metadata.push({
      key: 'context',
      label: getTrashContextLabel(item),
      value: getTrashContextValue(item),
      startNewRow: Boolean(submissionLabel && semesterValue),
    })
  }
  getTrashReportDetails(item).forEach((detail, index) => {
    metadata.push({ key: `report-${index}-${detail.label}`, ...detail })
  })
  metadata.push(
    { key: 'deleted-by', label: '刪除者', value: getTrashDeletedByLabel(item) },
    { key: 'deleted-at', label: '刪除時間', value: formatTrashDeletedAt(item?.deleted_at) }
  )

  return metadata
}

const applyDependencyCount = (label, count) => {
  if (label.includes('{count}')) return label.replace('{count}', count)
  return `${count} 筆${label}`
}

const formatTrashDependency = (dependency, itemType = '') => {
  if (!dependency) return null

  if (typeof dependency === 'object') {
    const count = Number(dependency.count || 0) || 1
    const normalizedKind = String(dependency.kind || '').toLowerCase()
    const typeRaw = String(dependency.type || '').toLowerCase()
    const typeLabel = String(dependency.label || '').trim() || ''

    if (['active', 'blocking', 'blocking_live', 'blockingActive'].includes(normalizedKind)) {
      const label = typeLabel || getFallbackRelationLabel(typeRaw, 'active', itemType)
      return {
        key: `blocking-${typeRaw || 'dependency'}-${count}`,
        label: `阻擋永久刪除：${applyDependencyCount(label, count)}`,
        severity: 'danger',
        blocking: true,
        deleteBlocking: true,
        restoreBlocking: false,
        kindOrder: 1,
      }
    }

    if (['trashed', 'deleted', 'soft_deleted'].includes(normalizedKind)) {
      const label = typeLabel || getFallbackRelationLabel(typeRaw, 'trashed', itemType)
      return {
        key: `trashed-${typeRaw || 'dependency'}-${count}`,
        label: `一併永久刪除：${applyDependencyCount(label, count)}`,
        severity: 'info',
        blocking: false,
        restoreBlocking: false,
        deleteBlocking: false,
        kindOrder: 1,
      }
    }
  }

  const raw = String(dependency || '').trim()
  if (!raw) return null

  if (raw.startsWith('阻擋永久刪除：')) {
    return {
      key: `blocking-${raw}`,
      label: raw,
      severity: 'danger',
      blocking: true,
      restoreBlocking: false,
      deleteBlocking: true,
      kindOrder: 1,
    }
  }

  if (raw.startsWith('阻擋還原：')) {
    return {
      key: `restore-blocking-${raw}`,
      label: raw,
      severity: 'warning',
      blocking: true,
      restoreBlocking: true,
      deleteBlocking: false,
      kindOrder: 0,
    }
  }

  if (raw.startsWith('無法復原：')) {
    return {
      key: `restore-blocking-${raw}`,
      label: `阻擋還原：${raw.replace('無法復原：', '')}`,
      severity: 'warning',
      blocking: true,
      restoreBlocking: true,
      deleteBlocking: false,
      kindOrder: 0,
    }
  }

  if (raw.startsWith('一併永久刪除：')) {
    return {
      key: `trashed-${raw}`,
      label: raw,
      severity: 'info',
      blocking: false,
      restoreBlocking: false,
      deleteBlocking: false,
      kindOrder: 1,
    }
  }

  if (
    raw.startsWith('關聯考古題：') ||
    raw.startsWith('關聯投稿：') ||
    raw.startsWith('隨投稿永久刪除：') ||
    raw === '關聯考古題仍啟用中'
  ) {
    return {
      key: `relation-${raw}`,
      label: raw,
      severity: 'secondary',
      blocking: false,
      restoreBlocking: false,
      deleteBlocking: false,
      kindOrder: 2,
    }
  }

  const value = raw.toLowerCase()
  const countMatch = raw.match(/(\d+)/)
  const count = countMatch ? Number(countMatch[1]) : 1

  const isActive = value.includes('active') || value.includes('啟用')
  const isTrashed =
    value.includes('trashed') ||
    value.includes('deleted') ||
    value.includes('已刪除') ||
    value.includes('刪除')
  const isSubmission = value.includes('submission')
  const isCourse = value.includes('course') || value.includes('課程')
  const isArchive = value.includes('archive') || value.includes('考古題')
  const isCategory = value.includes('category') || value.includes('分類')
  const isComment = value.includes('comment') || value.includes('留言')

  const relationLabel = (() => {
    if (isSubmission) {
      return isActive || isTrashed ? '投稿' : '相關投稿'
    }
    if (isCourse) return '課程'
    if (isArchive) return '考古題'
    if (isCategory) return '分類'
    if (isComment) return '留言'
    return '關聯資料'
  })()

  if (value.includes('linked archive')) {
    if (isActive) {
      return {
        key: `relation-${raw}`,
        label: '關聯：此項目仍關聯到考古題（未刪除）',
        severity: 'secondary',
        blocking: false,
        restoreBlocking: false,
        deleteBlocking: false,
        kindOrder: 2,
      }
    }
    if (isTrashed) {
      return {
        key: `relation-${raw}`,
        label: '一併永久刪除：關聯考古題已刪除',
        severity: 'info',
        blocking: false,
        restoreBlocking: false,
        deleteBlocking: false,
        kindOrder: 1,
      }
    }
  }

  if (value.includes('linked archive submissions')) {
    return {
      key: `relation-${raw}`,
      label: `關聯：此項目與考古題的其他投稿有 ${count} 筆關聯（不一定阻擋）`,
      severity: 'secondary',
      blocking: false,
      restoreBlocking: false,
      deleteBlocking: false,
      kindOrder: 2,
    }
  }

  const blockerLabel = (() => {
    if (itemType === 'archive') {
      return isSubmission
        ? `1 筆啟用中投稿引用此考古題`
        : isCourse
          ? `啟用中課程依附此課程`
          : isArchive
            ? `啟用中考古題依附`
            : `啟用中${relationLabel}`
    }
    if (itemType === 'course') {
      return isArchive
        ? `啟用中考古題依附此課程`
        : isSubmission
          ? `啟用中投稿依附此分類`
          : `啟用中${relationLabel}`
    }
    if (itemType === 'course_category') {
      return isCourse
        ? `啟用中課程依附此分類`
        : isSubmission
          ? `啟用中投稿依附此分類`
          : `啟用中${relationLabel}`
    }
    return `啟用中${relationLabel}`
  })()

  const cascadeLabel = (() => {
    if (itemType === 'archive') {
      return isSubmission
        ? `1 筆已刪除投稿連到此考古題`
        : isComment
          ? `考古題留言 ${count} 筆已在垃圾桶`
          : `已刪除${relationLabel}`
    }
    if (itemType === 'course') {
      return isArchive ? `${count} 筆已刪除考古題屬於此課程` : `已刪除${relationLabel}`
    }
    if (itemType === 'course_category') {
      return isCourse ? `${count} 門已刪除課程屬於此分類` : `已刪除${relationLabel}`
    }
    return `已刪除${relationLabel} ${count} 筆`
  })()

  if (isActive) {
    return {
      key: `blocking-${raw}`,
      label: `阻擋永久刪除：${blockerLabel.replace('1 筆', `${count} 筆`)}`,
      severity: 'danger',
      blocking: true,
      restoreBlocking: false,
      deleteBlocking: true,
      kindOrder: 1,
    }
  }

  if (isTrashed) {
    return {
      key: `trashed-${raw}`,
      label: `一併永久刪除：${cascadeLabel}`,
      severity: 'info',
      blocking: false,
      restoreBlocking: false,
      deleteBlocking: false,
      kindOrder: 1,
    }
  }

  return {
    key: `relation-${raw}`,
    label: `關聯：${relationLabel}${count ? ` ${count} 筆` : ''}`,
    severity: 'secondary',
    blocking: false,
    restoreBlocking: false,
    deleteBlocking: false,
    kindOrder: 2,
  }
}

const getFallbackRelationLabel = (typeRaw, kind, itemType) => {
  const t = typeRaw.toLowerCase()
  const isSubmission = t.includes('submission') || t.includes('投稿')
  const isCourse = t.includes('course') || t.includes('課程')
  const isArchive = t.includes('archive') || t.includes('考古題')

  if (kind === 'active') {
    if (itemType === 'archive' && isSubmission) return '{count} 筆啟用中投稿仍連到此考古題'
    if (itemType === 'course' && isArchive) return '{count} 筆啟用中考古題仍屬於此課程'
    if (itemType === 'course_category' && isCourse) return '{count} 門啟用中課程仍屬於此分類'
    if (isSubmission) return '{count} 筆啟用中投稿仍關聯此項目'
    if (isCourse) return '{count} 門啟用中課程仍關聯此項目'
    if (isArchive) return '{count} 筆啟用中考古題仍關聯此項目'
    return '{count} 筆啟用中關聯資料仍關聯此項目'
  }

  if (itemType === 'archive' && isSubmission) return '{count} 筆已刪除投稿連到此考古題'
  if (itemType === 'course' && isArchive) return '{count} 筆已刪除考古題屬於此課程'
  if (itemType === 'course_category' && isCourse) return '{count} 門已刪除課程屬於此分類'
  if (isSubmission) return '{count} 筆已刪除投稿關聯此項目'
  if (isCourse) return '{count} 門已刪除課程關聯此項目'
  if (isArchive) return '{count} 筆已刪除考古題關聯此項目'
  return '{count} 筆已刪除關聯資料關聯此項目'
}

const getTrashErrorMessage = (error, fallback = '操作失敗') => {
  const detail = error?.response?.data?.detail
  if (!detail) return fallback
  if (typeof detail === 'string') return detail
  if (detail.message) return detail.message
  if (Array.isArray(detail.blockingDependencies) && detail.blockingDependencies.length) {
    return '仍有依賴資料阻擋此操作'
  }
  return fallback
}

const getTrashBulkResultMessage = (data) => {
  const deletedCount = Number(data?.deleted_count ?? data?.deleted ?? 0)
  const failedCount = Number(data?.failed_count ?? data?.failed ?? 0)
  if (deletedCount > 0 && failedCount > 0)
    return `已永久刪除 ${deletedCount} 筆，${failedCount} 筆失敗`
  if (deletedCount > 0) return `已永久刪除 ${deletedCount} 筆`
  if (failedCount > 0) return `${failedCount} 筆永久刪除失敗`
  return '沒有可永久刪除的項目'
}

const confirmRestoreTrashItem = (item) => {
  confirm.require({
    message: `確定要還原「${item.display_name}」嗎？`,
    header: '確認還原',
    icon: 'pi pi-undo',
    accept: () => restoreTrashItem(item),
  })
}

const restoreTrashItem = async (item) => {
  try {
    const { data } = await archiveService.restoreTrashItem(item.item_type, item.id)
    toast.add({
      severity: 'success',
      summary: '已還原',
      detail: data?.message || '項目已還原',
      life: 3500,
    })
    await loadTrashItems()
  } catch (error) {
    console.error('還原垃圾桶項目失敗:', error)
    if (isUnauthorizedError(error)) return
    toast.add({
      severity: 'error',
      summary: '還原失敗',
      detail: getTrashErrorMessage(error, '項目還原失敗'),
      life: 4000,
    })
  }
}

const confirmPermanentDeleteTrashItem = (item) => {
  confirm.require({
    message: `確定要永久刪除「${item.display_name}」嗎？永久刪除後無法復原。`,
    header: '確認永久刪除',
    icon: 'pi pi-exclamation-triangle',
    acceptClass: 'p-button-danger',
    accept: () => permanentlyDeleteTrashItem(item),
  })
}

const permanentlyDeleteTrashItem = async (item) => {
  try {
    const { data } = await archiveService.permanentlyDeleteTrashItem(item.item_type, item.id)
    const deletedCount = Number(data?.deleted_count ?? data?.deleted ?? 1)
    toast.add({
      severity: 'success',
      summary: '已永久刪除',
      detail: `已永久刪除 ${deletedCount} 筆`,
      life: 3000,
    })
    await loadTrashItems()
  } catch (error) {
    console.error('永久刪除垃圾桶項目失敗:', error)
    if (isUnauthorizedError(error)) return
    toast.add({
      severity: 'error',
      summary: '永久刪除失敗',
      detail: getTrashErrorMessage(error, '永久刪除失敗'),
      life: 4500,
    })
  }
}

const confirmBulkDeleteTrash = () => {
  const scopeLabel =
    trashFilterOptions.find((option) => option.value === trashFilterType.value)?.label || '全部'
  confirm.require({
    message: `確定要永久刪除「${scopeLabel}」範圍內的垃圾桶項目嗎？此動作無法復原。`,
    header: '確認清空目前範圍',
    icon: 'pi pi-exclamation-triangle',
    acceptClass: 'p-button-danger',
    accept: bulkDeleteTrashScope,
  })
}

const bulkDeleteTrashScope = async () => {
  try {
    const scopeType = getTrashFilterApiValue(trashFilterType.value)
    const { data } = await archiveService.permanentlyDeleteTrashScope(scopeType)
    const deletedCount = Number(data?.deleted_count ?? data?.deleted ?? 0)
    const failedCount = Number(data?.failed_count ?? data?.failed ?? 0)
    if (deletedCount > 0) {
      toast.add({
        severity: failedCount ? 'warn' : 'success',
        summary: failedCount ? '部分完成' : '已清空',
        detail: getTrashBulkResultMessage(data),
        life: 4500,
      })
    } else {
      toast.add({
        severity: failedCount ? 'error' : 'info',
        summary: failedCount ? '清空失敗' : '沒有項目',
        detail: getTrashBulkResultMessage(data),
        life: 4500,
      })
    }
    await loadTrashItems()
  } catch (error) {
    console.error('清空垃圾桶範圍失敗:', error)
    if (isUnauthorizedError(error)) return
    toast.add({
      severity: 'error',
      summary: '清空失敗',
      detail: getTrashErrorMessage(error, '清空目前範圍失敗'),
      life: 4500,
    })
  }
}

const openArchiveRequestDialog = async (request) => {
  selectedArchiveRequest.value = request
  archiveRequestEditForm.value = {
    subject: request.subject,
    category: request.category,
    name: request.name,
    academic_year: request.academic_year,
    archive_type: request.archive_type,
    professor: request.professor,
    has_answers: Boolean(request.has_answers),
    requested_course_name: request.requested_course_name || '',
    requested_category_key: request.requested_category_key || '',
    requested_category_name: request.requested_category_name || '',
    requested_category_label: request.requested_category_label || '',
    requested_category_icon: request.requested_category_icon || 'pi pi-fw pi-book',
  }
  showArchiveRequestDialog.value = true
  await Promise.all([loadArchiveComparison(request), loadArchiveRequesterStats(request)])
}

const saveArchiveRequestEdit = async () => {
  if (!selectedArchiveRequest.value) return
  if (!canEditSelectedArchiveRequest.value) {
    toast.add({
      severity: 'info',
      summary: '僅能查看',
      detail: archiveRequestReadonlyMessage.value || '此投稿目前不能編輯。',
      life: 3000,
    })
    return
  }
  reviewEditLoading.value = true
  try {
    const { data } = await archiveService.updateSubmission(
      selectedArchiveRequest.value.id,
      archiveRequestEditForm.value
    )
    selectedArchiveRequest.value = data
    toast.add({ severity: 'success', summary: '成功', detail: '考古題投稿已更新', life: 3000 })
    await loadReviewItems()
    await loadArchiveComparison(data)
  } catch (error) {
    console.error('更新考古題投稿失敗:', error)
    if (isUnauthorizedError(error)) return
    toast.add({ severity: 'error', summary: '錯誤', detail: '考古題投稿更新失敗', life: 3000 })
  } finally {
    reviewEditLoading.value = false
  }
}

const previewArchiveRequestFile = async () => {
  if (!selectedArchiveRequest.value?.id) return
  archiveRequestPreviewLoading.value = true
  archiveRequestPreviewError.value = false
  try {
    if (archiveRequestPreviewUrl.value) {
      URL.revokeObjectURL(archiveRequestPreviewUrl.value)
      archiveRequestPreviewUrl.value = ''
    }
    const { data } = await archiveService.getSubmissionPreviewFile(selectedArchiveRequest.value.id)
    archiveRequestPreviewUrl.value = URL.createObjectURL(
      new Blob([data], { type: 'application/pdf' })
    )
    showArchiveRequestPreview.value = true
  } catch (error) {
    console.error('預覽投稿 PDF 失敗:', error)
    archiveRequestPreviewError.value = true
    if (isUnauthorizedError(error)) return
    toast.add({ severity: 'error', summary: '預覽失敗', detail: '無法載入投稿 PDF', life: 3000 })
  } finally {
    archiveRequestPreviewLoading.value = false
  }
}

const closeArchiveRequestPreview = () => {
  showArchiveRequestPreview.value = false
  archiveRequestPreviewError.value = false
  if (archiveRequestPreviewUrl.value) {
    URL.revokeObjectURL(archiveRequestPreviewUrl.value)
    archiveRequestPreviewUrl.value = ''
  }
}

const handleArchiveRequestPreviewError = () => {
  archiveRequestPreviewError.value = true
}

const revokeComparePreviewUrls = () => {
  if (compareRequestPreviewUrl.value) {
    URL.revokeObjectURL(compareRequestPreviewUrl.value)
    compareRequestPreviewUrl.value = ''
  }
  if (compareArchivePreviewUrl.value) {
    URL.revokeObjectURL(compareArchivePreviewUrl.value)
    compareArchivePreviewUrl.value = ''
  }
}

const openComparePreview = async (comparison) => {
  if (!selectedArchiveRequest.value?.id || !comparison?.id) return
  comparePreviewArchive.value = comparison
  comparePreviewLoading.value = true
  comparePreviewError.value = false
  revokeComparePreviewUrls()
  showComparePreview.value = true

  try {
    const [requestResponse, comparisonResponse] = await Promise.all([
      archiveService.getSubmissionPreviewFile(selectedArchiveRequest.value.id),
      archiveService.getSubmissionPreviewFile(comparison.id),
    ])
    compareRequestPreviewUrl.value = URL.createObjectURL(
      new Blob([requestResponse.data], { type: 'application/pdf' })
    )
    compareArchivePreviewUrl.value = URL.createObjectURL(
      new Blob([comparisonResponse.data], { type: 'application/pdf' })
    )
  } catch (error) {
    console.error('載入比對 PDF 失敗:', error)
    comparePreviewError.value = true
    if (isUnauthorizedError(error)) return
    toast.add({ severity: 'error', summary: '預覽失敗', detail: '無法載入比對 PDF', life: 3000 })
  } finally {
    comparePreviewLoading.value = false
  }
}

const closeComparePreview = () => {
  showComparePreview.value = false
  comparePreviewArchive.value = null
  comparePreviewError.value = false
  comparePreviewLoading.value = false
  revokeComparePreviewUrls()
}

const loadArchiveComparison = async (request) => {
  comparisonArchives.value = []
  if (!request?.id) return

  comparisonLoading.value = true
  try {
    const { data } = await archiveService.listSubmissionComparisons(request.id)
    comparisonArchives.value = Array.isArray(data) ? data : []
  } catch (error) {
    console.error('載入比對資料失敗:', error)
    if (isUnauthorizedError(error)) return
    toast.add({ severity: 'error', summary: '錯誤', detail: '比對資料載入失敗', life: 3000 })
  } finally {
    comparisonLoading.value = false
  }
}

const clearArchiveRequesterStats = () => {
  archiveRequesterStatsController?.abort()
  archiveRequesterStatsController = null
  archiveRequesterStats.value = null
  archiveRequesterStatsLoading.value = false
  archiveRequesterStatsError.value = ''
}

const loadArchiveRequesterStats = async (request) => {
  clearArchiveRequesterStats()
  if (!request?.requester_id) {
    archiveRequesterStatsError.value = '找不到投稿者資料'
    return
  }

  const controller = new AbortController()
  archiveRequesterStatsController = controller
  archiveRequesterStatsLoading.value = true
  try {
    const { data } = await getUserSubmissionStats(request.requester_id, {
      includeRecords: false,
      signal: controller.signal,
    })
    if (archiveRequesterStatsController === controller) {
      archiveRequesterStats.value = data
    }
  } catch (error) {
    if (error?.code === 'ERR_CANCELED') return
    if (archiveRequesterStatsController === controller) {
      archiveRequesterStatsError.value =
        error?.response?.status === 404 ? '找不到投稿者資料' : '投稿者統計載入失敗'
    }
  } finally {
    if (archiveRequesterStatsController === controller) {
      archiveRequesterStatsLoading.value = false
      archiveRequesterStatsController = null
    }
  }
}

const getComparisonBasisText = (item) => {
  const course = item?.requested_course_name || item?.subject || '—'
  const exam = item?.name || '—'
  const professor = item?.professor || '—'
  const semester = formatAcademicTerm(item?.academic_year) || '—'
  return `比對基準：課程 ${course}｜考試 ${exam}｜教師 ${professor}｜學期 ${semester}`
}

const formatComparisonSubmissionId = (item) => {
  return item?.id ? `#${item.id}` : '—'
}

const canTakedownComparisonItem = (item) => {
  return (
    item?.can_takedown === true &&
    ['pending', 'approved'].includes(normalizeSubmissionStatus(item?.status))
  )
}

const confirmTakedownComparisonItem = (item) => {
  if (!canTakedownComparisonItem(item) || !item?.id) return
  confirm.require({
    message: '確定要下架這筆比對項目嗎？',
    header: '確認下架',
    icon: 'pi pi-exclamation-triangle',
    acceptLabel: '下架',
    rejectLabel: '取消',
    accept: () => takedownComparisonItem(item),
  })
}

const takedownComparisonItem = async (item) => {
  if (!item?.id) return
  try {
    await archiveService.takedownSubmission(item.id)
    toast.add({ severity: 'success', summary: '完成', detail: '已下架', life: 3000 })
    await loadReviewItems()
    await loadArchiveComparison(selectedArchiveRequest.value)
  } catch (error) {
    console.error('下架比對項目失敗:', error)
    if (isUnauthorizedError(error)) return
    toast.add({
      severity: 'error',
      summary: '錯誤',
      detail: getTrashErrorMessage(error, '下架比對項目失敗'),
      life: 3000,
    })
  }
}

const getRequesterDisplay = (request) => {
  if (!request) return '未知帳號'
  return request.requester_name || request.requester_email || `使用者 #${request.requester_id}`
}

const reviewArchiveSubmission = async (submission, action) => {
  if (!submission?.id) return
  if (isReadonlyReviewSubmission(submission) && action !== 'republish') {
    toast.add({
      severity: 'info',
      summary: '僅能查看',
      detail: getReadonlyReviewSubmissionMessage(submission) || '此投稿目前不能變更審核狀態。',
      life: 3000,
    })
    return
  }
  try {
    if (action === 'approve') {
      await archiveService.approveSubmission(submission.id)
    } else if (action === 'takedown') {
      await archiveService.takedownSubmission(submission.id)
    } else if (action === 'republish') {
      await archiveService.republishSubmission(submission.id)
    } else {
      await archiveService.rejectSubmission(submission.id)
    }
    const actionMessages = {
      approve: '考古題投稿已通過',
      reject: '考古題投稿已退回',
      takedown: '考古題投稿已下架',
      republish: '考古題投稿已重新上架',
    }
    toast.add({
      severity: 'success',
      summary: '完成',
      detail: actionMessages[action] || '考古題投稿狀態已更新',
      life: 3000,
    })
    await loadReviewItems()
    showArchiveRequestDialog.value = false
  } catch (error) {
    console.error('審核考古題投稿失敗:', error)
    if (isUnauthorizedError(error)) return
    toast.add({
      severity: 'error',
      summary: '錯誤',
      detail: getTrashErrorMessage(error, '審核考古題投稿失敗'),
      life: 3000,
    })
  }
}

const confirmDeleteArchiveSubmission = (submission) => {
  if (!submission?.id) return
  confirm.require({
    message: `確定要刪除「${submission.subject} / ${submission.name}」這筆投稿紀錄嗎？`,
    header: '確認刪除投稿紀錄',
    icon: 'pi pi-exclamation-triangle',
    accept: () => deleteArchiveSubmissionAction(submission),
  })
}

const deleteArchiveSubmissionAction = async (submission) => {
  try {
    await archiveService.deleteSubmission(submission.id)
    toast.add({
      severity: 'success',
      summary: '已刪除',
      detail: '投稿紀錄已刪除',
      life: 3000,
    })
    if (selectedArchiveRequest.value?.id === submission.id) {
      showArchiveRequestDialog.value = false
      selectedArchiveRequest.value = null
    }
    await loadReviewItems()
  } catch (error) {
    console.error('刪除考古題投稿失敗:', error)
    if (isUnauthorizedError(error)) return
    toast.add({ severity: 'error', summary: '錯誤', detail: '投稿紀錄刪除失敗', life: 3000 })
  }
}

const openCreateDialog = () => {
  courseForm.value = {
    name: '',
    category: '',
  }
  courseFormErrors.value = {}
  editingCourse.value = null
  showCourseDialog.value = true
  trackEvent(EVENTS.CREATE_COURSE, { action: 'open-dialog' })
}

const openEditDialog = (course) => {
  courseForm.value = {
    name: course.name,
    category: course.category,
  }
  courseFormErrors.value = {}
  editingCourse.value = course
  showCourseDialog.value = true
  trackEvent(EVENTS.UPDATE_COURSE, { action: 'open-dialog', courseName: course.name })
}

const closeCourseDialog = () => {
  showCourseDialog.value = false
  courseForm.value = {
    name: '',
    category: '',
  }
  courseFormErrors.value = {}
  editingCourse.value = null
}

const validateCourseForm = () => {
  const errors = {}

  if (!courseForm.value.name.trim()) {
    errors.name = '課程名稱是必填欄位'
  }

  if (!courseForm.value.category) {
    errors.category = '分類是必填欄位'
  }

  courseFormErrors.value = errors
  return Object.keys(errors).length === 0
}

const saveCourse = async () => {
  if (!validateCourseForm()) return

  saveLoading.value = true
  try {
    if (editingCourse.value) {
      await updateCourse(editingCourse.value.id, courseForm.value)
      trackEvent(EVENTS.UPDATE_COURSE, {
        action: 'submit',
        courseName: courseForm.value.name,
        category: courseForm.value.category,
      })
      toast.add({
        severity: 'success',
        summary: '成功',
        detail: '課程更新成功',
        life: 3000,
      })
    } else {
      await createCourse(courseForm.value)
      trackEvent(EVENTS.CREATE_COURSE, {
        action: 'submit',
        courseName: courseForm.value.name,
        category: courseForm.value.category,
      })
      toast.add({
        severity: 'success',
        summary: '成功',
        detail: '課程新增成功',
        life: 3000,
      })
    }
    closeCourseDialog()
    await loadCourses()
  } catch (error) {
    console.error('儲存課程失敗:', error)
    if (isUnauthorizedError(error)) {
      return
    }
    toast.add({
      severity: 'error',
      summary: '錯誤',
      detail: editingCourse.value ? '課程更新失敗' : '課程新增失敗',
      life: 3000,
    })
  } finally {
    saveLoading.value = false
  }
}

const confirmDeleteCourse = (course) => {
  confirm.require({
    message: `確定要刪除課程「${course.name}」嗎？`,
    header: '刪除確認',
    icon: 'pi pi-exclamation-triangle',
    rejectClass: 'p-button-secondary p-button-outlined',
    acceptClass: 'p-button-danger',
    rejectLabel: '取消',
    acceptLabel: '刪除',
    accept: () => deleteCourseAction(course),
  })
}

const deleteCourseAction = async (course) => {
  try {
    await deleteCourse(course.id)
    trackEvent(EVENTS.DELETE_COURSE, {
      courseName: course.name,
      category: course.category,
    })
    toast.add({
      severity: 'success',
      summary: '成功',
      detail: '課程刪除成功',
      life: 3000,
    })
    await loadCourses()
  } catch (error) {
    console.error('刪除課程失敗:', error)
    if (isUnauthorizedError(error)) {
      return
    }
    toast.add({
      severity: 'error',
      summary: '錯誤',
      detail: '課程刪除失敗',
      life: 3000,
    })
  }
}

const openCreateCategoryDialog = () => {
  categoryForm.value = {
    key: '',
    name: '',
    label: '',
    icon: 'pi pi-fw pi-book',
    badge_color: DEFAULT_CATEGORY_BADGE_COLOR,
  }
  categoryFormErrors.value = {}
  editingCategory.value = null
  showCategoryDialog.value = true
}

const openEditCategoryDialog = (category) => {
  categoryForm.value = {
    key: category.key,
    name: category.name,
    label: category.label || '',
    icon: category.icon || 'pi pi-fw pi-book',
    badge_color: getCategoryBadgeColor(category),
  }
  categoryFormErrors.value = {}
  editingCategory.value = category
  showCategoryDialog.value = true
}

const closeCategoryDialog = () => {
  showCategoryDialog.value = false
  editingCategory.value = null
  categoryForm.value = {
    key: '',
    name: '',
    label: '',
    icon: 'pi pi-fw pi-book',
    badge_color: DEFAULT_CATEGORY_BADGE_COLOR,
  }
  categoryFormErrors.value = {}
}

const validateCategoryForm = () => {
  const errors = {}
  if (!categoryForm.value.key.trim()) {
    errors.key = '分類 Key 是必填欄位'
  } else if (!/^[a-z0-9-]+$/.test(categoryForm.value.key.trim())) {
    errors.key = '只能使用小寫英文字母、數字與連字號'
  }
  if (!categoryForm.value.name.trim()) {
    errors.name = '顯示名稱是必填欄位'
  }
  categoryFormErrors.value = errors
  return Object.keys(errors).length === 0
}

const saveCategory = async () => {
  if (!validateCategoryForm()) return

  categorySaveLoading.value = true
  try {
    const payload = {
      key: categoryForm.value.key.trim(),
      name: categoryForm.value.name.trim(),
      label: categoryForm.value.label.trim(),
      icon: categoryForm.value.icon.trim() || 'pi pi-fw pi-book',
      badge_color: getCategoryBadgeColor(categoryForm.value),
    }
    if (editingCategory.value) {
      await courseService.updateCategory(editingCategory.value.id, payload)
    } else {
      await courseService.createCategory(payload)
    }
    toast.add({
      severity: 'success',
      summary: '成功',
      detail: editingCategory.value ? '分類更新成功' : '分類新增成功',
      life: 3000,
    })
    closeCategoryDialog()
    await loadCourses()
  } catch (error) {
    console.error('儲存分類失敗:', error)
    if (isUnauthorizedError(error)) return
    toast.add({ severity: 'error', summary: '錯誤', detail: '分類儲存失敗', life: 3000 })
  } finally {
    categorySaveLoading.value = false
  }
}

const confirmToggleCategory = (category) => {
  const nextActive = !category.is_active
  confirm.require({
    message: `確定要${nextActive ? '啟用' : '停用'}分類「${category.name}」嗎？`,
    header: `${nextActive ? '啟用' : '停用'}分類`,
    icon: 'pi pi-exclamation-triangle',
    rejectClass: 'p-button-secondary p-button-outlined',
    acceptClass: nextActive ? 'p-button-success' : 'p-button-warning',
    rejectLabel: '取消',
    acceptLabel: nextActive ? '啟用' : '停用',
    accept: () => toggleCategoryActive(category, nextActive),
  })
}

const toggleCategoryActive = async (category, isActive) => {
  try {
    await courseService.setCategoryActive(category.id, isActive)
    toast.add({
      severity: 'success',
      summary: '成功',
      detail: `分類已${isActive ? '啟用' : '停用'}`,
      life: 3000,
    })
    await loadCourses()
  } catch (error) {
    console.error('更新分類狀態失敗:', error)
    if (isUnauthorizedError(error)) return
    toast.add({
      severity: 'error',
      summary: '錯誤',
      detail: error?.response?.data?.detail || '分類狀態更新失敗',
      life: 3000,
    })
  }
}

const confirmDeleteCategory = (category) => {
  confirm.require({
    message: `確定要刪除分類「${category.name}」嗎？刪除後將進入垃圾桶。`,
    header: '刪除分類',
    icon: 'pi pi-exclamation-triangle',
    rejectClass: 'p-button-secondary p-button-outlined',
    acceptClass: 'p-button-danger',
    rejectLabel: '取消',
    acceptLabel: '刪除',
    accept: () => deleteCategoryAction(category),
  })
}

const deleteCategoryAction = async (category) => {
  try {
    await courseService.deleteCategory(category.id)
    toast.add({ severity: 'success', summary: '成功', detail: '分類已移到垃圾桶', life: 3000 })
    await loadCourses()
  } catch (error) {
    console.error('刪除分類失敗:', error)
    if (isUnauthorizedError(error)) return
    toast.add({
      severity: 'error',
      summary: '錯誤',
      detail: error?.response?.data?.detail || '分類刪除失敗',
      life: 3000,
    })
  }
}

const openCreateUserDialog = () => {
  userForm.value = {
    name: '',
    email: '',
    password: '',
    is_admin: false,
  }
  userFormErrors.value = {}
  editingUser.value = null
  showUserDialog.value = true
  trackEvent(EVENTS.CREATE_USER, { action: 'open-dialog' })
}

const openEditUserDialog = (user) => {
  userForm.value = {
    name: user.name,
    email: user.email,
    password: '',
    is_admin: user.is_admin,
  }
  userFormErrors.value = {}
  editingUser.value = user
  showUserDialog.value = true
  trackEvent(EVENTS.UPDATE_USER, { action: 'open-dialog', userName: user.name })
}

const closeUserDialog = () => {
  showUserDialog.value = false
  userForm.value = {
    name: '',
    email: '',
    password: '',
    is_admin: false,
  }
  userFormErrors.value = {}
  editingUser.value = null
}

const closeResetPasswordDialog = () => {
  showResetPasswordDialog.value = false
  resetPasswordUser.value = null
  resetPasswordForm.value = {
    newPassword: '',
    confirmPassword: '',
  }
  resetPasswordFormErrors.value = {}
  resetPasswordLoading.value = false
}

const openResetPasswordDialog = (user) => {
  if (!user?.is_local) return

  resetPasswordUser.value = user
  resetPasswordForm.value = {
    newPassword: '',
    confirmPassword: '',
  }
  resetPasswordFormErrors.value = {}
  showResetPasswordDialog.value = true
}

const validateResetPasswordForm = () => {
  const errors = {}
  const newPassword = (resetPasswordForm.value.newPassword || '').trim()
  const confirmPassword = (resetPasswordForm.value.confirmPassword || '').trim()

  if (!newPassword) {
    errors.newPassword = '新密碼是必填欄位'
  } else if (newPassword.length < USER_PASSWORD_MIN_LENGTH) {
    errors.newPassword = `新密碼至少 ${USER_PASSWORD_MIN_LENGTH} 字`
  }

  if (!confirmPassword) {
    errors.confirmPassword = '請再次輸入新密碼'
  } else if (confirmPassword !== newPassword) {
    errors.confirmPassword = '兩次輸入的密碼不一致'
  }

  resetPasswordFormErrors.value = errors
  return Object.keys(errors).length === 0
}

const resetPassword = async () => {
  if (!validateResetPasswordForm()) return
  if (!resetPasswordUser.value?.is_local || !resetPasswordUser.value?.id) return

  resetPasswordLoading.value = true
  try {
    const payload = {
      new_password: (resetPasswordForm.value.newPassword || '').trim(),
    }

    await resetUserPassword(resetPasswordUser.value.id, payload)

    toast.add({
      severity: 'success',
      summary: '成功',
      detail: `使用者 ${getResetPasswordTargetLabel(resetPasswordUser.value)} 的密碼已更新。`,
      life: 3000,
    })

    closeResetPasswordDialog()
    await loadUsers()
  } catch (error) {
    console.error('重設密碼失敗:', error)
    if (isUnauthorizedError(error)) {
      return
    }
    toast.add({
      severity: 'error',
      summary: '錯誤',
      detail: `重設密碼失敗：${error?.response?.data?.detail || '請稍後再試'}`,
      life: 3500,
    })
  } finally {
    resetPasswordLoading.value = false
  }
}
const validateUserForm = () => {
  const errors = {}

  if (!userForm.value.name.trim()) {
    errors.name = '使用者名稱是必填欄位'
  }

  if (!userForm.value.email.trim()) {
    errors.email = '電子郵件是必填欄位'
  } else if (!/\S+@\S+\.\S+/.test(userForm.value.email)) {
    errors.email = '電子郵件格式不正確'
  }

  if (!editingUser.value && !userForm.value.password.trim()) {
    errors.password = '密碼是必填欄位'
  }

  userFormErrors.value = errors
  return Object.keys(errors).length === 0
}

const saveUser = async () => {
  if (!validateUserForm()) return

  userSaveLoading.value = true
  try {
    if (editingUser.value) {
      const updateData = {
        name: userForm.value.name,
        email: userForm.value.email,
        is_admin: userForm.value.is_admin,
      }
      if (userForm.value.password.trim()) {
        updateData.password = userForm.value.password
      }
      await updateUser(editingUser.value.id, updateData)
      trackEvent(EVENTS.UPDATE_USER, {
        action: 'submit',
        userName: userForm.value.name,
        isAdmin: userForm.value.is_admin,
      })
      toast.add({
        severity: 'success',
        summary: '成功',
        detail: '使用者更新成功',
        life: 3000,
      })
    } else {
      await createUser(userForm.value)
      trackEvent(EVENTS.CREATE_USER, {
        action: 'submit',
        userName: userForm.value.name,
        isAdmin: userForm.value.is_admin,
      })
      toast.add({
        severity: 'success',
        summary: '成功',
        detail: '使用者新增成功',
        life: 3000,
      })
    }
    closeUserDialog()
    await loadUsers()
  } catch (error) {
    console.error('儲存使用者失敗:', error)
    if (isUnauthorizedError(error)) {
      return
    }
    toast.add({
      severity: 'error',
      summary: '錯誤',
      detail: editingUser.value ? '使用者更新失敗' : '使用者新增失敗',
      life: 3000,
    })
  } finally {
    userSaveLoading.value = false
  }
}

const confirmDeleteUser = (user) => {
  confirm.require({
    message: `確定要刪除使用者「${user.name}」嗎？`,
    header: '刪除確認',
    icon: 'pi pi-exclamation-triangle',
    rejectClass: 'p-button-secondary p-button-outlined',
    acceptClass: 'p-button-danger',
    rejectLabel: '取消',
    acceptLabel: '刪除',
    accept: () => deleteUserAction(user),
  })
}

const deleteUserAction = async (user) => {
  try {
    await deleteUser(user.id)
    trackEvent(EVENTS.DELETE_USER, {
      userName: user.name,
      isAdmin: user.is_admin,
    })
    toast.add({
      severity: 'success',
      summary: '成功',
      detail: '使用者刪除成功',
      life: 3000,
    })
    await loadUsers()
  } catch (error) {
    console.error('刪除使用者失敗:', error)
    if (isUnauthorizedError(error)) {
      return
    }
    toast.add({
      severity: 'error',
      summary: '錯誤',
      detail: '使用者刪除失敗',
      life: 3000,
    })
  }
}

const openNotificationCreateDialog = () => {
  resetNotificationForm()
  showNotificationDialog.value = true
  trackEvent(EVENTS.CREATE_NOTIFICATION, { action: 'open-dialog' })
}

const openNotificationEditDialog = (notification) => {
  notificationForm.value = {
    title: notification.title,
    body: notification.body,
    severity: notification.severity,
    is_active: notification.is_active,
    starts_at: toDate(notification.starts_at),
    ends_at: toDate(notification.ends_at),
  }
  notificationFormErrors.value = {}
  editingNotification.value = notification
  showNotificationDialog.value = true
  trackEvent(EVENTS.UPDATE_NOTIFICATION, {
    action: 'open-dialog',
    notificationId: notification.id,
  })
}

const closeNotificationDialog = () => {
  showNotificationDialog.value = false
  resetNotificationForm()
}

const validateNotificationForm = () => {
  const errors = {}

  if (!notificationForm.value.title.trim()) {
    errors.title = '公告標題是必填欄位'
  }

  if (!notificationForm.value.body.trim()) {
    errors.body = '公告內容是必填欄位'
  }

  if (notificationForm.value.starts_at && notificationForm.value.ends_at) {
    if (notificationForm.value.ends_at.getTime() < notificationForm.value.starts_at.getTime()) {
      errors.ends_at = '結束時間需晚於生效時間'
    }
  }

  notificationFormErrors.value = errors
  return Object.keys(errors).length === 0
}

const saveNotification = async () => {
  if (!validateNotificationForm()) {
    return
  }

  notificationSaveLoading.value = true
  const payload = {
    title: notificationForm.value.title.trim(),
    body: notificationForm.value.body.trim(),
    severity: notificationForm.value.severity,
    is_active: notificationForm.value.is_active,
    starts_at: notificationForm.value.starts_at
      ? notificationForm.value.starts_at.toISOString()
      : null,
    ends_at: notificationForm.value.ends_at ? notificationForm.value.ends_at.toISOString() : null,
  }

  try {
    if (editingNotification.value) {
      await notificationService.update(editingNotification.value.id, payload)
      trackEvent(EVENTS.UPDATE_NOTIFICATION, {
        action: 'submit',
        notificationId: editingNotification.value.id,
      })
      toast.add({
        severity: 'success',
        summary: '成功',
        detail: '公告更新成功',
        life: 3000,
      })
    } else {
      await notificationService.create(payload)
      trackEvent(EVENTS.CREATE_NOTIFICATION, { action: 'submit' })
      toast.add({
        severity: 'success',
        summary: '成功',
        detail: '公告新增成功',
        life: 3000,
      })
    }
    closeNotificationDialog()
    await loadNotifications()
  } catch (error) {
    console.error('儲存公告失敗:', error)
    if (isUnauthorizedError(error)) {
      return
    }
    toast.add({
      severity: 'error',
      summary: '錯誤',
      detail: editingNotification.value ? '公告更新失敗' : '公告新增失敗',
      life: 3000,
    })
  } finally {
    notificationSaveLoading.value = false
  }
}

const confirmDeleteNotification = (notification) => {
  confirm.require({
    message: `確定要刪除公告「${notification.title}」嗎？`,
    header: '刪除確認',
    icon: 'pi pi-exclamation-triangle',
    rejectClass: 'p-button-secondary p-button-outlined',
    acceptClass: 'p-button-danger',
    rejectLabel: '取消',
    acceptLabel: '刪除',
    accept: () => deleteNotificationAction(notification),
  })
}

const deleteNotificationAction = async (notification) => {
  try {
    await notificationService.remove(notification.id)
    trackEvent(EVENTS.DELETE_NOTIFICATION, { notificationId: notification.id })
    toast.add({
      severity: 'success',
      summary: '成功',
      detail: '公告刪除成功',
      life: 3000,
    })
    await loadNotifications()
  } catch (error) {
    console.error('刪除公告失敗:', error)
    if (isUnauthorizedError(error)) {
      return
    }
    toast.add({
      severity: 'error',
      summary: '錯誤',
      detail: '公告刪除失敗',
      life: 3000,
    })
  }
}

const formatDateTime = (dateString) => {
  if (!dateString) return '從未登入'
  return formatRelativeOrAbsoluteDateTime(dateString)
}

// Persist the current tab in localStorage
const saveTabToStorage = (tabValue) => {
  try {
    setLocalItem(TAB_STORAGE_KEY, tabValue)
  } catch (e) {
    console.error('Failed to save tab to storage:', e)
  }
}

const loadTabData = async (value) => {
  const tab = String(value)
  await loadCategories()

  if (tab === '0') {
    await loadCourses()
    return
  }

  if (tab === '1') {
    await reloadUserStatistics()
    return
  }

  if (tab === '2') {
    await loadNotifications()
    return
  }

  if (tab === '3') {
    await reloadReviewCenter()
    return
  }

  if (tab === '4') {
    await loadTrashItems()
    return
  }

  if (tab === '5') return
}

const handleTabChange = (value) => {
  const tabValue = String(value)
  currentTab.value = tabValue
  saveTabToStorage(tabValue)

  const tabNames = {
    0: 'courses',
    1: 'users',
    2: 'notifications',
    3: 'reviews',
    4: 'trash',
    5: 'reports',
  }

  trackEvent(EVENTS.SWITCH_TAB, {
    tab: tabNames[tabValue] || tabValue,
  })
}

watch(
  currentTab,
  async (value) => {
    await loadTabData(value)
  },
  { immediate: true }
)

const refreshOnlineStatistics = () => {
  if (currentTab.value === '1' && userInsightsView.value !== 'level') {
    void loadOnlineStatistics()
  }
}

const scheduleLoginStatsRefresh = () => {
  if (loginStatsRefreshTimer !== null) window.clearTimeout(loginStatsRefreshTimer)
  const now = new Date()
  const bucketMinutes = activeLoginBucketConfig.value.bucketMinutes
  const nextHour = new Date(now)
  const nextBucketMinute = (Math.floor(now.getMinutes() / bucketMinutes) + 1) * bucketMinutes
  nextHour.setMinutes(nextBucketMinute, 0, 50)
  loginStatsRefreshTimer = window.setTimeout(
    () => {
      refreshOnlineStatistics()
      scheduleLoginStatsRefresh()
    },
    Math.max(1000, nextHour.getTime() - now.getTime())
  )
}

const updateStatisticsFontScale = () => {
  if (typeof document === 'undefined') return
  const scale = Number.parseFloat(
    window.getComputedStyle(document.documentElement).getPropertyValue('--app-font-scale')
  )
  statisticsFontScale.value = Number.isFinite(scale) && scale > 0 ? scale : 1
}

const observeStatisticsChartElement = (current, previous) => {
  if (!statisticsChartResizeObserver) return
  if (previous) statisticsChartResizeObserver.unobserve(previous)
  if (current) statisticsChartResizeObserver.observe(current)
}

watch(userStatisticsChartElement, observeStatisticsChartElement)
watch(reviewSubmissionChartElement, observeStatisticsChartElement)

onMounted(() => {
  if (typeof window === 'undefined') return
  updateStatisticsFontScale()
  if (typeof ResizeObserver !== 'undefined') {
    statisticsChartResizeObserver = new ResizeObserver((entries) => {
      entries.forEach((entry) => {
        const width = Math.max(0, Math.round(entry.contentRect.width))
        if (entry.target === userStatisticsChartElement.value) {
          userStatisticsChartWidth.value = width
        }
        if (entry.target === reviewSubmissionChartElement.value) {
          reviewSubmissionChartWidth.value = width
        }
      })
    })
    if (userStatisticsChartElement.value) {
      statisticsChartResizeObserver.observe(userStatisticsChartElement.value)
    }
    if (reviewSubmissionChartElement.value) {
      statisticsChartResizeObserver.observe(reviewSubmissionChartElement.value)
    }
  }
  if (typeof MutationObserver !== 'undefined') {
    statisticsFontScaleObserver = new MutationObserver(updateStatisticsFontScale)
    statisticsFontScaleObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-app-font-scale'],
    })
  }
  window.addEventListener('focus', refreshOnlineStatistics)
  scheduleLoginStatsRefresh()
})

onBeforeUnmount(() => {
  if (typeof window !== 'undefined') {
    window.removeEventListener('focus', refreshOnlineStatistics)
    if (loginStatsRefreshTimer !== null) window.clearTimeout(loginStatsRefreshTimer)
  }
  statisticsChartResizeObserver?.disconnect()
  statisticsFontScaleObserver?.disconnect()
  userSubmissionStatsController?.abort()
  archiveRequesterStatsController?.abort()
  closeArchiveRequestPreview()
  closeComparePreview()
})
</script>

<style scoped>
.admin-container {
  background: var(--p-tabs-tabpanel-background);
  min-width: 0;
  max-width: 100%;
  overflow-x: hidden;
}

.card {
  background-color: var(--bg-primary);
  min-width: 0;
  max-width: 100%;
}

:deep(.p-tabs) {
  background: var(--p-tabs-tabpanel-background);
  min-width: 0;
  max-width: 100%;
}

:deep(.p-tabpanels),
:deep(.p-tabpanel) {
  min-width: 0;
  max-width: 100%;
  overflow-x: hidden;
}

:deep(.p-tabview-header) {
  background: var(--bg-primary);
}

:deep(.p-tabview-content) {
  background: var(--bg-primary);
  padding: 0;
}

:deep(.p-datatable) {
  background: var(--bg-primary);
  max-width: 100%;
  overflow-x: auto;
}

:deep(.p-datatable-table-container) {
  max-width: 100%;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}

:deep(.p-datatable-thead > tr > th) {
  background: var(--bg-primary);
  border-color: var(--border-color);
}

:deep(.p-datatable-tbody > tr > td) {
  background: var(--bg-primary);
  border-color: var(--border-color);
}

:deep(.p-dialog) {
  background: var(--bg-primary);
}

:deep(.p-dialog-header) {
  background: var(--bg-primary);
  border-color: var(--border-color);
}

:deep(.p-dialog-content) {
  background: var(--bg-primary);
}

.search-icon {
  position: absolute;
  left: 1rem;
  top: 50%;
  margin-top: -0.5rem;
}

.relative {
  position: relative;
}

.search-container {
  display: flex;
  gap: 1rem;
  align-items: center;
  flex-wrap: wrap;
}

.review-search-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
  flex-wrap: wrap;
  margin-bottom: 1rem;
}

.review-search-toolbar .search-container {
  display: flex;
  align-items: center;
  gap: 1rem;
  flex-wrap: wrap;
  flex: 1 1 auto;
  min-width: 0;
}

.review-refresh-button {
  margin-left: auto;
  white-space: nowrap;
  min-height: 2.45rem;
  padding-top: 0.55rem;
  padding-bottom: 0.55rem;
}

:deep(.review-refresh-button .p-button-label) {
  font-size: 0.95rem;
  font-weight: 600;
}

.admin-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  width: 100%;
  min-width: 0;
}

.admin-insights-card {
  container: admin-insights / inline-size;
  display: grid;
  gap: 0.7rem;
  margin-bottom: 1rem;
  padding: 0.85rem;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  background: var(--bg-primary);
  color: var(--text-color);
}

.user-insights.admin-insights-card {
  row-gap: 0.5rem;
}

.admin-insights-card .chart-summary-item {
  align-content: center;
  justify-items: center;
  text-align: center;
}

.contributor-level-insights {
  margin-top: 1rem;
}

.contributor-level-insights__heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.6rem 1rem;
  color: var(--text-color);
}

.contributor-level-insights__heading h3,
.contributor-level-insights__heading p {
  margin: 0;
}

.contributor-level-insights__heading h3 {
  font-size: 1rem;
}

.contributor-level-insights__heading p {
  margin-top: 0.12rem;
  color: var(--text-secondary);
  font-size: 0.78rem;
}

.contributor-level-insights__grid {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
  min-width: 0;
}

.contributor-level-insights__actions {
  display: flex;
  min-width: 0;
  align-items: center;
  justify-content: flex-end;
  gap: 0.4rem 0.6rem;
}

:deep(.contributor-level-settings-button.p-button) {
  min-height: 2.25rem;
  padding: 0.28rem 0.52rem;
  gap: 0.28rem;
  font-size: var(--app-font-size-xs) !important;
}

:deep(.contributor-level-settings-button .p-button-icon),
:deep(.contributor-level-settings-button .p-button-label) {
  font-size: inherit !important;
}

.contributor-level-toggle {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  gap: 0.35rem;
  min-height: 2rem;
  padding: 0.32rem 0.6rem;
  border: 0;
  border-radius: 6px;
  background: transparent;
  box-shadow: none;
  color: var(--text-color);
  cursor: pointer;
  font: inherit;
  font-size: 0.78rem;
  font-weight: 700;
  white-space: nowrap;
}

.contributor-level-toggle:hover {
  background: color-mix(in srgb, var(--primary-color) 7%, transparent);
}

.contributor-level-toggle:focus-visible {
  outline: 2px solid var(--primary-color);
  outline-offset: 2px;
}

.section-collapse-toggle {
  border: 0;
  background: transparent;
  box-shadow: none;
}

.section-collapse-toggle:hover {
  background: color-mix(in srgb, var(--primary-color) 7%, transparent);
}

.section-collapse-toggle:focus-visible {
  outline: 2px solid var(--primary-color);
  outline-offset: 2px;
}

.contributor-level-stat {
  display: inline-flex;
  flex: 0 0 auto;
  width: max-content;
  max-width: 100%;
  min-width: 0;
  align-items: center;
  gap: 0.25rem;
  min-height: 2.35rem;
  padding: 0.28rem 0.32rem;
  border: 1px solid var(--border-color);
  border-radius: 7px;
  background: var(--bg-primary);
  color: var(--text-color);
  cursor: pointer;
  font: inherit;
  text-align: left;
}

.contributor-level-stat:hover,
.contributor-level-stat:focus-visible {
  border-color: var(--primary-color);
}

.contributor-level-stat:focus-visible {
  outline: 2px solid var(--primary-color);
  outline-offset: 2px;
}

.contributor-level-stat.is-active {
  border-color: var(--primary-color);
  box-shadow: inset 0 0 0 1px var(--primary-color);
  background: color-mix(in srgb, var(--primary-color) 10%, var(--bg-primary));
}

.contributor-level-stat__name {
  min-width: 0;
  overflow: hidden;
  font-size: 0.68rem;
  font-weight: 650;
  line-height: 1.2;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.contributor-level-stat :deep(.contributor-level--compact .contributor-level__badge) {
  min-width: calc(2.9rem * var(--app-font-scale));
  padding: calc(0.12rem * var(--app-font-scale)) calc(0.34rem * var(--app-font-scale));
  font-size: var(--app-font-size-xs);
}

.user-table-contributor-level {
  color: var(--text-color);
  font-size: var(--app-font-size-sm);
  white-space: nowrap;
}

.admin-mobile-list--users .mobile-user-level-tag {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  min-width: 0;
  padding: 0.18rem 0.38rem;
  border: 1px solid var(--border-color);
  border-radius: 5px;
  background: var(--bg-primary);
  color: var(--text-primary);
  font-size: var(--app-badge-font-size);
  font-weight: 700;
  line-height: 1.2;
  white-space: nowrap;
}

:deep(.user-management-table .p-datatable-thead > tr > th:first-child),
:deep(.user-management-table .p-datatable-tbody > tr > td:first-child) {
  width: clamp(7.5rem, calc(7.5rem * var(--app-font-scale)), 10.5rem);
  min-width: clamp(7.5rem, calc(7.5rem * var(--app-font-scale)), 10.5rem);
  max-width: clamp(7.5rem, calc(7.5rem * var(--app-font-scale)), 10.5rem);
  white-space: nowrap;
}

:deep(
  .user-management-table .p-datatable-thead > tr > th:first-child .p-datatable-column-header-content
) {
  gap: 0.3rem;
}

.user-insights__heading,
.user-insights__actions,
.user-insights__switch,
.user-insights__range {
  display: flex;
  align-items: center;
}

.user-insights__heading {
  justify-content: space-between;
  gap: 0.6rem 1rem;
}

.user-insights__heading h3,
.user-insights__heading p,
.user-insights__panel p {
  margin: 0;
}

.user-insights__heading h3 {
  color: var(--text-color);
  font-size: 1rem;
}

.user-insights__heading p,
.user-insights__description {
  color: var(--text-secondary);
  font-size: 0.78rem;
  line-height: 1.4;
}

.user-insights__actions,
.user-insights__range,
.user-insights__switch {
  flex-wrap: wrap;
  gap: 0.35rem;
}

.user-insights__switch,
.user-insights__range {
  padding: 0.16rem;
  border: 1px solid var(--border-color);
  border-radius: 7px;
  background: var(--bg-primary);
}

.user-insights__switch button,
.user-insights__range button,
.user-insights__toggle {
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  font: inherit;
  font-size: 0.75rem;
  font-weight: 650;
}

.user-insights__switch button,
.user-insights__range button {
  padding: 0.34rem 0.55rem;
}

.user-insights__switch button.is-active,
.user-insights__range button.is-active {
  background: color-mix(in srgb, var(--p-primary-color) 15%, var(--bg-primary));
  color: var(--p-primary-color);
}

.user-insights__toggle {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  min-height: 2rem;
  padding: 0.35rem 0.5rem;
}

.user-insights__switch button:focus-visible,
.user-insights__range button:focus-visible,
.user-insights__toggle:focus-visible {
  outline: 2px solid var(--p-primary-color);
  outline-offset: 2px;
}

.user-insights__panel {
  display: grid;
  gap: 0.65rem;
  min-width: 0;
  padding-top: 0.2rem;
}

.user-level-chart {
  display: grid;
  gap: 0.42rem;
  min-width: 0;
  max-height: 18rem;
  overflow-y: auto;
  padding: 0.15rem 0.2rem 0.15rem 0;
}

.user-login-column-chart {
  --temporal-edge-padding: clamp(1rem, calc(1.35rem * var(--app-font-scale)), 2rem);
  display: grid;
  grid-template-columns: 2rem minmax(0, 1fr);
  gap: 0.45rem;
  min-width: 0;
  height: clamp(13rem, 28vw, 18rem);
  padding-top: 0.35rem;
  color: var(--text-color);
  font-size: var(--app-font-size-xs);
}

.user-login-column-chart__y-axis {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  height: calc(100% - 2.55rem);
  color: var(--text-secondary);
  text-align: right;
}

.user-login-column-chart__plot {
  position: relative;
  min-width: 0;
  height: 100%;
  overflow: hidden;
  border-left: 1px solid var(--border-color);
  border-bottom: 1px solid var(--border-color);
}

.user-login-column-chart__grid,
.user-login-column-chart__bars {
  position: absolute;
  inset: 0 0 2.55rem;
}

.user-login-column-chart__grid {
  pointer-events: none;
}

.user-login-column-chart__grid span {
  position: absolute;
  right: 0;
  left: 0;
  border-top: 1px solid color-mix(in srgb, var(--border-color) 70%, transparent);
}

.user-login-column-chart__bars,
.user-login-column-chart__x-axis {
  display: grid;
  grid-template-columns: repeat(var(--login-chart-columns), minmax(0, 1fr));
}

.user-login-column-chart__bars {
  box-sizing: border-box;
  z-index: 1;
  align-items: end;
  gap: clamp(1px, 0.25vw, 3px);
  padding: 0 var(--temporal-edge-padding);
}

.user-login-column-chart__item {
  position: relative;
  display: flex;
  min-width: 0;
  height: 100%;
  align-items: flex-end;
  justify-content: center;
  outline: none;
}

.user-login-column-chart__item:hover,
.user-login-column-chart__item:focus-visible {
  z-index: 3;
}

.user-login-column-chart__tooltip {
  position: absolute;
  top: 0.35rem;
  left: 50%;
  width: max-content;
  max-width: min(22rem, calc(100vw - 3rem));
  padding: 0.3rem 0.45rem;
  border: 1px solid var(--border-color);
  border-radius: 5px;
  background: var(--bg-secondary);
  color: var(--text-primary);
  font-size: var(--app-font-size-xs);
  line-height: 1.35;
  overflow-wrap: anywhere;
  pointer-events: none;
  opacity: 0;
  transform: translateX(-50%);
  transition: opacity 120ms ease;
}

.user-login-column-chart__item:hover .user-login-column-chart__tooltip,
.user-login-column-chart__item:focus-visible .user-login-column-chart__tooltip {
  opacity: 1;
}

.user-login-column-chart__item:first-child .user-login-column-chart__tooltip {
  left: 0;
  transform: none;
}

.user-login-column-chart__item:last-child .user-login-column-chart__tooltip {
  right: 0;
  left: auto;
  transform: none;
}

@media (prefers-reduced-motion: reduce) {
  .user-login-column-chart__tooltip {
    transition: none;
  }
}

.user-login-column-chart__item:focus-visible {
  border-radius: 3px;
  box-shadow: inset 0 0 0 2px var(--p-primary-color);
}

.user-login-column-chart__bar {
  display: block;
  width: 100%;
  min-height: 0;
  border-radius: 4px 4px 1px 1px;
  background: transparent;
}

.user-login-column-chart__bar.has-value {
  min-height: 2px;
  background: var(--p-primary-color);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--p-primary-color) 60%, transparent);
}

.user-login-column-chart__x-axis {
  position: absolute;
  right: 0;
  bottom: 0;
  left: 0;
  box-sizing: border-box;
  height: 2.5rem;
  align-items: start;
  gap: 1px;
  padding: 0.35rem var(--temporal-edge-padding) 0;
  color: var(--text-secondary);
  text-align: center;
}

.user-login-column-chart__x-axis > span {
  min-width: 0;
  overflow: visible;
  font-size: var(--app-font-size-xs);
  line-height: 1.1;
  white-space: nowrap;
}

.user-login-column-chart__x-axis > span > span {
  display: block;
}

.user-level-chart__track {
  height: 0.72rem;
  overflow: hidden;
  border: 1px solid var(--border-color);
  border-radius: 999px;
  background: color-mix(in srgb, var(--border-color) 42%, var(--bg-primary));
}

.user-level-chart__fill {
  display: block;
  height: 100%;
  min-width: 0;
  border-radius: inherit;
}

.user-level-chart__row {
  display: grid;
  grid-template-columns: 4rem minmax(7.5rem, 0.75fr) minmax(8rem, 2fr) 3.7rem 3.5rem;
  align-items: center;
  gap: 0.5rem;
  min-width: 0;
  color: var(--text-color);
  font-size: 0.75rem;
}

.user-level-chart__name {
  min-width: 0;
  font-weight: 650;
  overflow-wrap: anywhere;
}

.user-level-chart__fill {
  box-sizing: border-box;
  border: 1px solid var(--chart-level-border);
  background: var(--chart-level-color);
}

.user-level-chart__row > strong,
.user-level-chart__row > span:last-child {
  text-align: right;
  white-space: nowrap;
}

.user-insights__empty {
  padding: 1rem;
  border: 1px dashed var(--border-color);
  border-radius: 7px;
  color: var(--text-secondary);
  font-size: 0.8rem;
  text-align: center;
}

.user-submission-dialog {
  display: grid;
  gap: 0.9rem;
  min-width: 0;
}

.user-submission-summary,
.user-submission-overview,
.user-submission-distribution {
  display: grid;
  gap: 0.7rem;
  min-width: 0;
  padding: 0.85rem;
  border: 1px solid var(--border-color);
  border-radius: 9px;
  background: var(--bg-secondary);
}

.user-submission-summary__identity,
.user-submission-summary__exp,
.user-submission-total {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.6rem 1rem;
}

.user-submission-summary__identity h3 {
  margin: 0.1rem 0 0;
  color: var(--text-color);
}

.user-submission-summary__eyebrow,
.user-submission-summary__exp span,
.user-submission-total span {
  color: var(--text-secondary);
  font-size: var(--app-font-size-xs);
}

.user-submission-level-progress {
  height: 0.72rem;
  box-sizing: border-box;
  overflow: hidden;
  padding: 2px;
  border: 1px solid var(--user-level-border);
  border-radius: 999px;
  background: color-mix(in srgb, var(--border-color) 55%, var(--bg-primary));
}

.user-submission-level-progress > span {
  display: block;
  height: 100%;
  border: 1px solid var(--user-level-border);
  border-radius: inherit;
  background: var(--user-level-color);
}

.user-submission-status-cards {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 0.4rem;
}

.user-submission-status-card {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  gap: 0.25rem 0.4rem;
  min-width: 0;
  padding: 0.5rem;
  border: 1px solid var(--border-color);
  border-radius: 7px;
  background: var(--bg-primary);
  color: var(--text-secondary);
  font-size: var(--app-font-size-xs);
}

.user-submission-status-card strong {
  grid-column: 1 / -1;
  color: var(--text-color);
  font-size: var(--app-font-size-base);
}

.user-submission-status-dot {
  width: 0.58rem;
  height: 0.58rem;
  flex: 0 0 auto;
  border-radius: 50%;
}

.user-submission-distribution__bar {
  display: flex;
  width: 100%;
  height: 0.85rem;
  overflow: hidden;
  border: 1px solid var(--border-color);
  border-radius: 999px;
  background: var(--bg-primary);
}

.user-submission-distribution__bar > span {
  height: 100%;
}

.user-submission-distribution__legend {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.35rem 0.75rem;
}

.user-submission-legend-row {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto 3.5rem;
  align-items: center;
  gap: 0.4rem;
  min-width: 0;
  color: var(--text-secondary);
  font-size: var(--app-font-size-xs);
}

.user-submission-legend-row strong,
.user-submission-legend-row > span:last-child {
  color: var(--text-color);
  text-align: right;
  white-space: nowrap;
}

.request-summary {
  display: grid;
  gap: 0.45rem;
  min-width: 0;
}

.request-summary__header {
  display: flex;
  min-width: 0;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 0.4rem 0.8rem;
}

.request-summary__header :deep(.p-tag),
.request-summary__id {
  flex: 0 0 auto;
  white-space: nowrap;
}

.request-summary__id {
  margin-left: auto;
}

.request-summary__description {
  min-width: 0;
  margin: 0;
  overflow-wrap: anywhere;
  line-height: 1.55;
}

.archive-requester-stats {
  display: grid;
  gap: 0.7rem;
  min-width: 0;
  padding: 0.85rem;
  border: 1px solid var(--border-color);
  border-radius: 9px;
  background: var(--bg-secondary);
}

.archive-requester-stats h4 {
  margin: 0;
}

.archive-requester-stats__identity {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem 0.8rem;
}

.archive-requester-stats__identity > div {
  display: inline-flex;
  min-width: 0;
  align-items: baseline;
  gap: 0.35rem;
}

.archive-requester-stats__identity span {
  color: var(--text-secondary);
  font-size: var(--app-font-size-xs);
}

.archive-requester-stats__identity > strong {
  margin-left: auto;
  white-space: nowrap;
}

.user-submission-records {
  display: grid;
  gap: 0.65rem;
  min-width: 0;
  padding-top: 0.2rem;
  border-top: 1px solid var(--border-color);
}

.user-submission-records__heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 0.5rem 0.75rem;
}

.user-submission-records__heading > div:first-child {
  display: grid;
  gap: 0.15rem;
}

.user-submission-records__heading h4 {
  margin: 0;
}

.user-submission-records__heading span {
  color: var(--text-secondary);
  font-size: var(--app-font-size-xs);
}

.user-submission-records__search {
  width: min(100%, 19rem);
  margin-left: auto;
}

.user-submission-record-list {
  display: grid;
  gap: 0.5rem;
}

.user-submission-record {
  display: grid;
  gap: 0.5rem;
  min-width: 0;
  padding: 0.7rem;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-secondary);
}

.user-submission-record__header,
.user-submission-record__header > div {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem 0.55rem;
}

.user-submission-record__header {
  justify-content: space-between;
}

.user-submission-record__header > strong,
.user-submission-record__kind {
  color: var(--text-secondary);
  font-size: var(--app-font-size-xs);
  white-space: nowrap;
}

.user-submission-record__title {
  display: flex;
  min-width: 0;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0.25rem 0.55rem;
}

.user-submission-record__title strong,
.user-submission-record__title span {
  min-width: 0;
  overflow-wrap: anywhere;
}

.user-submission-record__title span {
  color: var(--text-secondary);
  font-size: var(--app-font-size-sm);
}

.user-submission-record__meta {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.25rem 0.75rem;
  color: var(--text-secondary);
  font-size: var(--app-font-size-xs);
}

.user-submission-record__meta span {
  min-width: 0;
  overflow-wrap: anywhere;
}

.user-submission-record__comment {
  display: flex;
  min-width: 0;
  align-items: flex-start;
  gap: 0.35rem;
  padding-top: 0.45rem;
  border-top: 1px solid var(--border-color);
  color: var(--text-secondary);
  font-size: var(--app-font-size-xs);
}

.user-submission-record__comment strong {
  flex: 0 0 auto;
  color: var(--text-color);
}

.user-submission-record__comment span {
  min-width: 0;
  overflow-wrap: anywhere;
}

.user-submission-records__paginator {
  max-width: 100%;
  overflow-x: auto;
}

.contributor-level-settings-dialog {
  display: grid;
  gap: 0.75rem;
  min-width: 0;
}

.contributor-level-settings-help {
  margin: 0;
  padding: 0.8rem 1rem 0;
  color: var(--text-secondary);
  font-size: 0.82rem;
  line-height: 1.4;
}

.contributor-level-settings-list {
  display: grid;
  gap: 0.45rem;
  max-height: min(62vh, 34rem);
  overflow-y: auto;
  padding: 0 1rem 1rem;
}

.contributor-level-settings-row {
  display: grid;
  grid-template-columns: 3.2rem 4rem minmax(10rem, 1fr) minmax(11rem, 0.8fr) auto;
  min-width: 0;
  align-items: end;
  gap: 0.55rem;
  padding: 0.55rem;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-secondary);
}

.contributor-level-settings-number {
  align-self: center;
  color: var(--text-color);
  white-space: nowrap;
}

.contributor-level-settings-field {
  display: grid;
  min-width: 0;
  gap: 0.25rem;
  color: var(--text-secondary);
  font-size: 0.72rem;
  font-weight: 650;
}

.contributor-level-settings-max {
  align-self: center;
  color: var(--text-secondary);
  font-size: 0.72rem;
  white-space: nowrap;
}

.contributor-level-settings-footer {
  display: flex;
  width: 100%;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
}

.contributor-level-settings-footer-spacer {
  flex: 1 1 auto;
}

.admin-toolbar--section {
  align-items: flex-start;
}

.admin-toolbar__filters {
  display: flex;
  flex: 1 1 auto;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.75rem;
  min-width: 0;
}

.admin-toolbar__search {
  position: relative;
  display: block;
  flex: 1 1 20rem;
  min-width: min(100%, 16rem);
}

.admin-toolbar__search .search-icon {
  top: 50%;
  margin-top: 0;
  transform: translateY(-50%);
  pointer-events: none;
}

.admin-toolbar__search :deep(.p-inputtext) {
  width: 100%;
}

.admin-toolbar__select {
  flex: 0 1 16rem;
  min-width: min(100%, 12rem);
}

.admin-toolbar__actions {
  display: flex;
  flex: 0 0 auto;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 0.5rem;
  min-width: 0;
}

:deep(.admin-toolbar__button.p-button),
:deep(.admin-toolbar__actions .p-button) {
  width: auto;
  min-height: 2.45rem;
  white-space: nowrap;
}

.admin-toolbar__actions .review-refresh-button {
  margin-left: 0;
}

.admin-toolbar--trash-shell {
  align-items: flex-start;
}

.admin-toolbar--trash {
  flex: 1 1 34rem;
  justify-content: flex-end;
  width: auto;
}

.admin-toolbar__filters--trash {
  flex: 0 1 13rem;
}

.admin-toolbar__actions--trash {
  flex: 0 1 auto;
}

:deep(.review-refresh-button .p-button-icon) {
  font-size: 0.95rem;
}

.review-empty-state {
  padding: 1rem;
  color: var(--text-secondary);
}

.comparison-basis {
  color: var(--text-secondary);
  font-size: 0.9rem;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.comparison-row-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.submission-detail-comparison-mobile {
  display: none;
}

.comparison-mobile-card {
  display: grid;
  gap: 0.65rem;
  padding: 0.75rem;
  border: 1px solid color-mix(in srgb, var(--border-color) 82%, transparent);
  border-radius: 8px;
  background: color-mix(in srgb, var(--bg-primary) 92%, var(--bg-secondary) 8%);
}

.comparison-mobile-card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.65rem;
  min-width: 0;
}

.comparison-mobile-id {
  min-width: 0;
  color: var(--text-primary);
  font-size: 0.94rem;
  font-weight: 700;
  line-height: 1.3;
  overflow-wrap: anywhere;
}

.comparison-mobile-status {
  flex: 0 0 auto;
  max-width: 48%;
  justify-content: center;
  text-align: center;
}

.comparison-mobile-meta {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.5rem 0.75rem;
}

.comparison-mobile-meta-item {
  min-width: 0;
}

.comparison-mobile-meta-label {
  display: block;
  color: var(--text-secondary);
  font-size: 0.74rem;
  font-weight: 650;
  line-height: 1.2;
}

.comparison-mobile-meta-value {
  display: block;
  margin-top: 0.12rem;
  color: var(--text-primary);
  font-size: 0.9rem;
  line-height: 1.3;
  overflow-wrap: anywhere;
}

.comparison-mobile-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.45rem;
}

.comparison-mobile-actions :deep(.p-button) {
  width: auto;
  flex: 0 0 auto;
  min-height: 2.25rem;
}

.review-sort-header {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0;
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  font-weight: 600;
  cursor: pointer;
}

.review-row-action-area {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  align-items: flex-start;
  min-width: 0;
}

.review-sort-icon {
  font-size: 0.8rem;
  line-height: 1;
  opacity: 0.8;
  color: var(--text-color-secondary);
}

.review-card-action-note {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  margin: 0.15rem 0 0;
  width: fit-content;
  max-width: min(18rem, 100%);
  min-width: 0;
  min-height: 1.55rem;
  padding: 0.18rem 0.55rem;
  border: 1px solid var(--soft-note-border, var(--border-color));
  border-radius: 999px;
  background: var(--soft-note-bg, color-mix(in srgb, var(--surface-ground) 55%, transparent));
  color: var(--soft-note-color, var(--text-color-secondary));
  font-size: var(--app-font-size-xs);
  font-weight: 600;
  line-height: 1.35;
  white-space: normal;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.review-card-action-note .pi {
  flex: 0 0 auto;
  flex-shrink: 0;
  font-size: 0.95em;
}

.review-card-action-note span {
  min-width: 0;
  white-space: normal;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.review-card-action-note__text {
  min-width: 0;
  white-space: normal;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.review-card-action-note--info {
  --soft-note-bg: rgba(14, 116, 144, 0.1);
  --soft-note-border: rgba(14, 116, 144, 0.42);
  --soft-note-color: #0e7490;
}

.review-card-action-note--warning {
  --soft-note-bg: rgba(234, 88, 12, 0.11);
  --soft-note-border: rgba(234, 88, 12, 0.44);
  --soft-note-color: #c2410c;
}

:global(.dark) .review-card-action-note--info,
:global(.dark) :deep(.review-card-action-note--info) {
  --soft-note-bg: rgba(34, 211, 238, 0.16);
  --soft-note-border: rgba(103, 232, 249, 0.68);
  --soft-note-color: #67e8f9;
}

:global(.dark) .review-card-action-note--warning,
:global(.dark) :deep(.review-card-action-note--warning) {
  --soft-note-bg: rgba(251, 146, 60, 0.16);
  --soft-note-border: rgba(251, 191, 36, 0.68);
  --soft-note-color: #fbbf24;
}

.review-sort-icon.pi-sort-amount-up-alt,
.review-sort-icon.pi-sort-amount-down {
  color: var(--primary-color);
  opacity: 1;
}

.review-course-cell {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  flex-wrap: wrap;
}

:deep(.review-desktop-course-cell) {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.3rem;
  min-width: 0;
}

:deep(.review-desktop-course-cell__name),
:deep(.review-desktop-course-cell__admin-row) {
  display: block;
  width: 100%;
  min-width: 0;
  max-width: 100%;
}

:deep(.review-desktop-course-cell__name) {
  overflow-wrap: anywhere;
}

:deep(.review-desktop-course-cell__admin-row) {
  line-height: 1;
}

.category-color-options {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(5.5rem, 1fr));
  gap: 0.5rem;
}

.category-color-option {
  border-radius: 999px;
  padding: 0.4rem 0.65rem;
  cursor: pointer;
  transition:
    outline-color 0.15s ease,
    transform 0.15s ease;
}

.category-color-option:hover {
  transform: translateY(-1px);
}

.category-color-option.is-selected {
  outline: 2px solid var(--primary-color);
  outline-offset: 2px;
}

.category-badge-preview {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.5rem;
  color: var(--text-secondary);
  font-size: 0.86rem;
}

.category-color-option.category-badge,
:deep(.category-badge) {
  border: 1px solid transparent;
  font-weight: 700;
  letter-spacing: 0;
  line-height: 1.25;
  max-width: 100%;
  white-space: normal;
}

.category-color-option.category-badge--navy,
:deep(.category-badge--navy) {
  background: #dbe4f0;
  border-color: #475f83;
  color: #1f3a5f;
}

.category-color-option.category-badge--teal,
:deep(.category-badge--teal) {
  background: #d5ebe7;
  border-color: #2f766e;
  color: #175e58;
}

.category-color-option.category-badge--forest,
:deep(.category-badge--forest) {
  background: #dce8d8;
  border-color: #4f7a45;
  color: #315f2a;
}

.category-color-option.category-badge--amber,
:deep(.category-badge--amber) {
  background: #efe2c8;
  border-color: #9a6b24;
  color: #7a4d12;
}

.category-color-option.category-badge--burgundy,
:deep(.category-badge--burgundy) {
  background: #eed8dd;
  border-color: #8f3f50;
  color: #743041;
}

.category-color-option.category-badge--violet,
:deep(.category-badge--violet) {
  background: #e3dcef;
  border-color: #6d5599;
  color: #513f7d;
}

.category-color-option.category-badge--slate,
:deep(.category-badge--slate) {
  background: #dfe4ea;
  border-color: #64748b;
  color: #334155;
}

.category-color-option.category-badge--indigo,
:deep(.category-badge--indigo) {
  background: #dde1f2;
  border-color: #5262a3;
  color: #364381;
}

:global(.dark) .category-color-option.category-badge--navy,
:global(.dark) :deep(.category-badge--navy) {
  background: rgba(71, 95, 131, 0.28);
  border-color: rgba(125, 151, 190, 0.58);
  color: #c7d6ea;
}

:global(.dark) .category-color-option.category-badge--teal,
:global(.dark) :deep(.category-badge--teal) {
  background: rgba(45, 118, 110, 0.26);
  border-color: rgba(89, 170, 160, 0.52);
  color: #b7ded8;
}

:global(.dark) .category-color-option.category-badge--forest,
:global(.dark) :deep(.category-badge--forest) {
  background: rgba(79, 122, 69, 0.28);
  border-color: rgba(128, 174, 116, 0.52);
  color: #c2dfb9;
}

:global(.dark) .category-color-option.category-badge--amber,
:global(.dark) :deep(.category-badge--amber) {
  background: rgba(154, 107, 36, 0.28);
  border-color: rgba(199, 153, 78, 0.56);
  color: #ead2a3;
}

:global(.dark) .category-color-option.category-badge--burgundy,
:global(.dark) :deep(.category-badge--burgundy) {
  background: rgba(143, 63, 80, 0.28);
  border-color: rgba(194, 105, 122, 0.54);
  color: #e5bec8;
}

:global(.dark) .category-color-option.category-badge--violet,
:global(.dark) :deep(.category-badge--violet) {
  background: rgba(109, 85, 153, 0.28);
  border-color: rgba(159, 137, 199, 0.56);
  color: #d9cdef;
}

:global(.dark) .category-color-option.category-badge--slate,
:global(.dark) :deep(.category-badge--slate) {
  background: rgba(100, 116, 139, 0.26);
  border-color: rgba(148, 163, 184, 0.5);
  color: #d1d9e4;
}

:global(.dark) .category-color-option.category-badge--indigo,
:global(.dark) :deep(.category-badge--indigo) {
  background: rgba(82, 98, 163, 0.28);
  border-color: rgba(131, 146, 205, 0.56);
  color: #cfd6f1;
}

.review-load-error {
  margin-bottom: 1rem;
  padding: 0.75rem 1rem;
  border: 1px solid rgba(239, 68, 68, 0.38);
  border-radius: 8px;
  background: rgba(239, 68, 68, 0.12);
  color: #fecaca;
}

.admin-actor-time {
  display: grid;
  gap: 0.18rem;
  min-width: 0;
  max-width: 100%;
  line-height: 1.3;
}

.admin-actor-time__name {
  display: block;
  min-width: 0;
  overflow: hidden;
  color: var(--text-primary);
  font-size: var(--app-font-size-sm);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.admin-actor-time__time {
  display: block;
  color: var(--text-secondary);
  font-size: var(--app-font-size-xs);
  line-height: 1.25;
  white-space: nowrap;
}

:deep(.review-request-table .admin-actor-time),
:deep(.trash-table .admin-actor-time),
:deep(.notification-management-table .admin-actor-time) {
  min-width: 0;
}

:deep(.admin-desktop-status-column) {
  width: 6rem;
  min-width: 6rem;
  text-align: center;
}

.admin-desktop-status-cell {
  container-name: admin-status-cell;
  container-type: inline-size;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  min-width: 0;
}

:deep(.admin-desktop-status-cell .admin-desktop-status-tag.soft-badge) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  inline-size: fit-content;
  min-inline-size: 0;
  max-width: 100%;
  padding-inline: 0.5rem !important;
  text-align: center;
  white-space: nowrap;
}

:deep(.admin-desktop-status-tag .p-tag-label) {
  white-space: inherit;
}

:deep(.admin-desktop-status-label) {
  display: inline-flex;
  flex-direction: row;
  align-items: center;
  justify-content: center;
}

@container admin-status-cell (max-width: 3.75rem) {
  :deep(.admin-desktop-status-cell .admin-desktop-status-tag.soft-badge) {
    inline-size: fit-content;
    min-inline-size: 0;
    max-inline-size: 2.1rem;
    padding: 0.4rem 0.32rem !important;
    white-space: normal;
  }

  :deep(.admin-desktop-status-label) {
    flex-direction: column;
  }
}

:deep(.review-submission-type-cell) {
  container-name: review-submission-type-cell;
  container-type: inline-size;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  min-width: 0;
}

:deep(.review-desktop-submission-type-tag.soft-badge) {
  max-width: 100%;
  justify-content: center;
}

:deep(.submission-type-combined-label) {
  display: inline-flex;
  flex-direction: row;
  align-items: center;
  justify-content: center;
  line-height: 1.15;
  white-space: nowrap;
}

@container review-submission-type-cell (max-width: 7.25rem) {
  :deep(.submission-type-combined-label) {
    flex-direction: column;
  }

  :deep(.submission-type-combined-label__separator) {
    display: none;
  }
}

.notification-mobile-update,
.notification-mobile-update__value {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0.12rem;
  min-width: 0;
  max-width: 100%;
}

.notification-mobile-update {
  gap: 0.12rem 0.35rem;
}

.notification-mobile-update__label,
.notification-mobile-update__actor,
.notification-mobile-update__time {
  white-space: nowrap;
}

.notification-mobile-update__label,
.notification-mobile-update__time {
  color: var(--text-secondary);
}

.notification-mobile-update__actor {
  min-width: 0;
  overflow: hidden;
  color: var(--text-primary);
  text-overflow: ellipsis;
}

.notification-mobile-update__time {
  font-size: var(--app-font-size-xs);
}

.trash-name-cell {
  display: inline-flex;
  flex-direction: column;
  gap: 0.2rem;
  width: 100%;
  min-width: 0;
  max-width: 100%;
}

.trash-name-title {
  display: inline-flex;
  align-items: flex-start;
  gap: 0.35rem;
  box-sizing: border-box;
  min-width: 0;
  max-width: 100%;
  white-space: normal;
  overflow-wrap: anywhere;
}

.trash-name-title__text {
  min-width: 0;
  overflow-wrap: anywhere;
}

.trash-user-name {
  min-width: 0;
  max-width: 100%;
  overflow-wrap: anywhere;
}

.trash-user-email {
  display: block;
  min-width: 0;
  max-width: 100%;
  color: var(--text-secondary);
  font-size: var(--app-font-size-sm);
  font-weight: 400;
  line-height: 1.35;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.trash-tree-prefix {
  color: var(--text-secondary);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-weight: 700;
  letter-spacing: 0;
}

.trash-name-cell small {
  color: var(--text-secondary);
  margin-left: 0.15rem;
}

.trash-dependencies {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  width: 100%;
  min-width: 0;
  max-width: 100%;
}

:deep(.trash-table .trash-dependencies-column) {
  width: clamp(17rem, 22vw, 23rem);
  max-width: 23rem;
}

:deep(.trash-table .trash-name-column) {
  width: clamp(14rem, 18vw, 18rem);
  max-width: 18rem;
}

:deep(.trash-table .trash-dependencies .trash-dependency-chip) {
  max-width: 100%;
  white-space: normal;
  overflow-wrap: anywhere;
}

.trash-mobile-list {
  display: none;
}

:deep(.trash-table .p-datatable-tbody > tr.trash-row--relation-group-even) {
  --trash-relation-row-bg: rgba(16, 185, 129, 0.055);
}

:deep(.trash-table .p-datatable-tbody > tr.trash-row--relation-group-odd) {
  --trash-relation-row-bg: rgba(59, 130, 246, 0.045);
}

:deep(.trash-table .p-datatable-tbody > tr.trash-row--relation-group) {
  background: var(--trash-relation-row-bg);
}

:deep(.trash-table .p-datatable-tbody > tr.trash-row--relation-group > td) {
  background: var(--trash-relation-row-bg);
}

:deep(.trash-table .p-datatable-tbody > tr.trash-row--relation-group:hover > td) {
  background: color-mix(in srgb, var(--trash-relation-row-bg) 72%, var(--bg-secondary) 28%);
}

.trash-dependency-help {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  max-height: min(70vh, 44rem);
  overflow-y: auto;
  padding-right: 0.2rem;
  font-size: 0.92rem;
}

.trash-dependency-help-intro {
  margin: 0;
  color: var(--text-secondary);
  line-height: 1.55;
}

.trash-dependency-help-section {
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 0.75rem 0.85rem;
  background: color-mix(in srgb, var(--surface-card) 90%, transparent);
}

.trash-dependency-help-title {
  margin: 0 0 0.55rem 0;
  font-size: 0.95rem;
  font-weight: 700;
  color: var(--text-color);
}

.trash-dependency-help-label-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr));
  gap: 0.55rem;
}

.trash-dependency-help-label-card,
.trash-dependency-help-flow-card {
  border: 1px solid color-mix(in srgb, var(--border-color) 72%, transparent);
  border-radius: 8px;
  background: color-mix(in srgb, var(--surface-ground) 42%, transparent);
}

.trash-dependency-help-label-card {
  padding: 0.6rem;
}

.trash-dependency-help-label-card p,
.trash-dependency-help-flow-card p,
.trash-dependency-help-rule-list p {
  margin: 0;
  color: var(--text-secondary);
  line-height: 1.5;
}

.trash-dependency-help-label-card p {
  margin-top: 0.4rem;
  font-size: 0.86rem;
}

.trash-dependency-chip,
.trash-dependency-help-chip,
:deep(.trash-dependency-chip) {
  display: inline-flex;
  align-items: center;
  width: fit-content;
  max-width: 100%;
  min-height: 1.65rem;
  border: 1px solid var(--soft-badge-border, rgba(100, 116, 139, 0.28)) !important;
  border-radius: 999px;
  padding: 0.18rem 0.6rem;
  background: var(--soft-badge-bg, rgba(100, 116, 139, 0.1)) !important;
  color: var(--soft-badge-color, #334155) !important;
  font-size: 0.84rem;
  font-weight: 600;
  letter-spacing: 0;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

:deep(.review-card-chip.soft-badge),
:deep(.review-status-chip.soft-badge),
:deep(.trash-type-chip.soft-badge) {
  min-height: 1.75rem !important;
  padding: 0.22rem 0.62rem !important;
  font-size: var(--app-badge-font-size) !important;
  line-height: 1.25 !important;
}

:deep(.review-admin-upload-chip.soft-badge) {
  min-height: 1.45rem !important;
  padding: 0.16rem 0.48rem !important;
  font-size: var(--app-badge-font-size) !important;
  line-height: 1.25 !important;
}

:deep(.review-status-chip.soft-badge) {
  font-weight: 650 !important;
}

:deep(.review-card-chip.soft-badge .pi),
:deep(.review-status-chip.soft-badge .pi),
:deep(.review-admin-upload-chip.soft-badge .pi) {
  font-size: 0.95em !important;
}

:deep(.trash-dependency-chip.soft-badge) {
  font-size: 0.84rem !important;
}

.trash-dependency-help-rule-list {
  display: grid;
  gap: 0.35rem;
}

.trash-dependency-help-rule-list p {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 0.45rem;
  overflow-wrap: anywhere;
}

.trash-dependency-help-rule-list span {
  color: var(--primary-color);
  font-weight: 700;
}

.trash-dependency-help-flow-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(15rem, 1fr));
  gap: 0.65rem;
}

.trash-dependency-help-flow-card {
  padding: 0.7rem;
}

.trash-dependency-help-flow-card h5 {
  margin: 0 0 0.5rem;
  font-size: 0.9rem;
  font-weight: 700;
  color: var(--text-color);
}

.trash-dependency-help-flow-card p {
  margin-top: 0.55rem;
  font-size: 0.86rem;
}

.trash-dependency-help-flow {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.28rem;
  border: 1px dashed color-mix(in srgb, var(--border-color) 72%, transparent);
  border-radius: 8px;
  padding: 0.45rem;
  background: color-mix(in srgb, var(--surface-card) 72%, transparent);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.trash-dependency-help-flow span {
  border: 1px solid color-mix(in srgb, var(--border-color) 72%, transparent);
  border-radius: 999px;
  padding: 0.12rem 0.4rem;
  color: var(--text-color);
  font-size: 0.78rem;
  line-height: 1.45;
  background: color-mix(in srgb, var(--surface-ground) 55%, transparent);
}

.trash-dependency-help-flow i {
  color: var(--text-secondary);
  font-style: normal;
  font-size: 0.82rem;
}

.trash-dependency-help-note {
  margin: 0.5rem 0 0;
  border: 1px dashed color-mix(in srgb, var(--border-color) 60%, transparent);
  padding: 0.45rem 0.55rem;
  border-radius: 6px;
  color: var(--text-secondary);
  font-size: 0.86rem;
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.trash-dependency-help-note p {
  margin: 0;
}

.trash-dependency-help-note p + p {
  margin-top: 0.25rem;
}

@media (max-width: 640px) {
  .trash-dependency-help {
    max-height: 72vh;
  }

  .trash-dependency-help-section {
    padding: 0.7rem;
  }

  .trash-dependency-help-label-grid,
  .trash-dependency-help-flow-grid {
    grid-template-columns: 1fr;
  }
}

.compare-preview-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 1rem;
  flex: 1;
  min-height: 0;
}

.compare-preview-pane {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  overflow: hidden;
  background: var(--bg-secondary);
}

.compare-preview-pane header {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--border-color);
}

.compare-preview-pane header span {
  color: var(--text-secondary);
  font-size: 0.875rem;
}

.compare-preview-pane iframe {
  flex: 1;
  width: 100%;
  min-height: 0;
  border: 0;
  background: #52585b;
}

.compare-preview-error {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  min-height: 20rem;
  color: var(--text-secondary);
}

.category-name-mobile,
.category-key-mobile,
.category-key-mobile-inline {
  display: none;
}

.category-name-desktop {
  display: inline;
}

.category-key-desktop {
  display: inline;
}

.mobile-primary-text,
.mobile-long-text,
.mobile-metadata-text {
  display: block;
  min-width: 0;
  max-width: 100%;
}

.admin-mobile-card {
  display: none;
}

.admin-mobile-list {
  display: none;
}

.admin-mobile-paginator {
  width: 100%;
  min-width: 0;
  margin-top: 0.2rem;
}

.user-online-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  color: var(--text-color);
  font-size: 0.85rem;
  line-height: 1.35;
  white-space: nowrap;
}

.user-online-badge .pi {
  font-size: 0.58rem;
  line-height: 1;
}

.user-online-dot--online {
  color: #16a34a;
}

.user-online-dot--offline {
  color: var(--text-secondary);
}

:deep(.user-management-table .user-management-table-actions) {
  display: flex !important;
  flex-direction: row !important;
  align-items: center !important;
  justify-content: flex-start !important;
  gap: 0.5rem;
  flex-wrap: nowrap;
  white-space: nowrap;
  width: auto;
  min-width: 17rem;
}

:deep(.user-management-table .user-management-table-actions .p-button),
:deep(.user-management-table .user-management-table-actions button) {
  flex: 0 0 auto;
  width: auto;
  min-width: auto;
  white-space: nowrap;
}

:global(.dark) .user-online-dot--online {
  color: #22c55e;
}
:global(.dark) .user-online-dot--offline {
  color: var(--text-secondary);
}

/* Mobile responsive adjustments */
@media (max-width: 768px) {
  .admin-container {
    padding-left: 0.75rem !important;
    padding-right: 0.75rem !important;
    overflow-x: hidden;
  }

  :deep(.p-tablist),
  :deep(.p-tablist-content),
  :deep(.p-tablist-tab-list) {
    overflow-x: auto;
    overflow-y: hidden;
    overscroll-behavior-y: contain;
    scrollbar-width: thin;
    touch-action: pan-x;
  }

  :deep(.p-tab) {
    flex: 0 0 auto;
    white-space: nowrap;
  }

  :deep(.p-datatable) {
    font-size: 0.875rem;
    overflow-x: auto;
    border-radius: 8px;
    max-width: 100%;
  }

  :deep(.p-datatable-table-container) {
    overflow-x: visible !important;
    max-height: none !important;
  }

  :deep(.p-datatable-table) {
    display: block;
    min-width: 0 !important;
    width: 100% !important;
  }

  :deep(.p-datatable-thead) {
    display: none;
  }

  :deep(.p-datatable-tbody) {
    display: block;
  }

  :deep(.p-datatable-tbody > tr) {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 0.45rem;
    width: 100%;
    margin-bottom: 0.65rem;
    padding: 0.8rem;
    border: 1px solid var(--border-color);
    border-radius: 8px;
    background: color-mix(in srgb, var(--bg-secondary) 86%, transparent);
  }

  :deep(.p-datatable .p-datatable-tbody > tr > td) {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 0.2rem;
    width: 100%;
    min-width: 0;
    padding: 0 !important;
    border: 0 !important;
    background: transparent !important;
    overflow-wrap: normal;
    word-break: normal;
  }

  :deep(.p-datatable .p-datatable-tbody > tr > td .p-column-title) {
    display: block;
    color: var(--text-secondary);
    font-size: 0.72rem;
    font-weight: 700;
    line-height: 1.3;
  }

  :deep(.p-datatable .p-column-title + *) {
    width: 100%;
  }

  :deep(.p-datatable .p-tag) {
    width: fit-content;
    max-width: 100%;
    white-space: nowrap;
  }

  .mobile-card-order {
    width: auto;
    min-width: 0;
    flex-wrap: nowrap;
  }

  .mobile-card-order .w-2rem {
    width: auto !important;
    min-width: 1.25rem;
    text-align: center;
  }

  :deep(.mobile-card-order .p-button) {
    width: 2rem;
    min-width: 2rem;
    height: 2rem;
    min-height: 2rem;
  }

  :deep(.course-management-table .p-column-title),
  :deep(.category-management-table .p-column-title) {
    display: none !important;
  }

  :deep(.course-management-table .p-datatable-tbody > tr),
  :deep(.category-management-table .p-datatable-tbody > tr) {
    grid-template-columns: minmax(0, 1fr);
    align-items: stretch;
    gap: 0.55rem;
    padding: 0.9rem;
  }

  :deep(.category-management-table .p-datatable-tbody > tr > td:nth-child(1)) {
    align-self: stretch;
  }

  :deep(.category-management-table .p-datatable-tbody > tr > td:nth-child(2)) {
    align-self: stretch;
  }

  :deep(.category-management-table .p-datatable-tbody > tr > td:nth-child(3)) {
    align-self: stretch;
  }

  :deep(.category-management-table .p-datatable-tbody > tr > td:nth-child(4)) {
    display: none;
  }

  :deep(.category-management-table .p-datatable-tbody > tr > td:nth-child(5)) {
    align-self: stretch;
  }

  :deep(.category-management-table .p-datatable-tbody > tr > td:nth-child(6)) {
    align-self: stretch;
  }

  :deep(.course-management-table .p-datatable-tbody > tr > td),
  :deep(.category-management-table .p-datatable-tbody > tr > td) {
    grid-area: auto;
    align-self: stretch;
  }

  .category-name-desktop,
  .category-key-desktop {
    display: none;
  }

  .category-name-mobile {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    align-items: flex-start;
    width: 100%;
    min-width: 0;
  }

  .category-mobile-header {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    align-items: start;
    gap: 0.45rem;
    width: 100%;
  }

  .category-mobile-title {
    min-width: 0;
    color: var(--text-primary);
    font-size: 1rem;
    font-weight: 700;
    line-height: 1.35;
    word-break: normal;
    overflow-wrap: break-word;
  }

  .category-key-mobile {
    display: inline-flex;
    flex-direction: column;
    gap: 0.15rem;
    align-items: flex-start;
    max-width: 100%;
    padding: 0.35rem 0.55rem;
    border: 1px solid var(--border-color);
    border-radius: 0.55rem;
    background: color-mix(in srgb, var(--panel-bg) 88%, var(--primary-color) 12%);
  }

  .mobile-field-label {
    display: block;
    color: var(--accent-gold);
    font-size: 0.68rem;
    font-weight: 700;
    line-height: 1.25;
    letter-spacing: 0.04em;
    white-space: nowrap;
  }

  .mobile-field-value {
    display: block;
    color: var(--text-primary);
    font-size: 0.95rem;
    line-height: 1.35;
    overflow-wrap: anywhere;
  }

  .mobile-primary-text,
  .mobile-long-text,
  .mobile-metadata-text {
    min-width: 0;
    max-width: 100%;
    width: 100%;
    word-break: normal;
  }

  .mobile-primary-text {
    font-weight: 700;
    font-size: 1rem;
    line-height: 1.35;
    color: var(--text-primary);
    word-break: normal;
    overflow-wrap: break-word;
  }

  .mobile-long-text {
    overflow-wrap: anywhere;
    word-break: break-word;
  }

  .mobile-metadata-text {
    color: var(--text-secondary);
    font-size: 0.85rem;
    line-height: 1.35;
  }

  :deep(.admin-desktop-data-table.user-management-table),
  :deep(.admin-desktop-data-table.course-management-table),
  :deep(.admin-desktop-data-table.category-management-table),
  :deep(.admin-desktop-data-table.notification-management-table) {
    display: none;
  }

  .admin-mobile-list {
    display: flex;
    flex-direction: column;
    gap: 0.8rem;
    width: 100%;
    min-width: 0;
  }

  .admin-mobile-list .admin-mobile-card {
    display: flex;
    flex-direction: column;
    width: 100%;
    max-width: 100%;
    min-width: 0;
    gap: 0.85rem;
    box-sizing: border-box;
    padding: 1rem;
    border: 1px solid color-mix(in srgb, var(--primary-color) 38%, var(--border-color));
    border-radius: 8px;
    background: color-mix(in srgb, var(--bg-secondary) 86%, transparent);
  }

  .admin-mobile-list .admin-card-primary {
    display: block;
    width: 100%;
    max-width: 100%;
    min-width: 0;
  }

  .admin-mobile-list .admin-card-title {
    display: block;
    width: 100%;
    max-width: 100%;
    min-width: 0;
    color: var(--text-primary);
    font-size: 1rem;
    font-weight: 800;
    line-height: 1.35;
    word-break: normal;
    overflow-wrap: break-word;
  }

  .admin-mobile-list .admin-card-email {
    display: block;
    width: 100%;
    max-width: 100%;
    min-width: 0;
    margin-top: 0.25rem;
    color: var(--text-primary);
    font-size: 0.95rem;
    line-height: 1.4;
    word-break: normal;
    overflow-wrap: anywhere;
  }

  .admin-mobile-list .admin-card-meta {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.45rem;
    width: 100%;
    min-width: 0;
  }

  .admin-mobile-list .admin-card-meta-text {
    color: var(--text-primary);
    font-size: 0.9rem;
    line-height: 1.3;
    white-space: nowrap;
  }

  :deep(.admin-mobile-list .p-tag) {
    white-space: nowrap;
  }

  .admin-mobile-list--categories .admin-category-card {
    gap: 0.7rem;
  }

  .category-card-topline {
    display: flex;
    align-items: center;
    gap: 0.45rem;
    width: 100%;
    min-width: 0;
  }

  .category-card-order {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 1.85rem;
    height: 1.85rem;
    border-radius: 999px;
    background: color-mix(in srgb, var(--primary-color) 18%, transparent);
    color: var(--text-primary);
    font-size: 0.85rem;
    font-weight: 800;
    line-height: 1;
  }

  :deep(.category-card-topline .p-button) {
    width: 2rem;
    min-width: 2rem;
    height: 2rem;
    min-height: 2rem;
    padding-inline: 0;
    justify-content: center;
  }

  :deep(.category-card-topline .pi) {
    margin: 0;
    line-height: 1;
  }

  .category-card-main {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 0.75rem;
    width: 100%;
    min-width: 0;
  }

  .category-card-title {
    display: block;
    min-width: 0;
    color: var(--text-primary);
    font-size: 1.05rem;
    font-weight: 800;
    line-height: 1.35;
    word-break: normal;
    overflow-wrap: break-word;
  }

  .category-card-key {
    display: inline-flex;
    flex: 0 1 auto;
    flex-direction: column;
    gap: 0.1rem;
    align-items: flex-start;
    max-width: 48%;
    padding: 0.32rem 0.5rem;
    border: 1px solid var(--border-color);
    border-radius: 0.55rem;
    background: color-mix(in srgb, var(--panel-bg) 88%, var(--primary-color) 12%);
  }

  .category-card-key-label {
    color: var(--accent-gold);
    font-size: 0.68rem;
    font-weight: 800;
    line-height: 1.2;
    white-space: nowrap;
  }

  .category-card-key-value {
    max-width: 100%;
    color: var(--text-primary);
    font-size: 0.82rem;
    line-height: 1.25;
    overflow-wrap: anywhere;
  }

  .category-card-meta {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.45rem;
    width: 100%;
    min-width: 0;
  }

  .admin-mobile-list.admin-mobile-list--categories
    .admin-mobile-card-actions.category-card-actions {
    display: grid;
    grid-template-columns: repeat(3, minmax(44px, 1fr));
    gap: 0.5rem;
    width: 100%;
    align-items: center;
  }

  :deep(.admin-mobile-list--categories .admin-mobile-card-actions .p-button-label) {
    display: none;
  }

  :deep(.admin-mobile-list--categories .admin-mobile-card-actions .pi) {
    margin: 0;
    line-height: 1;
  }

  :deep(.admin-mobile-list--categories .admin-mobile-card-actions .p-button) {
    width: 100%;
    min-width: 44px;
    min-height: 44px;
    justify-content: center;
  }

  .admin-mobile-list--courses .admin-course-card {
    gap: 0.7rem;
  }

  .course-card-topline {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.45rem;
    width: 100%;
    min-width: 0;
  }

  .course-card-order {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 1.85rem;
    height: 1.85rem;
    border-radius: 999px;
    background: color-mix(in srgb, var(--primary-color) 18%, transparent);
    color: var(--text-primary);
    font-size: 0.85rem;
    font-weight: 800;
    line-height: 1;
  }

  :deep(.course-card-topline .p-button) {
    width: 2rem;
    min-width: 2rem;
    height: 2rem;
    min-height: 2rem;
    padding-inline: 0;
    justify-content: center;
  }

  :deep(.course-card-topline .pi) {
    margin: 0;
    line-height: 1;
  }

  :deep(.course-card-category) {
    width: fit-content;
    max-width: 100%;
    white-space: nowrap;
  }

  .course-card-primary {
    display: block;
    width: 100%;
    min-width: 0;
  }

  .course-card-title {
    display: block;
    width: 100%;
    max-width: 100%;
    min-width: 0;
    color: var(--text-primary);
    font-size: 1.05rem;
    font-weight: 800;
    line-height: 1.35;
    word-break: normal;
    overflow-wrap: break-word;
  }

  .admin-mobile-list .admin-mobile-card-actions {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    width: 100%;
    gap: 0.5rem;
  }

  :deep(.admin-mobile-list--courses .admin-mobile-card-actions .p-button-label) {
    display: none;
  }

  :deep(.admin-mobile-list--courses .admin-mobile-card-actions .pi) {
    margin: 0;
    line-height: 1;
  }

  :deep(.admin-mobile-list .admin-mobile-card-actions .p-button) {
    width: 100%;
    min-width: 0;
    min-height: 2.65rem;
    justify-content: center;
  }

  :deep(.user-management-table .p-column-title),
  :deep(.notification-management-table .p-column-title) {
    display: none !important;
  }

  :deep(.user-management-table .user-management-table-actions) {
    flex-wrap: wrap;
    white-space: normal;
    width: 100%;
    min-width: 0;
  }

  :deep(.user-management-table .p-datatable-tbody > tr),
  :deep(.notification-management-table .p-datatable-tbody > tr) {
    display: flex;
    flex-direction: column;
    grid-template-columns: minmax(0, 1fr);
    gap: 0.7rem;
    padding: 1rem;
  }

  :deep(.user-management-table .p-datatable-tbody > tr > td:nth-child(1)),
  :deep(.notification-management-table .p-datatable-tbody > tr > td:nth-child(1)) {
    display: block;
    width: 100%;
    max-width: 100%;
    min-width: 0;
  }

  :deep(.user-management-table .p-datatable-tbody > tr > td:nth-child(2)),
  :deep(.user-management-table .p-datatable-tbody > tr > td:nth-child(3)),
  :deep(.user-management-table .p-datatable-tbody > tr > td:nth-child(4)),
  :deep(.user-management-table .p-datatable-tbody > tr > td:nth-child(5)),
  :deep(.notification-management-table .p-datatable-tbody > tr > td:nth-child(2)),
  :deep(.notification-management-table .p-datatable-tbody > tr > td:nth-child(3)),
  :deep(.notification-management-table .p-datatable-tbody > tr > td:nth-child(4)),
  :deep(.notification-management-table .p-datatable-tbody > tr > td:nth-child(5)) {
    display: none;
  }

  :deep(.user-management-table .p-datatable-tbody > tr > td:last-child),
  :deep(.notification-management-table .p-datatable-tbody > tr > td:last-child) {
    display: block;
    width: 100%;
    max-width: 100%;
    min-width: 0;
  }

  :deep(.user-management-table .admin-desktop-cell),
  :deep(.notification-management-table .admin-desktop-cell) {
    display: none;
  }

  .admin-mobile-card {
    display: flex;
    flex-direction: column;
    width: 100%;
    max-width: 100%;
    min-width: 0;
    gap: 0.75rem;
    box-sizing: border-box;
  }

  :deep(.user-management-table .admin-mobile-card),
  :deep(.notification-management-table .admin-mobile-card) {
    display: flex;
    width: 100%;
    max-width: 100%;
    min-width: 0;
  }

  .admin-card-primary {
    display: block;
    width: 100%;
    max-width: 100%;
    min-width: 0;
  }

  .admin-card-title {
    display: block;
    width: 100%;
    max-width: 100%;
    min-width: 0;
    color: var(--text-primary);
    font-size: 1rem;
    font-weight: 800;
    line-height: 1.35;
    word-break: normal;
    overflow-wrap: break-word;
  }

  .admin-card-email {
    display: block;
    width: 100%;
    max-width: 100%;
    min-width: 0;
    margin-top: 0.25rem;
    color: var(--text-primary);
    font-size: 0.95rem;
    line-height: 1.4;
    word-break: normal;
    overflow-wrap: anywhere;
  }

  .admin-card-meta {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.45rem;
    width: 100%;
    min-width: 0;
  }

  .admin-card-meta-text {
    color: var(--text-primary);
    font-size: 0.9rem;
    line-height: 1.3;
    white-space: nowrap;
  }

  :deep(.notification-management-table .admin-card-actions) {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    width: 100%;
    gap: 0.5rem;
  }

  :deep(.user-management-table .admin-card-actions) {
    display: flex;
    flex-wrap: wrap;
    width: 100%;
    gap: 0.5rem;
    align-items: center;
  }

  :deep(.notification-management-table .admin-card-actions .p-button) {
    width: 100%;
    min-width: 0;
    min-height: 2.6rem;
  }

  :deep(.user-management-table .admin-card-actions .p-button) {
    width: auto;
    min-width: 7rem;
    min-height: 2.35rem;
  }

  .admin-card-actions {
    width: 100%;
    min-width: 0;
    display: flex;
    flex-wrap: wrap;
    gap: 0.45rem;
    align-items: stretch;
  }

  :deep(.admin-card-actions .p-button) {
    width: auto;
    min-width: 7rem;
    min-height: 2.35rem;
    justify-content: center;
  }

  :deep(.course-management-table .admin-card-actions),
  :deep(.category-management-table .admin-card-actions) {
    width: 100%;
    flex-direction: row;
    flex-wrap: wrap;
    gap: 0.35rem;
  }

  :deep(.course-management-table .admin-card-actions .p-button),
  :deep(.category-management-table .admin-card-actions .p-button) {
    min-width: 2.45rem;
    width: 2.45rem;
    height: 2.45rem;
    padding-inline: 0;
  }

  :deep(.course-management-table .admin-card-actions .p-button-label),
  :deep(.category-management-table .admin-card-actions .p-button-label) {
    display: none;
  }

  :deep(.course-management-table .admin-card-actions .pi),
  :deep(.category-management-table .admin-card-actions .pi) {
    margin: 0;
    line-height: 1;
  }

  :deep(.p-datatable .p-button) {
    min-height: 2.25rem;
    white-space: nowrap;
  }

  :deep(.p-datatable .p-button.p-button-icon-only) {
    width: 2.5rem;
    min-width: 2.5rem;
    flex-basis: 2.5rem;
    padding-inline: 0;
    justify-content: center;
  }

  :deep(.p-datatable-tbody > tr:last-child) {
    margin-bottom: 0;
  }

  :deep(.review-request-table .p-datatable-tbody > tr) {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0.55rem 0.75rem;
    padding: 0.9rem;
    align-items: center;
  }

  :deep(.review-request-table .p-datatable-tbody > tr > td) {
    width: 100%;
    min-width: 0;
    align-self: stretch;
  }

  :deep(.review-request-table .p-datatable-tbody > tr > td:first-child),
  :deep(.review-request-table .p-datatable-tbody > tr > td:last-child) {
    grid-column: 1 / -1;
  }

  :deep(.review-request-table .p-column-title) {
    display: none !important;
  }

  :deep(.review-card-title) {
    display: block;
    width: 100%;
    max-width: 100%;
    min-width: 0;
    color: var(--text-primary);
    font-size: 1rem;
    font-weight: 800;
    line-height: 1.35;
    word-break: normal;
    overflow-wrap: break-word;
  }

  :deep(.review-card-meta-text) {
    display: inline-flex;
    width: fit-content;
    max-width: 100%;
    color: var(--text-primary);
    font-size: 0.9rem;
    line-height: 1.35;
    white-space: nowrap;
  }

  :deep(.review-request-table .p-tag),
  :deep(.review-card-chip) {
    width: fit-content;
    max-width: 100%;
    white-space: nowrap;
  }

  :deep(.review-request-table--new .p-datatable-tbody > tr > td:nth-child(1)) {
    order: 1;
    grid-column: 1 / -1;
  }

  :deep(.review-request-table--new .p-datatable-tbody > tr > td:nth-child(3)) {
    order: 2;
    grid-column: 1;
  }

  :deep(.review-request-table--new .p-datatable-tbody > tr > td:nth-child(4)) {
    order: 3;
    grid-column: 2;
  }

  :deep(.review-request-table--new .p-datatable-tbody > tr > td:nth-child(5)) {
    order: 4;
    grid-column: 1;
  }

  :deep(.review-request-table--new .p-datatable-tbody > tr > td:nth-child(2)) {
    order: 5;
    grid-column: 1;
  }

  :deep(.review-request-table--new .p-datatable-tbody > tr > td:nth-child(6)) {
    order: 6;
    grid-column: 2;
  }

  :deep(.review-request-table--new .p-datatable-tbody > tr > td:nth-child(7)) {
    order: 7;
    grid-column: 1 / -1;
  }

  :deep(.review-card-actions) {
    display: grid;
    grid-template-columns: repeat(4, minmax(2.5rem, 1fr));
    width: 100%;
    gap: 0.45rem;
  }

  :deep(.review-card-action-note) {
    grid-column: 1 / -1;
    max-width: 100%;
  }

  :deep(.review-card-actions .p-button) {
    width: 100%;
    min-width: 0;
    min-height: 2.5rem;
    padding-inline: 0.4rem;
    justify-content: center;
  }

  :deep(.review-card-actions .p-button-label) {
    display: none;
  }

  :deep(.review-card-actions .pi) {
    margin: 0;
    line-height: 1;
  }

  :deep(.p-paginator) {
    font-size: 0.875rem;
    justify-content: flex-start;
    flex-wrap: wrap;
    padding: 0.5rem 0;
    max-width: 100%;
  }

  :deep(.p-paginator-current) {
    flex: 0 1 auto;
    min-width: 0;
    margin-inline-start: 0.5rem;
    text-align: center;
    white-space: nowrap;
  }

  .compare-preview-grid {
    grid-template-columns: 1fr;
  }

  :deep(.comparison-desktop-table) {
    display: none;
  }

  .submission-detail-comparison-mobile {
    display: grid;
    gap: 0.65rem;
  }
}

@media (max-width: 640px) {
  .comparison-mobile-actions :deep(.p-button) {
    flex: 1 1 calc(50% - 0.45rem);
    min-width: 0;
    justify-content: center;
  }

  :deep(.review-card-actions) {
    width: 100%;
    flex-wrap: nowrap;
    overflow-x: visible;
    padding-bottom: 0.1rem;
  }

  :deep(.review-card-actions .p-button) {
    flex: 1 1 0;
    width: auto;
    min-width: 0;
    justify-content: center;
  }
}

@media (max-width: 480px) {
  .comparison-mobile-meta {
    grid-template-columns: 1fr;
  }

  .comparison-mobile-card-header {
    flex-wrap: wrap;
  }

  .comparison-mobile-status {
    max-width: 100%;
  }

  :deep(.admin-card-actions .p-button) {
    min-width: 2.6rem;
    width: 2.6rem;
    padding-inline: 0.4rem;
    justify-content: center;
  }

  :deep(.admin-card-actions .p-button .p-button-label) {
    display: none;
  }

  :deep(.admin-card-actions .p-button .pi) {
    margin: 0;
    line-height: 1;
  }
}

@media (max-width: 600px) {
  :deep(.admin-card-actions .p-button) {
    min-width: 2.65rem;
    width: 2.65rem;
    min-height: 2.65rem;
    padding-inline: 0.45rem;
    justify-content: center;
  }

  :deep(.admin-card-actions .p-button .p-button-label) {
    display: none;
  }

  :deep(.admin-card-actions .p-button .pi) {
    margin: 0;
    line-height: 1;
  }

  :deep(.notification-management-table .admin-card-actions) {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    width: 100%;
    gap: 0.5rem;
  }

  :deep(.user-management-table .admin-card-actions) {
    display: flex;
    flex-wrap: wrap;
    width: 100%;
    gap: 0.5rem;
    align-items: center;
  }

  :deep(.notification-management-table .admin-card-actions .p-button) {
    width: 100%;
    min-width: 0;
    min-height: 2.65rem;
  }

  :deep(.user-management-table .admin-card-actions .p-button) {
    width: auto;
    min-width: 7rem;
    min-height: 2.35rem;
  }

  :deep(.admin-mobile-list .admin-mobile-card-actions .p-button) {
    width: 100%;
    min-width: 0;
    min-height: 2.65rem;
  }
}

@media (max-width: 1023px) {
  :deep(.admin-desktop-data-table.user-management-table),
  :deep(.admin-desktop-data-table.course-management-table),
  :deep(.admin-desktop-data-table.category-management-table),
  :deep(.admin-desktop-data-table.notification-management-table) {
    display: none;
  }

  .admin-mobile-list--users,
  .admin-mobile-list--courses,
  .admin-mobile-list--categories,
  .admin-mobile-list--notifications {
    display: flex;
    flex-direction: column;
    gap: 0.8rem;
    width: 100%;
    min-width: 0;
  }

  .admin-mobile-paginator {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 0.2rem;
    max-width: 100%;
    padding: 0.55rem 0.25rem;
    overflow: hidden;
  }

  .admin-mobile-paginator :deep(.p-paginator-first),
  .admin-mobile-paginator :deep(.p-paginator-prev),
  .admin-mobile-paginator :deep(.p-paginator-page),
  .admin-mobile-paginator :deep(.p-paginator-next),
  .admin-mobile-paginator :deep(.p-paginator-last) {
    flex: 0 0 auto;
    min-width: 2.25rem;
    width: 2.25rem;
    height: 2.25rem;
  }

  .admin-mobile-paginator :deep(.p-select) {
    flex: 0 0 auto;
    min-width: 4.25rem;
  }

  .admin-mobile-paginator :deep(.p-paginator-current) {
    flex: 0 1 auto;
    min-width: 0;
    margin-inline-start: 0.5rem;
    text-align: center;
    white-space: nowrap;
  }

  .admin-mobile-list--users .admin-mobile-card,
  .admin-mobile-list--courses .admin-mobile-card,
  .admin-mobile-list--categories .admin-mobile-card,
  .admin-mobile-list--notifications .admin-mobile-card {
    display: flex;
    flex-direction: column;
    width: 100%;
    max-width: 100%;
    min-width: 0;
    gap: 0.85rem;
    box-sizing: border-box;
    padding: 1rem;
    border: 1px solid color-mix(in srgb, var(--primary-color) 38%, var(--border-color));
    border-radius: 8px;
    background: color-mix(in srgb, var(--bg-secondary) 86%, transparent);
  }

  .admin-mobile-list--users .admin-card-primary,
  .admin-mobile-list--notifications .admin-card-primary,
  .admin-mobile-list--courses .course-card-primary,
  .admin-mobile-list--categories .category-card-main {
    width: 100%;
    max-width: 100%;
    min-width: 0;
  }

  .admin-mobile-list--users .admin-card-title,
  .admin-mobile-list--notifications .admin-card-title,
  .admin-mobile-list--courses .course-card-title,
  .admin-mobile-list--categories .category-card-title {
    display: block;
    max-width: 100%;
    min-width: 0;
    color: var(--text-primary);
    font-size: 1rem;
    font-weight: 800;
    line-height: 1.35;
    word-break: normal;
    overflow-wrap: break-word;
  }

  .admin-mobile-list--users .admin-card-email {
    display: block;
    max-width: 100%;
    min-width: 0;
    margin-top: 0.25rem;
    color: var(--text-primary);
    font-size: 0.95rem;
    line-height: 1.4;
    overflow-wrap: anywhere;
  }

  .admin-mobile-list--users .admin-card-meta,
  .admin-mobile-list--notifications .admin-card-meta,
  .admin-mobile-list--categories .category-card-meta,
  .admin-mobile-list--courses .course-card-topline,
  .admin-mobile-list--categories .category-card-topline {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.45rem;
    width: 100%;
    min-width: 0;
  }

  .admin-mobile-list--users .admin-card-meta-text,
  .admin-mobile-list--notifications .admin-card-meta-text {
    color: var(--text-primary);
    font-size: 0.9rem;
    line-height: 1.3;
    white-space: nowrap;
  }

  .admin-mobile-list--categories .category-card-main {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 0.75rem;
  }

  .admin-mobile-list--categories .category-card-order,
  .admin-mobile-list--courses .course-card-order {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 1.85rem;
    height: 1.85rem;
    border-radius: 999px;
    background: color-mix(in srgb, var(--primary-color) 18%, transparent);
    color: var(--text-primary);
    font-size: 0.85rem;
    font-weight: 800;
    line-height: 1;
  }

  :deep(.admin-mobile-list--categories .category-card-topline .p-button),
  :deep(.admin-mobile-list--courses .course-card-topline .p-button) {
    width: 2rem;
    min-width: 2rem;
    height: 2rem;
    min-height: 2rem;
    padding-inline: 0;
    justify-content: center;
  }

  :deep(.admin-mobile-list--categories .category-card-topline .pi),
  :deep(.admin-mobile-list--courses .course-card-topline .pi) {
    margin: 0;
    line-height: 1;
  }

  .admin-mobile-list--categories .category-card-key {
    display: inline-flex;
    flex: 0 1 auto;
    flex-direction: column;
    gap: 0.1rem;
    align-items: flex-start;
    max-width: 48%;
    padding: 0.32rem 0.5rem;
    border: 1px solid var(--border-color);
    border-radius: 0.55rem;
    background: color-mix(in srgb, var(--panel-bg) 88%, var(--primary-color) 12%);
  }

  .admin-mobile-list--categories .category-card-key-label {
    color: var(--accent-gold);
    font-size: 0.68rem;
    font-weight: 800;
    line-height: 1.2;
    white-space: nowrap;
  }

  .admin-mobile-list--categories .category-card-key-value {
    max-width: 100%;
    color: var(--text-primary);
    font-size: 0.82rem;
    line-height: 1.25;
    overflow-wrap: anywhere;
  }

  :deep(.admin-mobile-list--courses .course-card-category),
  :deep(.admin-mobile-list--categories .p-tag),
  :deep(.admin-mobile-list--users .p-tag),
  :deep(.admin-mobile-list--notifications .p-tag) {
    width: fit-content;
    max-width: 100%;
    white-space: nowrap;
  }

  .admin-mobile-list--users .admin-mobile-card-actions,
  .admin-mobile-list--courses .admin-mobile-card-actions,
  .admin-mobile-list--categories .admin-mobile-card-actions,
  .admin-mobile-list--notifications .announcement-mobile-actions {
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: 0.5rem;
    width: 100%;
    min-width: 0;
  }

  :deep(.admin-mobile-list--users .admin-mobile-card-actions .p-button),
  :deep(.admin-mobile-list--courses .admin-mobile-card-actions .p-button),
  :deep(.admin-mobile-list--categories .admin-mobile-card-actions .p-button),
  :deep(.admin-mobile-list--notifications .announcement-mobile-actions .p-button) {
    width: auto;
    min-height: 2.45rem;
    justify-content: center;
    white-space: nowrap;
  }
}

@media (max-width: 400px) {
  .admin-mobile-paginator {
    gap: 0.1rem;
    padding-inline: 0;
  }

  .admin-mobile-paginator :deep(.p-paginator-first),
  .admin-mobile-paginator :deep(.p-paginator-prev),
  .admin-mobile-paginator :deep(.p-paginator-page),
  .admin-mobile-paginator :deep(.p-paginator-next),
  .admin-mobile-paginator :deep(.p-paginator-last) {
    min-width: 2rem;
    width: 2rem;
    height: 2rem;
  }
}

@media (min-width: 641px) and (max-width: 1023px) {
  .admin-mobile-list--users .admin-mobile-card-actions,
  .admin-mobile-list--courses .admin-mobile-card-actions,
  .admin-mobile-list--categories .admin-mobile-card-actions,
  .admin-mobile-list--notifications .announcement-mobile-actions {
    flex-wrap: nowrap;
    justify-content: flex-start;
    overflow-x: auto;
    padding-bottom: 0.05rem;
  }

  :deep(.admin-mobile-list--users .admin-mobile-card-actions .p-button),
  :deep(.admin-mobile-list--courses .admin-mobile-card-actions .p-button),
  :deep(.admin-mobile-list--categories .admin-mobile-card-actions .p-button),
  :deep(.admin-mobile-list--notifications .announcement-mobile-actions .p-button) {
    flex: 0 0 auto;
    width: auto;
    min-width: 5.25rem;
    padding-inline: 0.65rem;
  }

  :deep(.admin-mobile-list--users .admin-mobile-card-actions .p-button-label),
  :deep(.admin-mobile-list--courses .admin-mobile-card-actions .p-button-label),
  :deep(.admin-mobile-list--categories .admin-mobile-card-actions .p-button-label),
  :deep(.admin-mobile-list--notifications .announcement-mobile-actions .p-button-label) {
    display: inline-flex;
  }

  :deep(.admin-mobile-list--users .admin-mobile-card-actions .pi),
  :deep(.admin-mobile-list--courses .admin-mobile-card-actions .pi),
  :deep(.admin-mobile-list--categories .admin-mobile-card-actions .pi),
  :deep(.admin-mobile-list--notifications .announcement-mobile-actions .pi) {
    margin-inline-end: 0.35rem;
  }
}

@media (max-width: 640px) {
  .admin-mobile-list--users .admin-mobile-card-actions,
  .admin-mobile-list--courses .admin-mobile-card-actions,
  .admin-mobile-list--categories .admin-mobile-card-actions,
  .admin-mobile-list--notifications .announcement-mobile-actions {
    flex-wrap: wrap;
    justify-content: stretch;
    overflow-x: visible;
  }

  :deep(.admin-mobile-list--users .admin-mobile-card-actions .p-button),
  :deep(.admin-mobile-list--courses .admin-mobile-card-actions .p-button),
  :deep(.admin-mobile-list--categories .admin-mobile-card-actions .p-button),
  :deep(.admin-mobile-list--notifications .announcement-mobile-actions .p-button) {
    flex: 1 1 calc(33.333% - 0.5rem);
    width: auto;
    min-width: 5.7rem;
    min-height: 2.65rem;
    padding-inline: 0.45rem;
  }

  :deep(.admin-mobile-list--users .admin-mobile-card-actions .p-button-label),
  :deep(.admin-mobile-list--courses .admin-mobile-card-actions .p-button-label),
  :deep(.admin-mobile-list--categories .admin-mobile-card-actions .p-button-label),
  :deep(.admin-mobile-list--notifications .announcement-mobile-actions .p-button-label) {
    display: inline-flex;
  }

  :deep(.admin-mobile-list--users .admin-mobile-card-actions .pi),
  :deep(.admin-mobile-list--courses .admin-mobile-card-actions .pi),
  :deep(.admin-mobile-list--categories .admin-mobile-card-actions .pi),
  :deep(.admin-mobile-list--notifications .announcement-mobile-actions .pi) {
    margin-inline-end: 0.3rem;
  }
}

@media (max-width: 768px) {
  .review-dialog-actions {
    display: grid !important;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0.5rem;
    justify-content: stretch;
  }

  :deep(.review-dialog-actions .p-button) {
    width: 100%;
    min-width: 0;
    min-height: 2.75rem;
    padding-inline: 0.45rem;
    justify-content: center;
  }

  :deep(.review-dialog-actions .p-button-label) {
    display: none;
  }

  :deep(.review-dialog-actions .pi) {
    margin: 0;
    line-height: 1;
  }
}

/* Desktop table overflow handling */
@media (min-width: 769px) {
  :deep(.p-datatable) {
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

  :deep(.p-datatable .admin-card-actions),
  :deep(.p-datatable .review-card-actions) {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-wrap: wrap;
  }

  :deep(.review-card-action-note) {
    width: 100%;
    max-width: min(18rem, 100%);
  }

  :deep(.review-card-action-note),
  :deep(.review-card-action-note .review-card-action-note__text) {
    white-space: normal;
  }

  /* Ensure buttons don't wrap on desktop */
  :deep(.p-datatable .flex.gap-2) {
    flex-wrap: nowrap;
    gap: 0.5rem;
  }
}

:global(.dark)
  :deep(.review-row-action-area .review-card-action-note--info.review-card-action-note),
:global(.dark)
  :deep(.review-row-action-area .review-card-action-note--info.review-card-action-note .pi),
:global(.dark)
  :deep(
    .review-row-action-area
      .review-card-action-note--info.review-card-action-note
      .review-card-action-note__text
  ) {
  color: #67e8f9 !important;
}

:global(.dark)
  :deep(.review-row-action-area .review-card-action-note--info.review-card-action-note) {
  border-color: rgba(103, 232, 249, 0.68) !important;
  background: rgba(34, 211, 238, 0.16) !important;
}

:global(.dark)
  :deep(.review-row-action-area .review-card-action-note--warning.review-card-action-note),
:global(.dark)
  :deep(.review-row-action-area .review-card-action-note--warning.review-card-action-note .pi),
:global(.dark)
  :deep(
    .review-row-action-area
      .review-card-action-note--warning.review-card-action-note
      .review-card-action-note__text
  ) {
  color: #fbbf24 !important;
}

:global(.dark)
  :deep(.review-row-action-area .review-card-action-note--warning.review-card-action-note) {
  border-color: rgba(251, 191, 36, 0.68) !important;
  background: rgba(251, 146, 60, 0.16) !important;
}

:deep(.review-mobile-summary) {
  display: none;
}

:deep(.review-mobile-card-header) {
  display: none;
}

@media (max-width: 1399px) {
  .review-center {
    padding: 0.75rem !important;
  }

  .review-search-toolbar {
    margin-bottom: 0.75rem;
  }

  .review-search-toolbar .relative {
    width: min(100%, 26rem) !important;
  }

  .review-search-toolbar .review-status-filter {
    width: min(100%, 26rem) !important;
  }

  .review-search-toolbar :deep(.p-inputtext) {
    min-height: 2.35rem;
    padding-top: 0.45rem;
    padding-bottom: 0.45rem;
    font-size: 0.92rem;
  }

  .review-section.mt-5 {
    margin-top: 1rem !important;
  }

  .review-section-header {
    gap: 0.5rem;
    margin-bottom: 0.65rem;
  }

  .review-section-header h3 {
    font-size: 1rem;
    line-height: 1.35;
  }

  :deep(.review-request-table) {
    overflow: visible;
  }

  :deep(.review-request-table .p-datatable-table-container) {
    overflow: visible;
  }

  :deep(.review-request-table .p-datatable-table) {
    display: block;
    width: 100%;
    min-width: 0 !important;
  }

  :deep(.review-request-table .p-datatable-thead) {
    display: none !important;
  }

  :deep(.review-request-table .p-datatable-tbody) {
    display: block;
    width: 100%;
  }

  :deep(.review-request-table .p-datatable-tbody > tr) {
    display: flex;
    flex-direction: column;
    width: 100%;
    min-width: 0;
    box-sizing: border-box;
    gap: 0.75rem;
    padding: 0.95rem;
    border: 1px solid var(--border-color);
    border-radius: 8px;
    background: color-mix(in srgb, var(--bg-primary) 94%, var(--bg-secondary) 6%);
  }

  :deep(.review-request-table .p-datatable-tbody > tr > td) {
    display: none;
    width: 100%;
    min-width: 0;
    padding: 0 !important;
    border: 0 !important;
    white-space: normal !important;
  }

  :deep(.review-request-table .p-column-title) {
    display: none !important;
  }

  :deep(.review-request-table--new .p-datatable-tbody > tr > td:nth-child(2)),
  :deep(
    .review-request-table:not(.review-request-table--new) .p-datatable-tbody > tr > td:first-child
  ),
  :deep(.review-request-table .p-datatable-tbody > tr > td:last-child) {
    display: flex;
    flex-direction: column;
    align-items: stretch;
  }

  :deep(.review-request-table--new .p-datatable-tbody > tr > td:nth-child(2)),
  :deep(
    .review-request-table:not(.review-request-table--new) .p-datatable-tbody > tr > td:first-child
  ) {
    order: 1;
  }

  :deep(.review-request-table .p-datatable-tbody > tr > td:last-child) {
    order: 2;
    padding-top: 0.75rem !important;
    border-top: 1px solid color-mix(in srgb, var(--border-color) 78%, transparent) !important;
  }

  :deep(.review-mobile-card-header) {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 0.8rem;
    width: 100%;
    min-width: 0;
  }

  :deep(.review-mobile-card-title-block) {
    display: flex;
    flex: 1 1 auto;
    min-width: 0;
    flex-direction: column;
    gap: 0.4rem;
  }

  :deep(.review-mobile-card-course-name) {
    min-width: 0;
    color: var(--text-primary);
    font-size: 1.02rem;
    font-weight: 800;
    line-height: 1.3;
    overflow-wrap: anywhere;
  }

  :deep(.review-mobile-type-badges) {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.35rem;
    min-width: 0;
  }

  :deep(.review-mobile-type-badges .review-admin-upload-chip) {
    font-size: 0.72rem;
    font-weight: 700;
  }

  :deep(.review-mobile-card-type-badge) {
    align-self: flex-start;
  }

  :deep(.review-mobile-card-status-badge) {
    flex: 0 0 auto;
    max-width: 42%;
    justify-content: center;
    white-space: nowrap;
    text-align: center;
  }

  :deep(.review-card-title) {
    display: none;
    align-items: center;
    flex-wrap: wrap;
    gap: 0.35rem;
    font-size: 1rem;
    font-weight: 800;
    line-height: 1.3;
  }

  :deep(.review-mobile-summary) {
    display: block;
    width: 100%;
    margin-top: 0.35rem;
  }

  :deep(.review-mobile-exam-name) {
    color: var(--text-primary);
    font-size: 0.94rem;
    font-weight: 650;
    line-height: 1.3;
    overflow-wrap: anywhere;
  }

  :deep(.review-mobile-info-grid) {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0.42rem 0.65rem;
    width: 100%;
    margin-top: 0.55rem;
  }

  :deep(.review-mobile-info-item) {
    display: inline-flex;
    flex-wrap: wrap;
    align-items: baseline;
    align-content: flex-start;
    gap: 0.12rem 0.35rem;
    min-width: 0;
  }

  :deep(.review-mobile-info-label) {
    display: inline;
    flex: 0 0 auto;
    color: var(--text-secondary);
    font-size: 0.72rem;
    font-weight: 650;
    line-height: 1.2;
  }

  :deep(.review-mobile-info-value) {
    display: inline;
    flex: 1 1 auto;
    min-width: 0;
    color: var(--text-primary);
    font-size: 0.84rem;
    line-height: 1.3;
    overflow-wrap: anywhere;
  }

  :deep(.review-card-meta-text) {
    color: var(--text-secondary);
    font-size: 0.86rem;
    line-height: 1.35;
    white-space: normal;
    overflow-wrap: anywhere;
  }

  :deep(.review-request-table .text-xs) {
    display: inline-flex;
    color: var(--text-secondary);
    line-height: 1.35;
    white-space: normal;
  }

  :deep(.review-request-table .p-tag),
  :deep(.review-card-chip) {
    width: fit-content;
    max-width: 100%;
    flex-shrink: 0;
    white-space: nowrap;
  }

  :deep(.review-row-action-area) {
    display: flex;
    flex-direction: column;
    width: 100%;
    gap: 0.55rem;
  }

  :deep(.review-card-action-note) {
    order: 1;
    width: 100%;
    max-width: 100%;
    margin: 0;
  }

  :deep(.p-datatable .review-card-actions),
  :deep(.review-card-actions) {
    order: 2;
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    justify-content: flex-end;
    width: 100%;
    gap: 0.45rem;
    overflow-x: visible;
    padding-bottom: 0.05rem;
  }

  :deep(.p-datatable .review-card-actions .p-button),
  :deep(.review-card-actions .p-button) {
    width: auto;
    flex: 0 0 auto;
    min-width: 5.75rem;
    min-height: 2.35rem;
    padding-inline: 0.5rem;
    justify-content: center;
  }

  :deep(.p-datatable .review-card-actions .p-button .p-button-label),
  :deep(.review-card-actions .p-button .p-button-label) {
    display: inline-flex;
  }

  :deep(.p-datatable .review-card-actions .p-button .pi),
  :deep(.review-card-actions .p-button .pi) {
    margin-inline-end: 0.35rem;
    line-height: 1;
  }
}

@media (min-width: 900px) and (max-width: 1399px) {
  :deep(.review-mobile-info-grid) {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0.55rem 1rem;
  }

  :deep(.review-request-table .p-datatable-tbody > tr) {
    padding: 1.1rem;
  }

  :deep(.review-card-actions) {
    justify-content: flex-end;
  }
}

@media (max-width: 640px) {
  :deep(.review-request-table .p-datatable-tbody > tr) {
    gap: 0.4rem;
    padding: 0.8rem;
  }

  :deep(.review-request-table .p-datatable-tbody > tr > td) {
    width: 100%;
  }

  :deep(.p-datatable .review-card-actions),
  :deep(.review-card-actions) {
    display: flex;
    flex-wrap: nowrap;
    justify-content: stretch;
    overflow-x: visible;
  }

  :deep(.p-datatable .review-card-actions .p-button),
  :deep(.review-card-actions .p-button) {
    flex: 1 1 0;
    width: auto;
    min-width: 0;
    min-height: 2.45rem;
    padding-inline: 0.45rem;
  }

  :deep(.p-datatable .review-card-actions .p-button .p-button-label),
  :deep(.review-card-actions .p-button .p-button-label) {
    display: none;
  }

  :deep(.p-datatable .review-card-actions .p-button .pi),
  :deep(.review-card-actions .p-button .pi) {
    margin: 0;
  }
}

@media (min-width: 641px) and (max-width: 1023px) {
  .admin-toolbar {
    align-items: center;
  }

  .admin-toolbar__filters {
    flex: 1 1 30rem;
    flex-direction: row;
  }

  .admin-toolbar__search {
    flex: 1 1 16rem;
    width: auto !important;
    min-width: min(100%, 16rem);
  }

  .admin-toolbar__select {
    flex: 0 1 13.5rem;
    width: auto !important;
    min-width: 12rem;
  }

  .review-search-toolbar .admin-toolbar__search.relative,
  .review-search-toolbar .review-status-filter.admin-toolbar__select {
    width: auto !important;
  }

  .admin-toolbar__actions {
    width: auto;
    flex: 0 0 auto;
    justify-content: flex-end;
  }

  :deep(.admin-toolbar__button.p-button),
  :deep(.admin-toolbar__actions .p-button) {
    flex: 0 0 auto;
    width: auto !important;
    min-width: 0;
    padding-inline: 0.8rem;
  }

  .admin-toolbar--trash {
    flex: 1 1 38rem;
  }

  .admin-toolbar__filters--trash {
    flex: 0 1 14rem;
  }

  .admin-toolbar__actions--trash {
    flex: 1 1 auto;
  }
}

@media (min-width: 641px) and (max-width: 760px) {
  .admin-mobile-list--users .user-card-title-group,
  .admin-mobile-list--notifications .announcement-card-title-group {
    display: flex;
    flex: 1 1 0;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.4rem 0.5rem;
    min-width: 0;
  }

  .admin-mobile-list--users .user-card-title-group .admin-tablet-card-title,
  .admin-mobile-list--notifications .announcement-card-title-group .admin-tablet-card-title {
    flex: 0 1 auto;
    width: fit-content;
    min-width: 0;
  }

  .admin-mobile-list--users .user-role-tag-group,
  .admin-mobile-list--notifications .announcement-type-tag-group {
    flex: 0 0 auto;
  }

  .admin-mobile-list--users .user-role-tag-group :deep(.p-tag),
  .admin-mobile-list--notifications .announcement-type-tag-group :deep(.p-tag) {
    flex-shrink: 0;
    white-space: nowrap;
  }

  .admin-toolbar:not(.admin-toolbar--trash):not(.admin-toolbar--trash-shell):not(
      .admin-toolbar--section
    ) {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    align-items: center;
    gap: 0.65rem 0.75rem;
  }

  .admin-toolbar:not(.admin-toolbar--trash):not(.admin-toolbar--trash-shell):not(
      .admin-toolbar--section
    )
    > .admin-toolbar__filters {
    display: contents;
  }

  .admin-toolbar:not(.admin-toolbar--trash):not(.admin-toolbar--trash-shell):not(
      .admin-toolbar--section
    )
    .admin-toolbar__search {
    grid-column: 1 / -1;
    width: 100% !important;
    min-width: 0;
  }

  .admin-toolbar:not(.admin-toolbar--trash):not(.admin-toolbar--trash-shell):not(
      .admin-toolbar--section
    )
    .admin-toolbar__select {
    grid-column: 1;
    width: 100% !important;
    min-width: min(100%, 15rem);
  }

  .admin-toolbar:not(.admin-toolbar--trash):not(.admin-toolbar--trash-shell):not(
      .admin-toolbar--section
    )
    > .admin-toolbar__actions {
    grid-column: 2;
    justify-self: end;
    width: auto;
  }
}

@media (min-width: 761px) and (max-width: 1023px) {
  .admin-toolbar:not(.admin-toolbar--trash):not(.admin-toolbar--trash-shell):not(
      .admin-toolbar--section
    ) {
    display: grid;
    grid-template-columns: minmax(16rem, 1fr) minmax(12rem, 15rem) auto;
    align-items: center;
    gap: 0.75rem;
  }

  .admin-toolbar:not(.admin-toolbar--trash):not(.admin-toolbar--trash-shell):not(
      .admin-toolbar--section
    )
    > .admin-toolbar__filters {
    display: contents;
  }

  .admin-toolbar:not(.admin-toolbar--trash):not(.admin-toolbar--trash-shell):not(
      .admin-toolbar--section
    )
    .admin-toolbar__search,
  .admin-toolbar:not(.admin-toolbar--trash):not(.admin-toolbar--trash-shell):not(
      .admin-toolbar--section
    )
    .admin-toolbar__select {
    width: 100% !important;
    min-width: 0;
  }

  .admin-toolbar:not(.admin-toolbar--trash):not(.admin-toolbar--trash-shell):not(
      .admin-toolbar--section
    )
    > .admin-toolbar__actions {
    justify-self: end;
    width: auto;
  }
}

@media (max-width: 640px) {
  .admin-toolbar {
    align-items: stretch;
    justify-content: flex-start;
  }

  .admin-toolbar__filters,
  .admin-toolbar__actions {
    width: 100%;
  }

  .admin-toolbar__filters {
    flex-direction: column;
    align-items: stretch;
  }

  .admin-toolbar__search,
  .admin-toolbar__select {
    flex: 0 1 auto;
    width: 100% !important;
    min-width: 0;
  }

  .admin-toolbar__actions {
    justify-content: flex-end;
  }

  :deep(.admin-toolbar__button.p-button),
  :deep(.admin-toolbar__actions .p-button) {
    width: auto !important;
    min-width: 0;
  }

  .admin-toolbar--trash {
    width: 100%;
  }

  .admin-toolbar__filters--trash {
    flex: 1 1 100%;
  }

  .admin-toolbar__actions--trash {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    justify-content: stretch;
  }

  :deep(.admin-toolbar__actions--trash .p-button) {
    width: 100% !important;
    min-width: 0;
    padding-inline: 0.45rem;
    white-space: normal;
  }
}

@media (max-width: 1399px) {
  :deep(.trash-table) {
    display: none !important;
  }

  .trash-mobile-list {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    width: 100%;
    min-width: 0;
  }

  .trash-mobile-card {
    display: flex;
    flex-direction: column;
    gap: 0.65rem;
    width: 100%;
    min-width: 0;
    box-sizing: border-box;
    padding: 0.78rem;
    border: 1px solid color-mix(in srgb, var(--primary-color) 34%, var(--border-color));
    border-radius: 8px;
    background: color-mix(in srgb, var(--bg-secondary) 86%, transparent);
  }

  .trash-mobile-card.trash-row--relation-group-even {
    background: color-mix(in srgb, rgba(16, 185, 129, 0.12) 72%, var(--bg-secondary) 28%);
  }

  .trash-mobile-card.trash-row--relation-group-odd {
    background: color-mix(in srgb, rgba(59, 130, 246, 0.1) 72%, var(--bg-secondary) 28%);
  }

  .trash-mobile-card-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 0.7rem;
    width: 100%;
    min-width: 0;
  }

  .trash-mobile-card-title-block {
    display: flex;
    flex: 1 1 auto;
    min-width: 0;
    flex-direction: column;
    gap: 0.35rem;
  }

  .trash-mobile-card-title {
    display: inline-flex;
    align-items: flex-start;
    gap: 0.35rem;
    max-width: 100%;
    color: var(--text-primary);
    font-size: 1rem;
    font-weight: 800;
    line-height: 1.35;
    overflow-wrap: anywhere;
    white-space: normal;
  }

  .trash-mobile-card-badges {
    display: flex;
    flex: 0 1 auto;
    flex-wrap: wrap;
    justify-content: flex-end;
    align-items: flex-start;
    gap: 0.35rem;
    max-width: 54%;
    min-width: 0;
  }

  :deep(.trash-mobile-card-badges .p-tag) {
    flex-shrink: 0;
    justify-content: center;
    text-align: center;
    white-space: nowrap;
  }

  :deep(.trash-mobile-type-badge),
  :deep(.trash-mobile-status) {
    max-width: 100%;
  }

  .trash-mobile-info-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0.38rem 0.65rem;
    width: 100%;
    min-width: 0;
  }

  .trash-mobile-info-item {
    display: inline-flex;
    flex-wrap: wrap;
    align-items: baseline;
    align-content: flex-start;
    gap: 0.12rem 0.35rem;
    min-width: 0;
  }

  .trash-mobile-info-label {
    display: inline;
    flex: 0 0 auto;
    color: var(--text-secondary);
    font-size: 0.72rem;
    font-weight: 700;
    line-height: 1.2;
  }

  .trash-mobile-info-value {
    display: inline;
    flex: 1 1 auto;
    min-width: 0;
    color: var(--text-primary);
    font-size: 0.85rem;
    line-height: 1.35;
    overflow-wrap: anywhere;
  }

  .trash-mobile-dependencies {
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem;
    width: 100%;
    min-width: 0;
  }

  .trash-mobile-card-footer {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-start;
    justify-content: space-between;
    gap: 0.55rem 0.75rem;
    width: 100%;
    min-width: 0;
    margin-top: 0.05rem;
    padding-top: 0.65rem;
    border-top: 1px solid color-mix(in srgb, var(--border-color) 78%, transparent);
  }

  .trash-mobile-card-footer .trash-mobile-dependencies {
    flex: 1 1 12rem;
  }

  :deep(.trash-mobile-dependencies .trash-dependency-chip) {
    min-height: 1.55rem !important;
    padding: 0.18rem 0.52rem !important;
    border-width: 1px !important;
    font-size: 0.74rem !important;
    line-height: 1.22 !important;
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--soft-badge-border) 38%, transparent) !important;
  }

  :deep(.trash-mobile-dependencies .trash-dependency-chip--relation) {
    --soft-badge-bg: rgba(51, 65, 85, 0.14);
    --soft-badge-border: rgba(51, 65, 85, 0.42);
    --soft-badge-color: #263548;
  }

  :deep(.trash-mobile-dependencies .trash-dependency-chip--restore-blocked) {
    --soft-badge-bg: rgba(217, 119, 6, 0.18);
    --soft-badge-border: rgba(217, 119, 6, 0.48);
    --soft-badge-color: #7c2d12;
  }

  :deep(.trash-mobile-dependencies .trash-dependency-chip--delete-blocked) {
    --soft-badge-bg: rgba(234, 88, 12, 0.18);
    --soft-badge-border: rgba(234, 88, 12, 0.5);
    --soft-badge-color: #7c2d12;
  }

  :deep(.trash-mobile-dependencies .trash-dependency-chip--cascade) {
    --soft-badge-bg: rgba(79, 70, 229, 0.16);
    --soft-badge-border: rgba(79, 70, 229, 0.46);
    --soft-badge-color: #3730a3;
  }

  :deep(.trash-mobile-dependencies .trash-dependency-chip--clear) {
    --soft-badge-bg: rgba(22, 163, 74, 0.16);
    --soft-badge-border: rgba(22, 163, 74, 0.44);
    --soft-badge-color: #14532d;
  }

  .trash-mobile-card-actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: flex-end;
    gap: 0.45rem;
    flex: 0 0 auto;
    width: auto;
    min-width: 0;
    overflow-x: visible;
    padding-bottom: 0.05rem;
  }

  :deep(.trash-mobile-card-actions .p-button) {
    flex: 0 0 auto;
    width: auto;
    min-width: 5.25rem;
    min-height: 2.35rem;
    padding-inline: 0.65rem;
    justify-content: center;
    white-space: nowrap;
  }

  :deep(.trash-mobile-card-actions .p-button-label) {
    display: inline-flex;
  }

  :deep(.trash-mobile-card-actions .pi) {
    margin-inline-end: 0.35rem;
    line-height: 1;
  }

  :global(.dark .trash-mobile-card) {
    border-color: color-mix(in srgb, var(--primary-color) 40%, var(--border-color));
    background: color-mix(in srgb, var(--bg-secondary) 82%, #000 18%);
  }

  :global(.dark .trash-mobile-card .trash-mobile-dependencies .trash-dependency-chip--relation) {
    --soft-badge-bg: rgba(148, 163, 184, 0.24);
    --soft-badge-border: rgba(203, 213, 225, 0.5);
    --soft-badge-color: #f1f5f9;
    background: var(--soft-badge-bg) !important;
    border-color: var(--soft-badge-border) !important;
    color: var(--soft-badge-color) !important;
  }

  :global(
    .dark .trash-mobile-card .trash-mobile-dependencies .trash-dependency-chip--restore-blocked
  ) {
    --soft-badge-bg: rgba(245, 158, 11, 0.25);
    --soft-badge-border: rgba(251, 191, 36, 0.62);
    --soft-badge-color: #fef3c7;
    background: var(--soft-badge-bg) !important;
    border-color: var(--soft-badge-border) !important;
    color: var(--soft-badge-color) !important;
  }

  :global(
    .dark .trash-mobile-card .trash-mobile-dependencies .trash-dependency-chip--delete-blocked
  ) {
    --soft-badge-bg: rgba(248, 113, 113, 0.23);
    --soft-badge-border: rgba(251, 146, 60, 0.62);
    --soft-badge-color: #ffedd5;
    background: var(--soft-badge-bg) !important;
    border-color: var(--soft-badge-border) !important;
    color: var(--soft-badge-color) !important;
  }

  :global(.dark .trash-mobile-card .trash-mobile-dependencies .trash-dependency-chip--cascade) {
    --soft-badge-bg: rgba(99, 102, 241, 0.28);
    --soft-badge-border: rgba(129, 140, 248, 0.62);
    --soft-badge-color: #eef2ff;
    background: var(--soft-badge-bg) !important;
    border-color: var(--soft-badge-border) !important;
    color: var(--soft-badge-color) !important;
  }

  :global(.dark .trash-mobile-card .trash-mobile-dependencies .trash-dependency-chip--clear) {
    --soft-badge-bg: rgba(34, 197, 94, 0.22);
    --soft-badge-border: rgba(74, 222, 128, 0.56);
    --soft-badge-color: #dcfce7;
    background: var(--soft-badge-bg) !important;
    border-color: var(--soft-badge-border) !important;
    color: var(--soft-badge-color) !important;
  }

  :global(.dark) :deep(.trash-mobile-card-actions .p-button-success.p-button-outlined) {
    border-color: rgba(74, 222, 128, 0.62);
    background: rgba(34, 197, 94, 0.12);
    color: #bbf7d0;
  }

  :global(.dark) :deep(.trash-mobile-card-actions .p-button-danger.p-button-outlined) {
    border-color: rgba(248, 113, 113, 0.64);
    background: rgba(248, 113, 113, 0.1);
    color: #fecaca;
  }
}

@media (min-width: 900px) and (max-width: 1399px) {
  .trash-mobile-card {
    padding: 1rem;
  }

  .trash-mobile-info-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0.5rem 1rem;
  }

  .trash-mobile-info-item--row-start {
    grid-column: 1;
  }

  .trash-mobile-card-actions {
    justify-content: flex-end;
  }
}

@media (max-width: 640px) {
  .trash-mobile-card-header {
    gap: 0.55rem;
  }

  .trash-mobile-card-badges {
    max-width: 52%;
  }

  .trash-mobile-card-actions {
    display: grid;
    grid-auto-flow: column;
    grid-auto-columns: minmax(0, 1fr);
    gap: 0.5rem;
    overflow-x: visible;
  }

  .trash-mobile-card-footer {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
  }

  .trash-mobile-card-footer .trash-mobile-dependencies,
  .trash-mobile-card-footer .trash-mobile-card-actions {
    width: 100%;
  }

  :deep(.trash-mobile-card-actions .p-button) {
    width: 100%;
    min-width: 0;
    min-height: 2.65rem;
    padding-inline: 0.45rem;
  }

  :deep(.trash-mobile-card-actions .p-button-label) {
    display: inline-flex;
  }

  :deep(.trash-mobile-card-actions .pi) {
    margin-inline-end: 0.35rem;
  }
}

@media (max-width: 360px) {
  .trash-mobile-info-grid {
    grid-template-columns: 1fr;
  }

  .trash-mobile-info-item--row-start {
    grid-column: auto;
  }
}

.review-center,
.review-center :deep(.p-component) {
  font-size: var(--app-font-size-base) !important;
}

.review-center .search-icon,
.review-center :deep(.pi),
.review-center :deep(.p-button-icon),
.review-center .review-sort-icon,
.review-center .review-card-action-note .pi {
  font-size: var(--app-icon-size) !important;
}

.review-center :deep(.p-inputtext),
.review-center :deep(.p-inputtext::placeholder),
.review-center :deep(.p-select),
.review-center :deep(.p-select-label),
.review-center :deep(.p-datatable),
.review-center :deep(.p-datatable-thead > tr > th),
.review-center :deep(.p-datatable-tbody > tr > td),
.review-center :deep(.p-paginator),
.review-center :deep(.p-paginator-page),
.review-center .review-card-meta-text,
.review-center .review-sort-header,
.review-center .review-empty-state,
.review-center .review-mobile-info-label,
.review-center .review-mobile-info-value,
.review-center .review-mobile-exam-name,
.review-center .text-xs {
  font-size: var(--app-font-size-sm) !important;
  line-height: 1.35;
}

.review-center .review-card-title,
.review-center .review-mobile-card-course-name {
  font-size: var(--app-font-size-base) !important;
  line-height: 1.32;
}

.review-center :deep(.p-tag),
.review-center :deep(.soft-badge),
.review-center .review-card-chip,
.review-center .review-status-chip,
.review-center .review-admin-upload-chip {
  font-size: var(--app-badge-font-size) !important;
  line-height: 1.25 !important;
}

.review-center .review-card-action-note,
.review-center .review-card-action-note__text {
  font-size: var(--app-font-size-xs) !important;
  line-height: 1.25 !important;
}

.review-center .review-card-action-note .pi {
  font-size: calc(var(--app-font-size-xs) * 0.95) !important;
}

.review-center :deep(.p-button),
.review-center .review-action-button {
  min-height: calc(2rem * var(--app-font-scale));
  font-size: var(--app-font-size-sm) !important;
  line-height: 1.25;
}

.review-center :deep(.p-button-label),
.review-center :deep(.p-button-icon) {
  font-size: inherit !important;
}

.admin-container :deep(.p-tab) {
  font-size: var(--app-font-size-base) !important;
  line-height: 1.35;
  white-space: normal;
}

.admin-toolbar--course,
.admin-toolbar--course :deep(.p-component),
.course-management-table,
.category-management-table {
  font-size: var(--app-font-size-base) !important;
}

.admin-toolbar--course .search-icon,
.admin-toolbar--course :deep(.pi),
.course-management-table :deep(.pi),
.category-management-table :deep(.pi),
.admin-mobile-list--courses :deep(.pi),
.admin-mobile-list--categories :deep(.pi) {
  font-size: var(--app-icon-size) !important;
}

.admin-toolbar--course :deep(.p-inputtext),
.admin-toolbar--course :deep(.p-inputtext::placeholder),
.admin-toolbar--course :deep(.p-select),
.admin-toolbar--course :deep(.p-select-label),
.course-management-table :deep(.p-datatable-thead > tr > th),
.course-management-table :deep(.p-datatable-tbody > tr > td),
.category-management-table :deep(.p-datatable-thead > tr > th),
.category-management-table :deep(.p-datatable-tbody > tr > td),
.course-card-order,
.category-card-order,
.category-card-key-value,
.course-management-table :deep(.p-paginator-current),
.admin-mobile-paginator :deep(.p-paginator-current),
.mobile-field-label,
.mobile-field-value {
  font-size: var(--app-font-size-sm) !important;
  line-height: 1.35;
}

.course-card-title,
.category-card-title,
.category-name-desktop,
.category-mobile-title,
.mobile-primary-text {
  font-size: var(--app-font-size-base) !important;
  line-height: 1.32;
}

.course-management-table :deep(.p-tag),
.category-management-table :deep(.p-tag),
.admin-mobile-list--courses :deep(.p-tag),
.admin-mobile-list--categories :deep(.p-tag),
.course-card-category {
  font-size: var(--app-badge-font-size) !important;
  line-height: 1.25 !important;
}

.admin-toolbar--course :deep(.p-button),
.course-management-table :deep(.p-button),
.category-management-table :deep(.p-button),
.admin-mobile-list--courses :deep(.p-button),
.admin-mobile-list--categories :deep(.p-button) {
  min-height: calc(2rem * var(--app-font-scale));
  font-size: var(--app-font-size-sm) !important;
  line-height: 1.25;
}

.admin-toolbar--course :deep(.p-button-label),
.course-management-table :deep(.p-button-label),
.category-management-table :deep(.p-button-label),
.admin-mobile-list--courses :deep(.p-button-label),
.admin-mobile-list--categories :deep(.p-button-label) {
  font-size: inherit !important;
}

.admin-toolbar--announcement,
.admin-toolbar--announcement :deep(.p-component),
.notification-management-table {
  font-size: var(--app-font-size-base) !important;
}

.admin-toolbar--announcement .search-icon,
.admin-toolbar--announcement :deep(.pi),
.notification-management-table :deep(.pi),
.admin-mobile-list--notifications :deep(.pi) {
  font-size: var(--app-icon-size) !important;
}

.admin-toolbar--announcement :deep(.p-inputtext),
.admin-toolbar--announcement :deep(.p-inputtext::placeholder),
.admin-toolbar--announcement :deep(.p-select),
.admin-toolbar--announcement :deep(.p-select-label),
.notification-management-table :deep(.p-datatable-thead > tr > th),
.notification-management-table :deep(.p-datatable-tbody > tr > td),
.notification-management-table :deep(.p-paginator),
.notification-management-table :deep(.p-paginator-page),
.notification-management-table :deep(.p-paginator-current),
.notification-management-table :deep(.text-sm),
.notification-management-table :deep(.text-700),
.admin-mobile-list--notifications .admin-card-meta-text {
  font-size: var(--app-font-size-sm) !important;
  line-height: 1.35;
}

.notification-management-table .mobile-primary-text,
.admin-announcement-card .admin-card-title,
.admin-announcement-mobile-card .admin-card-title {
  font-size: var(--app-font-size-base) !important;
  line-height: 1.32;
}

.notification-management-table :deep(.p-tag),
.admin-mobile-list--notifications :deep(.p-tag) {
  font-size: var(--app-badge-font-size) !important;
  line-height: 1.25 !important;
}

.admin-toolbar--announcement :deep(.p-button),
.notification-management-table :deep(.p-button),
.admin-mobile-list--notifications :deep(.p-button) {
  min-height: calc(2rem * var(--app-font-scale));
  font-size: var(--app-font-size-sm) !important;
  line-height: 1.25;
}

.admin-toolbar--announcement :deep(.p-button-label),
.notification-management-table :deep(.p-button-label),
.admin-mobile-list--notifications :deep(.p-button-label) {
  font-size: inherit !important;
}

.admin-toolbar--users,
.admin-toolbar--users :deep(.p-component),
.user-management-table {
  font-size: var(--app-font-size-base) !important;
}

.admin-toolbar--users .search-icon,
.admin-toolbar--users :deep(.pi),
.user-management-table :deep(.pi),
.admin-mobile-list--users :deep(.pi),
.user-online-badge .pi {
  font-size: var(--app-icon-size) !important;
}

.admin-toolbar--users :deep(.p-inputtext),
.admin-toolbar--users :deep(.p-inputtext::placeholder),
.admin-toolbar--users :deep(.p-select),
.admin-toolbar--users :deep(.p-select-label),
.user-management-table :deep(.p-datatable-thead > tr > th),
.user-management-table :deep(.p-datatable-tbody > tr > td),
.user-management-table :deep(.p-paginator),
.user-management-table :deep(.p-paginator-page),
.user-management-table :deep(.p-paginator-current),
.user-management-table :deep(.text-sm),
.admin-mobile-list--users .admin-card-email,
.admin-mobile-list--users .admin-card-meta-text,
.user-online-badge {
  font-size: var(--app-font-size-sm) !important;
  line-height: 1.35;
}

.user-management-table .mobile-primary-text,
.admin-user-card .admin-card-title,
.admin-user-mobile-card .admin-card-title {
  font-size: var(--app-font-size-base) !important;
  line-height: 1.32;
}

.user-management-table :deep(.p-tag),
.admin-mobile-list--users :deep(.p-tag) {
  font-size: var(--app-badge-font-size) !important;
  line-height: 1.25 !important;
}

.admin-toolbar--users :deep(.p-button),
.user-management-table :deep(.p-button),
.admin-mobile-list--users :deep(.p-button) {
  min-height: calc(2rem * var(--app-font-scale));
  font-size: var(--app-font-size-sm) !important;
  line-height: 1.25;
}

.admin-toolbar--users :deep(.p-button-label),
.user-management-table :deep(.p-button-label),
.admin-mobile-list--users :deep(.p-button-label) {
  font-size: inherit !important;
}

.admin-insights-card,
.admin-insights-card :deep(.p-component) {
  font-size: var(--app-font-size-base) !important;
}

.admin-insights-card h3,
.admin-insights-card .user-insights__switch button,
.admin-insights-card .user-insights__range button,
.admin-insights-card .section-collapse-toggle,
.admin-insights-card .contributor-level-toggle,
.admin-insights-card .contributor-level-stat strong,
.admin-insights-card .user-level-chart__name {
  font-size: var(--app-font-size-sm) !important;
  line-height: 1.35;
}

.admin-insights-card p,
.admin-insights-card .user-insights__empty,
.admin-insights-card .contributor-level-stat span,
.admin-insights-card .contributor-level-stats__summary,
.admin-insights-card .user-level-chart__row > span,
.admin-insights-card .user-login-column-chart__y-axis,
.admin-insights-card .user-login-column-chart__x-axis > span {
  font-size: var(--app-font-size-xs) !important;
  line-height: 1.35;
}

.admin-insights-card :deep(.p-button) {
  min-height: max(2.25rem, calc(2rem * var(--app-font-scale)));
  font-size: var(--app-font-size-sm) !important;
}

.admin-insights-card .user-insights__switch button,
.admin-insights-card .user-insights__range button,
.admin-insights-card .section-collapse-toggle,
.admin-insights-card .contributor-level-toggle,
.admin-insights-card .contributor-level-stat {
  min-height: max(2.25rem, calc(2rem * var(--app-font-scale)));
}

.admin-toolbar--users :deep(.p-inputtext),
.admin-toolbar--users :deep(.p-select) {
  min-height: max(2.35rem, calc(2.35rem * var(--app-font-scale)));
}

.admin-toolbar--users :deep(.p-button),
.user-management-table :deep(.p-button),
.admin-mobile-list--users :deep(.p-button) {
  min-height: max(2.25rem, calc(2rem * var(--app-font-scale)));
}

.admin-insights-card :deep(.p-button-label),
.admin-insights-card :deep(.p-button-icon) {
  font-size: inherit !important;
}

.admin-insights-card :deep(.p-tag),
.admin-insights-card .contributor-level-badge {
  font-size: var(--app-badge-font-size) !important;
}

.trash-center,
.trash-center :deep(.p-component),
.trash-table,
.trash-paginator {
  font-size: var(--app-font-size-base) !important;
}

.trash-center :deep(.pi),
.trash-center :deep(.p-button-icon),
.trash-table :deep(.pi),
.trash-mobile-list :deep(.pi) {
  font-size: var(--app-icon-size) !important;
}

.trash-center :deep(.p-select),
.trash-center :deep(.p-select-label),
.trash-table :deep(.p-datatable-thead > tr > th),
.trash-table :deep(.p-datatable-tbody > tr > td),
.trash-table :deep(.p-paginator),
.trash-table :deep(.p-paginator-page),
.trash-table :deep(.p-paginator-current),
.trash-paginator,
.trash-paginator :deep(.p-paginator-page),
.trash-paginator :deep(.p-paginator-current),
.trash-name-cell,
.trash-name-cell small,
.trash-mobile-info-label,
.trash-mobile-info-value {
  font-size: var(--app-font-size-sm) !important;
  line-height: 1.35;
}

.trash-name-title,
.trash-mobile-card-title {
  font-size: var(--app-font-size-base) !important;
  line-height: 1.32;
}

.trash-center :deep(.p-tag),
.trash-center :deep(.soft-badge),
.trash-type-chip,
.trash-dependency-chip,
.trash-dependency-help-chip,
.trash-mobile-dependencies :deep(.trash-dependency-chip) {
  font-size: var(--app-badge-font-size) !important;
  line-height: 1.25 !important;
}

.trash-center :deep(.p-button),
.trash-action-button,
.trash-mobile-card-actions :deep(.p-button) {
  min-height: calc(2rem * var(--app-font-scale));
  font-size: var(--app-font-size-sm) !important;
  line-height: 1.25;
}

.trash-center :deep(.p-button-label),
.trash-center :deep(.p-button-icon),
.trash-mobile-card-actions :deep(.p-button-label) {
  font-size: inherit !important;
}

@media (min-width: 641px) and (max-width: 1399px) {
  :deep(.review-request-table .p-datatable-tbody > tr) {
    gap: 0.6rem;
    padding: 0.95rem;
  }

  :deep(.review-mobile-card-title-block) {
    flex-direction: row;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.4rem 0.5rem;
  }

  :deep(.review-mobile-card-course-name) {
    flex: 0 1 auto;
    max-width: 100%;
    word-break: normal;
    overflow-wrap: break-word;
  }

  :deep(.review-mobile-type-badges) {
    flex: 0 0 auto;
  }

  :deep(.review-mobile-summary) {
    margin-top: 0.15rem;
  }

  :deep(.review-mobile-info-grid) {
    gap: 0.4rem 0.85rem;
    margin-top: 0.4rem;
  }

  :deep(.review-mobile-info-item),
  .trash-mobile-info-item {
    display: inline-flex;
    flex-wrap: wrap;
    align-items: baseline;
    align-content: flex-start;
    gap: 0.12rem 0.35rem;
    min-width: 0;
  }

  :deep(.review-mobile-info-label),
  .trash-mobile-info-label {
    display: inline;
    flex: 0 0 auto;
    white-space: nowrap;
  }

  :deep(.review-mobile-info-value),
  .trash-mobile-info-value {
    display: inline;
    flex: 1 1 auto;
    min-width: 0;
    margin-top: 0;
    word-break: normal;
    overflow-wrap: break-word;
  }

  :deep(.review-card-action-note) {
    width: fit-content;
    max-width: 100%;
  }

  .trash-mobile-card {
    gap: 0.55rem;
    padding: 0.9rem;
  }

  .trash-mobile-info-grid {
    gap: 0.4rem 0.85rem;
  }

  .trash-mobile-dependencies {
    align-items: flex-start;
  }

  :deep(.trash-mobile-dependencies .trash-dependency-chip) {
    width: fit-content;
    max-width: 100%;
    white-space: normal;
    word-break: normal;
    overflow-wrap: break-word;
  }
}

@container admin-insights (max-width: 40rem) {
  .admin-insights-card .chart-summary-control-row {
    display: grid;
    grid-template-areas:
      'controls'
      'summary'
      'timezone';
    grid-template-columns: minmax(0, 1fr);
    gap: 0.45rem;
  }

  .admin-insights-card .chart-control-stack {
    display: contents;
  }

  .admin-insights-card .chart-summary-group {
    display: grid;
    grid-area: summary;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0.3rem;
    width: 100%;
  }

  .admin-insights-card .chart-summary-item {
    box-sizing: border-box;
    min-width: 0;
    width: 100%;
    padding: 0.35rem 0.2rem;
  }

  .admin-insights-card .chart-summary-item > span,
  .admin-insights-card .chart-summary-item > strong {
    max-width: 100%;
    text-align: center;
    white-space: normal;
  }

  .admin-insights-card .chart-summary-item > span {
    word-break: keep-all;
  }

  .admin-insights-card .chart-summary-item > strong {
    overflow-wrap: anywhere;
  }

  .admin-insights-card .chart-control-stack .user-insights__range {
    display: inline-flex;
    grid-area: controls;
    width: max-content;
    max-width: 100%;
    margin-inline-start: auto;
    flex-wrap: nowrap;
    justify-self: end;
  }

  .admin-insights-card .chart-control-stack .user-insights__range button {
    box-sizing: border-box;
    flex: 0 0 auto;
    min-width: 0;
    width: auto;
    white-space: nowrap;
  }

  .admin-insights-card .chart-timezone-label {
    grid-area: timezone;
    justify-self: end;
  }
}

@media (max-width: 640px) {
  .archive-requester-stats__identity {
    align-items: flex-start;
    flex-direction: column;
  }

  .archive-requester-stats__identity > strong {
    margin-left: 0;
  }

  .user-submission-record__meta {
    grid-template-columns: 1fr;
  }

  .user-submission-record__comment {
    flex-direction: column;
  }

  .user-insights__heading,
  .user-submission-summary__identity,
  .user-submission-summary__exp {
    align-items: flex-start;
    flex-direction: column;
  }

  .user-insights__actions {
    width: 100%;
    align-items: center;
    justify-content: flex-end;
  }

  .user-insights__switch {
    width: fit-content;
    max-width: 100%;
    margin-inline-start: 0;
    justify-content: flex-end;
  }

  .user-insights__switch button {
    flex: 0 1 auto;
    white-space: nowrap;
  }

  .user-insights__toggle {
    margin-inline-start: 0;
  }

  .user-login-column-chart {
    --temporal-edge-padding: clamp(1.5rem, calc(1.75rem * var(--app-font-scale)), 2.5rem);
    grid-template-columns: 1.6rem minmax(0, 1fr);
    height: 13rem;
    gap: 0.3rem;
  }

  .user-login-column-chart__grid,
  .user-login-column-chart__bars {
    inset-block-end: 3rem;
  }

  .user-login-column-chart__x-axis {
    height: 3rem;
  }

  .admin-mobile-list--users .user-card-title-group {
    display: grid;
    grid-template-areas:
      'level name'
      'role role';
    grid-template-columns: auto minmax(0, 1fr);
    align-items: center;
    gap: 0.35rem 0.45rem;
  }

  .admin-mobile-list--users .mobile-user-level-tag {
    grid-area: level;
  }

  .admin-mobile-list--users .user-card-title-group .admin-tablet-card-title {
    grid-area: name;
    width: 100%;
    min-width: 0;
    overflow-wrap: anywhere;
  }

  .admin-mobile-list--users .user-role-tag-group {
    grid-area: role;
  }

  .user-level-chart__row {
    grid-template-columns: auto minmax(0, 1fr) auto;
    gap: 0.35rem 0.45rem;
  }

  .user-level-chart__track {
    grid-column: 1 / 3;
  }

  .user-level-chart__row > span:last-child {
    grid-column: 3;
  }

  .user-submission-status-cards,
  .user-submission-distribution__legend {
    grid-template-columns: 1fr;
  }

  .user-submission-status-card {
    grid-template-columns: auto minmax(0, 1fr) auto;
  }

  .user-submission-status-card strong {
    grid-column: auto;
  }

  .contributor-level-insights__heading {
    align-items: flex-start;
    flex-wrap: wrap;
  }

  .contributor-level-insights__heading p {
    display: none;
  }

  .contributor-level-insights__actions {
    flex: 1 1 auto;
    flex-wrap: wrap;
  }

  .contributor-level-stat {
    max-width: 100%;
    min-width: 8.5rem;
    min-height: 2.75rem;
    padding: 0.35rem 0.5rem;
  }

  .contributor-level-settings-row {
    grid-template-columns: auto minmax(0, 1fr);
    align-items: center;
  }

  .contributor-level-settings-field {
    grid-column: 1 / -1;
  }

  .contributor-level-settings-max {
    grid-column: 1 / -1;
  }

  .contributor-level-settings-footer-spacer {
    display: none;
  }

  .contributor-level-settings-footer :deep(.p-button) {
    flex: 1 1 100%;
  }
}

@media (max-width: 640px) {
  .admin-insights-card .user-insights__switch.user-insights__switch--two,
  .admin-insights-card .user-insights__switch.user-insights__switch--three {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    width: 100%;
    max-width: 100%;
  }

  .admin-insights-card .user-insights__switch > .user-insights__switch-option {
    display: block;
    flex: none;
    box-sizing: border-box;
    width: 100%;
    min-width: 0;
    max-width: none;
    white-space: normal;
  }

  .admin-insights-card .user-insights__switch--three > .user-insights__switch-option--wide {
    grid-column: 1 / -1;
    justify-self: stretch;
    width: 100%;
    min-width: 0;
  }
}

@media (min-width: 641px) and (max-width: 899px) {
  .user-insights__heading {
    align-items: flex-start;
    flex-wrap: wrap;
  }

  .user-submission-status-cards {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .contributor-level-insights__heading {
    align-items: flex-start;
  }

  .contributor-level-insights__actions {
    flex-wrap: wrap;
  }
}

@media (min-width: 641px) and (max-width: 871px) {
  .user-insights__actions {
    flex: 0 1 auto;
    max-width: 100%;
    min-width: 0;
    margin-inline-start: auto;
    justify-content: flex-end;
  }

  .user-insights__switch {
    max-width: 100%;
    justify-content: flex-end;
  }

  .user-insights__toggle {
    margin-inline-start: 0;
  }
}

@media (min-width: 641px) and (max-width: 1399px) {
  :deep(.admin-desktop-data-table.course-management-table),
  :deep(.admin-desktop-data-table.user-management-table),
  :deep(.admin-desktop-data-table.notification-management-table) {
    display: none;
  }

  .admin-mobile-list--courses,
  .admin-mobile-list--users,
  .admin-mobile-list--notifications {
    display: flex;
    flex-direction: column;
    gap: 0.8rem;
    width: 100%;
    min-width: 0;
  }

  .admin-mobile-list--courses .admin-tablet-card,
  .admin-mobile-list--users .admin-tablet-card,
  .admin-mobile-list--notifications .admin-tablet-card {
    display: flex;
    flex-direction: column;
    gap: 0.65rem;
    width: 100%;
    max-width: 100%;
    min-width: 0;
    box-sizing: border-box;
    padding: 0.95rem;
    border: 1px solid color-mix(in srgb, var(--primary-color) 38%, var(--border-color));
    border-radius: 8px;
    background: color-mix(in srgb, var(--bg-secondary) 86%, transparent);
  }

  .admin-tablet-card-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 0.75rem;
    width: 100%;
    min-width: 0;
  }

  .admin-tablet-title-group {
    display: flex;
    flex: 1 1 auto;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.4rem 0.5rem;
    min-width: 0;
  }

  .admin-tablet-card-title {
    flex: 0 1 auto;
    width: auto;
    max-width: 100%;
    min-width: 0;
    word-break: normal;
    overflow-wrap: break-word;
  }

  .admin-tablet-tag-group,
  .admin-tablet-status-group {
    display: flex;
    flex: 0 0 auto;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.35rem;
  }

  .admin-tablet-status-group {
    justify-content: flex-end;
    max-width: 46%;
  }

  .admin-tablet-tag-group :deep(.p-tag),
  .admin-tablet-status-group :deep(.p-tag),
  .admin-mobile-list--users .user-online-badge {
    flex-shrink: 0;
    white-space: nowrap;
  }

  .admin-tablet-metadata {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0.4rem 0.85rem;
    width: 100%;
    min-width: 0;
  }

  .admin-tablet-metadata-item {
    display: inline-flex;
    flex-wrap: wrap;
    align-items: baseline;
    align-content: flex-start;
    gap: 0.12rem 0.35rem;
    min-width: 0;
  }

  .admin-tablet-metadata-label {
    flex: 0 0 auto;
    color: var(--text-secondary);
    font-weight: 650;
    white-space: nowrap;
  }

  .admin-tablet-metadata-value {
    flex: 1 1 auto;
    min-width: 0;
    color: var(--text-primary);
    word-break: normal;
    overflow-wrap: break-word;
  }

  .admin-tablet-metadata .admin-card-email {
    display: inline;
    width: auto;
    margin-top: 0;
    overflow-wrap: anywhere;
  }

  .course-card-order-item {
    align-items: center;
  }

  .course-card-order-actions {
    display: inline-flex;
    flex: 0 0 auto;
    align-items: center;
    gap: 0.25rem;
  }

  .course-card-order-actions :deep(.p-button) {
    width: 2rem;
    min-width: 2rem;
    height: 2rem;
    min-height: 2rem;
    padding-inline: 0;
    justify-content: center;
  }

  .admin-mobile-paginator {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 0.2rem;
    max-width: 100%;
    padding: 0.55rem 0.25rem;
    overflow: hidden;
  }

  .admin-tablet-actions,
  .admin-mobile-list--users .admin-tablet-actions,
  .admin-mobile-list--courses .admin-tablet-actions,
  .admin-mobile-list--notifications .admin-tablet-actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: flex-end;
    gap: 0.5rem;
    width: 100%;
    min-width: 0;
    overflow-x: visible;
  }

  .admin-tablet-actions :deep(.p-button),
  .admin-mobile-list--users .admin-tablet-actions :deep(.p-button),
  .admin-mobile-list--courses .admin-tablet-actions :deep(.p-button),
  .admin-mobile-list--notifications .admin-tablet-actions :deep(.p-button) {
    flex: 0 0 auto;
    width: auto;
    min-width: 5.25rem;
    white-space: nowrap;
  }

  :global(.dark) .admin-mobile-list--courses .admin-tablet-card,
  :global(.dark) .admin-mobile-list--users .admin-tablet-card,
  :global(.dark) .admin-mobile-list--notifications .admin-tablet-card {
    border-color: color-mix(in srgb, var(--primary-color) 42%, var(--border-color));
    background: color-mix(in srgb, var(--bg-secondary) 84%, #000 16%);
  }
}

@media (min-width: 900px) and (max-width: 1399px) {
  .admin-tablet-metadata {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .admin-tablet-metadata-item--wide {
    grid-column: span 2;
  }
}

@media (max-width: 640px) {
  .admin-tablet-card-header {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-start;
    justify-content: space-between;
    gap: 0.55rem;
    min-width: 0;
  }

  .admin-tablet-title-group {
    display: flex;
    flex: 1 1 auto;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.35rem;
    min-width: 0;
  }

  .admin-tablet-status-group,
  .admin-tablet-tag-group {
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem;
  }

  .admin-tablet-metadata {
    display: grid;
    grid-template-columns: 1fr;
    gap: 0.4rem;
    min-width: 0;
  }

  .admin-tablet-metadata-item {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 0.35rem;
    min-width: 0;
  }

  .admin-tablet-metadata-value {
    min-width: 0;
    overflow-wrap: anywhere;
  }
}

.admin-mobile-list--categories .category-card-main--mobile,
.category-card-top-tags--mobile {
  display: none;
}

@media (max-width: 1399px) {
  :deep(.admin-desktop-data-table.course-management-table),
  :deep(.admin-desktop-data-table.category-management-table) {
    display: none;
  }

  .admin-mobile-list--courses,
  .admin-mobile-list--categories {
    display: flex;
    flex-direction: column;
    gap: 0.8rem;
    width: 100%;
    min-width: 0;
  }

  .admin-mobile-list--courses .admin-course-card,
  .admin-mobile-list--categories .category-responsive-card {
    width: 100%;
    max-width: 100%;
    min-width: 0;
    box-sizing: border-box;
    padding: 0.85rem 0.9rem;
    border: 1px solid color-mix(in srgb, var(--primary-color) 38%, var(--border-color));
    border-radius: 8px;
    background: color-mix(in srgb, var(--bg-secondary) 86%, transparent);
  }

  .admin-mobile-list--categories .category-card-topline,
  .admin-mobile-list--courses .admin-tablet-metadata {
    width: 6.75rem;
    min-width: 6.75rem;
  }

  .admin-mobile-list--categories .category-card-topline,
  .admin-mobile-list--courses .course-card-order-item {
    flex-wrap: nowrap;
    gap: 0.35rem;
  }

  .admin-mobile-list--categories .category-card-order,
  .admin-mobile-list--categories .category-card-key-label {
    font-weight: 700;
  }

  .admin-mobile-list--categories .category-card-key-value {
    font-weight: 400;
  }

  .admin-mobile-list--courses .course-card-order-item .admin-tablet-metadata-label {
    display: none;
  }

  .admin-mobile-list--categories .category-card-title-group {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.35rem 0.5rem;
    min-width: 0;
  }

  .admin-mobile-list--categories .category-card-title-group :deep(.p-tag),
  .admin-mobile-list--categories .category-card-meta :deep(.p-tag),
  .admin-mobile-list--courses .admin-tablet-tag-group :deep(.p-tag) {
    flex-shrink: 0;
    white-space: nowrap;
  }

  .admin-mobile-list--categories .category-card-main {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.4rem 0.75rem;
    min-width: 0;
  }

  .admin-mobile-list--categories .category-card-key {
    display: inline-flex;
    flex: 0 1 auto;
    flex-direction: row;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 0.1rem 0.35rem;
    max-width: 100%;
    padding: 0.28rem 0.5rem;
    border: 1px solid var(--border-color);
    border-radius: 0.55rem;
    background: color-mix(in srgb, var(--panel-bg) 88%, var(--primary-color) 12%);
  }

  :global(.dark) .admin-mobile-list--courses .admin-course-card,
  :global(.dark) .admin-mobile-list--categories .category-responsive-card {
    border-color: color-mix(in srgb, var(--primary-color) 42%, var(--border-color));
    background: color-mix(in srgb, var(--bg-secondary) 84%, #000 16%);
  }
}

@media (max-width: 767px) {
  .admin-mobile-list--categories .category-responsive-card {
    display: flex;
    flex-direction: column;
    gap: 0.7rem;
    padding: 1rem;
  }

  .admin-mobile-list--categories .category-card-main--tablet,
  .admin-mobile-list--categories .category-card-meta--tablet {
    display: none;
  }

  .admin-mobile-list--categories .category-card-main--mobile {
    display: flex;
  }

  .admin-mobile-list--categories .category-card-topline {
    display: flex;
    align-items: center;
    gap: 0.45rem;
    width: 100%;
    min-width: 0;
  }

  .admin-mobile-list--categories .category-card-top-tags--mobile {
    display: flex;
    flex: 1 1 auto;
    flex-wrap: wrap;
    align-items: center;
    justify-content: flex-end;
    gap: 0.35rem;
    min-width: 0;
  }

  .admin-mobile-list--categories .category-card-main--mobile {
    align-items: flex-start;
    justify-content: space-between;
    flex-wrap: nowrap;
    gap: 0.75rem;
    width: 100%;
  }

  .admin-mobile-list--categories .category-card-key {
    display: inline-flex;
    flex: 0 1 auto;
    flex-direction: row;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 0.1rem;
    max-width: 48%;
    padding: 0.32rem 0.5rem;
    border: 1px solid var(--border-color);
    border-radius: 0.55rem;
    background: color-mix(in srgb, var(--panel-bg) 88%, var(--primary-color) 12%);
  }

  .admin-mobile-list--categories .category-card-actions {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0.5rem;
    width: 100%;
  }

  .admin-mobile-list--categories .category-card-actions :deep(.p-button) {
    width: 100%;
    min-width: 0;
    min-height: 2.75rem;
    justify-content: center;
  }

  .admin-mobile-list--categories .category-card-actions :deep(.p-button-label) {
    display: inline-flex;
  }

  .admin-mobile-list--categories .category-card-actions :deep(.pi) {
    margin-inline-end: 0.3rem;
  }

  .admin-mobile-list--courses .admin-course-card {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    align-items: center;
    gap: 0.7rem;
    padding: 1rem;
  }

  .admin-mobile-list--courses .admin-tablet-card-header,
  .admin-mobile-list--courses .admin-tablet-title-group {
    display: contents;
  }

  .admin-mobile-list--courses .admin-tablet-metadata {
    display: block;
    grid-column: 1;
    grid-row: 1;
    width: auto;
    min-width: 0;
  }

  .admin-mobile-list--courses .course-card-order-item {
    display: flex;
    flex-wrap: nowrap;
    align-items: center;
    justify-content: flex-start;
    gap: 0.35rem;
    width: auto;
  }

  .admin-mobile-list--courses .course-card-order-item .admin-tablet-metadata-label {
    display: none;
  }

  .admin-mobile-list--courses .admin-tablet-tag-group {
    display: flex;
    grid-column: 2;
    grid-row: 1;
    justify-self: end;
    min-width: 0;
  }

  .admin-mobile-list--courses .admin-tablet-card-title {
    grid-column: 1 / -1;
    grid-row: 2;
    width: 100%;
  }

  .admin-mobile-list--courses .admin-tablet-actions {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    grid-column: 1 / -1;
    grid-row: 3;
    gap: 0.5rem;
    width: 100%;
  }

  .admin-mobile-list--courses .admin-tablet-actions :deep(.p-button) {
    width: 100%;
    min-width: 0;
    min-height: 2.75rem;
    justify-content: center;
  }

  .admin-mobile-list--courses .admin-tablet-actions :deep(.p-button-label) {
    display: inline-flex;
  }

  .admin-mobile-list--courses .admin-tablet-actions :deep(.pi) {
    margin-inline-end: 0.3rem;
  }
}

@media (min-width: 768px) and (max-width: 1399px) {
  .admin-mobile-list--categories .category-responsive-card {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr) auto auto;
    align-items: center;
    gap: 0.65rem 0.8rem;
  }

  .admin-mobile-list--categories .category-card-main--mobile,
  .admin-mobile-list--categories .category-card-top-tags--mobile {
    display: none;
  }

  .admin-mobile-list--categories .category-card-meta--tablet {
    display: flex;
  }

  .admin-mobile-list--categories .category-card-topline {
    grid-column: 1;
    align-self: center;
    min-width: 6.75rem;
    width: auto;
  }

  .admin-mobile-list--categories .category-card-main--tablet {
    display: grid;
    grid-column: 2;
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas:
      'title'
      'key';
    align-items: center;
    gap: 0.4rem;
    width: 100%;
    min-width: 0;
  }

  .admin-mobile-list--categories .category-card-main--tablet .category-card-title-group {
    grid-area: title;
  }

  .admin-mobile-list--categories .category-card-main--tablet .category-card-key {
    grid-area: key;
    justify-self: start;
    white-space: nowrap;
  }

  .admin-mobile-list--categories .category-card-meta--tablet {
    grid-column: 3;
    align-self: center;
    justify-self: end;
    width: auto;
  }

  .admin-mobile-list--categories .category-card-key {
    flex-direction: row;
    flex-wrap: wrap;
    align-items: baseline;
    max-width: 100%;
    padding: 0.28rem 0.5rem;
  }

  .admin-mobile-list--categories .category-card-actions {
    display: flex;
    grid-column: 4;
    flex-wrap: wrap;
    justify-content: flex-end;
    gap: 0.4rem;
    width: auto;
  }

  .admin-mobile-list--categories .category-card-actions :deep(.p-button) {
    flex: 0 0 auto;
    width: auto;
    min-width: 5rem;
    min-height: 2.45rem;
    white-space: nowrap;
  }

  .admin-mobile-list--courses .admin-course-card {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr) auto;
    align-items: center;
    gap: 0.65rem 0.8rem;
  }

  .admin-mobile-list--courses .admin-tablet-metadata {
    display: block;
    grid-column: 1;
    grid-row: 1;
    width: 6.75rem;
  }

  .admin-mobile-list--courses .admin-tablet-card-header {
    grid-column: 2;
    grid-row: 1;
    width: auto;
  }

  .admin-mobile-list--courses .admin-tablet-actions {
    display: flex;
    grid-column: 3;
    grid-row: 1;
    flex-wrap: wrap;
    justify-content: flex-end;
    gap: 0.4rem;
    width: auto;
  }

  .admin-mobile-list--courses .admin-tablet-actions :deep(.p-button) {
    flex: 0 0 auto;
    width: auto;
    min-width: 5rem;
    min-height: 2.45rem;
    white-space: nowrap;
  }
}

@media (min-width: 1024px) and (max-width: 1399px) {
  .admin-mobile-list--categories .category-card-main--tablet {
    grid-template-columns: minmax(0, 1fr) 12rem;
    grid-template-areas: 'title key';
    column-gap: 0.75rem;
  }
}

@media (min-width: 1400px) {
  :deep(.admin-desktop-data-table.course-management-table),
  :deep(.admin-desktop-data-table.category-management-table) {
    display: block;
  }

  .admin-mobile-list--courses,
  .admin-mobile-list--categories {
    display: none;
  }
}

@media (max-width: 1399px) {
  .admin-mobile-list--categories .category-card-actions :deep(.p-button),
  .admin-mobile-list--courses .course-card-actions :deep(.p-button),
  .admin-mobile-list--notifications .announcement-mobile-actions :deep(.p-button),
  .admin-mobile-list--users .user-management-card-actions :deep(.p-button),
  .review-center :deep(.review-card-actions .p-button),
  .trash-center .trash-mobile-card-actions :deep(.p-button) {
    min-height: calc(2rem * var(--app-font-scale));
    padding-block: var(--p-button-sm-padding-y, 0.375rem);
    line-height: 1.25;
    align-items: center;
  }
}
</style>
