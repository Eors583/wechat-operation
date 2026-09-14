import { resolveTemplateVideoSource, uploadTemplateVideo } from '@/api/client'

const mediaCleanups = new WeakMap<Document, Set<() => void>>()

export const releaseTemplateVideos = (document: Document) => {
  for (const cleanup of mediaCleanups.get(document) ?? []) cleanup()
  mediaCleanups.delete(document)
}

const videoUrl = (link: HTMLAnchorElement): URL | null => {
  const url = new URL(link.href)
  if (
    url.origin !== 'https://mp.weixin.qq.com' ||
    url.pathname !== '/mp/readtemplate' ||
    url.searchParams.get('t') !== 'pages/video_player_tmpl' ||
    !/^wxv_[0-9]+$/.test(url.searchParams.get('vid') ?? '')
  ) return null
  return url
}

export const prepareTemplateVideos = (document: Document) => {
  mediaCleanups.set(document, new Set())
  for (const link of document.querySelectorAll<HTMLAnchorElement>('a[href]')) {
    if (!videoUrl(link) || !link.querySelector('img')) continue
    link.querySelectorAll('span').forEach((caption) => caption.remove())
    link.style.position = 'relative'
    link.style.display = 'block'
    const button = document.createElement('button')
    button.type = 'button'
    button.dataset.videoPlay = 'true'
    button.setAttribute('aria-label', '播放视频')
    button.textContent = '▶'
    button.style.cssText = 'position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);' +
      'width:48px;height:48px;border-radius:50%;border:1px solid currentColor;' +
      'background:var(--app-bg-surface,Canvas);color:var(--app-text-primary,CanvasText);' +
      'font-size:22px;cursor:pointer;padding:0;line-height:1'
    link.append(button)
    const upload = document.createElement('button')
    upload.type = 'button'
    upload.dataset.videoUpload = 'true'
    upload.textContent = '上传视频'
    upload.style.cssText = 'display:block;margin:8px auto;max-width:100%;cursor:pointer;' +
      'color:var(--app-text-primary,CanvasText);background:var(--app-bg-surface,Canvas);' +
      'border:1px solid currentColor;border-radius:4px;padding:4px 12px'
    link.append(upload)
  }
}

export const playTemplateVideo = (target: Element | null, sourceUrl?: string): boolean => {
  const link = target?.closest<HTMLAnchorElement>('a[href]')
  if (!link) return false
  const url = videoUrl(link)
  if (!url) return false
  if (link.getAttribute('aria-busy') === 'true') return true
  if (target?.closest('[data-video-upload]')) {
    const input = link.ownerDocument.createElement('input')
    input.type = 'file'
    input.accept = 'video/mp4,.mp4'
    input.addEventListener('change', () => {
      const file = input.files?.[0]
      if (!file) return
      link.setAttribute('aria-busy', 'true')
      const upload = link.querySelector<HTMLButtonElement>('[data-video-upload]')!
      upload.disabled = true
      void uploadTemplateVideo(url.searchParams.get('vid')!, file, (loaded) => {
        upload.textContent = `上传中 ${Math.round(loaded / file.size * 100)}%`
      }).then(() => {
        link.querySelector('[role=status]')?.remove()
        upload.textContent = '已保存到资源池'
      }).catch((error: unknown) => {
        upload.textContent = '重新上传'
        showVideoError(link, error instanceof Error ? error.message : '视频上传失败，请重试。')
      }).finally(() => {
        upload.disabled = false
        link.removeAttribute('aria-busy')
      })
    }, { once: true })
    input.click()
    return true
  }
  const cleanups = mediaCleanups.get(link.ownerDocument)
  if (!cleanups) return true
  link.setAttribute('aria-busy', 'true')
  const button = link.querySelector<HTMLButtonElement>('[data-video-play]')
  if (button) button.textContent = '…'
  showVideoError(link, '视频加载中…')
  const controller = new AbortController()
  const wrapper = link.ownerDocument.createElement('div')
  wrapper.dataset.templateVideo = 'true'
  wrapper.style.cssText = 'display:grid;min-width:0;max-width:100%'
  const player = link.ownerDocument.createElement('video')
  player.controls = true
  player.playsInline = true
  player.preload = 'auto'
  player.poster = link.querySelector('img')?.src ?? ''
  const cover = link.querySelector('img')?.getBoundingClientRect()
  const ratio = cover?.width && cover.height ? cover.width / cover.height : 16 / 9
  player.style.cssText = `grid-area:1/1;display:block;width:100%;max-width:100%;min-width:0;` +
    `aspect-ratio:${ratio};object-fit:contain;visibility:hidden`
  let objectUrl: string | undefined
  let disposed = false
  let timer: ReturnType<typeof setTimeout> | undefined
  const clearDeadline = () => clearTimeout(timer)
  const cleanup = () => {
    if (disposed) return
    disposed = true
    clearDeadline()
    controller.abort()
    player.pause()
    player.removeAttribute('src')
    player.load()
    player.remove()
    if (objectUrl) URL.revokeObjectURL(objectUrl)
    cleanups.delete(cleanup)
  }
  cleanups.add(cleanup)
  const fail = (message = '视频无法播放，请上传 H.264 编码的 MP4 文件。') => {
    if (disposed) return
    cleanup()
    if (wrapper.isConnected) wrapper.replaceWith(link)
    link.style.removeProperty('grid-area')
    link.style.removeProperty('z-index')
    link.removeAttribute('aria-busy')
    if (button) button.textContent = '▶'
    showVideoError(link, message)
  }
  const decodingDeadline = () => {
    clearDeadline()
    timer = setTimeout(() => fail('视频加载超时，请点击重试。'), 15000)
  }
  player.addEventListener('error', () => fail(), { signal: controller.signal })
  player.addEventListener('playing', clearDeadline, { signal: controller.signal })
  player.addEventListener('seeked', clearDeadline, { signal: controller.signal })
  player.addEventListener('seeking', decodingDeadline, { signal: controller.signal })
  player.addEventListener('waiting', decodingDeadline, { signal: controller.signal })
  player.addEventListener('pause', clearDeadline, { signal: controller.signal })
  // Metadata alone does not mean that a video frame can be decoded.
  player.addEventListener('loadeddata', () => {
    if (disposed || player.readyState < 2) return
    clearDeadline()
    if (player.videoWidth && player.videoHeight) {
      player.style.aspectRatio = `${player.videoWidth} / ${player.videoHeight}`
    }
    player.style.visibility = 'visible'
    link.remove()
    void player.play().catch((error: unknown) => {
      if (error && typeof error === 'object' && 'name' in error && error.name === 'NotAllowedError') {
        // Leave the poster and native controls visible for a second user click.
        clearDeadline()
      } else if (!disposed) {
        fail('视频启动失败，请点击重试。')
      }
    })
  }, { once: true, signal: controller.signal })
  timer = setTimeout(() => fail('视频加载超时，请点击重试。'), 120000)
  void (async () => {
    try {
      if (!sourceUrl) throw new Error('缺少原文链接，请重新选择排版模板。')
      const media = await resolveTemplateVideoSource(
        sourceUrl, url.searchParams.get('vid')!, controller.signal,
      )
      if (disposed || !link.isConnected) return
      objectUrl = URL.createObjectURL(media)
      link.replaceWith(wrapper)
      link.style.gridArea = '1 / 1'
      link.style.zIndex = '1'
      wrapper.append(player, link)
      decodingDeadline()
      player.src = objectUrl
      player.load()
    } catch (error) {
      if (!disposed) fail(error instanceof Error ? error.message : '视频加载失败，请重试。')
    }
  })()
  return true
}

const showVideoError = (link: HTMLAnchorElement, text: string) => {
  link.querySelector('[role=status]')?.remove()
  const message = link.ownerDocument.createElement('span')
  message.setAttribute('role', 'status')
  message.textContent = text
  message.style.cssText = 'display:block;text-align:center;font-size:13px;white-space:normal;overflow-wrap:anywhere'
  link.append(message)
}
