import { spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { mkdir } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const isWindows = process.platform === 'win32'
const pnpm = isWindows ? 'pnpm.cmd' : 'pnpm'
const failures = []
const includeE2e = process.argv.includes('--e2e')

const run = (label, command, args, cwd, env = process.env) => {
  console.log(`\n[verify] ${label}`)
  const isBatch = isWindows && command.toLowerCase().endsWith('.cmd')
  const executable = isBatch ? (process.env.ComSpec ?? 'cmd.exe') : command
  const commandArgs = isBatch ? ['/d', '/c', command, ...args] : args
  const result = spawnSync(executable, commandArgs, { cwd, stdio: 'inherit', shell: false, env })
  if (result.status !== 0) {
    if (result.error) console.error(result.error.message)
    failures.push(label)
  }
}

run('design-tokens', process.execPath, [resolve(root, 'scripts/generate-design-tokens.mjs')], root)

for (const [label, relative] of [['user', 'apps/user-client'], ['admin', 'apps/admin-console']]) {
  const cwd = resolve(root, relative)
  if (!existsSync(resolve(cwd, 'package.json'))) {
    failures.push(`${label}: missing package.json`)
    continue
  }
  const scripts = ['api:check', 'lint', 'typecheck', 'test', 'build']
  if (includeE2e) scripts.push('test:e2e')
  for (const script of scripts) run(`${label}:${script}`, pnpm, ['run', script], cwd)
}

const backend = resolve(root, 'services/platform-backend')
if (!existsSync(resolve(backend, 'pyproject.toml'))) {
  failures.push('backend: missing pyproject.toml')
} else {
  const verificationDirectory = resolve(root, 'tmp/root-verify')
  await mkdir(verificationDirectory, { recursive: true })
  const backendEnv = {
    ...process.env,
    APP_ENV: 'test',
    DATABASE_URL: `sqlite+aiosqlite:///${resolve(verificationDirectory, 'backend.db').replaceAll('\\', '/')}`,
    TOKEN_SECRET: 'root-verification-secret-at-least-32-characters',
    MOCK_EXTERNAL_SERVICES: 'true',
    WECHAT_PROVIDER_MODE: 'mock',
  }
  run('backend:ruff', 'uv', ['run', 'ruff', 'check', '.'], backend)
  run('backend:mypy', 'uv', ['run', 'mypy', 'app'], backend)
  run('backend:pytest', 'uv', ['run', 'pytest'], backend)
  if (existsSync(resolve(backend, 'alembic.ini'))) run('backend:alembic', 'uv', ['run', 'alembic', 'upgrade', 'head'], backend, backendEnv)
  run('backend:openapi-export', 'uv', ['run', 'python', 'scripts/export_openapi.py'], backend, backendEnv)
  run('suite:openapi-contract', process.execPath, [resolve(root, 'scripts/openapi-contract.mjs')], root)
}

for (const file of ['deploy/compose/compose.dev.yml', 'deploy/compose/compose.test.yml', 'deploy/compose/compose.demo.yml']) {
  run(`compose:${file}`, 'docker', ['compose', '--env-file', '.env.example', '-f', file, 'config', '--quiet'], root)
}

if (failures.length) {
  console.error(`\nVerification failed:\n- ${failures.join('\n- ')}`)
  process.exit(1)
}

console.log('\nAll local verification commands passed.')
