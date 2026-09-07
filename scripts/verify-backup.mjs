import { createHash } from 'node:crypto'
import { createReadStream } from 'node:fs'
import { readFile, realpath } from 'node:fs/promises'
import { dirname, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const backupRoot = await realpath(resolve(root, 'backups'))
const requested = process.argv[2]
if (!requested) throw new Error('Usage: node scripts/verify-backup.mjs backups/<timestamp>')
const directory = await realpath(resolve(root, requested))
if (relative(backupRoot, directory).startsWith('..')) throw new Error('Backup path must stay inside the suite backups directory.')

const digest = (path) => new Promise((fulfill, reject) => {
  const hash = createHash('sha256')
  createReadStream(path).on('data', (chunk) => hash.update(chunk)).on('error', reject).on('end', () => fulfill(hash.digest('hex')))
})

const manifest = JSON.parse(await readFile(resolve(directory, 'manifest.json'), 'utf8'))
for (const file of manifest.files) {
  const actual = await digest(resolve(directory, file.name))
  if (actual !== file.sha256) throw new Error(`${file.name} checksum mismatch`)
  console.log(`${file.name}: checksum OK`)
}
console.log('Backup files are intact. A restore drill in an isolated environment is still required.')

