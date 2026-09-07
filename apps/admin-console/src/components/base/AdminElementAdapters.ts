/* eslint-disable vue/one-component-per-file, vue/require-default-prop */
import {
  ElAlert,
  ElButton,
  ElButtonGroup,
  ElDialog,
  ElAvatar,
  ElInput,
  ElLoading,
  ElOption,
  ElPagination,
  ElProgress,
  ElSelect,
  ElSwitch,
  ElTable,
  ElTableColumn,
  ElTag,
  ElTimeline,
  ElTimelineItem,
  ElTooltip,
} from 'element-plus'
import {
  type Component,
  type InjectionKey,
  type PropType,
  computed,
  defineComponent,
  h,
  inject,
  onBeforeUnmount,
  provide,
  ref,
  watch,
} from 'vue'
import { RouterLink, type RouteLocationRaw } from 'vue-router'
import AppIcon from './AppIcon.vue'

type SelectOption = { label: string; value: unknown; disable?: boolean; disabled?: boolean }
export type AdminTableColumn<T = Record<string, unknown>> = {
  name: string
  label: string
  field?: string | ((row: T) => unknown)
  align?: 'left' | 'center' | 'right'
  sortable?: boolean
}

const colorType = (color?: string): 'primary' | 'success' | 'warning' | 'danger' | 'info' => {
  if (color === 'positive') return 'success'
  if (color === 'negative') return 'danger'
  if (color === 'warning') return 'warning'
  if (color === 'info') return 'info'
  return 'primary'
}

const alertType = (type?: string): 'success' | 'warning' | 'error' | 'info' => {
  if (type === 'positive' || type === 'success') return 'success'
  if (type === 'negative' || type === 'danger' || type === 'error') return 'error'
  if (type === 'warning') return 'warning'
  return 'info'
}

export const AdminButton = defineComponent({
  name: 'AdminButton',
  inheritAttrs: false,
  props: {
    label: String,
    icon: String,
    color: String,
    flat: Boolean,
    outline: Boolean,
    round: Boolean,
    dense: Boolean,
    loading: Boolean,
    disable: Boolean,
    unelevated: Boolean,
    to: [String, Object] as PropType<RouteLocationRaw>,
  },
  emits: ['click'],
  setup(props, { attrs, slots, emit }) {
    const renderButton = (navigate?: (event?: MouseEvent) => void) =>
      h(
        ElButton,
        {
          ...attrs,
          type: props.flat && !props.color ? 'default' : colorType(props.color),
          plain: props.outline || props.flat,
          circle: props.round,
          size: props.dense ? 'small' : undefined,
          loading: props.loading,
          disabled: props.disable || Boolean(attrs.disabled),
          onClick: (event: MouseEvent) => {
            navigate?.(event)
            emit('click', event)
          },
        },
        {
          default: () => [
            props.icon ? h(AppIcon, { name: props.icon, size: 17 }) : null,
            props.label ? h('span', { class: 'admin-button__label' }, props.label) : null,
            slots.default?.(),
          ],
        },
      )
    return () =>
      props.to
        ? h(
            RouterLink,
            { to: props.to, custom: true },
            {
              default: ({ navigate }: { navigate: (event?: MouseEvent) => void }) =>
                renderButton(navigate),
            },
          )
        : renderButton()
  },
})

export const AdminInput = defineComponent({
  name: 'AdminInput',
  inheritAttrs: false,
  props: {
    modelValue: { type: [String, Number] as PropType<string | number | null>, default: '' },
    label: String,
    type: String,
    autogrow: Boolean,
    disable: Boolean,
    clearable: Boolean,
    debounce: [String, Number],
  },
  emits: ['update:modelValue', 'blur', 'keyup'],
  setup(props, { attrs, slots, emit }) {
    let debounceTimer: ReturnType<typeof setTimeout> | undefined

    const updateModelValue = (value: string) => {
      if (debounceTimer !== undefined) clearTimeout(debounceTimer)
      const nextValue = props.type === 'number' ? Number(value) : value
      const delay = Math.max(0, Number(props.debounce) || 0)
      if (delay === 0) {
        debounceTimer = undefined
        emit('update:modelValue', nextValue)
        return
      }
      debounceTimer = setTimeout(() => {
        debounceTimer = undefined
        emit('update:modelValue', nextValue)
      }, delay)
    }

    onBeforeUnmount(() => {
      if (debounceTimer !== undefined) clearTimeout(debounceTimer)
    })

    return () =>
      h(
        ElInput,
        {
          ...attrs,
          modelValue: props.modelValue ?? '',
          placeholder: props.label || String(attrs.placeholder ?? ''),
          ariaLabel: String(attrs['aria-label'] ?? props.label ?? ''),
          type: props.type || 'text',
          autosize: props.autogrow ? { minRows: 2, maxRows: 8 } : undefined,
          disabled: props.disable || Boolean(attrs.disabled),
          clearable: props.clearable,
          showPassword: props.type === 'password',
          'onUpdate:modelValue': updateModelValue,
          onBlur: (event: FocusEvent) => emit('blur', event),
          onKeyup: (event: KeyboardEvent) => emit('keyup', event),
        },
        slots,
      )
  },
})

export const AdminSelect = defineComponent({
  name: 'AdminSelect',
  inheritAttrs: false,
  props: {
    modelValue: {
      type: [String, Number, Boolean, Array] as PropType<
        string | number | boolean | unknown[] | null
      >,
      default: '',
    },
    options: { type: Array as PropType<SelectOption[]>, default: () => [] },
    label: String,
    disable: Boolean,
    clearable: Boolean,
    multiple: Boolean,
    useInput: Boolean,
    fillInput: Boolean,
    newValueMode: String,
    hideSelected: Boolean,
    inputDebounce: [String, Number],
    useChips: Boolean,
    emitValue: Boolean,
    mapOptions: Boolean,
    outlined: Boolean,
    dense: Boolean,
    filterable: Boolean,
    allowCreate: Boolean,
    defaultFirstOption: Boolean,
    reserveKeyword: { type: Boolean, default: undefined },
  },
  emits: ['update:modelValue'],
  setup(props, { attrs, emit }) {
    return () => {
      const allowCreate = props.allowCreate || props.newValueMode === 'add-unique'
      const filterable = props.filterable || props.useInput || allowCreate
      return h(
        ElSelect,
        {
          ...attrs,
          modelValue: props.modelValue,
          placeholder: props.label || String(attrs.placeholder ?? ''),
          ariaLabel: String(attrs['aria-label'] ?? props.label ?? ''),
          disabled: props.disable || Boolean(attrs.disabled),
          clearable: props.clearable,
          multiple: props.multiple,
          size:
            (attrs.size as '' | 'small' | 'default' | 'large' | undefined) ??
            (props.dense ? 'small' : undefined),
          filterable,
          allowCreate,
          defaultFirstOption: props.defaultFirstOption || props.fillInput || allowCreate,
          reserveKeyword: props.hideSelected ? false : (props.reserveKeyword ?? true),
          debounce: Math.max(0, Number(props.inputDebounce) || 0),
          'onUpdate:modelValue': (value: unknown) => emit('update:modelValue', value),
        },
        {
          default: () =>
            props.options.map((option) =>
              h(ElOption, {
                key: String(option.value),
                label: option.label,
                value: option.value as string | number | boolean | Record<string, unknown>,
                disabled: Boolean(option.disable || option.disabled),
              }),
            ),
        },
      )
    }
  },
})

export const AdminToggle = defineComponent({
  name: 'AdminToggle',
  inheritAttrs: false,
  props: {
    modelValue: Boolean,
    label: String,
    disable: Boolean,
    color: String,
  },
  emits: ['update:modelValue'],
  setup(props, { attrs, emit }) {
    return () =>
      h('label', { class: 'admin-toggle' }, [
        h(ElSwitch, {
          ...attrs,
          modelValue: props.modelValue,
          disabled: props.disable,
          'onUpdate:modelValue': (value: string | number | boolean) =>
            emit('update:modelValue', Boolean(value)),
        }),
        props.label ? h('span', props.label) : null,
      ])
  },
})

export const AdminBadge = defineComponent({
  name: 'AdminBadge',
  inheritAttrs: false,
  props: { label: String, color: String, outline: Boolean },
  setup(props, { attrs, slots }) {
    return () =>
      h(
        ElTag,
        { ...attrs, type: colorType(props.color), effect: props.outline ? 'plain' : 'light' },
        { default: () => props.label || slots.default?.() },
      )
  },
})

export const AdminDialog = defineComponent({
  name: 'AdminDialog',
  inheritAttrs: false,
  props: {
    modelValue: Boolean,
    persistent: Boolean,
    maximized: Boolean,
    transitionShow: String,
    transitionHide: String,
  },
  emits: ['update:modelValue', 'hide'],
  setup(props, { attrs, slots, emit }) {
    return () => {
      const dialogAttrs = { ...attrs }
      delete dialogAttrs.position
      return h(
        ElDialog,
        {
          ...dialogAttrs,
          class: ['admin-center-dialog', dialogAttrs.class],
          modelValue: props.modelValue,
          width: props.maximized
            ? 'calc(100vw - 48px)'
            : ((attrs.width as string | number | undefined) ?? 'min(760px, calc(100vw - 48px))'),
          alignCenter: true,
          closeOnClickModal: !props.persistent,
          closeOnPressEscape: !props.persistent,
          showClose: false,
          appendToBody: true,
          destroyOnClose: true,
          'onUpdate:modelValue': (value: boolean) => emit('update:modelValue', value),
          onClosed: () => emit('hide'),
        },
        slots,
      )
    }
  },
})

export const AdminAvatar = defineComponent({
  name: 'AdminAvatar',
  inheritAttrs: false,
  props: {
    icon: String,
    size: { type: [String, Number], default: 40 },
    color: String,
    textColor: String,
  },
  setup(props, { attrs, slots }) {
    return () => {
      const backgrounds: Record<string, string> = {
        primary: 'var(--app-action-primary)',
        'blue-1': 'var(--app-action-primary-soft)',
        'green-1': 'color-mix(in srgb, var(--app-action-success) 14%, var(--app-bg-surface))',
        'red-1': 'color-mix(in srgb, var(--app-action-danger) 14%, var(--app-bg-surface))',
        'orange-1': 'color-mix(in srgb, var(--app-action-warning) 14%, var(--app-bg-surface))',
        'purple-1': 'color-mix(in srgb, #805ad5 14%, var(--app-bg-surface))',
      }
      const avatarSize =
        typeof props.size === 'string' ? Number.parseInt(props.size, 10) || 'default' : props.size
      return h(
        ElAvatar,
        {
          ...attrs,
          size: avatarSize,
          style: [
            attrs.style,
            props.color ? { background: backgrounds[props.color] || props.color } : undefined,
          ],
        },
        {
          default: () =>
            slots.default?.() ||
            (props.icon
              ? h(AppIcon, { name: props.icon, color: props.textColor || props.color })
              : null),
        },
      )
    }
  },
})

export const AdminBanner = defineComponent({
  name: 'AdminBanner',
  inheritAttrs: false,
  props: { icon: String, type: String },
  setup(props, { attrs, slots }) {
    return () =>
      h(
        ElAlert,
        { ...attrs, closable: false, type: alertType(props.type), showIcon: false },
        {
          title: () =>
            h('div', { class: 'admin-banner__content' }, [
              slots.avatar?.() || (props.icon ? h(AppIcon, { name: props.icon, size: 20 }) : null),
              h('div', { class: 'admin-banner__body' }, slots.default?.()),
              slots.action ? h('div', { class: 'admin-banner__action' }, slots.action()) : null,
            ]),
        },
      )
  },
})

export const AdminTable = defineComponent({
  name: 'AdminTable',
  inheritAttrs: false,
  props: {
    rows: { type: Array as PropType<unknown[]>, default: () => [] },
    columns: { type: Array as PropType<AdminTableColumn[]>, default: () => [] },
    rowKey: { type: String, default: 'id' },
    loading: Boolean,
    pagination: Object as PropType<
      Record<string, unknown> & { page?: number; rowsPerPage?: number }
    >,
    rowsPerPageOptions: { type: Array as PropType<number[]>, default: () => [] },
    noDataLabel: String,
  },
  emits: ['row-click', 'update:pagination'],
  setup(props, { attrs, slots, emit }) {
    const normalizePage = (value: unknown) => {
      const page = Number(value)
      return Number.isFinite(page) ? Math.max(1, Math.trunc(page)) : 1
    }
    const normalizeRowsPerPage = (value: unknown, fallback: number) => {
      const rowsPerPage = Number(value)
      return Number.isFinite(rowsPerPage) && rowsPerPage >= 0 ? Math.trunc(rowsPerPage) : fallback
    }
    const initialRowsPerPage = normalizeRowsPerPage(
      props.pagination?.rowsPerPage,
      normalizeRowsPerPage(props.rowsPerPageOptions[0], 10),
    )
    const currentPage = ref(normalizePage(props.pagination?.page))
    const rowsPerPage = ref(initialRowsPerPage)
    const pageCount = computed(() =>
      rowsPerPage.value === 0 ? 1 : Math.max(1, Math.ceil(props.rows.length / rowsPerPage.value)),
    )
    const pageRows = computed(() => {
      if (rowsPerPage.value === 0) return props.rows
      const start = (currentPage.value - 1) * rowsPerPage.value
      return props.rows.slice(start, start + rowsPerPage.value)
    })
    const pageSizes = computed(() => {
      const values = props.rowsPerPageOptions
        .map(Number)
        .filter((value) => Number.isInteger(value) && value > 0)
      if (rowsPerPage.value > 0 && !values.includes(rowsPerPage.value)) {
        values.unshift(rowsPerPage.value)
      }
      return [...new Set(values)]
    })
    const emitPagination = () =>
      emit('update:pagination', {
        ...props.pagination,
        page: currentPage.value,
        rowsPerPage: rowsPerPage.value,
      })
    const updatePage = (value: number) => {
      const nextPage = Math.min(normalizePage(value), pageCount.value)
      if (nextPage === currentPage.value) return
      currentPage.value = nextPage
      emitPagination()
    }
    const updateRowsPerPage = (value: number) => {
      const nextRowsPerPage = normalizeRowsPerPage(value, rowsPerPage.value)
      if (nextRowsPerPage === rowsPerPage.value) return
      rowsPerPage.value = nextRowsPerPage
      currentPage.value = 1
      emitPagination()
    }

    watch(
      () => [props.pagination?.page, props.pagination?.rowsPerPage] as const,
      ([page, perPage]) => {
        if (page !== undefined) currentPage.value = Math.min(normalizePage(page), pageCount.value)
        if (perPage !== undefined) {
          rowsPerPage.value = normalizeRowsPerPage(perPage, rowsPerPage.value)
        }
      },
    )
    watch(pageCount, (count) => {
      if (currentPage.value <= count) return
      currentPage.value = count
      emitPagination()
    })

    const cellValue = (column: AdminTableColumn, row: Record<string, unknown>): unknown => {
      if (typeof column.field === 'function') return column.field(row)
      return row[column.field || column.name]
    }
    return () =>
      h('div', { class: 'admin-table', style: { minWidth: 0, maxWidth: '100%' } }, [
        h(
          ElTable,
          {
            ...attrs,
            class: ['admin-table__table', attrs.class],
            data: pageRows.value as Record<string, unknown>[],
            rowKey: props.rowKey,
            border: true,
            stripe: true,
            emptyText: props.noDataLabel || '暂无数据',
            loading: props.loading,
            onRowClick: (row: Record<string, unknown>, column: unknown, event: Event) =>
              emit('row-click', event, row, column),
          },
          {
            default: () =>
              props.columns.map((column) =>
                h(
                  ElTableColumn,
                  {
                    key: column.name,
                    prop: typeof column.field === 'string' ? column.field : column.name,
                    label: column.label,
                    align: column.align || 'left',
                    sortable: column.sortable,
                    minWidth: column.name === 'actions' ? 150 : 120,
                    fixed: column.name === 'actions' ? 'right' : undefined,
                  },
                  {
                    default: ({ row }: { row: Record<string, unknown> }) => {
                      const slot = slots[`body-cell-${column.name}`]
                      return slot
                        ? slot({ row, value: cellValue(column, row), col: column })
                        : String(cellValue(column, row) ?? '—')
                    },
                  },
                ),
              ),
          },
        ),
        props.pagination && rowsPerPage.value > 0 && props.rows.length > 0
          ? h(
              'div',
              {
                class: 'admin-table__pagination',
                style: {
                  display: 'flex',
                  justifyContent: 'flex-end',
                  maxWidth: '100%',
                  overflowX: 'auto',
                },
              },
              [
                h(ElPagination, {
                  currentPage: currentPage.value,
                  pageSize: rowsPerPage.value,
                  pageSizes: pageSizes.value,
                  total: props.rows.length,
                  pagerCount: 5,
                  layout:
                    pageSizes.value.length > 1
                      ? 'total, sizes, prev, pager, next'
                      : 'total, prev, pager, next',
                  disabled: props.loading,
                  'onUpdate:currentPage': updatePage,
                  'onUpdate:pageSize': updateRowsPerPage,
                }),
              ],
            )
          : null,
      ])
  },
})

const passthrough = (name: string, defaultTag = 'div') => {
  const componentClass = name.replace(/([a-z0-9])([A-Z])/g, '$1-$2').toLowerCase()
  return defineComponent({
    name,
    inheritAttrs: false,
    props: {
      tag: String,
      caption: Boolean,
      side: Boolean,
      avatar: Boolean,
      bordered: Boolean,
      separator: [Boolean, String] as PropType<boolean | string>,
    },
    setup(props, { attrs, slots }) {
      return () =>
        h(
          props.tag || defaultTag,
          {
            ...attrs,
            class: [
              componentClass,
              attrs.class,
              props.caption
                ? [`${componentClass}--caption`, 'caption-text', 'text-secondary']
                : null,
              props.side ? `${componentClass}--side` : null,
              props.avatar ? `${componentClass}--avatar` : null,
              props.bordered ? `${componentClass}--bordered` : null,
              props.separator ? `${componentClass}--separator` : null,
              props.bordered || props.separator ? 'admin-list-surface' : null,
            ],
            style: [
              attrs.style,
              props.side ? { flex: '0 0 auto', marginInlineStart: 'auto' } : null,
              props.avatar ? { flex: '0 0 auto' } : null,
            ],
          },
          slots.default?.(),
        )
    },
  })
}

export const AdminCell = passthrough('AdminCell')
export const AdminCardSection = passthrough('AdminCardSection', 'section')
export const AdminCardActions = passthrough('AdminCardActions')
export const AdminList = passthrough('AdminList')
export const AdminItem = passthrough('AdminItem')
export const AdminItemSection = passthrough('AdminItemSection')
export const AdminItemLabel = passthrough('AdminItemLabel', 'span')
export const AdminToolbar = passthrough('AdminToolbar')
export const AdminToolbarTitle = passthrough('AdminToolbarTitle')
export const AdminSpace = defineComponent({
  name: 'AdminSpace',
  setup: () => () => h('span', { class: 'admin-space' }),
})

export const AdminProgress = defineComponent({
  name: 'AdminProgress',
  inheritAttrs: false,
  props: { value: { type: Number, default: 0 }, color: String, size: String, rounded: Boolean },
  setup(props, { attrs }) {
    return () =>
      h(ElProgress, {
        ...attrs,
        percentage: Math.round(props.value * 100),
        showText: false,
        strokeWidth: Number.parseInt(props.size || '6', 10),
      })
  },
})

export const AdminTooltip = defineComponent({
  name: 'AdminTooltip',
  inheritAttrs: false,
  setup(_, { attrs, slots }) {
    return () => h(ElTooltip, { ...attrs, content: String(attrs.content ?? '') }, slots)
  },
})

export const AdminTimeline = ElTimeline as Component
export const AdminTimelineEntry = defineComponent({
  name: 'AdminTimelineEntry',
  inheritAttrs: false,
  props: { title: String, subtitle: String, color: String, icon: String },
  setup(props, { attrs, slots }) {
    return () =>
      h(
        ElTimelineItem,
        { ...attrs, timestamp: props.subtitle, type: colorType(props.color) },
        { default: () => [props.title ? h('strong', props.title) : null, slots.default?.()] },
      )
  },
})

type TabsContext = { value: () => unknown; update: (value: unknown) => void }
const tabsKey: InjectionKey<TabsContext> = Symbol('admin-tabs')

export const AdminTabs = defineComponent({
  name: 'AdminTabs',
  props: { modelValue: { type: [String, Number] as PropType<unknown>, default: '' } },
  emits: ['update:modelValue'],
  setup(props, { slots, emit }) {
    provide(tabsKey, {
      value: () => props.modelValue,
      update: (value) => emit('update:modelValue', value),
    })
    return () => h(ElButtonGroup, { class: 'admin-tabs' }, { default: () => slots.default?.() })
  },
})

export const AdminTab = defineComponent({
  name: 'AdminTab',
  props: {
    name: { type: [String, Number] as PropType<unknown>, required: true },
    label: String,
    icon: String,
  },
  setup(props) {
    const context = inject(tabsKey)
    return () =>
      h(
        ElButton,
        {
          type: context?.value() === props.name ? 'primary' : 'default',
          onClick: () => context?.update(props.name),
        },
        {
          default: () => [
            props.icon ? h(AppIcon, { name: props.icon, size: 16 }) : null,
            props.label,
          ],
        },
      )
  },
})

export const AdminTabPanels = defineComponent({
  name: 'AdminTabPanels',
  props: { modelValue: { type: [String, Number] as PropType<unknown>, default: '' } },
  setup(props, { slots }) {
    provide(tabsKey, { value: () => props.modelValue, update: () => undefined })
    return () => h('div', { class: 'admin-tab-panels' }, slots.default?.())
  },
})

export const AdminTabPanel = defineComponent({
  name: 'AdminTabPanel',
  props: { name: { type: [String, Number] as PropType<unknown>, required: true } },
  setup(props, { slots }) {
    const context = inject(tabsKey)
    return () =>
      context?.value() === props.name
        ? h('section', { class: 'admin-tab-panel' }, slots.default?.())
        : null
  },
})

export const AdminInnerLoading = defineComponent({
  name: 'AdminInnerLoading',
  directives: { loading: ElLoading.directive },
  props: { showing: Boolean, label: String },
  setup(props) {
    return () =>
      props.showing
        ? h('div', { class: 'admin-inner-loading', 'aria-busy': 'true' }, props.label || '加载中…')
        : null
  },
})
