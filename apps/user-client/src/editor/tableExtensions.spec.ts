import { expect, it } from 'vitest'
import { Editor } from '@tiptap/vue-3'
import StarterKit from '@tiptap/starter-kit'
import { tableExtensions } from './tableExtensions'
import { normalizeTiptapJson } from '@/api/client'

it('retains table structure through editor -> API normalization -> editor reload', () => {
  const editor = new Editor({ extensions: [StarterKit, ...tableExtensions] })
  editor.commands.insertTable({ rows: 3, cols: 3, withHeaderRow: true })
  editor.commands.insertContent('单元格文字')
  const original = editor.getJSON()
  const saved = normalizeTiptapJson(original)
  editor.commands.setContent(saved!)
  expect(editor.getJSON()).toEqual(original)
  expect(editor.getHTML()).toContain('<table>')
  expect(editor.getHTML()).toContain('单元格文字')
  expect(editor.view.dom.querySelectorAll('tr')).toHaveLength(3)
  expect(editor.view.dom.querySelectorAll('th')).toHaveLength(3)
  editor.destroy()
})
