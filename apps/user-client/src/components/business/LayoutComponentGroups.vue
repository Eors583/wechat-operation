<script setup lang="ts">
import type { LayoutComponentGroup, LayoutContentBlock } from '@/api/types'

const props = defineProps<{ groups: LayoutComponentGroup[]; blocks: LayoutContentBlock[]; disabled: boolean; selectedIds: string[] }>()
const emit = defineEmits<{ update: [groups: LayoutComponentGroup[]]; select: [ids: string[]]; add: [] }>()
const kinds = [
  { label: '导语卡片', value: 'lead_card' },
  { label: '署名信息组', value: 'credits' },
  { label: '装饰标题组', value: 'decorated_heading' },
  { label: '普通正文', value: 'body' },
  { label: '固定内容', value: 'fixed' },
]
const update = (index: number, patch: Partial<LayoutComponentGroup>) => {
  if (props.disabled) return
  emit('update', props.groups.map((group, position) => position === index ? { ...group, ...patch } : group))
}
const excerpt = (group: LayoutComponentGroup) => props.blocks.filter(block => group.blockIds.includes(block.id)).map(block => block.text).join(' ').slice(0, 120)
const setField = (index: number, fieldIndex: number, key: 'label' | 'value', value: unknown) => {
  const group = props.groups[index]
  if (group) update(index, { fields: group.fields.map((field, position) => position === fieldIndex ? { ...field, [key]: String(value ?? '') } : field) })
}
</script>

<template>
  <div class="component-groups">
    <q-expansion-item label="组合组件识别" icon="widgets" :caption="`${groups.length} 组`">
      <q-btn flat dense label="将所选原文添加为组件" :disable="disabled || !selectedIds.length || selectedIds.length > 100 || groups.length >= 100" @click="emit('add')" />
      <div v-if="!groups.length" class="component-groups__empty">未发现组合组件，可选中原文后添加。</div>
      <section v-for="(group, index) in groups" :key="group.id" class="component-groups__item">
        <div class="component-groups__row">
          <q-select :model-value="group.kind" :options="kinds" emit-value map-options dense outlined label="组件类型" :disable="disabled" @update:model-value="update(index, { kind: $event, enabled: false, confirmed: false })" />
          <q-badge :color="group.confirmed ? 'positive' : 'warning'">{{ group.confirmed ? '已确认' : '待确认' }}</q-badge>
          <q-btn flat dense label="选择此组" :disable="disabled" @click="emit('select', group.blockIds)" />
          <q-btn flat round dense icon="close" aria-label="移除组件" :disable="disabled" @click="emit('update', groups.filter((_, position) => position !== index))" />
        </div>
        <div class="component-groups__excerpt">{{ excerpt(group) }}</div>
        <div class="component-groups__row">
          <q-checkbox :model-value="group.confirmed" label="确认识别" :disable="disabled" @update:model-value="update(index, { confirmed: Boolean($event), enabled: false })" />
          <q-toggle :model-value="group.enabled" label="用于排版" :disable="disabled || !group.confirmed || ['body', 'fixed'].includes(group.kind)" @update:model-value="update(index, { enabled: Boolean($event) })" />
        </div>
        <div v-if="group.kind === 'lead_card'" class="component-groups__empty">使用新文章首段，不复制原文导语。</div>
        <template v-if="group.kind === 'credits'">
          <div v-for="(field, fieldIndex) in group.fields" :key="fieldIndex" class="component-groups__row">
            <q-input :model-value="field.label" label="字段" outlined dense maxlength="40" :disable="disabled" @update:model-value="setField(index, fieldIndex, 'label', $event)" />
            <q-input :model-value="field.value" label="你的姓名或来源" outlined dense maxlength="120" :disable="disabled" @update:model-value="setField(index, fieldIndex, 'value', $event)" />
            <q-btn flat round dense icon="close" aria-label="删除署名行" :disable="disabled" @click="update(index, { fields: group.fields.filter((_, position) => position !== fieldIndex) })" />
          </div>
          <q-btn flat dense label="添加署名行" :disable="disabled || group.fields.length >= 12" @click="update(index, { fields: [...group.fields, { label: '作者', value: '' }] })" />
          <label>字段名颜色 <input type="color" :value="group.labelStyle.color || '#888888'" :disabled="disabled" @input="update(index, { labelStyle: { ...group.labelStyle, color: ($event.target as HTMLInputElement).value } })" /></label>
        </template>
        <div v-if="group.kind === 'decorated_heading'" class="component-groups__row">
          <q-input :model-value="group.sequence" label="图片对应第几章" type="number" min="1" max="100" dense outlined :disable="disabled" @update:model-value="update(index, { sequence: $event ? Number($event) : null })" />
          <q-input :model-value="group.imageWidth" label="图片宽度" type="number" min="24" max="680" dense outlined :disable="disabled" @update:model-value="update(index, { imageWidth: Number($event) })" />
        </div>
        <div class="component-groups__row">
          <q-select :model-value="group.containerStyle.align || 'left'" :options="['left', 'center', 'right', 'justify']" label="组件对齐" dense outlined :disable="disabled" @update:model-value="update(index, { containerStyle: { ...group.containerStyle, align: $event } })" />
          <q-input :model-value="group.containerStyle.marginBottom ?? 16" label="下方间距" type="number" min="0" max="72" dense outlined :disable="disabled" @update:model-value="update(index, { containerStyle: { ...group.containerStyle, marginBottom: Number($event) } })" />
          <q-input :model-value="group.containerStyle.padding ?? 0" label="内边距" type="number" min="0" max="72" dense outlined :disable="disabled" @update:model-value="update(index, { containerStyle: { ...group.containerStyle, padding: Number($event) } })" />
        </div>
        <div class="component-groups__row">
          <label>文字颜色 <input type="color" :value="group.textStyle.color || '#222222'" :disabled="disabled" @input="update(index, { textStyle: { ...group.textStyle, color: ($event.target as HTMLInputElement).value } })" /></label>
          <label>容器背景 <input type="color" :value="(group.containerStyle.background || '#ffffff').slice(0, 7)" :disabled="disabled" @input="update(index, { containerStyle: { ...group.containerStyle, background: ($event.target as HTMLInputElement).value } })" /></label>
          <q-btn flat dense label="透明背景" :disable="disabled" @click="update(index, { containerStyle: { ...group.containerStyle, background: '#00000000' } })" />
        </div>
      </section>
    </q-expansion-item>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/tokens' as space;
.component-groups {
  flex: 0 1 auto;
  min-height: 48px;
  min-width: 0;
  max-height: 40vh;
  overflow-y: auto;
  border-bottom: 1px solid var(--app-border-default);
  &__item { min-width: 0; padding: space.$space-3; border-top: 1px solid var(--app-border-default); }
  &__row { display: flex; flex-wrap: wrap; align-items: center; gap: space.$space-2; min-width: 0; margin-bottom: space.$space-2; }
  &__row > .q-field { flex: 1 1 130px; min-width: 0; }
  &__excerpt, &__empty { min-width: 0; padding: space.$space-2; color: var(--app-text-secondary); overflow-wrap: anywhere; }
  label { display: flex; align-items: center; gap: space.$space-2; min-width: 0; }
}
</style>
