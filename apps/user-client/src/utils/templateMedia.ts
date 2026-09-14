import { resolveTemplateVideoSource } from '@/api/client'

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
  }
}

export const playTemplateVideo = (target: Element | null, sourceUrl?: string): boolean => {
  const link = target?.closest<HTMLAnchorElement>('a[href]')
  if (!link) return false
  const url = videoUrl(link)
  if (!url) return false
  if (link.getAttribute('aria-busy') === 'true') return true
  link.setAttribute('aria-busy', 'true')
  const button = link.querySelector<HTMLButtonElement>('[data-video-play]')
  if (button) button.textContent = '…'
  const player = link.ownerDocument.createElement('video')
  player.controls = true
  player.playsInline = true
  player.poster = link.querySelector('img')?.src ?? ''
  player.style.cssText = 'display:block;width:100%;max-width:100%;min-width:0;aspect-ratio:16/9'
  const fail = () => {
    if (player.isConnected) player.replaceWith(link)
    link.removeAttribute('aria-busy')
    if (button) button.textContent = '▶'
    if (!link.querySelector('[role=status]')) {
      const message = link.ownerDocument.createElement('span')
      message.setAttribute('role', 'status')
      message.textContent = '视频加载失败，请点击重试'
      message.style.cssText = 'display:block;text-align:center;font-size:13px'
      link.append(message)
    }
  }
  player.addEventListener('error', fail, { once: true })
  link.querySelector('[role=status]')?.remove()
  void (async () => {
    try {
      if (!sourceUrl) throw new Error('Missing article source')
      const media = new URL(await resolveTemplateVideoSource(sourceUrl, url.searchParams.get('vid')!))
      if (media.protocol !== 'https:' || media.hostname !== 'mpvideo.qpic.cn') throw new Error('Invalid video source')
      if (!link.isConnected) return
      player.src = media.href
      link.replaceWith(player)
      void player.play().catch(() => { /* Native controls remain available when autoplay is blocked. */ })
    } catch {
      fail()
    }
  })()
  return true
}
