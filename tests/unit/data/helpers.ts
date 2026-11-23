import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { parse } from 'yaml'

export const VALID_FIXTURES = fileURLToPath(new URL('../../fixtures/data/valid', import.meta.url))

// Reads one fixture file as the plain object `yaml` produces (dates stay strings).
export function readFixture(relativePath: string): Record<string, unknown> {
  const text = readFileSync(`${VALID_FIXTURES}/${relativePath}`, 'utf8')
  return parse(text) as Record<string, unknown>
}

// Sets (or, with undefined, deletes) the value at a dotted path such as `options.0.prices.0.seller`.
// Mutates in place, so call it on a fresh readFixture() result or a structuredClone().
export function edit<T>(target: T, path: string, value: unknown): T {
  const keys = path.split('.')
  const last = keys.pop()
  if (last === undefined) throw new Error('edit: empty path')
  let node: unknown = target
  for (const key of keys) {
    if (typeof node !== 'object' || node === null) throw new Error(`edit: no object at ${key}`)
    node = (node as Record<string, unknown>)[key]
  }
  if (typeof node !== 'object' || node === null) throw new Error(`edit: no object at ${last}`)
  if (value === undefined) delete (node as Record<string, unknown>)[last]
  else (node as Record<string, unknown>)[last] = value
  return target
}

type Parsed = { success: boolean; error?: { issues: { path: PropertyKey[]; message: string }[] } }

// Dotted paths of every issue a failed safeParse reported, so a test can prove it failed for the
// intended reason and not an incidental one.
export function issuePaths(result: Parsed): string[] {
  return (result.error?.issues ?? []).map((issue) => issue.path.map(String).join('.'))
}

export function issueMessages(result: Parsed): string[] {
  return (result.error?.issues ?? []).map((issue) => issue.message)
}
