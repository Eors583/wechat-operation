import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import StatusBadge from './StatusBadge.vue'

describe('StatusBadge', () => {
  it.each([
    ['draft', '草稿'],
    ['testing', '测试中'],
    ['published', '已发布'],
    ['available', '已发布'],
    ['disabled', '已停用'],
    ['unknown', '结果待核对'],
  ])('maps %s to a stable Chinese label', (status, label) => {
    const wrapper = mount(StatusBadge, { props: { status } })
    expect(wrapper.text()).toContain(label)
  })

  it('supports an explicit simplified label', () => {
    const wrapper = mount(StatusBadge, { props: { status: 'limited', label: '当前不支持' } })
    expect(wrapper.text()).toContain('当前不支持')
  })
})
