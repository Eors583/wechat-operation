import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ConfirmActionDialog from './ConfirmActionDialog.vue'

describe('ConfirmActionDialog', () => {
  it('requires an audit reason before a risky action can be confirmed', async () => {
    const wrapper = mount(ConfirmActionDialog, {
      attachTo: document.body,
      props: {
        modelValue: true,
        title: '冻结重试',
        description: '使用冻结快照重放任务。',
        requireReason: true,
      },
    })

    await new Promise((resolve) => setTimeout(resolve, 80))

    const confirm = document.body.querySelector(
      '.confirm-dialog__actions .el-button:last-child',
    ) as HTMLButtonElement
    expect(confirm).toBeTruthy()
    expect(confirm.disabled).toBe(true)

    const input = document.body.querySelector('textarea, input') as HTMLTextAreaElement
    input.value = '供应商故障已经恢复'
    input.dispatchEvent(new Event('input', { bubbles: true }))
    await wrapper.vm.$nextTick()

    expect(confirm.disabled).toBe(false)
    confirm.click()
    expect(wrapper.emitted('confirm')?.[0]).toEqual(['供应商故障已经恢复'])
    wrapper.unmount()
  })
})
