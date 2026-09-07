<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useInfiniteQuery } from '@tanstack/vue-query'
import { useQuasar } from 'quasar'
import { api } from '@/api/client'
import type { Skill } from '@/api/types'
import { queryClient } from '@/boot/query'
import AppButton from '@/components/base/AppButton.vue'
import AppDialog from '@/components/base/AppDialog.vue'
import PageHeader from '@/components/composite/PageHeader.vue'
import AsyncStatePanel from '@/components/composite/AsyncStatePanel.vue'
import SkillCard from '@/components/business/SkillCard.vue'
import { usePublicSettings } from '@/composables/usePublicSettings'

const $q = useQuasar()
const { settings: publicSettings } = usePublicSettings()
const personalSkillsEnabled = computed(
  () => publicSettings.value.features.featureFlags.personal_skills !== false,
)
const skillsQuery = useInfiniteQuery({
  queryKey: ['skills'],
  queryFn: ({ pageParam }) => api.listSkillsPage(pageParam),
  initialPageParam: undefined as string | undefined,
  getNextPageParam: (lastPage) => lastPage.nextCursor,
})
const search = ref('')
const tab = ref<'all' | 'enabled' | 'personal'>('all')
const category = ref('all')
const busyId = ref('')
const detailDialog = ref(false)
const editDialog = ref(false)
const selected = ref<Skill | null>(null)
const saving = ref(false)
const form = reactive({ id: '', name: '', scenes: '', requirements: '', examples: '' })

const skills = computed(() => [
  ...new Map(
    (skillsQuery.data.value?.pages.flatMap((page) => page.items) ?? []).map((skill) => [
      skill.id,
      skill,
    ]),
  ).values(),
])
const categories = computed(() => ['all', ...new Set(skills.value.map((item) => item.category))])
const filtered = computed(() => {
  const value = search.value.trim().toLocaleLowerCase()
  return skills.value
    .filter(
      (item) =>
        tab.value === 'all' ||
        (tab.value === 'enabled' && item.enabled) ||
        (tab.value === 'personal' && item.scope === 'personal'),
    )
    .filter((item) => category.value === 'all' || item.category === category.value)
    .filter(
      (item) =>
        !value ||
        `${item.name} ${item.description} ${item.scenes}`.toLocaleLowerCase().includes(value),
    )
})

const showDetail = (skill: Skill) => {
  selected.value = skill
  detailDialog.value = true
}
const openEdit = (skill?: Skill) => {
  selected.value = skill ?? null
  Object.assign(
    form,
    skill
      ? {
          id: skill.id,
          name: skill.name,
          scenes: skill.scenes,
          requirements: skill.requirements,
          examples: skill.examples.join('\n'),
        }
      : { id: '', name: '', scenes: '', requirements: '', examples: '' },
  )
  editDialog.value = true
}

const editSelected = () => {
  if (!selected.value) return
  detailDialog.value = false
  openEdit(selected.value)
}

const toggle = async (skill: Skill, enabled: boolean) => {
  if (skill.scope === 'personal' && !personalSkillsEnabled.value) {
    $q.notify({ type: 'warning', message: '个人技能功能当前已停用。' })
    return
  }
  busyId.value = skill.id
  try {
    await api.setSkillEnabled(skill.id, enabled)
    await queryClient.invalidateQueries({ queryKey: ['skills'] })
    $q.notify({
      type: 'positive',
      message: enabled ? '技能已启用，可用于之后的新生成。' : '技能已停用，历史文章不会改变。',
    })
  } finally {
    busyId.value = ''
  }
}

const save = async () => {
  if (!form.name.trim() || !form.scenes.trim() || !form.requirements.trim()) return
  saving.value = true
  try {
    await api.saveSkill({
      id: form.id || undefined,
      name: form.name.trim(),
      scenes: form.scenes.trim(),
      requirements: form.requirements.trim(),
      examples: form.examples
        .split('\n')
        .map((item) => item.trim())
        .filter(Boolean),
    })
    await queryClient.invalidateQueries({ queryKey: ['skills'] })
    editDialog.value = false
    $q.notify({ type: 'positive', message: form.id ? '技能已更新。' : '技能已创建并启用。' })
  } finally {
    saving.value = false
  }
}

const remove = () => {
  if (!selected.value || selected.value.scope !== 'personal') return
  $q.dialog({
    title: '删除技能',
    message: `确定删除“${selected.value.name}”吗？历史任务不会改变。`,
    cancel: true,
    persistent: true,
  }).onOk(async () => {
    await api.deleteSkill(selected.value!.id)
    detailDialog.value = false
    await queryClient.invalidateQueries({ queryKey: ['skills'] })
  })
}
</script>

<template>
  <q-page class="app-page skills-page">
    <PageHeader title="技能库">
      <template #actions
        ><AppButton
          v-if="personalSkillsEnabled"
          variant="outline"
          icon="add"
          label="创建技能"
          @click="openEdit()"
      /></template>
    </PageHeader>

    <section class="skills-filter">
      <div>
        <q-input
          v-model="search"
          outlined
          dense
          clearable
          placeholder="搜索技能名称或功能"
          aria-label="搜索技能"
          ><template #prepend><q-icon name="search" /></template></q-input
        ><q-select
          v-model="category"
          outlined
          dense
          emit-value
          map-options
          label="分类"
          :options="
            categories.map((item) => ({ label: item === 'all' ? '全部分类' : item, value: item }))
          "
        />
      </div>
      <q-tabs v-model="tab" dense active-color="primary" indicator-color="primary" align="left"
        ><q-tab name="all" :label="`全部技能 ${skills.length}`" /><q-tab
          name="enabled"
          :label="`已启用 ${skills.filter((item) => item.enabled).length}`" /><q-tab
          name="personal"
          :label="`我的技能 ${skills.filter((item) => item.scope === 'personal').length}`"
      /></q-tabs>
    </section>

    <q-banner v-if="!personalSkillsEnabled" rounded class="skills-disabled-banner"
      >个人技能功能当前已停用；已发布的官方技能仍可正常启停和使用。</q-banner
    >
    <AsyncStatePanel
      :loading="skillsQuery.isPending.value"
      :error="skillsQuery.error.value instanceof Error ? skillsQuery.error.value.message : null"
      :empty="!filtered.length"
      empty-title="没有找到技能"
      :empty-description="
        skillsQuery.hasNextPage.value
          ? '当前已加载的技能中没有匹配项，可以继续加载更多技能。'
          : personalSkillsEnabled
            ? '调整筛选条件，或创建一个自己的技能。'
            : '调整筛选条件查看可用的官方技能。'
      "
      @retry="skillsQuery.refetch()"
    >
      <section class="skills-grid">
        <SkillCard
          v-for="skill in filtered"
          :key="skill.id"
          :skill="skill"
          :busy="busyId === skill.id"
          @detail="showDetail(skill)"
          @edit="openEdit(skill)"
          @toggle="toggle(skill, $event)"
        />
      </section>
    </AsyncStatePanel>
    <div v-if="skillsQuery.hasNextPage.value" class="skills-load-more">
      <AppButton
        variant="outline"
        label="加载更多技能"
        :loading="skillsQuery.isFetchingNextPage.value"
        @click="skillsQuery.fetchNextPage()"
      />
    </div>

    <AppDialog v-if="selected" v-model="detailDialog" title="技能详情" width="820px">
      <div class="skill-detail">
        <div class="skill-detail__hero">
          <div>
            <q-icon
              :name="selected.scope === 'official' ? 'description' : 'edit_note'"
              size="38px"
            />
          </div>
          <h2>{{ selected.name }}</h2>
          <p>{{ selected.description }}</p>
        </div>
        <section>
          <h3>示例指令</h3>
          <div class="skill-detail__examples">
            <q-card v-for="example in selected.examples" :key="example" flat bordered
              ><q-card-section
                ><q-icon name="chat_bubble_outline" />{{ example }}</q-card-section
              ></q-card
            >
          </div>
        </section>
        <q-list bordered separator
          ><q-item
            ><q-item-section
              ><q-item-label caption>技能类型</q-item-label
              ><q-item-label>{{
                selected.scope === 'official' ? '官方技能' : '我的技能'
              }}</q-item-label></q-item-section
            ></q-item
          ><q-item
            ><q-item-section
              ><q-item-label caption>适用场景</q-item-label
              ><q-item-label class="wrap-anywhere">{{
                selected.scenes
              }}</q-item-label></q-item-section
            ></q-item
          ><q-item
            ><q-item-section
              ><q-item-label caption>写作要求</q-item-label
              ><q-item-label class="wrap-anywhere">{{
                selected.requirements
              }}</q-item-label></q-item-section
            ></q-item
          ></q-list
        >
      </div>
      <template #actions>
        <AppButton
          v-if="selected.scope === 'personal' && personalSkillsEnabled"
          variant="danger"
          label="删除技能"
          @click="remove"
        />
        <AppButton
          v-if="selected.scope === 'personal' && personalSkillsEnabled"
          variant="outline"
          label="编辑"
          @click="editSelected"
        />
        <AppButton
          v-if="selected.scope === 'official' || personalSkillsEnabled"
          :variant="selected.enabled ? 'primary' : 'outline'"
          :label="selected.enabled ? '已启用' : '启用技能'"
          @click="toggle(selected, !selected.enabled)"
        />
      </template>
    </AppDialog>

    <AppDialog v-model="editDialog" :title="form.id ? '编辑我的技能' : '创建技能'" width="700px">
      <q-form class="skill-form" @submit.prevent="save">
        <q-input v-model="form.name" outlined label="技能名称" maxlength="40" autofocus />
        <q-input
          v-model="form.scenes"
          outlined
          type="textarea"
          label="适用场景"
          placeholder="例如：产品发布稿、行业观察、活动复盘"
          maxlength="500"
          autogrow
        />
        <q-input
          v-model="form.requirements"
          outlined
          type="textarea"
          label="写作要求"
          placeholder="用普通语言描述希望 AI 遵循的写作方法"
          maxlength="3000"
          autogrow
        />
        <q-input
          v-model="form.examples"
          outlined
          type="textarea"
          label="示例文章或指令（选填，每行一条）"
          maxlength="3000"
          autogrow
        />
      </q-form>
      <template #actions
        ><AppButton variant="ghost" label="取消" @click="editDialog = false" /><AppButton
          label="保存技能"
          :loading="saving"
          :disabled="!form.name.trim() || !form.scenes.trim() || !form.requirements.trim()"
          @click="save"
      /></template>
    </AppDialog>
  </q-page>
</template>

<style scoped lang="scss">
.skills-filter {
  min-width: 0;
  margin-bottom: 26px;
}
.skills-filter > div {
  display: grid;
  grid-template-columns: minmax(260px, 1fr) minmax(160px, 240px);
  gap: 12px;
  min-width: 0;
}
.skills-filter .q-tabs {
  margin-top: 20px;
  border-bottom: 1px solid var(--app-border-default);
}
.skills-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 20px;
  min-width: 0;
}
.skills-load-more {
  display: flex;
  justify-content: center;
  min-width: 0;
  padding: 18px 0 4px;
}
.skills-disabled-banner {
  margin-bottom: 16px;
  color: var(--app-text-secondary);
  background: var(--app-bg-subtle);
  overflow-wrap: anywhere;
}

.skill-detail {
  display: grid;
  gap: 24px;
  min-width: 0;
  padding: 24px;
}
.skill-detail__hero {
  display: grid;
  place-items: center;
  text-align: center;
}
.skill-detail__hero > div {
  display: grid;
  place-items: center;
  width: 76px;
  height: 76px;
  color: var(--app-action-primary);
  background: var(--app-action-soft);
  border-radius: 16px;
}
.skill-detail__hero h2 {
  margin: 14px 0 0;
  font-size: 24px;
}
.skill-detail__hero p {
  max-width: 650px;
  margin: 6px 0 0;
  color: var(--app-text-secondary);
  overflow-wrap: anywhere;
}
.skill-detail h3 {
  margin: 0 0 12px;
}
.skill-detail__examples {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}
.skill-detail__examples .q-card__section {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 10px;
  overflow-wrap: anywhere;
}
.skill-detail .q-list {
  border-color: var(--app-border-default);
  border-radius: 10px;
}

.skill-form {
  display: grid;
  gap: 16px;
  min-width: 0;
  padding: 22px;
}
.skill-form :deep(textarea.q-field__native) {
  max-height: 180px;
  overflow-y: auto !important;
  overflow-wrap: anywhere;
}

@media (max-width: 1199px) {
  .skills-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (max-width: 599px) {
  .skills-filter {
    padding-inline: 10px;
  }
  .skills-filter > div,
  .skills-grid,
  .skill-detail__examples {
    grid-template-columns: 1fr;
  }
  .skills-filter .q-tabs :deep(.q-tab__label) {
    font-size: 12px;
  }
}
</style>
