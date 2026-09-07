const escapeHtml = (value: string) =>
  value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')

const inlineMarkdown = (value: string) =>
  escapeHtml(value)
    .replace(
      /\[([^\]\n]+)]\((https?:\/\/[^\s)]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>',
    )
    .replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
    .replace(/__([^_\n]+)__/g, '<strong>$1</strong>')
    .replace(/`([^`\n]+)`/g, '<code>$1</code>')

const paragraphHtml = (lines: string[]) => `<p>${lines.map(inlineMarkdown).join('<br>')}</p>`

const splitTableRow = (line: string) => {
  const trimmed = line.trim().replace(/^\|/, '').replace(/\|$/, '')
  const cells: string[] = []
  let cell = ''
  let inlineCode = false
  for (let index = 0; index < trimmed.length; index += 1) {
    const character = trimmed[index]
    const next = trimmed[index + 1]
    if (character === '\\' && next === '|') {
      cell += '|'
      index += 1
    } else if (character === '`') {
      inlineCode = !inlineCode
      cell += character
    } else if (character === '|' && !inlineCode) {
      cells.push(cell.trim())
      cell = ''
    } else {
      cell += character
    }
  }
  cells.push(cell.trim())
  return cells
}

const tableAlignments = (line: string) => {
  const cells = splitTableRow(line)
  if (!cells.length || cells.some((cell) => !/^:?-{3,}:?$/.test(cell.replace(/\s/g, ''))))
    return null
  return cells.map((cell) => {
    const compact = cell.replace(/\s/g, '')
    if (compact.startsWith(':') && compact.endsWith(':')) return 'center'
    if (compact.endsWith(':')) return 'right'
    return 'left'
  })
}

const tableCellClass = (alignment: string) =>
  alignment === 'left' ? '' : ` class="markdown-table__cell--${alignment}"`

const tableHtml = (header: string[], rows: string[][], alignments: string[]) => {
  const headerHtml = header
    .map(
      (cell, index) =>
        `<th scope="col"${tableCellClass(alignments[index] ?? 'left')}>${inlineMarkdown(cell)}</th>`,
    )
    .join('')
  const bodyHtml = rows
    .map(
      (row) =>
        `<tr>${header
          .map(
            (_, index) =>
              `<td${tableCellClass(alignments[index] ?? 'left')}>${inlineMarkdown(row[index] ?? '')}</td>`,
          )
          .join('')}</tr>`,
    )
    .join('')
  return (
    '<div class="markdown-table-wrap" role="region" aria-label="表格" tabindex="0">' +
    `<table><thead><tr>${headerHtml}</tr></thead><tbody>${bodyHtml}</tbody></table></div>`
  )
}

export const renderSafeMarkdown = (source: string): string => {
  const blocks: string[] = []
  let paragraph: string[] = []
  let list: string[] = []
  let listTag: 'ul' | 'ol' = 'ul'
  let quote: string[] = []
  let code: string[] | null = null

  const flushParagraph = () => {
    if (!paragraph.length) return
    blocks.push(paragraphHtml(paragraph))
    paragraph = []
  }
  const flushList = () => {
    if (!list.length) return
    blocks.push(
      `<${listTag}>${list.map((item) => `<li>${inlineMarkdown(item)}</li>`).join('')}</${listTag}>`,
    )
    list = []
  }
  const flushQuote = () => {
    if (!quote.length) return
    blocks.push(`<blockquote>${quote.map(inlineMarkdown).join('<br>')}</blockquote>`)
    quote = []
  }
  const flushTextBlocks = () => {
    flushParagraph()
    flushList()
    flushQuote()
  }

  const lines = source.replace(/\r\n/g, '\n').split('\n')
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index] ?? ''
    if (line.trim().startsWith('```')) {
      if (code) {
        blocks.push(`<pre><code>${escapeHtml(code.join('\n'))}</code></pre>`)
        code = null
      } else {
        flushTextBlocks()
        code = []
      }
      continue
    }
    if (code) {
      code.push(line)
      continue
    }
    if (!line.trim()) {
      flushTextBlocks()
      continue
    }
    const header = line.includes('|') ? splitTableRow(line) : []
    const alignments = index + 1 < lines.length ? tableAlignments(lines[index + 1] ?? '') : null
    if (header.length && alignments?.length === header.length) {
      flushTextBlocks()
      const rows: string[][] = []
      index += 2
      while (
        index < lines.length &&
        (lines[index] ?? '').trim() &&
        (lines[index] ?? '').includes('|')
      ) {
        rows.push(splitTableRow(lines[index] ?? ''))
        index += 1
      }
      index -= 1
      blocks.push(tableHtml(header, rows, alignments))
      continue
    }
    const headingMatch = line.match(/^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$/)
    if (headingMatch) {
      flushTextBlocks()
      const level = headingMatch[1]?.length ?? 1
      blocks.push(`<h${level}>${inlineMarkdown(headingMatch[2] ?? '')}</h${level}>`)
      continue
    }
    if (/^\s{0,3}([-*_])(?:\s*\1){2,}\s*$/.test(line)) {
      flushTextBlocks()
      blocks.push('<hr>')
      continue
    }
    const quoteMatch = line.match(/^\s{0,3}>\s?(.*)$/)
    if (quoteMatch) {
      flushParagraph()
      flushList()
      quote.push(quoteMatch[1] ?? '')
      continue
    }
    const unorderedMatch = line.match(/^\s*[-*+]\s+(.+)$/)
    const orderedMatch = line.match(/^\s*\d+[.)]\s+(.+)$/)
    const listMatch = unorderedMatch ?? orderedMatch
    if (listMatch) {
      flushParagraph()
      flushQuote()
      const nextTag = orderedMatch ? 'ol' : 'ul'
      if (list.length && listTag !== nextTag) flushList()
      listTag = nextTag
      list.push(listMatch[1] ?? '')
      continue
    }
    flushList()
    flushQuote()
    paragraph.push(line)
  }

  if (code) blocks.push(`<pre><code>${escapeHtml(code.join('\n'))}</code></pre>`)
  flushTextBlocks()
  return blocks.join('')
}
