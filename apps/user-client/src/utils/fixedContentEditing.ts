import { api, uploadTemplateVideo } from '@/api/client'
import type { LayoutContentBlock } from '@/api/types'

type Options = {
  isolateVideoUploads?: boolean
  blocks: () => LayoutContentBlock[]
  enabled: (id: string) => boolean
  save: (block: LayoutContentBlock) => Promise<void> | void
  error: (message: string) => void
}

// Mount controls outside saved markup. Paths always refer to the original block DOM.
export const mountFixedContentEditing = (document: Document, options: Options) => {
  const controller = new AbortController()
  const { signal } = controller
  const urls: string[] = []
  let busy = false
  const style = document.createElement('style')
  style.textContent = `[data-inline-text]{cursor:text!important;user-select:text!important;-webkit-user-select:text!important;outline:none!important}[data-inline-text] *{user-select:text!important;-webkit-user-select:text!important}.inline-upload{position:fixed;max-width:calc(100vw - 16px);padding:6px 10px;border:1px solid currentColor;border-radius:4px;background:Canvas;color:CanvasText;font:14px system-ui;cursor:pointer;z-index:1}.inline-upload[hidden]{display:none}`
  document.head.append(style)
  const upload = document.createElement('button')
  upload.type = 'button'
  upload.className = 'inline-upload'
  upload.textContent = '上传替换'
  upload.hidden = true
  document.body.append(upload)
  let mediaAction: (() => void) | undefined
  const fail = (error: unknown) =>
    options.error(error instanceof Error ? error.message : '修改未保存，请重试。')
  for (const root of document.querySelectorAll<HTMLElement>('[data-fixed-block-id]')) {
    const id = root.dataset.fixedBlockId!
    const block = options.blocks().find((item) => item.id === id)
    if (!block) continue
    const original = new DOMParser().parseFromString(block.html, 'text/html').body
    const originals = Array.from(original.querySelectorAll<HTMLElement>('*'))
    const rendered = Array.from(root.querySelectorAll<HTMLElement>('*'))
    const rows = new Set<HTMLElement>()
    const walker = document.createTreeWalker(original, NodeFilter.SHOW_TEXT)
    while (walker.nextNode()) {
      if (!walker.currentNode.textContent?.trim()) continue
      const parent = walker.currentNode.parentElement!
      if (parent.closest('[data-profile-card], [data-mpvid], video')) continue
      const row =
        parent.closest<HTMLElement>('p,li,td,th,figcaption,h1,h2,h3,h4,h5,h6,div,section') ?? parent
      if (row !== original && !row.querySelector('img,video,[data-mpvid]')) rows.add(row)
    }
    const commit = async (index: number, change: (target: HTMLElement) => void) => {
      if (busy || !options.enabled(id)) throw new Error('请等待当前修改保存后重试。')
      const current = options.blocks().find((item) => item.id === id)
      if (!current) throw new Error('当前模板已切换，请重新编辑。')
      const draft = new DOMParser().parseFromString(current.html, 'text/html').body
      const target = draft.querySelectorAll<HTMLElement>('*')[index]
      if (!target) throw new Error('内容已变化，请重新编辑。')
      change(target)
      busy = true
      try {
        await options.save({ ...current, html: draft.innerHTML, text: draft.textContent ?? '' })
      } finally {
        busy = false
      }
    }
    for (const row of rows) {
      if ([...rows].some((other) => other !== row && row.contains(other))) continue
      const index = originals.indexOf(row)
      const target = rendered[index]
      if (!target) continue
      target.dataset.inlineText = 'true'
      target.contentEditable = String(options.enabled(id))
      target.setAttribute('aria-label', '修改当前行文字')
      target.addEventListener(
        'mouseenter',
        () => {
          target.contentEditable = String(options.enabled(id))
        },
        { signal },
      )
      let before = target.innerHTML
      target.addEventListener(
        'focus',
        () => {
          before = target.innerHTML
        },
        { signal },
      )
      target.addEventListener(
        'beforeinput',
        (event) => {
          if (busy || !options.enabled(id)) event.preventDefault()
        },
        { signal },
      )
      target.addEventListener('drop', (event) => event.preventDefault(), { signal })
      target.addEventListener(
        'paste',
        (event) => {
          event.preventDefault()
          if (busy || !options.enabled(id)) return
          const text = event.clipboardData?.getData('text/plain') ?? ''
          const selection = document.getSelection()
          if (!selection?.rangeCount) return
          const range = selection.getRangeAt(0)
          range.deleteContents()
          const node = document.createTextNode(text)
          range.insertNode(node)
          range.setStartAfter(node)
          range.collapse(true)
          selection.removeAllRanges()
          selection.addRange(range)
        },
        { signal },
      )
      target.addEventListener(
        'keydown',
        (event) => {
          if (event.key === 'Escape') {
            target.innerHTML = before
            target.blur()
          }
        },
        { signal },
      )
      target.addEventListener(
        'blur',
        () => {
          if (target.innerHTML === before) return
          const value = target.innerHTML
          void commit(index, (element) => {
            element.innerHTML = value
          })
            .then(() => {
              before = value
            })
            .catch((error) => {
              fail(error)
              if (target.isConnected) target.focus()
            })
        },
        { signal },
      )
    }
    originals.forEach((element, index) => {
      const isVideo = element.matches('a[data-mpvid]')
      if (!isVideo && (!element.matches('img') || element.closest('[data-mpvid]'))) return
      const target = rendered[index]
      if (!target) return
      const imageId = element.getAttribute('data-fixed-image-id')
      if (imageId && target.tagName === 'IMG') {
        void api
          .downloadDocument(imageId)
          .then((blob) => {
            if (signal.aborted) return
            const url = URL.createObjectURL(blob)
            urls.push(url)
            target.setAttribute('src', url)
          })
          .catch(fail)
      }
      const choose = () => {
        if (busy || !options.enabled(id)) return
        const input = document.createElement('input')
        input.type = 'file'
        input.accept = isVideo ? 'video/mp4' : 'image/png,image/jpeg,image/gif,image/webp'
        input.addEventListener(
          'change',
          () => {
            const file = input.files?.[0]
            if (!file) return
            void (async () => {
              if (isVideo) {
                const videoId = options.isolateVideoUploads
                  ? `wxv_${Array.from(crypto.getRandomValues(new Uint32Array(3))).join('')}`
                  : element.getAttribute('data-mpvid')!
                busy = true
                try {
                  await uploadTemplateVideo(videoId, file, () => {})
                } finally {
                  busy = false
                }
                if (!signal.aborted && options.enabled(id)) {
                  await commit(index, (video) => {
                    const url = new URL(video.getAttribute('href')!)
                    url.searchParams.set('vid', videoId)
                    video.setAttribute('href', url.toString())
                    video.setAttribute('data-src', url.toString())
                    video.setAttribute('data-mpvid', videoId)
                  })
                }
              } else {
                if (!['image/png', 'image/jpeg', 'image/gif', 'image/webp'].includes(file.type))
                  throw new Error('请选择 PNG、JPG、GIF 或 WebP 图片。')
                busy = true
                let documentId: string | undefined
                try {
                  documentId = (
                    await api.uploadFile(file, { saveToLibrary: false, waitForReady: false })
                  ).documentId
                } finally {
                  busy = false
                }
                if (!documentId) throw new Error('图片上传未完成，请重试。')
                if (signal.aborted || !options.enabled(id)) return
                await commit(index, (image) => {
                  image.setAttribute('data-fixed-image-id', documentId!)
                })
                if (target.isConnected) {
                  const url = URL.createObjectURL(file)
                  urls.push(url)
                  target.setAttribute('src', url)
                }
              }
            })()
              .catch(fail)
              .finally(() => {
                upload.textContent = '上传替换'
              })
            upload.textContent = '上传中…'
          },
          { once: true },
        )
        input.click()
      }
      target.tabIndex = 0
      const show = () => {
        if (!options.enabled(id) || busy) return
        const rect = target.getBoundingClientRect()
        upload.style.top = `${Math.max(8, rect.top)}px`
        upload.style.left = `${Math.max(8, Math.min(rect.right - 100, document.documentElement.clientWidth - 112))}px`
        upload.hidden = false
        mediaAction = choose
      }
      target.addEventListener('mouseenter', show, { signal })
      target.addEventListener('focus', show, { signal })
      target.addEventListener(
        'mouseleave',
        (event) => {
          if (event.relatedTarget !== upload && !busy) upload.hidden = true
        },
        { signal },
      )
    })
  }
  upload.addEventListener('click', () => mediaAction?.(), { signal })
  upload.addEventListener(
    'mouseleave',
    () => {
      if (!busy) upload.hidden = true
    },
    { signal },
  )
  document.defaultView?.addEventListener(
    'scroll',
    () => {
      upload.hidden = true
    },
    { signal },
  )
  return () => {
    controller.abort()
    style.remove()
    upload.remove()
    urls.forEach(URL.revokeObjectURL)
  }
}
