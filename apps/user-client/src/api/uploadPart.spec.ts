import { afterEach, expect, it, vi } from 'vitest'
import { uploadPart } from './uploadPart'

afterEach(() => vi.unstubAllGlobals())
it('reports byte events and preserves ETag', async () => {
  const progress = vi.fn()
  class Xhr {
    upload = { onprogress: (_event: { loaded: number }) => {} }
    status = 200
    onload = () => {}
    open = vi.fn()
    getResponseHeader = () => 'etag'
    send() {
      this.upload.onprogress({ loaded: 2 })
      this.onload()
    }
  }
  vi.stubGlobal('XMLHttpRequest', Xhr)
  const response = await uploadPart('/part', new Blob(['1234']), undefined, progress)
  expect(progress).toHaveBeenCalledExactlyOnceWith(2)
  expect(response.headers.get('ETag')).toBe('etag')
})
it('aborts in-flight uploads and cleans up signal listeners', async () => {
  class Xhr {
    upload = {}
    onabort = () => {}
    open() {}
    send() {}
    abort() {
      this.onabort()
    }
  }
  vi.stubGlobal('XMLHttpRequest', Xhr)
  const controller = new AbortController()
  const cleanup = vi.spyOn(controller.signal, 'removeEventListener')
  const pending = uploadPart('/part', new Blob(['1234']), controller.signal, vi.fn())
  controller.abort()
  await expect(pending).rejects.toMatchObject({ name: 'AbortError' })
  expect(cleanup).toHaveBeenCalled()
})
