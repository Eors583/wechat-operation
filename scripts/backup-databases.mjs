import { createHash } from 'node:crypto'
import { createReadStream, createWriteStream } from 'node:fs'
import { mkdir, stat, writeFile } from 'node:fs/promises'
import { finished } from 'node:stream/promises'
import { spawn } from 'node:child_process'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const composeFile = process.env.COMPOSE_FILE ?? resolve(root, 'deploy/compose/compose.dev.yml')
const stamp = new Date().toISOString().replaceAll(':', '-').replace(/\.\d{3}Z$/, 'Z')
const output = resolve(root, 'backups', stamp)
await mkdir(output, { recursive: true })

const dump = async (service, user, database, filename) => {
  const destination = createWriteStream(resolve(output, filename), { flags: 'wx' })
  const child = spawn('docker', [
    'compose', '-f', composeFile, 'exec', '-T', service,
    'pg_dump', '--format=custom', '--no-owner', '--no-acl', '--username', user, database,
  ], { cwd: root, stdio: ['ignore', 'pipe', 'inherit'] })
  child.stdout.pipe(destination)
  await Promise.all([
    finished(destination),
    new Promise((fulfill, reject) => {
      child.once('error', reject)
      child.once('close', (code) => code === 0 ? fulfill() : reject(new Error(`${service} pg_dump exited ${code}`)))
    }),
  ])
}

const sha256 = (path) => new Promise((fulfill, reject) => {
  const hash = createHash('sha256')
  createReadStream(path).on('data', (chunk) => hash.update(chunk)).on('error', reject).on('end', () => fulfill(hash.digest('hex')))
})

await dump('business-db', process.env.BUSINESS_DB_USER ?? 'wechat_ai', process.env.BUSINESS_DB_NAME ?? 'wechat_ai', 'business.dump')
await dump('retrieval-db', process.env.RETRIEVAL_DB_USER ?? 'wechat_ai', process.env.RETRIEVAL_DB_NAME ?? 'wechat_ai_retrieval', 'retrieval.dump')

const files = await Promise.all(['business.dump', 'retrieval.dump'].map(async (name) => {
  const path = resolve(output, name)
  return { name, bytes: (await stat(path)).size, sha256: await sha256(path) }
}))

const manifest = {
  createdAt: new Date().toISOString(),
  environment: process.env.APP_ENV ?? 'development',
  composeFile,
  files,
  objectStorage: 'Object storage is not included. Verify provider versioning, replication, lifecycle, and restore separately.',
}
await writeFile(resolve(output, 'manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`, { flag: 'wx' })
console.log(`Database backup written to ${output}`)
