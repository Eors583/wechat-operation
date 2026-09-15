import { Extension } from '@tiptap/vue-3'

// A visual line break inside a heading must not create another numbered section.
export const headingLineBreak = Extension.create({
  name: 'headingLineBreak',
  priority: 1000,
  addKeyboardShortcuts() {
    return {
      Enter: () => {
        const { $from, $to } = this.editor.state.selection
        if (
          $from.parent.type.name !== 'heading' ||
          !$from.sameParent($to) ||
          $to.parentOffset === $to.parent.content.size
        )
          return false
        return this.editor.commands.setHardBreak()
      },
    }
  },
})
