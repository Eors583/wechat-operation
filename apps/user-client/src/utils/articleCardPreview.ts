import type { Article } from '@/api/types'

export function articleCardPreview(article: Pick<Article, 'title' | 'contentHtml'>) {
  // Parse without inserting external HTML into the live page. Vue renders text only.
  const document = new DOMParser().parseFromString(article.contentHtml, 'text/html')
  document.querySelectorAll('script,style').forEach((node) => node.remove())
  const heading = document.body.firstElementChild
  const title =
    heading?.tagName === 'H1' ? heading.textContent?.trim() || article.title : article.title
  if (heading?.tagName === 'H1') heading.remove()
  const text =
    Array.from(document.body.children)
      .map((node) => node.textContent?.trim() ?? '')
      .filter(Boolean)
      .slice(0, 3)
      .join('\n') ||
    document.body.textContent?.trim() ||
    ''
  return { title, excerpt: text.length > 320 ? `${text.slice(0, 320)}…` : text }
}
