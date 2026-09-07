import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const source = JSON.parse(await readFile(resolve(root, 'design/tokens.json'), 'utf8'))
const targets = ['apps/user-client', 'apps/admin-console']

const kebab = (value) => value.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`)
const quote = (value) => (typeof value === 'string' ? JSON.stringify(value) : value)
const cssValue = (value) => {
  if (typeof value !== 'string') return value
  const color = /^#([0-9a-f])\1([0-9a-f])\2([0-9a-f])\3$/i.exec(value)
  return color ? `#${color[1]}${color[2]}${color[3]}` : value
}

const scssMap = (name, values) => {
  const entries = Object.entries(values).map(([key, value]) => `  ${JSON.stringify(key)}: ${quote(value)}`)
  return `$${name}: (\n${entries.join(',\n')}\n);`
}

const sharedMaps = [
  scssMap('app-breakpoints', source.breakpoint),
  scssMap('app-space', source.space),
  scssMap('app-radius', source.radius),
  scssMap('app-font', source.font),
  scssMap('app-motion', source.motion),
  scssMap('app-z-index', source.zIndex),
].join('\n\n')

const variables = (theme) => Object.entries(theme)
  .map(([key, value]) => `  --app-${kebab(key)}: ${cssValue(value)};`)
  .join('\n')

const scss = `// Generated from design/tokens.json. Do not edit by hand.\n${sharedMaps}\n\n:root, .body--light {\n${variables(source.theme.light)}\n}\n\n.body--dark {\n${variables(source.theme.dark)}\n}\n`
const ts = `// Generated from design/tokens.json. Do not edit by hand.\nexport const designTokens = ${JSON.stringify(source, null, 2)} as const\n\nexport type ThemePreference = 'light' | 'dark' | 'system'\n`

for (const target of targets) {
  const directory = resolve(root, target, 'src/styles/tokens')
  await mkdir(directory, { recursive: true })
  await Promise.all([
    writeFile(resolve(directory, '_generated.scss'), scss),
    writeFile(resolve(directory, 'generated.ts'), ts),
  ])
  console.log(`Generated tokens for ${target}`)
}
