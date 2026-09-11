import type { Article, LayoutTemplate, ModuleStyle } from '@/api/types'
import { createDefaultStyles } from '@/api/styleDefaults'

export function defaultArticleTemplate(article: Article, templates: LayoutTemplate[]) {
  if (article.layoutTemplate) return article.layoutTemplate
  const usable = templates.filter(
    (t) =>
      t.enabled &&
      t.status === 'ready' &&
      (!article.accountId || t.accountId === null || t.accountId === article.accountId),
  )
  return (
    usable.find((t) => t.id === article.templateId) ??
    usable.find((t) => Boolean(article.accountId) && t.accountId === article.accountId) ??
    usable.find((t) => t.accountId === null) ??
    usable[0] ??
    null
  )
}

export function articleDownloadFile(
  title: string,
  versionNo: number,
  html: string,
  titleStyle: ModuleStyle = createDefaultStyles().title,
): File {
  const parsed = new DOMParser().parseFromString(html, 'text/html')
  if (!parsed.body.textContent?.trim()) throw new Error('排版正文为空，未下载。')
  const heading = parsed.body.querySelector('h1')
  const actualTitle = heading?.textContent?.trim() || title
  if (!heading) {
    const element = parsed.createElement('h1')
    element.textContent = actualTitle
    Object.assign(element.style, {
      color: titleStyle.color,
      background: titleStyle.background,
      fontSize: `${titleStyle.fontSize}px`,
      fontWeight: titleStyle.fontWeight,
      textAlign: titleStyle.align,
      lineHeight: String(titleStyle.lineHeight),
      padding: `${titleStyle.padding}px`,
      marginBottom: `${titleStyle.spacing}px`,
    })
    parsed.body.prepend(element)
  }
  parsed.title = actualTitle
  const filename = Array.from(actualTitle, (character) =>
    character.charCodeAt(0) < 32 ? '_' : character,
  )
    .join('')
    .replace(/[\\/:*?"<>|]/g, '_')
    .slice(0, 100)
  return new File(
    [
      `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src https: data:;">
${parsed.head.innerHTML}<style>body{max-width:800px;margin:32px auto;padding:0 20px;color:#222;background:#fff;overflow-wrap:anywhere}img,table{max-width:100%}table{width:100%;table-layout:fixed}h1{font-size:26px;line-height:1.5}</style>
</head><body>${parsed.body.innerHTML}</body></html>`,
    ],
    `${filename || '文章'}-第${versionNo}版.html`,
    { type: 'text/html;charset=utf-8' },
  )
}
