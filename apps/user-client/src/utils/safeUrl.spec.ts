import { describe, expect, it } from 'vitest'
import { linkAttachmentLabel, safeHttpUrl } from './safeUrl'

describe('untrusted HTTP URL boundary', () => {
  it('accepts a normal HTTP(S) URL and creates a bounded non-secret label', () => {
    const value = safeHttpUrl('https://mp.weixin.qq.com/s/abc?scene=1', {
      rejectSensitiveQuery: true,
    })
    expect(value).toBe('https://mp.weixin.qq.com/s/abc?scene=1')
    expect(linkAttachmentLabel(value)).toBe('mp.weixin.qq.com/s/abc')
    expect(linkAttachmentLabel(`https://example.com/${'a'.repeat(400)}`)).toHaveLength(255)
  })

  it('normalizes bare domain links to HTTPS', () => {
    expect(safeHttpUrl('baidu.com', { rejectSensitiveQuery: true })).toBe('https://baidu.com/')
    expect(safeHttpUrl('mp.weixin.qq.com/s/abc?scene=1', { rejectSensitiveQuery: true })).toBe(
      'https://mp.weixin.qq.com/s/abc?scene=1',
    )
    expect(safeHttpUrl('www.example.com/a?from=wechat', { rejectSensitiveQuery: true })).toBe(
      'https://www.example.com/a?from=wechat',
    )
  })

  it.each([
    'https://user:pass@example.com/private',
    'javascript:alert(1)',
    'https://',
    `https://example.com/${'x'.repeat(2000)}`,
    'https://example.com/resource?access_token=secret',
    'https://example.com/resource?api_key=secret',
    'https://example.com/resource?token=secret',
    'https://example.com/resource?authorization=secret',
    'https://example.com/resource#access_token=secret',
  ])('rejects malformed, credential-bearing, long or obvious secret URLs: %s', (value) => {
    expect(safeHttpUrl(value, { rejectSensitiveQuery: true })).toBe('')
  })

  it('can require HTTPS for renderable image resources', () => {
    expect(safeHttpUrl('http://example.com/a.png', { httpsOnly: true })).toBe('')
    expect(safeHttpUrl('https://example.com/a.png', { httpsOnly: true })).toBe(
      'https://example.com/a.png',
    )
  })

  it('keeps an encoded malformed pathname from crashing label rendering', () => {
    expect(linkAttachmentLabel('https://example.com/%E0%A4%A')).toBe('example.com/%E0%A4%A')
  })
})
