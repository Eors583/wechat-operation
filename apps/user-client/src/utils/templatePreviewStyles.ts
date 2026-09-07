import type { ModuleKey, ModuleStyle } from '@/api/types'

const cssModuleName = (key: ModuleKey) => key.replaceAll('_', '-')

export const templatePreviewCssVariables = (styles: Record<ModuleKey, ModuleStyle>) => {
  const variables: Record<string, string> = {}
  ;(Object.entries(styles) as [ModuleKey, ModuleStyle][]).forEach(([key, style]) => {
    const prefix = `--article-${cssModuleName(key)}`
    variables[`${prefix}-color`] = style.color
    variables[`${prefix}-background`] = style.background
    variables[`${prefix}-font-size`] = `${style.fontSize}px`
    variables[`${prefix}-font-weight`] = style.fontWeight
    variables[`${prefix}-text-align`] = style.align
    variables[`${prefix}-line-height`] = String(style.lineHeight)
    variables[`${prefix}-margin-top`] = `${style.marginTop ?? 0}px`
    variables[`${prefix}-margin-bottom`] = `${style.spacing}px`
    variables[`${prefix}-text-indent`] = `${style.textIndent ?? 0}px`
    variables[`${prefix}-padding`] = `${style.padding}px`
    if (style.borderAll) variables[`${prefix}-border`] = style.borderAll
    variables[`${prefix}-border-left`] =
      style.borderLeft || (style.border === 'left' ? '4px solid var(--app-action-primary)' : 'none')
  })
  return variables
}
