import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { createDefaultStyles } from '@/api/styleDefaults'
import type { Article, LayoutTemplate, OfficialAccount } from '@/api/types'
import WechatFinalPreview from './WechatFinalPreview.vue'

const article: Article = {
  id: 'article-test',
  title: '一段不会被误发布的最终预览文章',
  summary: '摘要',
  taskId: 'task-test',
  projectId: null,
  status: 'editing',
  updatedAt: '2026-08-31T06:20:00.000Z',
  versionNo: 1,
  contentHtml: '<h1>最终预览文章</h1><p>正文</p>',
  coverState: 'ready',
  renderId: 'render-test',
  accountId: 'account-test',
  templateId: 'template-test',
}

const account: OfficialAccount = {
  id: 'account-test',
  name: '品牌内容号',
  avatarText: '品',
  avatarColor: '#08a657',
  status: 'connected',
  authorizedAt: '2026-08-18T02:32:00.000Z',
  lastSyncedAt: '2026-08-31T06:20:00.000Z',
  capabilities: ['draft', 'publish'],
}

const template: LayoutTemplate = {
  id: 'template-test',
  accountId: account.id,
  name: '标准排版',
  enabled: true,
  sourceUrl: '',
  status: 'ready',
  updatedAt: '2026-08-31T06:20:00.000Z',
  sourcePreview: [],
  extractionMode: 'manual',
  styles: createDefaultStyles(),
}

describe('WechatFinalPreview', () => {
  it('identifies the locked destination and requires a separate publish confirmation', async () => {
    const wrapper = mount(WechatFinalPreview, {
      attachTo: document.body,
      props: { modelValue: true, article, account, template, action: 'publish' },
    })
    await new Promise((resolve) => setTimeout(resolve, 0))
    const text = document.body.textContent ?? ''

    expect(text).toContain('发布前最终预览')
    expect(text).toContain('品牌内容号')
    expect(text).toContain('标准排版')
    expect(text).toContain('确认发布')
    expect(text).toContain('只读')
    wrapper.unmount()
  })

  it('disables confirmation when the account needs reconnecting', async () => {
    const wrapper = mount(WechatFinalPreview, {
      attachTo: document.body,
      props: {
        modelValue: true,
        article,
        account: { ...account, status: 'reconnect' },
        template,
        action: 'draft',
      },
    })
    await new Promise((resolve) => setTimeout(resolve, 0))
    const confirm = Array.from(document.body.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('确认存入草稿箱'),
    )

    expect(confirm).toBeDefined()
    expect(confirm?.hasAttribute('disabled')).toBe(true)
    expect(document.body.textContent).toContain('请先重新扫码连接')
    wrapper.unmount()
  })
})
