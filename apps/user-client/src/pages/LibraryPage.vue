<script setup lang="ts">
import { computed, ref, watchEffect } from 'vue'
import { useRouter } from 'vue-router'
import { useInfiniteQuery } from '@tanstack/vue-query'
import type { QTableColumn } from 'quasar'
import { useQuasar } from 'quasar'
import { api } from '@/api/client'
import { articleStatusColor, articleStatusLabel } from '@/api/articleStatus'
import type { LibraryItem, LibraryItemType } from '@/api/types'
import { queryClient } from '@/boot/query'
import { platform } from '@/platform'
import PageHeader from '@/components/composite/PageHeader.vue'
import AsyncStatePanel from '@/components/composite/AsyncStatePanel.vue'
import ResponsiveTable from '@/components/composite/ResponsiveTable.vue'
import FilePreviewDialog from '@/components/business/FilePreviewDialog.vue'
import AppButton from '@/components/base/AppButton.vue'

const router = useRouter()
const $q = useQuasar()
const type = ref<LibraryItemType | 'all'>('all')
const projectId = ref<string | 'all' | 'unclassified'>('all')
const search = ref('')
const fileFormat = ref('all')
const clearFilters = () => {
  fileFormat.value = 'all'
  projectId.value = 'all'
  type.value = 'all'
  search.value = ''
}
const previewItem = ref<LibraryItem | null>(null)
const previewOpen = ref(false)
const previewLoading = ref(false)
const reparsingId = ref('')
const uploading = ref(false)

const projectsQuery = useInfiniteQuery({
  queryKey: ['projects'],
  queryFn: ({ pageParam }) => api.listProjectsPage(pageParam),
  initialPageParam: undefined as string | undefined,
  getNextPageParam: (lastPage) => lastPage.nextCursor,
})
const libraryQuery = useInfiniteQuery({
  queryKey: computed(() => ['library', type.value, projectId.value, search.value]),
  queryFn: ({ pageParam }) =>
    api.listLibraryItemsPage(
      { type: type.value, projectId: projectId.value, search: search.value },
      pageParam,
    ),
  initialPageParam: undefined as string | undefined,
  getNextPageParam: (lastPage) => lastPage.nextCursor,
  refetchInterval: (query) =>
    query.state.data?.pages.some((page) => page.items.some((item) => item.status === 'reading'))
      ? 3000
      : false,
})
const projects = computed(() => [
  ...new Map(
    (projectsQuery.data.value?.pages.flatMap((page) => page.items) ?? []).map((project) => [
      project.id,
      project,
    ]),
  ).values(),
])
const rows = computed(() => [
  ...new Map(
    (libraryQuery.data.value?.pages.flatMap((page) => page.items) ?? []).map((item) => [
      item.id,
      item,
    ]),
  ).values(),
])
const projectName = (id: string | null) =>
  projects.value.find((item) => item.id === id)?.name ?? '未分类'
const selectedProjectName = computed(() =>
  projectId.value === 'all' ? '全部项目' : projectName(projectId.value),
)
const projectCards = computed(() => [
  { id: 'all', name: '全部项目' },
  { id: 'unclassified', name: '未分类' },
  ...projects.value,
])
const formatLabel = (item: LibraryItem) => {
  if (item.type === 'article') return '公众号文章'
  const extension = item.fileType ?? ''
  const labels: Record<string, string> = {
    PDF: 'PDF',
    PPT: 'PPT',
    PPTX: 'PPT',
    DOC: 'Word',
    DOCX: 'Word',
    XLS: 'Excel',
    XLSX: 'Excel',
    TXT: '文本',
    MD: 'Markdown',
    CSV: 'CSV',
    HTML: 'HTML',
    PNG: '图片',
    JPG: '图片',
    JPEG: '图片',
    MP3: '音频',
    M4A: '音频',
    MP4: '视频',
  }
  return labels[extension] ?? '文件'
}
const visibleRows = computed(() =>
  rows.value.filter((item) => fileFormat.value === 'all' || formatLabel(item) === fileFormat.value),
)
watchEffect(() => {
  if (
    fileFormat.value !== 'all' &&
    libraryQuery.hasNextPage.value &&
    !libraryQuery.isFetching.value &&
    !libraryQuery.isError.value
  ) {
    void libraryQuery.fetchNextPage()
  }
})
const formatOptions = [
  'all',
  '公众号文章',
  'PDF',
  'PPT',
  'Word',
  'Excel',
  '文本',
  'Markdown',
  'CSV',
  'HTML',
  '图片',
  '音频',
  '视频',
  '文件',
].map((value) => ({ value, label: value === 'all' ? '全部类型' : value }))

const columns: QTableColumn<LibraryItem>[] = [
  { name: 'title', label: '名称', field: 'title', align: 'left', style: 'width: 28%' },
  {
    name: 'type',
    label: '类型',
    field: (row) => (row.type === 'article' ? '文章' : (row.fileType ?? '资料')),
    align: 'left',
    style: 'width: 12%',
  },
  {
    name: 'sourceTask',
    label: '来源会话',
    field: (row) => row.sourceTaskTitle ?? '无',
    align: 'left',
    style: 'width: 17%',
  },
  { name: 'status', label: '状态', field: 'status', align: 'left', style: 'width: 14%' },
  { name: 'updatedAt', label: '更新时间', field: 'updatedAt', align: 'left', style: 'width: 17%' },
  { name: 'actions', label: '操作', field: 'id', align: 'right', style: 'width: 12%' },
]

const statusText = (status: LibraryItem['status']) =>
  status === 'reading'
    ? '读取中'
    : status === 'ready'
      ? '已读取'
      : status === 'failed'
        ? '读取失败'
        : articleStatusLabel(status)

const statusColor = (status: LibraryItem['status']) =>
  status === 'failed'
    ? 'negative'
    : status === 'reading'
      ? 'warning'
      : status === 'ready'
        ? 'positive'
        : articleStatusColor(status)

const open = async (item: LibraryItem) => {
  if (item.type === 'article') void router.push(`/articles/${item.sourceId}/edit`)
  else {
    previewItem.value = item
    previewOpen.value = true
    previewLoading.value = true
    try {
      previewItem.value = await api.getLibraryItem(item.id)
    } catch (error) {
      $q.notify({
        type: 'negative',
        message: error instanceof Error ? error.message : '资料详情加载失败。',
      })
    } finally {
      previewLoading.value = false
    }
  }
}

const rename = (item: LibraryItem) => {
  $q.dialog({
    title: '重命名',
    prompt: { model: item.title, type: 'text' },
    cancel: true,
    persistent: true,
  }).onOk(async (value: string) => {
    if (!value.trim()) return
    await api.updateLibraryItemTitle(item.id, value)
    await libraryQuery.refetch()
  })
}

const remove = (item: LibraryItem) => {
  $q.dialog({
    title: '删除内容',
    message:
      item.type === 'reference'
        ? '删除资料后，曾参考它的文章仍可查看，但后续 AI 不再引用该资料。'
        : '删除文章不会删除原任务对话。确定继续吗？',
    cancel: true,
    persistent: true,
  }).onOk(async () => {
    await api.deleteLibraryItem(item.id)
    await queryClient.invalidateQueries({ queryKey: ['library'] })
  })
}

const reparse = async (item: LibraryItem) => {
  if (item.type !== 'reference') return
  reparsingId.value = item.id
  try {
    await api.reparseDocument(item.sourceId)
    await libraryQuery.refetch()
    if (previewItem.value?.id === item.id) previewItem.value = await api.getLibraryItem(item.id)
    $q.notify({ type: 'positive', message: '资料已重新解析，可以用于后续创作。' })
  } catch (error) {
    $q.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '资料重新解析失败。',
    })
  } finally {
    reparsingId.value = ''
  }
}

const uploadReferences = async () => {
  const files = await platform.pickFiles(
    '.pdf,.docx,.pptx,.xlsx,.csv,.txt,.md,.html,.png,.jpg,.jpeg,.mp3,.m4a,.mp4',
  )
  if (!files.length) return
  uploading.value = true
  let completed = 0
  try {
    for (const file of files.slice(0, 20)) {
      try {
        await api.uploadFile(file, {
          projectId:
            projectId.value !== 'all' && projectId.value !== 'unclassified'
              ? projectId.value
              : null,
          saveToLibrary: true,
        })
        completed += 1
        await queryClient.invalidateQueries({ queryKey: ['library'] })
      } catch (error) {
        $q.notify({
          type: 'negative',
          message: `${file.name}：${error instanceof Error ? error.message : '上传失败。'}`,
        })
      }
    }
    if (completed)
      $q.notify({
        type: 'positive',
        message: `${completed} 个资料已上传，安全扫描与解析在后台继续。`,
      })
  } finally {
    uploading.value = false
  }
}
</script>

<template>
  <q-page class="app-page library-page">
    <PageHeader title="文章库">
      <template #actions
        ><AppButton
          variant="outline"
          icon="upload_file"
          label="上传资料"
          :loading="uploading"
          @click="uploadReferences" /><q-btn
          color="primary"
          unelevated
          no-caps
          icon="add"
          label="新建创作"
          to="/create"
      /></template>
    </PageHeader>

    <section class="library-projects" aria-label="项目筛选">
      <button
        v-for="project in projectCards"
        :key="project.id"
        type="button"
        :class="{ 'is-active': projectId === project.id }"
        :aria-pressed="projectId === project.id"
        :title="project.name"
        @click="projectId = project.id"
      >
        <q-icon name="folder_open" />
        <span
          ><strong>{{ project.name }}</strong
          ><small>查看项目中的资料与文章</small></span
        >
      </button>
      <AppButton
        v-if="projectsQuery.hasNextPage.value"
        variant="ghost"
        label="更多项目"
        @click="projectsQuery.fetchNextPage()"
      />
    </section>

    <section class="library-toolbar surface-card">
      <div class="library-toolbar__filters">
        <div class="library-breadcrumb">
          文章库 / <strong>{{ selectedProjectName }}</strong>
        </div>
        <q-input
          v-model="search"
          outlined
          dense
          clearable
          debounce="250"
          placeholder="搜索当前项目中的文件"
          aria-label="搜索文章库"
          ><template #prepend><q-icon name="search" /></template
        ></q-input>
        <q-select
          v-model="fileFormat"
          outlined
          dense
          emit-value
          map-options
          aria-label="文件类型"
          :options="formatOptions"
        />
      </div>
      <q-tabs
        v-model="type"
        dense
        active-color="primary"
        indicator-color="primary"
        align="left"
        class="library-toolbar__tabs"
      >
        <q-tab name="all" :label="`全部内容 ${rows.length}`" /><q-tab
          name="article"
          label="文章"
        /><q-tab name="reference" label="参考资料" />
      </q-tabs>
    </section>

    <section class="library-table surface-card">
      <AsyncStatePanel
        :loading="libraryQuery.isPending.value"
        :error="libraryQuery.error.value instanceof Error ? libraryQuery.error.value.message : null"
        :empty="!visibleRows.length"
        empty-title="没有找到内容"
        empty-description="调整筛选条件，或从 AI 创作页开始新的文章。"
        @retry="libraryQuery.refetch()"
      >
        <template #empty-action>
          <AppButton
            v-if="projectId !== 'all' || type !== 'all' || search || fileFormat !== 'all'"
            variant="outline"
            label="查看全部内容"
            @click="clearFilters"
          />
        </template>
        <ResponsiveTable :rows="visibleRows" :columns="columns">
          <template #row="{ row, props }">
            <q-tr :props="props">
              <q-td key="title" :props="props"
                ><button class="library-title" @click="open(row)">
                  <q-icon
                    :name="
                      row.type === 'article'
                        ? 'article'
                        : row.fileType === 'PDF'
                          ? 'picture_as_pdf'
                          : 'description'
                    "
                    :color="
                      row.type === 'article'
                        ? 'primary'
                        : row.fileType === 'PDF'
                          ? 'negative'
                          : 'info'
                    "
                    size="24px"
                  /><span
                    ><strong>{{ row.title }}</strong
                    ><small>{{ row.summary }}</small></span
                  >
                </button></q-td
              >
              <q-td key="type" :props="props">{{ formatLabel(row) }}</q-td>
              <q-td key="sourceTask" :props="props">{{ row.sourceTaskTitle ?? '无' }}</q-td>
              <q-td key="status" :props="props"
                ><q-badge :color="statusColor(row.status)" outline>{{
                  statusText(row.status)
                }}</q-badge></q-td
              >
              <q-td key="updatedAt" :props="props">{{
                new Date(row.updatedAt).toLocaleString('zh-CN', {
                  month: '2-digit',
                  day: '2-digit',
                  hour: '2-digit',
                  minute: '2-digit',
                })
              }}</q-td>
              <q-td key="actions" :props="props" class="text-right"
                ><q-btn
                  v-if="row.type === 'reference' && row.status === 'failed'"
                  flat
                  dense
                  color="warning"
                  no-caps
                  label="重试解析"
                  :loading="reparsingId === row.id"
                  @click="reparse(row)"
                /><q-btn
                  flat
                  dense
                  color="primary"
                  no-caps
                  :label="row.type === 'article' ? '打开文章' : '查看文件'"
                  @click="open(row)"
                /><q-btn flat round dense icon="more_horiz" aria-label="更多操作"
                  ><q-menu
                    ><q-list
                      ><q-item clickable v-close-popup @click="rename(row)"
                        ><q-item-section>重命名</q-item-section></q-item
                      ><q-item
                        v-if="row.type === 'reference' && row.status === 'failed'"
                        clickable
                        v-close-popup
                        @click="reparse(row)"
                        ><q-item-section>重试解析</q-item-section></q-item
                      ><q-item clickable v-close-popup @click="remove(row)"
                        ><q-item-section class="text-negative">删除</q-item-section></q-item
                      ></q-list
                    ></q-menu
                  ></q-btn
                ></q-td
              >
            </q-tr>
          </template>
          <template #card="{ row }">
            <q-card flat class="library-card surface-card" role="listitem">
              <q-card-section
                ><q-icon
                  :name="row.type === 'article' ? 'article' : 'description'"
                  color="primary"
                  size="28px"
                />
                <div>
                  <h2>{{ row.title }}</h2>
                  <p>{{ row.summary }}</p>
                </div></q-card-section
              >
              <q-card-section class="library-card__meta"
                ><span>{{ formatLabel(row) }}</span
                ><span>来源会话：{{ row.sourceTaskTitle ?? '无' }}</span
                ><q-badge :color="statusColor(row.status)" outline>{{
                  statusText(row.status)
                }}</q-badge
                ><span>{{
                  new Date(row.updatedAt).toLocaleDateString('zh-CN')
                }}</span></q-card-section
              >
              <q-card-actions align="right"
                ><q-btn
                  v-if="row.type === 'reference' && row.status === 'failed'"
                  flat
                  no-caps
                  color="warning"
                  label="重试解析"
                  :loading="reparsingId === row.id"
                  @click="reparse(row)" /><q-btn
                  flat
                  no-caps
                  label="重命名"
                  @click="rename(row)" /><q-btn
                  color="primary"
                  flat
                  no-caps
                  :label="row.type === 'article' ? '打开文章' : '查看文件'"
                  @click="open(row)"
              /></q-card-actions>
            </q-card>
          </template>
        </ResponsiveTable>
      </AsyncStatePanel>
      <div v-if="libraryQuery.hasNextPage.value" class="library-load-more">
        <AppButton
          variant="outline"
          label="加载更多"
          :loading="libraryQuery.isFetchingNextPage.value"
          @click="libraryQuery.fetchNextPage()"
        />
      </div>
    </section>

    <FilePreviewDialog
      v-model="previewOpen"
      :item="previewItem"
      :loading="previewLoading"
      :reparsing="reparsingId === previewItem?.id"
      @retry="reparse"
    />
  </q-page>
</template>

<style scoped lang="scss">
.library-page {
  min-width: 0;
}
.library-projects {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 190px), 1fr));
  gap: 16px;
  min-width: 0;
  margin-bottom: 26px;
}
.library-projects button {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  gap: 14px;
  min-width: 0;
  padding: 18px 20px;
  color: var(--app-text-primary);
  text-align: left;
  background: var(--app-bg-surface);
  border: 1px solid var(--app-border-default);
  border-radius: 8px;
  cursor: pointer;
}
.library-projects button:hover,
.library-projects button.is-active {
  border-color: var(--app-action-primary);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--app-action-primary) 18%, transparent);
}
.library-projects button.is-active {
  background: color-mix(in srgb, var(--app-action-soft) 58%, var(--app-bg-surface));
}
.library-projects .q-icon {
  color: var(--app-action-primary);
  font-size: 34px;
}
.library-projects span {
  display: grid;
  min-width: 0;
}
.library-projects strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 16px;
}
.library-projects small {
  margin-top: 4px;
  color: var(--app-text-secondary);
  overflow-wrap: anywhere;
}

.library-toolbar {
  min-width: 0;
  margin-bottom: 0;
  padding: 16px 16px 0;
}
.library-toolbar__tabs {
  min-width: 0;
  margin-top: 14px;
  border-top: 1px solid var(--app-border-default);
}
.library-toolbar__filters {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) minmax(120px, 180px);
  gap: 12px;
  min-width: 0;
}
.library-breadcrumb {
  align-self: center;
  min-width: 0;
  color: var(--app-text-secondary);
  overflow-wrap: anywhere;
}
.library-table {
  min-width: 0;
  overflow: clip;
}
.library-load-more {
  display: flex;
  justify-content: center;
  padding: 14px;
  border-top: 1px solid var(--app-border-default);
}

.library-title {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  gap: 10px;
  width: 100%;
  min-width: 0;
  padding: 0;
  color: inherit;
  text-align: left;
  background: none;
  border: 0;
  cursor: pointer;
}
.library-title span {
  display: grid;
  min-width: 0;
}
.library-title strong {
  overflow-wrap: anywhere;
}
.library-title small {
  display: -webkit-box;
  margin-top: 3px;
  color: var(--app-text-secondary);
  overflow: hidden;
  overflow-wrap: anywhere;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.library-card {
  min-width: 0;
}
.library-card .q-card__section:first-child {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 12px;
  min-width: 0;
}
.library-card h2 {
  margin: 0;
  font-size: 17px;
  overflow-wrap: anywhere;
}
.library-card p {
  margin: 5px 0 0;
  color: var(--app-text-secondary);
  overflow-wrap: anywhere;
}
.library-card__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  color: var(--app-text-secondary);
  border-block: 1px solid var(--app-border-default);
}

@media (max-width: 599px) {
  .library-projects {
    grid-template-columns: 1fr;
    gap: 10px;
    margin-bottom: 16px;
  }
  .library-projects button {
    padding: 14px;
  }
  .library-toolbar {
    padding-inline: 10px;
  }
  .library-toolbar__filters {
    grid-template-columns: 1fr;
  }
  .library-toolbar__tabs :deep(.q-tab__label) {
    font-size: 12px;
  }
  .library-table {
    overflow: visible;
    background: transparent;
    border: 0;
    box-shadow: none;
  }
}

@media (min-width: 600px) and (max-width: 1023px) {
  .library-projects {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
