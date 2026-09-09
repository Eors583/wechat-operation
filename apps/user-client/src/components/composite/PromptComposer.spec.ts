import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import {
  QInput,
  QChip,
  QTooltip,
  QSelect,
  QMenu,
  QList,
  QItem,
  QItemLabel,
  QItemSection,
  QToggle,
  QCheckbox,
} from 'quasar'
import PromptComposer from './PromptComposer.vue'

const notify = vi.fn()
vi.mock('quasar', async (original) => ({
  ...(await original<typeof import('quasar')>()),
  useQuasar: () => ({ notify }),
}))
vi.mock('@/api/client', () => ({ api: {} }))
const global = {
  components: {
    QInput,
    QChip,
    QTooltip,
    QSelect,
    QMenu,
    QList,
    QItem,
    QItemLabel,
    QItemSection,
    QToggle,
    QCheckbox,
  },
  stubs: { AppDialog: true },
}

describe('composer file drop', () => {
  it('shows the selected skill and emits a new selection from the menu', async () => {
    const skills = [
      {
        id: 'skill-rewrite',
        scope: 'official' as const,
        name: '爆款文章改写',
        description: '保留原文事实与核心观点',
        category: '内容创作',
        enabled: true,
        scenes: '文章改写',
        requirements: '忠于原文',
        examples: [],
      },
      {
        id: 'skill-title',
        scope: 'official' as const,
        name: '公众号标题优化',
        description: '生成清晰、有点击动力的标题',
        category: '内容创作',
        enabled: true,
        scenes: '标题优化',
        requirements: '避免标题党',
        examples: [],
      },
    ]
    const wrapper = mount(PromptComposer, {
      attachTo: document.body,
      props: { skills, selectedSkillId: 'skill-rewrite' },
      global,
    })

    expect(wrapper.get('[aria-label="当前技能：爆款文章改写，点击更改"]').text()).toContain(
      '爆款文章改写',
    )
    await wrapper.get('[aria-label="当前技能：爆款文章改写，点击更改"]').trigger('click')
    const titleOption = wrapper
      .findAllComponents(QItem)
      .find((item) => item.text().includes('公众号标题优化'))
    expect(titleOption).toBeTruthy()
    await titleOption!.trigger('click')
    expect(wrapper.emitted('update:selectedSkillId')).toEqual([['skill-title']])

    await wrapper.setProps({ selectedSkillId: 'skill-title' })
    expect(wrapper.get('[aria-label="当前技能：公众号标题优化，点击更改"]').text()).toContain(
      '公众号标题优化',
    )
    wrapper.unmount()
  })

  it('offers stable automatic routing before fixed model choices', () => {
    const wrapper = mount(PromptComposer, {
      props: {
        skills: [],
        models: [
          {
            id: 'model-1',
            name: '测试模型',
            providerName: '测试供应商',
            modelId: 'test-model',
            modelType: 'chat',
            contextWindow: 32_768,
            maxOutputTokens: 4_096,
          },
        ],
      },
      global,
    })
    const options = wrapper.getComponent(QSelect).props('options') as Array<{
      label: string
      value: string | null
      description: string
    }>
    expect(options[0]).toEqual({
      label: '自动（稳定优先）',
      value: null,
      description: '主模型异常时自动切换备用模型',
    })
    expect(options[1]).toMatchObject({
      value: 'model-1',
      description: expect.stringContaining('失败自动切换'),
    })
    wrapper.unmount()
  })

  it('shares file validation, keeps nested drag feedback stable and sends the original files', async () => {
    const wrapper = mount(PromptComposer, {
      props: { skills: [], allowedExtensions: ['txt'], maxFileMb: 1 },
      global,
    })
    const area = wrapper.get('section')
    const file = new File(['reference'], '资料.txt', { type: 'text/plain' })
    const dataTransfer = {
      types: ['Files'],
      files: [
        file,
        new File(['x'], 'bad.exe'),
        new File([new Uint8Array(1024 * 1024 + 1)], 'too-big.txt'),
      ],
      items: [],
      dropEffect: '',
    }
    await area.trigger('dragenter', { dataTransfer })
    await area.trigger('dragenter', { dataTransfer })
    await area.trigger('dragleave', { dataTransfer })
    expect(wrapper.find('[role="status"]').exists()).toBe(true)
    await area.trigger('drop', { dataTransfer })
    expect(wrapper.find('[role="status"]').exists()).toBe(false)
    expect(wrapper.findAll('.q-chip')).toHaveLength(1)
    expect(wrapper.find('.q-chip .prompt-composer__file-status').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('待上传')
    expect(wrapper.find('.q-chip .q-spinner').exists()).toBe(false)
    expect(notify).toHaveBeenCalled()
    await wrapper.get('textarea').setValue('参考资料写文章')
    await wrapper.get('[aria-label="发送消息"]').trigger('click')
    const payload = wrapper.emitted('send')![0]![0] as { attachments: { sourceFile: File }[] }
    expect(payload.attachments[0]!.sourceFile).toBe(file)
    await wrapper.setProps({ disabled: true })
    await area.trigger('drop', { dataTransfer })
    expect(wrapper.findAll('.q-chip')).toHaveLength(0)
    wrapper.unmount()
  })
  it('skips directories while retaining valid sibling files', async () => {
    const wrapper = mount(PromptComposer, { props: { skills: [] }, global })
    const file = new File(['reference'], '保留.txt')
    await wrapper.get('section').trigger('drop', {
      dataTransfer: {
        types: ['Files'],
        files: [],
        items: [
          {
            kind: 'file',
            webkitGetAsEntry: () => ({ isDirectory: true }),
            getAsFile: () => new File([], 'folder'),
          },
          { kind: 'file', webkitGetAsEntry: () => ({ isDirectory: false }), getAsFile: () => file },
        ],
      },
    })
    expect(wrapper.findAll('.q-chip')).toHaveLength(1)
    expect(wrapper.text()).toContain('保留.txt')
    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({ message: expect.stringContaining('文件夹') }),
    )
    wrapper.unmount()
  })
  it('does not intercept ordinary text drops and limits attachments to 20', async () => {
    const wrapper = mount(PromptComposer, { props: { skills: [] }, global })
    const area = wrapper.get('section')
    const event = new Event('drop', { bubbles: true, cancelable: true })
    Object.defineProperty(event, 'dataTransfer', { value: { types: ['text/plain'] } })
    area.element.dispatchEvent(event)
    expect(event.defaultPrevented).toBe(false)
    await area.trigger('drop', {
      dataTransfer: {
        types: ['Files'],
        files: Array.from({ length: 22 }, (_, i) => new File(['x'], `${i}.txt`)),
        items: [],
      },
    })
    expect(wrapper.findAll('.q-chip')).toHaveLength(20)
    wrapper.unmount()
  })
})
