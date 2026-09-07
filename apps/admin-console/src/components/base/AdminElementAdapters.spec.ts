import { mount } from '@vue/test-utils'
import { ElDialog, ElInput, ElSelect } from 'element-plus'
import { nextTick } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  AdminDialog,
  AdminInput,
  AdminItemLabel,
  AdminSelect,
  AdminTable,
  AdminToolbar,
} from './AdminElementAdapters'

describe('AdminElementAdapters', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('maps searchable, user-created selects to Element Plus props', () => {
    const wrapper = mount(AdminSelect, {
      props: {
        modelValue: [] as never,
        multiple: true,
        useInput: true,
        newValueMode: 'add-unique',
      },
    })

    const select = wrapper.findComponent(ElSelect)
    expect(select.props('filterable')).toBe(true)
    expect(select.props('allowCreate')).toBe(true)
  })

  it('paginates table rows and switches to the requested page', async () => {
    const rows = Array.from({ length: 5 }, (_, index) => ({ id: index + 1 }))
    const wrapper = mount(AdminTable, {
      props: {
        rows,
        columns: [{ name: 'id', label: 'ID', field: 'id' }],
        pagination: { page: 1, rowsPerPage: 2 },
      },
    })

    expect(wrapper.findComponent({ name: 'ElTable' }).props('data')).toEqual(rows.slice(0, 2))

    const pagination = wrapper.findComponent({ name: 'ElPagination' })
    expect(pagination.exists()).toBe(true)
    expect(pagination.props('pageSize')).toBe(2)
    expect(pagination.props('total')).toBe(5)

    pagination.vm.$emit('update:current-page', 2)
    await nextTick()

    expect(wrapper.findComponent({ name: 'ElTable' }).props('data')).toEqual(rows.slice(2, 4))
    expect(wrapper.emitted('update:pagination')?.at(-1)).toEqual([{ page: 2, rowsPerPage: 2 }])
  })

  it('adds semantic classes to passthrough layout components', () => {
    expect(mount(AdminToolbar).classes()).toContain('admin-toolbar')

    const label = mount(AdminItemLabel, { props: { caption: true } })
    expect(label.classes()).toEqual(
      expect.arrayContaining([
        'admin-item-label',
        'admin-item-label--caption',
        'caption-text',
        'text-secondary',
      ]),
    )
  })

  it('makes persistent dialogs ignore Escape and hide the default close button', () => {
    const wrapper = mount(AdminDialog, {
      props: { modelValue: true, persistent: true },
    })

    const dialog = wrapper.findComponent(ElDialog)
    expect(dialog.props('closeOnPressEscape')).toBe(false)
    expect(dialog.props('showClose')).toBe(false)
  })

  it('always renders centered Element Plus dialogs even when legacy position is supplied', () => {
    const wrapper = mount(AdminDialog, {
      props: { modelValue: true },
      attrs: { position: 'right' },
    })

    const dialog = wrapper.findComponent(ElDialog)
    expect(dialog.exists()).toBe(true)
    expect(dialog.props('alignCenter')).toBe(true)
  })

  it('emits debounced input values only after the configured delay', async () => {
    vi.useFakeTimers()
    const wrapper = mount(AdminInput, {
      props: { modelValue: '', debounce: 180 },
    })

    wrapper.findComponent(ElInput).vm.$emit('update:modelValue', 'updated')
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()

    vi.advanceTimersByTime(179)
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()

    vi.advanceTimersByTime(1)
    await nextTick()
    expect(wrapper.emitted('update:modelValue')).toEqual([['updated']])
  })
})
