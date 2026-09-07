import { spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const projects = ['apps/user-client', 'apps/admin-console', 'services/platform-backend']

if (!existsSync(resolve(root, '.gitmodules'))) {
  const missing = projects.filter((project) => !existsSync(resolve(root, project)))
  if (missing.length) {
    console.error(`Monorepo project directories are missing:\n${missing.join('\n')}`)
    process.exit(1)
  }
  console.log('Monorepo project directories are present.')
  process.exit(0)
}

const result = spawnSync('git', ['submodule', 'status', '--recursive'], { cwd: root, encoding: 'utf8' })
if (result.status !== 0) {
  process.stderr.write(result.stderr)
  process.exit(result.status ?? 1)
}

const invalid = result.stdout.split(/\r?\n/).filter(Boolean).filter((line) => /^[-+U]/.test(line))
if (invalid.length) {
  console.error(`Submodule state is not releaseable:\n${invalid.join('\n')}`)
  process.exit(1)
}

process.stdout.write(result.stdout)
