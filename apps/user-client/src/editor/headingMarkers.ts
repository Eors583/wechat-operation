import { Plugin, PluginKey } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'
import type { LayoutComponentGroup } from '@/api/types'

export const headingMarkerKey = new PluginKey('templateHeadingMarkers')
export type HeadingMarker = { group: LayoutComponentGroup; url?: string; loading: boolean }

export const headingMarkers = (getMarkers: () => HeadingMarker[]) =>
  new Plugin({
    key: headingMarkerKey,
    props: {
      decorations(state) {
        const markers = getMarkers()
        if (!markers.length) return DecorationSet.empty
        const fallback = markers.every(({ group }) => group.fallbackRender === 'text_index')
        const decorations: Decoration[] = []
        let sequence = 0
        state.doc.forEach((node, position) => {
          if (node.type.name !== 'heading' || node.attrs.level !== 2) return
          sequence += 1
          const number = sequence
          const marker = markers.find(({ group }) => group.sequence === number)
          decorations.push(
            Decoration.widget(
              position,
              () => {
                const wrapper = document.createElement('div')
                wrapper.contentEditable = 'false'
                wrapper.className = 'article-heading-image'
                const style = marker?.group.containerStyle
                wrapper.style.textAlign = style?.align ?? 'left'
                wrapper.style.marginTop = `${style?.marginTop ?? 0}px`
                wrapper.style.marginBottom = `${style?.marginBottom ?? 8}px`
                if (marker?.url) {
                  const image = document.createElement('img')
                  image.src = marker.url
                  image.alt = `第 ${number} 章序号`
                  image.style.width = `${marker.group.imageWidth}px`
                  image.style.maxWidth = '100%'
                  image.style.height = 'auto'
                  wrapper.append(image)
                } else {
                  wrapper.classList.add('article-heading-image--text')
                  wrapper.style.removeProperty('text-align')
                  wrapper.textContent = marker?.loading
                    ? `第 ${number} 章图片加载中…`
                    : fallback
                      ? String(number).padStart(2, '0')
                      : `第 ${number} 章序号图片不可用`
                }
                return wrapper
              },
              { side: -1, key: `${number}:${marker?.url ?? ''}:${marker?.loading}:${fallback}` },
            ),
          )
        })
        return DecorationSet.create(state.doc, decorations)
      },
    },
  })
