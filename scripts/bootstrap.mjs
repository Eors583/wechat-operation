import { copyFile, stat } from 'node:fs/promises'
import { spawnSync } from 'node:child_process'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const isWindows = process.platform === 'win32'
const pnpm = isWindows ? 'pnpm.cmd' : 'pnpm'

const exists = async (path) => stat(path).then(() => true, () => false)
const run = (command, args, cwd = root) => {
  const result = spawnSync(command, args, { cwd, stdio: 'inherit', shell: false })
  if (result.status !== 0) process.exit(result.status ?? 1)
}

if (!(await exists(resolve(root, '.env')))) {
  await copyFile(resolve(root, '.env.example'), resolve(root, '.env'))
  console.log('Created .env from .env.example; replace every production placeholder before deployment.')
}

run(process.execPath, [resolve(root, 'scripts/generate-design-tokens.mjs')])

for (const directory of ['apps/user-client', 'apps/admin-console']) {
  const cwd = resolve(root, directory)
  if (await exists(resolve(cwd, 'package.json'))) run(pnpm, ['install', '--frozen-lockfile=false'], cwd)
}

const backend = resolve(root, 'services/platform-backend')
if (await exists(resolve(backend, 'pyproject.toml'))) run('uv', ['sync', '--all-groups'], backend)

console.log('Bootstrap completed. Start the suite with deploy/compose/compose.dev.yml.')

