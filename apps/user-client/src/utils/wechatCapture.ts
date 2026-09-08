export const WECHAT_CAPTURE_PREFIX = 'WECHAT_ARTICLE_CAPTURE_V1\n'

export type WechatArticleCapture = {
  title: string
  text: string
}

export const parseWechatArticleCapture = (value: string): WechatArticleCapture | null => {
  if (!value.startsWith(WECHAT_CAPTURE_PREFIX)) return null
  try {
    const payload = JSON.parse(value.slice(WECHAT_CAPTURE_PREFIX.length)) as Record<string, unknown>
    const title = typeof payload.title === 'string' ? payload.title.trim().slice(0, 200) : ''
    const text = typeof payload.text === 'string' ? payload.text.trim() : ''
    if (!title || text.replace(/\s/g, '').length < 80 || text.length > 300_000) return null
    return { title, text }
  } catch {
    return null
  }
}

const captureScript = `(()=>{const r=document.querySelector('#js_content,.rich_media_content');if(!r){alert('没有找到公众号正文，请确认当前页面是已正常打开的微信文章。');return}const t=(document.querySelector('meta[property="og:title"]')?.content||document.title||'微信公众号文章').trim().slice(0,200);const x=(r.innerText||r.textContent||'').replace(/\\n{3,}/g,'\\n\\n').trim().slice(0,300000);if(x.replace(/\\s/g,'').length<80){alert('读取到的正文过短，请确认文章已完整显示。');return}const v='${WECHAT_CAPTURE_PREFIX.replace('\n', '\\n')}'+JSON.stringify({title:t,text:x});const done=()=>alert('正文已采集。请返回蓝血平台，在输入框中粘贴。');const fallback=()=>{const a=document.createElement('textarea');a.value=v;a.style.position='fixed';a.style.opacity='0';document.body.appendChild(a);a.select();document.execCommand('copy');a.remove();done()};navigator.clipboard?.writeText?navigator.clipboard.writeText(v).then(done).catch(fallback):fallback()})()`

export const WECHAT_CAPTURE_BOOKMARKLET = `javascript:${encodeURIComponent(captureScript)}`
