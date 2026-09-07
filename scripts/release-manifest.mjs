import { writeFile } from 'node:fs/promises'
import { spawnSync } from 'node:child_process'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const repositories = {
  suite: '.',
  userClient: 'apps/user-client',
  adminConsole: 'apps/admin-console',
  platformBackend: 'services/platform-backend',
}

const git = (cwd, ...args) => {
  const result = spawnSync('git', args, { cwd, encoding: 'utf8' })
  if (result.status !== 0) return null
  return result.stdout.trim()
}

const manifest = {
  version: process.env.APP_VERSION ?? 'unversioned',
  generatedAt: new Date().toISOString(),
  repositories: Object.fromEntries(Object.entries(repositories).map(([name, path]) => {
    const cwd = resolve(root, path)
    return [name, {
      commit: git(cwd, 'rev-parse', 'HEAD'),
      branch: git(cwd, 'branch', '--show-current'),
      dirty: Boolean(git(cwd, 'status', '--porcelain')),
    }]
  })),
}

const invalid = Object.entries(manifest.repositories).filter(([, repository]) => !repository.commit || !repository.branch || repository.dirty)
if (invalid.length) {
  console.error(`Release manifest refused:\n${invalid.map(([name, repository]) => `- ${name}: commit=${repository.commit ?? 'missing'}, branch=${repository.branch || 'missing'}, dirty=${repository.dirty}`).join('\n')}`)
  process.exit(1)
}

await writeFile(resolve(root, 'release-manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`)
console.log('Wrote release-manifest.json')
