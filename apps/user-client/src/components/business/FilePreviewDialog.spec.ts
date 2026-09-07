import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import FilePreviewDialog from './FilePreviewDialog.vue'

const { downloadDocument, openViewer } = vi.hoisted(() => ({
  downloadDocument: vi.fn(),
  openViewer: vi.fn(),
}))

vi.mock('@/api/client', () => ({ api: { downloadDocument } }))
vi.mock('@/platform', () => ({ platform: { downloadFile: vi.fn() } }))
vi.mock('@aiden0z/pptx-renderer/browser', () => ({
  RECOMMENDED_ZIP_LIMITS: {},
  PptxViewer: { open: openViewer },
}))

describe('FilePreviewDialog', () => {
  beforeEach(() => {
    downloadDocument.mockReset()
    openViewer.mockReset()
    downloadDocument.mockResolvedValue({
      type: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
      arrayBuffer: vi.fn().mockResolvedValue(new ArrayBuffer(4)),
    } as unknown as Blob)
    openViewer.mockImplementation(async (_file, container: HTMLElement) => {
      const slide = document.createElement('div')
      slide.textContent = 'rendered slide'
      container.append(slide)
      return { destroy: vi.fn() }
    })
  })

  it('renders the owned PPTX instead of exposing extracted text', async () => {
    const wrapper = mount(FilePreviewDialog, {
      props: {
        modelValue: true,
        item: {
          id: 'library-item',
          type: 'reference',
          title: '战略规划.pptx',
          projectId: null,
          taskId: null,
          status: 'ready',
          updatedAt: '2026-09-07T00:00:00Z',
          summary: '内部摘要',
          sourceId: 'document-id',
          extractedText: '不应展示的内部解析文字',
          pageCount: 110,
        },
      },
      global: {
        stubs: {
          AppDialog: {
            props: ['modelValue', 'title'],
            template: '<div><slot /><footer><slot name="actions" /></footer></div>',
          },
          AppButton: { props: ['label'], template: '<button>{{ label }}</button>' },
          QIcon: true,
          QSpinner: true,
        },
      },
    })

    await flushPromises()

    expect(downloadDocument).toHaveBeenCalledWith('document-id')
    await vi.waitFor(() => expect(openViewer).toHaveBeenCalledOnce())
    expect(wrapper.text()).toContain('原文件预览')
    expect(wrapper.text()).toContain('rendered slide')
    expect(wrapper.text()).not.toContain('解析文字')
    expect(wrapper.text()).not.toContain('不应展示的内部解析文字')
  })

  it('shows an owned PDF in the embedded file viewer', async () => {
    downloadDocument.mockResolvedValue(new Blob(['pdf bytes'], { type: 'application/pdf' }))
    const wrapper = mount(FilePreviewDialog, {
      props: {
        modelValue: true,
        item: {
          id: 'library-item',
          type: 'reference',
          title: '战略管理.pdf',
          projectId: null,
          taskId: null,
          status: 'ready',
          updatedAt: '2026-09-07T00:00:00Z',
          summary: '内部摘要',
          sourceId: 'pdf-document-id',
          extractedText: '不应展示的 PDF 解析文字',
          pageCount: 30,
        },
      },
      global: {
        stubs: {
          AppDialog: {
            props: ['modelValue', 'title'],
            template: '<div><slot /><footer><slot name="actions" /></footer></div>',
          },
          AppButton: { props: ['label'], template: '<button>{{ label }}</button>' },
          PdfPreview: { template: '<div data-test="pdf-preview">rendered pdf</div>' },
          QIcon: true,
          QSpinner: true,
        },
      },
    })

    await flushPromises()

    expect(wrapper.get('[data-test="pdf-preview"]').text()).toBe('rendered pdf')
    expect(wrapper.text()).toContain('原文件预览')
    expect(wrapper.text()).not.toContain('此格式暂不支持')
    expect(wrapper.text()).not.toContain('不应展示的 PDF 解析文字')
  })
})
