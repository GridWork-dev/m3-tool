// Reads the data directory into a DataSet for tools and tests. Astro's own loader reads the same
// files for the site; this one exists so the same checks can run without building the site.
//
// Layout: generations/*.yaml, plus {variants,parts,maintenance,issues}/<generation>/*.yaml
import type { Dirent } from 'node:fs'
import { readdir, readFile, stat } from 'node:fs/promises'
import { join, relative, sep } from 'node:path'
import { parse } from 'yaml'
import type { DataSet, Entry, QualityIssue } from './quality.ts'
import { Generation, KnownIssue, MaintenanceItem, Part, Variant } from './schemas.ts'

type Collection = keyof DataSet

const SCHEMAS = {
  generations: Generation,
  variants: Variant,
  parts: Part,
  maintenance: MaintenanceItem,
  issues: KnownIssue,
} as const

const COLLECTIONS = Object.keys(SCHEMAS) as Collection[]

// `yaml` follows YAML 1.2, so `checked: 2026-11-23` stays a string here. The schemas coerce dates
// from strings and from Date objects (Astro's loader produces those) to the same instant.
export async function loadDataSet(
  dataDir: string,
): Promise<{ set: DataSet; issues: QualityIssue[] }> {
  const info = await stat(dataDir).catch(() => undefined)
  if (!info?.isDirectory()) throw new Error(`data directory not found: ${dataDir}`)

  const set: DataSet = { generations: [], variants: [], parts: [], maintenance: [], issues: [] }
  const issues: QualityIssue[] = []

  for (const collection of COLLECTIONS) {
    for (const file of await listFiles(dataDir, collection)) {
      const problem = layoutProblem(collection, file)
      if (problem) {
        issues.push(problem)
        continue
      }
      const text = await readFile(join(dataDir, file), 'utf8')
      const entry = parseEntry(collection, file, text, issues)
      if (entry) (set[collection] as Entry<unknown>[]).push(entry)
    }
  }
  return { set, issues }
}

// Paths relative to the data directory, with forward slashes, sorted so output is stable.
async function listFiles(dataDir: string, collection: Collection): Promise<string[]> {
  let entries: Dirent[]
  try {
    entries = await readdir(join(dataDir, collection), { recursive: true, withFileTypes: true })
  } catch (error) {
    if (error instanceof Error && 'code' in error && error.code === 'ENOENT') return []
    throw error
  }
  return entries
    .filter((entry) => entry.isFile() && entry.name !== '.gitkeep')
    .map((entry) => relative(dataDir, join(entry.parentPath, entry.name)).split(sep).join('/'))
    .sort()
}

// Files the loader would read, but not where the layout puts them, or not named .yaml.
function layoutProblem(collection: Collection, file: string): QualityIssue | undefined {
  if (file.endsWith('.yml')) {
    return { file, code: 'schema', message: 'data files use the .yaml extension, not .yml' }
  }
  if (!file.endsWith('.yaml')) return undefined
  const depth = file.split('/').length - 1 // directories below the data dir, counting the collection
  const expected = collection === 'generations' ? 1 : 2
  if (depth === expected) return undefined
  const where =
    collection === 'generations' ? 'generations/<id>.yaml' : `${collection}/<generation>/<id>.yaml`
  return {
    file,
    code: 'directory-generation-mismatch',
    message: `file is not where the layout expects it (${where})`,
  }
}

function parseEntry(
  collection: Collection,
  file: string,
  text: string,
  issues: QualityIssue[],
): Entry<unknown> | undefined {
  if (!file.endsWith('.yaml')) return undefined
  let raw: unknown
  try {
    raw = parse(text)
  } catch (error) {
    const message = error instanceof Error ? error.message.split('\n')[0] : String(error)
    issues.push({ file, code: 'schema', message: `YAML parse error: ${message}` })
    return undefined
  }
  const result = SCHEMAS[collection].safeParse(raw)
  if (!result.success) {
    for (const issue of result.error.issues) {
      const path = issue.path.length > 0 ? issue.path.map(String).join('.') : '(file)'
      issues.push({ file, code: 'schema', message: `${path}: ${issue.message}` })
    }
    return undefined
  }
  return { file, data: result.data }
}
