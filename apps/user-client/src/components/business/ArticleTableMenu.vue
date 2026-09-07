<script setup lang="ts">
import type { Editor } from '@tiptap/vue-3'
defineProps<{ editor?: Editor }>()
</script>
<template>
  <q-btn flat round dense icon="table_chart" aria-label="表格操作" :disable="!editor">
    <q-menu>
      <q-list>
        <q-item
          clickable
          v-close-popup
          :disable="editor?.isActive('table')"
          @click="
            editor?.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run()
          "
          ><q-item-section>插入三列表格</q-item-section></q-item
        >
        <q-item
          clickable
          v-close-popup
          :disable="!editor?.isActive('table')"
          @click="editor?.chain().focus().addRowAfter().run()"
          ><q-item-section>在下方增加一行</q-item-section></q-item
        >
        <q-item
          clickable
          v-close-popup
          :disable="!editor?.isActive('table')"
          @click="editor?.chain().focus().addColumnAfter().run()"
          ><q-item-section>在右侧增加一列</q-item-section></q-item
        >
        <q-item
          clickable
          v-close-popup
          :disable="!editor?.isActive('table')"
          @click="editor?.chain().focus().deleteRow().run()"
          ><q-item-section>删除当前行</q-item-section></q-item
        >
        <q-item
          clickable
          v-close-popup
          :disable="!editor?.isActive('table')"
          @click="editor?.chain().focus().deleteColumn().run()"
          ><q-item-section>删除当前列</q-item-section></q-item
        >
        <q-item
          clickable
          v-close-popup
          :disable="!editor?.isActive('table')"
          @click="editor?.chain().focus().deleteTable().run()"
          ><q-item-section>删除表格</q-item-section></q-item
        >
      </q-list>
    </q-menu>
  </q-btn>
</template>
