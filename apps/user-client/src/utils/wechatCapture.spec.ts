import { describe, expect, it } from 'vitest'
import {
  parseWechatArticleCapture,
  WECHAT_CAPTURE_BOOKMARKLET,
  WECHAT_CAPTURE_PREFIX,
} from './wechatCapture'

describe('WeChat local article capture', () => {
  it('accepts a complete local capture and rejects ordinary or incomplete clipboard text', () => {
    const text = '这是从当前微信公众号页面读取的真实正文。'.repeat(12)
    expect(
      parseWechatArticleCapture(
        `${WECHAT_CAPTURE_PREFIX}${JSON.stringify({ title: '测试文章', text })}`,
      ),
    ).toEqual({ title: '测试文章', text })
    expect(parseWechatArticleCapture(text)).toBeNull()
    expect(
      parseWechatArticleCapture(
        `${WECHAT_CAPTURE_PREFIX}${JSON.stringify({ title: '测试文章', text: '太短' })}`,
      ),
    ).toBeNull()
  })

  it('builds a local-only bookmarklet without sending the source URL to the server', () => {
    const script = decodeURIComponent(WECHAT_CAPTURE_BOOKMARKLET.slice('javascript:'.length))
    expect(script).toContain("document.querySelector('#js_content,.rich_media_content')")
    expect(script).toContain('navigator.clipboard')
    expect(script).not.toContain('fetch(')
    expect(script).not.toContain('location.href')
  })
})
