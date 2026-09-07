import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import PdfPreview from './PdfPreview.vue'

const { destroy, getDocument, render } = vi.hoisted(() => ({
  destroy: vi.fn(),
  getDocument: vi.fn(),
  render: vi.fn(() => ({ promise: Promise.resolve() })),
}))

vi.mock('pdfjs-dist', () => ({
  GlobalWorkerOptions: { workerSrc: '' },
  getDocument,
}))

class ImmediateIntersectionObserver {
  constructor(private readonly callback: IntersectionObserverCallback) {}
  observe(target: Element) {
    this.callback([{ isIntersecting: true, target } as IntersectionObserverEntry], this as never)
  }
  disconnect() {}
  unobserve() {}
}

describe('PdfPreview', () => {
  beforeEach(() => {
    destroy.mockReset()
    render.mockClear()
    getDocument.mockReset()
    getDocument.mockReturnValue({
      destroy,
      promise: Promise.resolve({
        numPages: 2,
        getPage: vi.fn().mockResolvedValue({
          getViewport: ({ scale }: { scale: number }) => ({
            width: 100 * scale,
            height: 200 * scale,
          }),
          render,
        }),
      }),
    })
    vi.stubGlobal('IntersectionObserver', ImmediateIntersectionObserver)
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
      {} as CanvasRenderingContext2D,
    )
  })

  it('renders every PDF page to a lazy canvas', async () => {
    const wrapper = mount(PdfPreview, {
      props: {
        file: {
          type: 'application/pdf',
          arrayBuffer: vi.fn().mockResolvedValue(new ArrayBuffer(4)),
        } as unknown as Blob,
      },
      global: { stubs: { QSpinner: true } },
    })

    await flushPromises()
    await vi.waitFor(() => expect(render).toHaveBeenCalledTimes(2))

    expect(wrapper.findAll('canvas')).toHaveLength(2)
    expect(wrapper.text()).toContain('1 / 2')
    expect(wrapper.text()).toContain('2 / 2')
  })
})
