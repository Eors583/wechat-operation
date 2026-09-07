import Table from '@tiptap/extension-table'
import TableRow from '@tiptap/extension-table-row'
import TableCell from '@tiptap/extension-table-cell'
import TableHeader from '@tiptap/extension-table-header'

// Both editing surfaces use exactly the same table schema.
const ArticleTable = Table.extend({
  renderHTML() {
    return [
      'div',
      { class: 'tableWrapper', tabindex: '0', role: 'region', 'aria-label': '文章表格' },
      ['table', {}, ['tbody', 0]],
    ]
  },
})
export const tableExtensions = [
  ArticleTable.configure({ resizable: false }),
  TableRow,
  TableCell,
  TableHeader,
]
