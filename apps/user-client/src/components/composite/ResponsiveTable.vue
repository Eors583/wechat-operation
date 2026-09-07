<script setup lang="ts" generic="T extends object">
import type { QTableColumn } from 'quasar'

const props = withDefaults(
  defineProps<{ rows: T[]; columns: QTableColumn<T>[]; rowKey?: string; loading?: boolean }>(),
  { rowKey: 'id', loading: false },
)

const cellValue = (row: T, column: QTableColumn<T>) =>
  typeof column.field === 'function'
    ? column.field(row)
    : (row as Record<string, unknown>)[column.field]

const rowIdentity = (row: T) => String((row as Record<string, unknown>)[props.rowKey])
</script>

<template>
  <div class="responsive-table">
    <q-table
      class="responsive-table__desktop"
      flat
      :rows="rows"
      :columns="columns"
      :row-key="rowKey"
      :loading="loading"
      hide-pagination
      :rows-per-page-options="[0]"
    >
      <template #body="props">
        <slot name="row" :row="props.row" :props="props">
          <q-tr :props="props"
            ><q-td v-for="column in columns" :key="column.name" :props="props">{{
              cellValue(props.row, column)
            }}</q-td></q-tr
          >
        </slot>
      </template>
      <template #no-data><slot name="empty" /></template>
    </q-table>
    <div class="responsive-table__mobile" role="list">
      <slot v-for="row in rows" :key="rowIdentity(row)" name="card" :row="row" />
      <slot v-if="!rows.length" name="empty" />
    </div>
  </div>
</template>

<style scoped lang="scss">
.responsive-table {
  min-width: 0;

  &__desktop {
    color: var(--app-text-primary);
    background: transparent;

    :deep(table) {
      table-layout: fixed;
      width: 100%;
    }

    :deep(th),
    :deep(td) {
      min-width: 0;
      padding: 15px 18px;
      overflow-wrap: anywhere;
      white-space: normal;
    }

    :deep(th) {
      color: var(--app-text-primary);
      font-weight: 600;
    }

    :deep(thead tr) {
      background: var(--app-bg-subtle);
    }
  }

  &__mobile {
    display: none;
    gap: 12px;
  }
}

@media (max-width: 767px) {
  .responsive-table__desktop {
    display: none;
  }

  .responsive-table__mobile {
    display: grid;
  }
}
</style>
