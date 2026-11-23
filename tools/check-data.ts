import { readFile } from 'node:fs/promises'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'
import { loadDataSet } from '../src/data/load.ts'
import { checkDataSet } from '../src/data/quality.ts'
import { AssetManifest } from '../src/lib/asset-manifest.ts'

const MANIFEST_PATH = fileURLToPath(new URL('../src/assets/manifest.json', import.meta.url))

// Parses the asset manifest against its schema. One line per problem, in the same
// `<file>: <code>: <message>` shape as the data files.
async function checkManifest(manifestPath: string): Promise<string[]> {
  const file = relative(process.cwd(), manifestPath) || manifestPath
  let text: string
  try {
    text = await readFile(manifestPath, 'utf8')
  } catch (error) {
    if (error instanceof Error && 'code' in error && error.code === 'ENOENT') {
      return [`${file}: schema: manifest not found`]
    }
    throw error
  }
  let raw: unknown
  try {
    raw = JSON.parse(text)
  } catch (error) {
    return [
      `${file}: schema: not valid JSON: ${error instanceof Error ? error.message : String(error)}`,
    ]
  }
  const result = AssetManifest.safeParse(raw)
  if (result.success) return []
  return result.error.issues.map((issue) => {
    const path = issue.path.length > 0 ? issue.path.map(String).join('.') : '(file)'
    // A bad record key reports only "Invalid key in record", with the reason nested inside.
    const reason =
      issue.code === 'invalid_key'
        ? `${issue.message}: ${issue.issues.map((nested) => nested.message).join('; ')}`
        : issue.message
    return `${file}: schema: ${path}: ${reason}`
  })
}

// Validates every file under the data directory against the schemas, then runs the cross-file
// checks. Prints one `<file>: <code>: <message>` line per problem, and nothing when all is well.
// With `manifestPath`, it also parses the asset manifest, and the CLI always does.
export async function runCheckData(
  dataDir: string,
  opts: { manifestPath?: string } = {},
): Promise<{ exitCode: 0 | 1; lines: string[] }> {
  let loaded: Awaited<ReturnType<typeof loadDataSet>>
  try {
    loaded = await loadDataSet(dataDir)
  } catch (error) {
    return {
      exitCode: 1,
      lines: [`${dataDir}: error: ${error instanceof Error ? error.message : String(error)}`],
    }
  }
  const { set, issues } = loaded
  const loadedCount = Object.values(set).reduce((sum, entries) => sum + entries.length, 0)
  if (loadedCount === 0 && issues.length === 0) {
    return { exitCode: 1, lines: [`${dataDir}: error: no data files found, nothing was checked`] }
  }
  const all = [...issues, ...checkDataSet(set)].sort((a, b) => a.file.localeCompare(b.file))
  const lines = all.map((issue) => `${join(dataDir, issue.file)}: ${issue.code}: ${issue.message}`)
  if (opts.manifestPath) lines.push(...(await checkManifest(opts.manifestPath)))
  return { exitCode: lines.length > 0 ? 1 : 0, lines }
}

// Exit codes: 0 clean, 1 problems found, 2 bad usage.
if (import.meta.main) {
  const dataDir = process.argv[2]
  if (!dataDir) {
    console.error('usage: node tools/check-data.ts <dir>')
    process.exit(2)
  }
  const { exitCode, lines } = await runCheckData(dataDir, { manifestPath: MANIFEST_PATH })
  for (const line of lines) console.log(line)
  process.exitCode = exitCode
}
