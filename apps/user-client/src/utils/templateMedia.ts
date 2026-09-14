export const openTemplateVideo = (target: Element | null): boolean => {
  const link = target?.closest<HTMLAnchorElement>('a[href]')
  if (!link) return false
  const url = new URL(link.href)
  if (
    url.origin !== 'https://mp.weixin.qq.com' ||
    url.pathname !== '/mp/readtemplate' ||
    url.searchParams.get('t') !== 'pages/video_player_tmpl'
  ) return false
  window.open(url.href, '_blank', 'noopener,noreferrer')
  return true
}
