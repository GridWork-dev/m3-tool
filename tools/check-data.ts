import { join } from 'node:path'
import { loadDataSet } from '../src/data/load.ts'
import { checkDataSet } from '../src/data/quality.ts'

// Validates every file under the data directory against the schemas, then runs the cross-file
// checks. Prints one `<file>: <code>: <message>` line per problem, and nothing when all is well.
export async function runCheckData(dataDir: string): Promise<{ exitCode: 0 | 1; lines: string[] }> {
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
  return { exitCode: lines.length > 0 ? 1 : 0, lines }
}

// Exit codes: 0 clean, 1 problems found, 2 bad usage.
if (import.meta.main) {
  const dataDir = process.argv[2]
  if (!dataDir) {
    console.error('usage: node tools/check-data.ts <dir>')
    process.exit(2)
  }
  const { exitCode, lines } = await runCheckData(dataDir)
  for (const line of lines) console.log(line)
  process.exitCode = exitCode
}
