import { describe, expect, it } from 'vitest'
import { normalizeTiptapJson } from './client'

const canonicalTypes = new Set([
  'doc',
  'paragraph',
  'text',
  'heading',
  'bulletList',
  'orderedList',
  'listItem',
  'blockquote',
  'hardBreak',
  'horizontalRule',
  'codeBlock',
  'image',
])

describe('canonical Tiptap boundary', () => {
  it('degrades legacy module nodes and removes unsupported marks before save', () => {
    const result = normalizeTiptapJson({
      type: 'doc',
      content: [
        { type: 'lead', content: [{ type: 'text', text: '导语' }] },
        {
          type: 'highlight',
          content: [{ type: 'text', text: '重点', marks: [{ type: 'sparkle' }] }],
        },
        {
          type: 'caption',
          content: [
            {
              type: 'text',
              text: '说明',
              marks: [{ type: 'link', attrs: { href: 'javascript:alert(1)' } }],
            },
          ],
        },
        {
          type: 'paragraph',
          content: [
            {
              type: 'text',
              text: '凭据链接',
              marks: [{ type: 'link', attrs: { href: 'https://user:pass@example.com/private' } }],
            },
          ],
        },
      ],
    })

    const nodes: Record<string, unknown>[] = []
    const visit = (node: Record<string, unknown>) => {
      nodes.push(node)
      if (Array.isArray(node.content))
        node.content.forEach((child) => visit(child as Record<string, unknown>))
    }
    visit(result!)

    const paragraphs = result!.content as Record<string, unknown>[]
    expect(paragraphs.map((node) => node.type)).toEqual([
      'paragraph',
      'paragraph',
      'paragraph',
      'paragraph',
    ])
    expect(
      paragraphs.slice(0, 3).map((node) => (node.attrs as Record<string, unknown>).module),
    ).toEqual(['lead', 'highlight', 'caption'])
    expect(nodes.every((node) => canonicalTypes.has(String(node.type)))).toBe(true)
    expect(nodes.filter((node) => node.type === 'text').every((node) => !('marks' in node))).toBe(
      true,
    )
  })

  it('keeps only type-specific attributes and rejects unsafe image sources', () => {
    const result = normalizeTiptapJson({
      type: 'doc',
      content: [
        { type: 'orderedList', attrs: { start: 3, type: null, unexpected: true }, content: [] },
        { type: 'codeBlock', attrs: { language: 'typescript', extra: 'nope' }, content: [] },
        { type: 'image', attrs: { src: 'data:image/png;base64,unsafe', alt: '图' } },
        { type: 'image', attrs: { assetId: 'asset_without_safe_src', alt: '图' } },
        { type: 'image', attrs: { src: 'https://example.com/image.png', alt: '图', width: 100 } },
        { type: 'image', attrs: { src: 'https://user:pass@example.com/image.png', alt: '凭据图' } },
      ],
    })!
    const nodes = result.content as Record<string, unknown>[]

    expect(nodes[0]).toEqual({ type: 'paragraph', content: [] })
    expect(nodes[1]).toMatchObject({ type: 'codeBlock', attrs: { language: 'typescript' } })
    expect(nodes[2]).toEqual({ type: 'paragraph', content: [] })
    expect(nodes[3]).toEqual({ type: 'paragraph', content: [] })
    expect(nodes[4]).toMatchObject({
      type: 'image',
      attrs: { src: 'https://example.com/image.png', alt: '图' },
    })
    expect(nodes[4]!.attrs).not.toHaveProperty('width')
    expect(nodes[5]).toEqual({ type: 'paragraph', content: [] })
  })

  it('repairs legacy nesting into the server ProseMirror hierarchy', () => {
    const result = normalizeTiptapJson({
      type: 'doc',
      content: [
        {
          type: 'paragraph',
          content: [
            { type: 'mystery', text: '段落内未知节点' },
            { type: 'hardBreak', content: [{ type: 'text', text: '不得保留' }] },
          ],
        },
        {
          type: 'bulletList',
          content: [{ type: 'paragraph', content: [{ type: 'text', text: '列表项' }] }],
        },
        { type: 'blockquote', content: [] },
        { type: 'text', text: '根级文本' },
      ],
    })!
    const blocks = result.content as Record<string, unknown>[]
    const listItems = blocks[1]!.content as Record<string, unknown>[]
    const itemBlocks = listItems[0]!.content as Record<string, unknown>[]

    expect(blocks.map((node) => node.type)).toEqual([
      'paragraph',
      'bulletList',
      'paragraph',
      'paragraph',
    ])
    expect((blocks[0]!.content as Record<string, unknown>[])[0]).toEqual({
      type: 'text',
      text: '段落内未知节点',
    })
    expect((blocks[0]!.content as Record<string, unknown>[])[1]).toEqual({ type: 'hardBreak' })
    expect(listItems[0]!.type).toBe('listItem')
    expect(itemBlocks[0]!.type).toBe('paragraph')
    expect((blocks[3]!.content as Record<string, unknown>[])[0]).toEqual({
      type: 'text',
      text: '根级文本',
    })
  })
})
