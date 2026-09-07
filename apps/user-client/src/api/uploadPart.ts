/** Upload progress counts transmitted file bytes, not elapsed time. */
export const uploadPart = (
  url: string,
  body: Blob,
  signal: AbortSignal | undefined,
  onProgress: (loaded: number) => void,
): Promise<Response> =>
  new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new DOMException('操作已取消。', 'AbortError'))
    const xhr = new XMLHttpRequest()
    const abort = () => xhr.abort()
    const cleanup = () => signal?.removeEventListener('abort', abort)
    xhr.open('PUT', url)
    xhr.upload.onprogress = (event) => onProgress(Math.min(body.size, event.loaded))
    xhr.onload = () => {
      cleanup()
      const headers = new Headers()
      const etag = xhr.getResponseHeader('ETag')
      if (etag) headers.set('ETag', etag)
      resolve(new Response(null, { status: xhr.status, headers }))
    }
    xhr.onerror = () => {
      cleanup()
      reject(new TypeError('文件上传网络连接失败，请重试。'))
    }
    xhr.onabort = () => {
      cleanup()
      reject(new DOMException('操作已取消。', 'AbortError'))
    }
    signal?.addEventListener('abort', abort, { once: true })
    try {
      xhr.send(body)
    } catch (error) {
      cleanup()
      reject(error)
    }
  })
