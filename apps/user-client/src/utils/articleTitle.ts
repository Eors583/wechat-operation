import type { JSONContent } from '@tiptap/vue-3'

export const separateArticleTitle = (content: JSONContent, fallbackTitle: string) => {
  const first = content.content?.[0]
  const inline = first?.content ?? []
  const title = inline
    .map((node) => node.text ?? '')
    .join('')
    .trim()
  const hasTitle =
    first?.type === 'heading' &&
    first.attrs?.level === 1 &&
    inline.every((node) => node.type === 'text') &&
    title.length > 0

  return {
    title: hasTitle ? title : fallbackTitle,
    content: hasTitle ? { ...content, content: content.content!.slice(1) } : content,
    separated: hasTitle,
  }
}
