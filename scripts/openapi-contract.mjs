import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const exportedPath = resolve(root, 'services/platform-backend/openapi.json')
const snapshotPath = resolve(root, 'contracts/generated/platform.openapi.json')
const update = process.argv.includes('--update')

const normalize = (text) => `${JSON.stringify(JSON.parse(text), null, 2)}\n`
const exported = normalize(await readFile(exportedPath, 'utf8'))

if (update) {
  await mkdir(dirname(snapshotPath), { recursive: true })
  await writeFile(snapshotPath, exported)
  console.log(`Updated locked OpenAPI snapshot: ${snapshotPath}`)
  process.exit(0)
}

let snapshot
try {
  snapshot = normalize(await readFile(snapshotPath, 'utf8'))
} catch (error) {
  if (error && error.code === 'ENOENT') {
    console.error('Locked OpenAPI snapshot is missing. Run: node scripts/openapi-contract.mjs --update')
    process.exit(1)
  }
  throw error
}

if (snapshot !== exported) {
  console.error('Backend OpenAPI differs from the locked release snapshot. Review the diff, update compatible clients, then explicitly refresh the snapshot.')
  process.exit(1)
}

const document = JSON.parse(snapshot)
console.log(`OpenAPI contract matches the locked snapshot (${Object.keys(document.paths ?? {}).length} paths).`)

