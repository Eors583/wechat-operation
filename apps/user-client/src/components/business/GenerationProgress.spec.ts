import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import GenerationProgress from './GenerationProgress.vue'

describe('real generation progress', () => {
  afterEach(() => vi.useRealTimers())

  it('shows actual stage transitions, bounded history, and elapsed time without inventing work', async () => {
    vi.useFakeTimers()
    const wrapper = mount(GenerationProgress, {
      props: { stage: 'reading', history: ['reading'], modelName: 'Kimi K2.6' },
      global: { stubs: { QSpinnerDots: true } },
    })
    await wrapper.setProps({ stage: 'planning', history: ['reading', 'planning'] })
    await wrapper.setProps({ stage: 'generating', history: ['reading', 'planning', 'generating'] })
    expect(wrapper.get('[role="status"]').text()).toContain('正在生成正文内容')
    expect(wrapper.findAll('li > span:last-child').map((item) => item.text())).toEqual([
      '整理参考资料与创作上下文',
      '规划文章结构与引用安排',
    ])
    await vi.advanceTimersByTimeAsync(31000)
    expect(wrapper.text()).toContain('已等待 31 秒')
    expect(wrapper.text()).toContain('仍在等待模型返回正文')
    expect(wrapper.get('[role="status"]').text()).toContain('正在生成正文内容')
    await wrapper.setProps({ stage: 'reconnecting' })
    expect(wrapper.get('[role="status"]').text()).toContain('恢复进度同步')
    await wrapper.setProps({ stage: 'generating' })
    expect(wrapper.findAll('li')).toHaveLength(2)
    await wrapper.setProps({ stage: 'checking' })
    await wrapper.setProps({
      stage: 'saving',
      history: ['reading', 'planning', 'generating', 'checking', 'saving'],
    })
    expect(wrapper.findAll('li')).toHaveLength(3)
    expect(wrapper.get('[role="status"]').text()).toContain('正在保存文章版本')
    wrapper.unmount()
    expect(vi.getTimerCount()).toBe(0)
  })
})
