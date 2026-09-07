<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useInfiniteQuery } from '@tanstack/vue-query'
import { useQuasar } from 'quasar'
import { api } from '@/api/client'
import type { Project, Task } from '@/api/types'
import AppButton from '@/components/base/AppButton.vue'
import AppDialog from '@/components/base/AppDialog.vue'
import { queryClient } from '@/boot/query'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'

const auth = useAuthStore()
const ui = useUiStore()
const route = useRoute()
const router = useRouter()
const $q = useQuasar()

const projectsQuery = useInfiniteQuery({
  queryKey: ['projects'],
  queryFn: ({ pageParam }) => api.listProjectsPage(pageParam),
  initialPageParam: undefined as string | undefined,
  getNextPageParam: (lastPage) => lastPage.nextCursor,
})
const tasksQuery = useInfiniteQuery({
  queryKey: ['tasks'],
  queryFn: ({ pageParam }) => api.listTasksPage(undefined, pageParam),
  initialPageParam: undefined as string | undefined,
  getNextPageParam: (lastPage) => lastPage.nextCursor,
})
const projects = computed(() => [
  ...new Map(
    (projectsQuery.data.value?.pages.flatMap((page) => page.items) ?? []).map((project) => [
      project.id,
      project,
    ]),
  ).values(),
])
const tasks = computed(() => [
  ...new Map(
    (tasksQuery.data.value?.pages.flatMap((page) => page.items) ?? []).map((task) => [
      task.id,
      task,
    ]),
  ).values(),
])
const uncategorizedTasks = computed(() => tasks.value.filter((item) => !item.projectId))

const nav = [
  { to: '/skills', icon: 'grid_view', label: '技能库' },
  { to: '/articles', icon: 'article', label: '文章库' },
  { to: '/official-accounts', icon: 'settings', label: '公众号管理' },
]

const projectDialog = ref(false)
const projectSaving = ref(false)
const projectForm = reactive({ id: '', name: '', description: '', writingRequirements: '' })
const draggingTaskId = ref('')
const dragOverProjectId = ref<string | null | undefined>(undefined)

const openProject = (project?: Project) => {
  Object.assign(
    projectForm,
    project ?? { id: '', name: '', description: '', writingRequirements: '' },
  )
  projectDialog.value = true
}

const saveProject = async () => {
  if (!projectForm.name.trim()) return
  projectSaving.value = true
  try {
    if (projectForm.id)
      await api.updateProject(projectForm.id, {
        name: projectForm.name,
        description: projectForm.description,
        writingRequirements: projectForm.writingRequirements,
      })
    else await api.createProject(projectForm.name)
    await queryClient.invalidateQueries({ queryKey: ['projects'] })
    projectDialog.value = false
    $q.notify({ type: 'positive', message: projectForm.id ? '项目设置已保存。' : '项目已创建。' })
  } finally {
    projectSaving.value = false
  }
}

const removeProject = (project: Project) => {
  $q.dialog({
    title: '删除项目',
    message: `删除“${project.name}”后，其中任务、文章和资料将转为“未分类”，不会一并删除。`,
    cancel: true,
    persistent: true,
  }).onOk(async () => {
    try {
      await api.deleteProject(project.id)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['projects'] }),
        queryClient.invalidateQueries({ queryKey: ['tasks'] }),
        queryClient.invalidateQueries({ queryKey: ['library'] }),
      ])
      $q.notify({ type: 'positive', message: '项目已删除，相关内容已转入未分类。' })
    } catch (error) {
      $q.notify({
        type: 'negative',
        message: error instanceof Error ? error.message : '项目删除失败，请稍后重试。',
      })
    }
  })
}

const renameProject = (project: Project) => {
  $q.dialog({
    title: '重命名项目',
    prompt: {
      model: project.name,
      type: 'text',
      label: '项目名称',
      maxlength: 40,
      isValid: (value) => Boolean(String(value).trim()),
    },
    cancel: true,
    persistent: true,
  }).onOk(async (value: string) => {
    const name = value.trim()
    if (!name || name === project.name) return
    try {
      await api.updateProject(project.id, { name })
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['projects'] }),
        queryClient.invalidateQueries({ queryKey: ['tasks'] }),
      ])
      $q.notify({ type: 'positive', message: '项目已重命名。' })
    } catch (error) {
      $q.notify({
        type: 'negative',
        message: error instanceof Error ? error.message : '项目重命名失败，请稍后重试。',
      })
    }
  })
}

const renameTask = (task: Task) => {
  $q.dialog({
    title: '重命名创作',
    prompt: {
      model: task.title,
      type: 'text',
      label: '创作标题',
      maxlength: 80,
      isValid: (value) => Boolean(String(value).trim()),
    },
    cancel: true,
    persistent: true,
  }).onOk(async (value: string) => {
    const title = value.trim()
    if (!title || title === task.title) return
    try {
      await api.updateTask(task.id, { title })
      await queryClient.invalidateQueries({ queryKey: ['tasks'] })
      await queryClient.invalidateQueries({ queryKey: ['task', task.id] })
      $q.notify({ type: 'positive', message: '创作已重命名。' })
    } catch (error) {
      $q.notify({
        type: 'negative',
        message: error instanceof Error ? error.message : '创作重命名失败，请稍后重试。',
      })
    }
  })
}

const removeTask = (task: Task) => {
  $q.dialog({
    title: '删除创作',
    message: `确定删除“${task.title}”吗？删除后不会继续显示在左侧列表。`,
    cancel: true,
    persistent: true,
  }).onOk(async () => {
    try {
      await api.deleteTask(task.id)
      await queryClient.invalidateQueries({ queryKey: ['tasks'] })
      if (route.params.id === task.id) await router.replace('/create')
      $q.notify({ type: 'positive', message: '创作已删除。' })
    } catch (error) {
      $q.notify({
        type: 'negative',
        message: error instanceof Error ? error.message : '创作删除失败，请稍后重试。',
      })
    }
  })
}

const beginTaskDrag = (event: DragEvent, task: Task) => {
  draggingTaskId.value = task.id
  event.dataTransfer?.setData('text/plain', task.id)
  if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move'
}

const endTaskDrag = () => {
  draggingTaskId.value = ''
  dragOverProjectId.value = undefined
}

const allowProjectDrop = (event: DragEvent, projectId: string | null) => {
  if (!draggingTaskId.value) return
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
  dragOverProjectId.value = projectId
}

const moveDraggedTask = async (projectId: string | null) => {
  const taskId = draggingTaskId.value
  const task = tasks.value.find((item) => item.id === taskId)
  endTaskDrag()
  if (!task || task.projectId === projectId) return
  try {
    await api.updateTask(task.id, { projectId })
    await queryClient.invalidateQueries({ queryKey: ['tasks'] })
    await queryClient.invalidateQueries({ queryKey: ['task', task.id] })
    $q.notify({ type: 'positive', message: projectId ? '创作已移入项目。' : '创作已移入未分类。' })
  } catch (error) {
    $q.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '移动创作失败，请稍后重试。',
    })
  }
}

const logout = async () => {
  try {
    await auth.logout()
  } catch {
    $q.notify({ type: 'warning', message: '本机账号数据已清除，但服务端撤销状态尚未确认。' })
  } finally {
    queryClient.clear()
    await router.replace('/login')
  }
}

watch(
  () => route.fullPath,
  () => {
    if ($q.screen.lt.md) ui.drawerOpen = false
  },
)
</script>

<template>
  <q-layout view="hHh LpR fFf" class="main-layout">
    <q-header v-if="$q.screen.lt.md" class="main-layout__header">
      <q-toolbar>
        <q-btn flat round dense icon="menu" aria-label="打开导航" @click="ui.toggleDrawer" />
        <q-toolbar-title><q-icon name="auto_awesome" /> 公众号运营系统</q-toolbar-title>
        <q-btn flat round dense icon="add" aria-label="新建任务" to="/create" />
      </q-toolbar>
    </q-header>

    <q-drawer
      v-model="ui.drawerOpen"
      :width="272"
      :breakpoint="1024"
      show-if-above
      bordered
      class="main-layout__drawer"
    >
      <div class="drawer-shell">
        <AppButton
          class="drawer-shell__create"
          variant="outline"
          icon="add"
          label="新建创作"
          full-width
          @click="router.push('/create')"
        />
        <nav class="drawer-shell__nav" aria-label="主导航">
          <q-item
            v-for="item in nav"
            :key="item.to"
            clickable
            :to="item.to"
            :active="route.path === item.to"
            active-class="is-active"
          >
            <q-item-section avatar><q-icon :name="item.icon" /></q-item-section
            ><q-item-section>{{ item.label }}</q-item-section>
          </q-item>
        </nav>
        <q-separator />
        <section class="drawer-shell__projects">
          <header>
            <span>项目列表</span
            ><q-btn
              flat
              round
              dense
              icon="create_new_folder"
              aria-label="新建项目"
              @click="openProject()"
              ><q-tooltip>新建项目</q-tooltip></q-btn
            >
          </header>
          <div class="drawer-shell__project-scroll">
            <q-expansion-item
              v-for="project in projects"
              :key="project.id"
              dense
              dense-toggle
              hide-expand-icon
              icon="folder"
              :label="project.name"
              :aria-label="project.name"
              :default-opened="tasks.some((task) => task.projectId === project.id)"
              :class="{ 'is-drop-target': dragOverProjectId === project.id }"
              @dragover="allowProjectDrop($event, project.id)"
              @dragleave="dragOverProjectId = undefined"
              @drop.prevent="moveDraggedTask(project.id)"
            >
              <template #header>
                <q-item-section avatar><q-icon name="folder" /></q-item-section>
                <q-item-section
                  ><q-item-label lines="1"
                    ><span class="drawer-shell__project-name">{{ project.name }}</span
                    ><q-tooltip>{{ project.name }}</q-tooltip></q-item-label
                  ></q-item-section
                >
                <q-item-section side>
                  <q-btn
                    class="drawer-shell__project-action"
                    flat
                    round
                    dense
                    icon="more_horiz"
                    aria-label="项目操作"
                    @click.stop
                  >
                    <q-menu
                      ><q-list>
                        <q-item clickable v-close-popup @click="renameProject(project)"
                          ><q-item-section>重命名</q-item-section></q-item
                        >
                        <q-item clickable v-close-popup @click="removeProject(project)"
                          ><q-item-section class="text-negative">删除项目</q-item-section></q-item
                        >
                      </q-list></q-menu
                    >
                  </q-btn>
                </q-item-section>
              </template>
              <q-item
                v-for="task in tasks.filter((item) => item.projectId === project.id)"
                :key="task.id"
                clickable
                :to="`/tasks/${task.id}`"
                :active="route.params.id === task.id"
                active-class="is-active"
                class="task-item"
                draggable="true"
                :class="{ 'is-dragging': draggingTaskId === task.id }"
                @dragstart="beginTaskDrag($event, task)"
                @dragend="endTaskDrag"
              >
                <q-item-section
                  ><q-item-label lines="1">{{ task.title }}</q-item-label></q-item-section
                >
                <q-item-section side>
                  <q-btn
                    class="drawer-shell__task-action"
                    flat
                    round
                    dense
                    icon="more_horiz"
                    aria-label="创作操作"
                    @click.prevent.stop
                  >
                    <q-menu
                      ><q-list dense>
                        <q-item clickable v-close-popup @click="renameTask(task)"
                          ><q-item-section>重命名</q-item-section></q-item
                        >
                        <q-item clickable v-close-popup @click="removeTask(task)"
                          ><q-item-section class="text-negative">删除</q-item-section></q-item
                        >
                      </q-list></q-menu
                    >
                  </q-btn>
                </q-item-section>
              </q-item>
              <q-item v-if="!tasks.some((task) => task.projectId === project.id)" dense
                ><q-item-section class="text-muted">{{
                  tasksQuery.hasNextPage.value ? '更多任务尚未加载' : '暂无任务'
                }}</q-item-section></q-item
              >
            </q-expansion-item>
            <q-expansion-item
              v-if="uncategorizedTasks.length"
              dense
              dense-toggle
              default-opened
              aria-label="未分类"
              :class="{ 'is-drop-target': dragOverProjectId === null }"
              @dragover="allowProjectDrop($event, null)"
              @dragleave="dragOverProjectId = undefined"
              @drop.prevent="moveDraggedTask(null)"
            >
              <template #header>
                <q-item-section avatar><q-icon name="folder_open" /></q-item-section>
                <q-item-section
                  ><q-item-label lines="1"
                    ><span class="drawer-shell__project-name">未分类</span></q-item-label
                  ></q-item-section
                >
              </template>
              <q-item
                v-for="task in uncategorizedTasks"
                :key="task.id"
                clickable
                :to="`/tasks/${task.id}`"
                :active="route.params.id === task.id"
                active-class="is-active"
                class="task-item"
                draggable="true"
                :class="{ 'is-dragging': draggingTaskId === task.id }"
                @dragstart="beginTaskDrag($event, task)"
                @dragend="endTaskDrag"
              >
                <q-item-section
                  ><q-item-label lines="1">{{ task.title }}</q-item-label></q-item-section
                >
                <q-item-section side>
                  <q-btn
                    class="drawer-shell__task-action"
                    flat
                    round
                    dense
                    icon="more_horiz"
                    aria-label="创作操作"
                    @click.prevent.stop
                  >
                    <q-menu
                      ><q-list dense>
                        <q-item clickable v-close-popup @click="renameTask(task)"
                          ><q-item-section>重命名</q-item-section></q-item
                        >
                        <q-item clickable v-close-popup @click="removeTask(task)"
                          ><q-item-section class="text-negative">删除</q-item-section></q-item
                        >
                      </q-list></q-menu
                    >
                  </q-btn>
                </q-item-section>
              </q-item>
            </q-expansion-item>
            <AppButton
              v-if="projectsQuery.hasNextPage.value"
              variant="ghost"
              label="加载更多项目"
              :loading="projectsQuery.isFetchingNextPage.value"
              full-width
              @click="projectsQuery.fetchNextPage()"
            />
            <AppButton
              v-if="tasksQuery.hasNextPage.value"
              variant="ghost"
              label="加载更多任务"
              :loading="tasksQuery.isFetchingNextPage.value"
              full-width
              @click="tasksQuery.fetchNextPage()"
            />
          </div>
        </section>
        <section class="drawer-shell__user">
          <div class="drawer-shell__profile">
            <q-avatar color="primary" text-color="white">{{
              auth.user?.name.slice(0, 1)
            }}</q-avatar>
            <span
              ><strong>{{ auth.user?.name }}</strong
              ><small>{{ auth.user?.role }}</small
              ><small class="drawer-shell__points"
                >剩余 <b>{{ auth.user?.points }}</b> 积分</small
              ></span
            >
            <q-btn
              class="drawer-shell__settings"
              flat
              round
              dense
              icon="settings"
              aria-label="账号菜单"
            >
              <q-menu hover anchor="top right" self="bottom right" :offset="[0, 8]">
                <q-list class="drawer-shell__account-menu">
                  <q-item clickable v-close-popup to="/settings">
                    <q-item-section avatar><q-icon name="settings" /></q-item-section>
                    <q-item-section>个人设置</q-item-section>
                  </q-item>
                  <q-item clickable v-close-popup @click="logout">
                    <q-item-section avatar><q-icon name="logout" /></q-item-section>
                    <q-item-section>退出登录</q-item-section>
                  </q-item>
                </q-list>
              </q-menu>
            </q-btn>
          </div>
        </section>
      </div>
    </q-drawer>

    <q-page-container class="main-layout__content"><router-view /></q-page-container>

    <AppDialog
      v-model="projectDialog"
      :title="projectForm.id ? '项目设置' : '新建项目'"
      width="560px"
    >
      <q-form class="project-form" @submit.prevent="saveProject">
        <q-input v-model="projectForm.name" outlined label="项目名称" maxlength="40" autofocus />
        <q-input
          v-if="projectForm.id"
          v-model="projectForm.description"
          outlined
          type="textarea"
          label="项目说明（可选）"
          maxlength="500"
          autogrow
        />
        <q-input
          v-if="projectForm.id"
          v-model="projectForm.writingRequirements"
          outlined
          type="textarea"
          label="项目写作要求（可选）"
          maxlength="2000"
          autogrow
        />
      </q-form>
      <template #actions>
        <AppButton variant="ghost" label="取消" @click="projectDialog = false" />
        <AppButton
          :label="projectForm.id ? '保存设置' : '创建项目'"
          :loading="projectSaving"
          :disabled="!projectForm.name.trim()"
          @click="saveProject"
        />
      </template>
    </AppDialog>
  </q-layout>
</template>

<style scoped lang="scss">
.main-layout {
  min-width: 0;
  color: var(--app-text-primary);
  background: var(--app-bg-page);

  &__header {
    color: var(--app-text-primary);
    background: color-mix(in srgb, var(--app-bg-surface) 92%, transparent);
    backdrop-filter: blur(12px);
    border-bottom: 1px solid var(--app-border-default);
  }
  &__header .q-toolbar-title {
    display: flex;
    align-items: center;
    gap: 8px;
    font-weight: 700;
  }
  &__header .q-toolbar-title .q-icon {
    color: var(--app-action-primary);
  }

  &__drawer {
    color: var(--app-text-primary);
    background: var(--app-bg-surface);
  }
  &__content {
    min-width: 0;
    min-height: 100dvh;
  }
}

.drawer-shell {
  display: grid;
  grid-template-rows: auto auto auto minmax(0, 1fr) auto;
  min-width: 0;
  min-height: 100%;
  padding: 28px 18px 16px;

  &__create {
    min-height: 54px;
    font-size: 16px;
  }

  &__nav {
    margin: 22px 0 16px;
  }
  &__nav .q-item {
    min-height: 48px;
    margin: 4px 0;
    border-radius: 8px;
    font-size: 16px;
  }
  &__nav .q-item__section--avatar {
    min-width: 40px;
  }
  &__nav .q-icon {
    font-size: 24px;
  }

  .is-active {
    color: var(--app-action-primary);
    background: var(--app-action-soft);
  }
  .is-drop-target :deep(.q-item),
  .is-drop-target {
    color: var(--app-action-primary);
    background: var(--app-action-soft);
    outline: 1px dashed var(--app-action-primary);
    outline-offset: -2px;
  }

  &__projects {
    display: grid;
    grid-template-rows: auto minmax(0, 1fr);
    min-height: 0;
    padding-top: 16px;
  }
  &__projects > header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 2px 6px 12px;
    color: var(--app-text-secondary);
    font-size: 14px;
  }
  &__project-scroll {
    min-height: 0;
    overflow-y: auto;
    overscroll-behavior: contain;
  }
  &__project-name {
    display: block;
    max-width: 128px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  &__project-action {
    width: 24px;
    min-width: 24px;
    height: 24px;
    min-height: 24px;
    padding: 0;
    color: var(--app-text-secondary);
    font-size: 16px;
  }
  &__task-action {
    width: 22px;
    min-width: 22px;
    height: 22px;
    min-height: 22px;
    padding: 0;
    color: var(--app-text-secondary);
    font-size: 14px;
  }
  @media (hover: hover) and (pointer: fine) {
    &__project-action,
    &__task-action {
      opacity: 0;
      transition: opacity var(--app-motion-fast);
      pointer-events: none;
    }

    :deep(.q-expansion-item__container > .q-item:hover) &__project-action,
    :deep(.q-expansion-item__container > .q-item:focus-within) &__project-action,
    .task-item:hover &__task-action,
    .task-item:focus-within &__task-action {
      opacity: 1;
      pointer-events: auto;
    }
  }

  :deep(.q-expansion-item__container > .q-item) {
    min-height: 42px;
    padding-inline: 6px;
    border-radius: 8px;
  }
  :deep(.q-expansion-item__container > .q-item .q-item__section--avatar) {
    min-width: 28px;
    padding-right: 6px;
  }
  :deep(.q-expansion-item__toggle-icon) {
    display: none;
  }
  .task-item {
    min-height: 36px;
    margin-left: 34px;
    padding: 6px 8px;
    border-radius: 7px;
  }
  .task-item[draggable='true'] {
    cursor: grab;
  }
  .task-item.is-dragging {
    opacity: 0.55;
    cursor: grabbing;
  }
  .task-item :deep(.q-item__section--main) {
    min-width: 0;
  }

  &__user {
    display: grid;
    gap: 4px;
    padding-top: 14px;
    border-top: 1px solid var(--app-border-default);
  }
  &__profile {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr) auto;
    align-items: center;
    gap: 10px;
    min-width: 0;
    padding: 8px;
    color: var(--app-text-primary);
    border-radius: 10px;
  }
  &__profile:hover {
    background: var(--app-bg-subtle);
  }
  &__profile span {
    display: grid;
    min-width: 0;
  }
  &__profile strong,
  &__profile small {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  &__profile small {
    color: var(--app-text-secondary);
  }
  &__points {
    margin-top: 3px;
  }
  &__points b {
    color: var(--app-action-primary);
    font-weight: 600;
  }
  &__settings {
    color: var(--app-text-secondary);
  }
  &__account-menu {
    min-width: 132px;
  }
}

@media (max-height: 720px) and (min-width: 1024px) {
  .drawer-shell {
    padding-top: 16px;

    &__create {
      min-height: 46px;
    }
    &__nav {
      margin-block: 10px;
    }
    &__nav .q-item {
      min-height: 42px;
    }
    &__projects {
      padding-top: 8px;
    }
  }
}

.project-form {
  display: grid;
  gap: 16px;
  min-width: 0;
  padding: 22px;

  :deep(textarea.q-field__native) {
    max-height: 180px;
    overflow-y: auto !important;
    overflow-wrap: anywhere;
  }
}
</style>
