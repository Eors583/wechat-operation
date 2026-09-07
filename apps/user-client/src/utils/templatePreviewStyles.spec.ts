import { describe, expect, it } from 'vitest'
import { createDefaultStyles } from '@/api/styleDefaults'
import { templatePreviewCssVariables } from './templatePreviewStyles'

describe('templatePreviewCssVariables', () => {
  it('maps validated template modules to scoped editor CSS variables', () => {
    const styles = createDefaultStyles()
    styles.body.fontSize = 17
    styles.body.fontWeight = '400'
    styles.highlight.border = 'left'
    styles.heading_marker.enabled = true

    const variables = templatePreviewCssVariables(styles)

    expect(variables['--article-body-font-size']).toBe('17px')
    expect(variables['--article-body-font-weight']).toBe('400')
    expect(variables['--article-highlight-border-left']).toBe('4px solid var(--app-action-primary)')
    expect(variables['--article-heading-marker-color']).toBe(styles.heading_marker.color)
  })
})
