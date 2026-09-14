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

export const playTemplateVideo = (target: Element | null): boolean => {
  const link = target?.closest<HTMLAnchorElement>('a[href]')
  if (!link) return false
  const url = videoUrl(link)
  if (!url) return false
  const player = link.ownerDocument.createElement('iframe')
  const source = new URL('https://mp.weixin.qq.com/mp/readtemplate')
  source.search = new URLSearchParams({
    t: 'pages/video_player_tmpl', action: 'mpvideo', auto: '1', vid: url.searchParams.get('vid')!,
  }).toString()
  player.src = source.href
  player.title = '视频播放器'
  player.allow = 'autoplay; fullscreen; encrypted-media'
  player.setAttribute('sandbox', 'allow-scripts allow-same-origin allow-presentation')
  player.referrerPolicy = 'no-referrer'
  player.style.cssText = 'display:block;width:100%;max-width:100%;min-width:0;aspect-ratio:16/9;border:0'
  link.replaceWith(player)
  return true
}
