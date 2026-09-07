const sensitiveQueryName =
  /^(?:.*token|auth|authorization|api_?key|key|password|passwd|secret|credential|signature|sig)$/i
const bareDomainUrl = /^(?:[a-z0-9-]+\.)+[a-z]{2,}(?::\d{2,5})?(?:[/?#].*)?$/i

export const safeHttpUrl = (
  value: unknown,
  options: { httpsOnly?: boolean; maxLength?: number; rejectSensitiveQuery?: boolean } = {},
) => {
  if (typeof value !== 'string') return ''
  const source = value.trim()
  if (!source || source.length > (options.maxLength ?? 2000)) return ''
  try {
    const url = new URL(bareDomainUrl.test(source) ? `https://${source}` : source)
    const protocolAllowed =
      url.protocol === 'https:' || (!options.httpsOnly && url.protocol === 'http:')
    if (!protocolAllowed || !url.hostname || url.username || url.password) return ''
    if (
      options.rejectSensitiveQuery &&
      (url.hash || [...url.searchParams.keys()].some((key) => sensitiveQueryName.test(key)))
    )
      return ''
    return url.href
  } catch {
    return ''
  }
}

export const linkAttachmentLabel = (urlValue: string) => {
  const url = new URL(urlValue)
  let path = url.pathname
  try {
    path = decodeURIComponent(path)
  } catch {
    /* Keep the safely parsed encoded pathname. */
  }
  path = path === '/' ? '' : path.replace(/\s+/g, ' ')
  return `${url.hostname}${path}`.slice(0, 255)
}
