import { describe, expect, it } from 'vitest'
import { reactive } from 'vue'
import { cloneData } from './clone'

describe('cloneData', () => {
  it('clones nested Vue reactive values into independent plain data', () => {
    const source = reactive({ name: 'published', options: [{ enabled: true }] })

    const copy = cloneData(source)
    copy.options[0]!.enabled = false

    expect(copy).toEqual({ name: 'published', options: [{ enabled: false }] })
    expect(source.options[0]!.enabled).toBe(true)
  })
})
