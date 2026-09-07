import type { ModuleKey, ModuleStyle } from './types'

const defaultStyle = (patch: Partial<ModuleStyle> = {}): ModuleStyle => ({
  fontSize: 16,
  fontWeight: '400',
  color: '#25322c',
  background: '#ffffff',
  align: 'left',
  lineHeight: 1.75,
  spacing: 16,
  padding: 0,
  border: 'none',
  ...patch,
})

export const createDefaultStyles = (): Record<ModuleKey, ModuleStyle> => ({
  table_header: defaultStyle({
    fontSize: 15,
    fontWeight: '600',
    background: '#eef8f2',
    lineHeight: 1.6,
    spacing: 0,
    padding: 8,
    borderAll: '1px solid #d1d5db',
  }),
  table_cell: defaultStyle({
    fontSize: 15,
    lineHeight: 1.6,
    spacing: 0,
    padding: 8,
    borderAll: '1px solid #d1d5db',
  }),
  title: defaultStyle({ fontSize: 30, fontWeight: '700', color: '#14211b', spacing: 24 }),
  lead: defaultStyle({ fontSize: 16, color: '#5d6963', background: '#f1f6f3', padding: 16 }),
  heading_marker: defaultStyle({
    enabled: false,
    fontSize: 24,
    fontWeight: '700',
    color: '#ff4c00',
    align: 'center',
    spacing: 4,
  }),
  heading1: defaultStyle({ fontSize: 23, fontWeight: '700', color: '#078c49', spacing: 22 }),
  heading2: defaultStyle({ fontSize: 19, fontWeight: '600', color: '#1f2d27', spacing: 18 }),
  body: defaultStyle(),
  highlight: defaultStyle({
    fontWeight: '600',
    background: '#eef8f2',
    padding: 16,
    border: 'left',
  }),
  quote: defaultStyle({ color: '#5d6963', background: '#f5f6f5', padding: 16, border: 'left' }),
  list: defaultStyle({ spacing: 10 }),
  caption: defaultStyle({ fontSize: 13, color: '#7f8a84', align: 'center', spacing: 10 }),
  divider: defaultStyle({ spacing: 24 }),
})
