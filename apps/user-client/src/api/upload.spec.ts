import { describe, expect, it } from 'vitest'
import { normalizedFileMimeType } from './client'

describe('upload MIME normalization', () => {
  it.each([
    ['data.csv', 'application/vnd.ms-excel', 'text/csv'],
    ['voice.m4a', 'audio/x-m4a', 'audio/mp4'],
    ['notes.md', 'application/octet-stream', 'text/markdown'],
    ['photo.JPG', '', 'image/jpeg'],
    [
      'slides.pptx',
      'application/zip',
      'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    ],
  ])('uses the locked backend MIME for %s', (name, type, expected) => {
    expect(normalizedFileMimeType({ name, type })).toBe(expected)
  })

  it('accepts an allowed MIME when the filename has no known extension', () => {
    expect(normalizedFileMimeType({ name: 'upload', type: 'application/pdf' })).toBe(
      'application/pdf',
    )
  })

  it('rejects an unknown MIME and extension', () => {
    expect(normalizedFileMimeType({ name: 'archive.zip', type: 'application/zip' })).toBe('')
  })
})
