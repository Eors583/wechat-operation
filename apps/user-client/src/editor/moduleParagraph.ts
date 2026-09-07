import Paragraph from '@tiptap/extension-paragraph'

const modules = new Set(['lead', 'body', 'highlight', 'caption'])

export const moduleParagraph = Paragraph.extend({
  addAttributes() {
    return {
      module: {
        default: null,
        parseHTML: (element) => {
          const value = element.getAttribute('data-module')
          return value && modules.has(value) ? value : null
        },
        renderHTML: ({ module }) =>
          module && modules.has(String(module)) ? { 'data-module': module } : {},
      },
    }
  },
})
