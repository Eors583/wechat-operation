import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { OfficialAccount } from '@/api/types'
import OfficialAccountCard from './OfficialAccountCard.vue'

const account: OfficialAccount = {
  id: 'raw-account-id-must-not-render',
  name: '品牌内容号',
  avatarText: '品',
  avatarColor: '#08a657',
  status: 'connected',
  authorizedAt: '2026-08-18T02:32:00.000Z',
  lastSyncedAt: '2026-08-31T06:20:00.000Z',
  capabilities: ['draft', 'publish'],
}

describe('OfficialAccountCard', () => {
  it('shows the V3 list fields without exposing raw id, type, or capabilities', () => {
    const wrapper = mount(OfficialAccountCard, { props: { account } })

    expect(wrapper.text()).toContain('品牌内容号')
    expect(wrapper.text()).toContain('已绑定 · 长期有效')
    expect(wrapper.text()).toContain('最近同步')
    expect(wrapper.text()).not.toContain(account.id)
    expect(wrapper.text()).not.toContain('服务号')
    expect(wrapper.text()).not.toContain('写入草稿箱')
  })

  it('offers a new scan only when authorization was revoked', async () => {
    const wrapper = mount(OfficialAccountCard, {
      props: { account: { ...account, status: 'reconnect' } },
    })
    const reconnect = wrapper
      .findAll('button')
      .find((button) => button.text().includes('重新扫码绑定'))

    expect(reconnect).toBeDefined()
    expect(wrapper.text()).toContain('授权已解除')
    await reconnect?.trigger('click')
    expect(wrapper.emitted('reconnect')).toHaveLength(1)
  })
})
