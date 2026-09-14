import { resolveTemplateVideoSource, uploadTemplateVideo } from '@/api/client'

const mediaUrls = new WeakMap<Document, Set<string>>()

export const releaseTemplateVideos = (document: Document) => {
  for (const player of document.querySelectorAll('video')) {
    player.pause()
    player.removeAttribute('src')
    player.load()
  }
  for (const url of mediaUrls.get(document) ?? []) URL.revokeObjectURL(url)
  mediaUrls.delete(document)
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
  mediaUrls.set(document, new Set())
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
  link.setAttribute('aria-busy', 'true')
  const button = link.querySelector<HTMLButtonElement>('[data-video-play]')
  if (button) button.textContent = '…'
  const player = link.ownerDocument.createElement('video')
  player.controls = true
  player.playsInline = true
  player.poster = link.querySelector('img')?.src ?? ''
  player.style.cssText = 'display:block;width:100%;max-width:100%;min-width:0;aspect-ratio:16/9'
  let objectUrl: string | undefined
  const fail = (message = '视频无法播放，请上传 H.264 编码的 MP4 文件。') => {
    if (!mediaUrls.has(link.ownerDocument)) return
    if (objectUrl) {
      URL.revokeObjectURL(objectUrl)
      mediaUrls.get(link.ownerDocument)?.delete(objectUrl)
      objectUrl = undefined
    }
    if (player.isConnected) player.replaceWith(link)
    link.removeAttribute('aria-busy')
    if (button) button.textContent = '▶'
    showVideoError(link, message)
  }
  player.addEventListener('error', () => fail(), { once: true })
  link.querySelector('[role=status]')?.remove()
  void (async () => {
    try {
      if (!sourceUrl) throw new Error('Missing article source')
      const media = await resolveTemplateVideoSource(sourceUrl, url.searchParams.get('vid')!)
      if (!link.isConnected || !mediaUrls.has(link.ownerDocument)) return
      objectUrl = URL.createObjectURL(media)
      mediaUrls.get(link.ownerDocument)!.add(objectUrl)
      player.src = objectUrl
      link.replaceWith(player)
      void player.play().catch(() => { /* Native controls remain available when autoplay is blocked. */ })
    } catch (error) {
      fail(error instanceof Error ? error.message : '视频加载失败，请重试。')
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
