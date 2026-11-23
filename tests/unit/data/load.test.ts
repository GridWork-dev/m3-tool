import { cp, mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, beforeEach, expect, test } from 'vitest'
import { parse } from 'yaml'
import { loadDataSet } from '../../../src/data/load.ts'
import { VALID_FIXTURES } from './helpers.ts'

let dir: string
beforeEach(async () => {
  dir = await mkdtemp(join(tmpdir(), 'load-data-'))
  await cp(VALID_FIXTURES, dir, { recursive: true })
})
afterEach(() => rm(dir, { recursive: true }))

const put = async (file: string, text: string) => {
  await mkdir(join(dir, file, '..'), { recursive: true })
  await writeFile(join(dir, file), text)
}

test('entries carry paths relative to the data directory, with forward slashes', async () => {
  const { set } = await loadDataSet(dir)
  expect(set.generations.map((entry) => entry.file)).toEqual(['generations/e46.yaml'])
  expect(set.parts.map((entry) => entry.file)).toEqual([
    'parts/e46/fixture-coilovers.yaml',
    'parts/e46/fixture-generic-wheels.yaml',
    'parts/e46/fixture-trunk-lid.yaml',
    'parts/e46/fixture-wheel.yaml',
  ])
  expect(set.variants.map((entry) => entry.file)).toEqual([
    'variants/e46/e46-us-coupe.yaml',
    'variants/e46/fixture-csl-coupe.yaml',
  ])
})

test('yaml 1.2 keeps date scalars as strings, which the schemas then coerce', async () => {
  expect(typeof (parse('d: 2026-11-23') as { d: unknown }).d).toBe('string')
  const { set } = await loadDataSet(dir)
  const accessed = set.variants[0]?.data.sources[0]?.accessed
  expect(accessed).toBeInstanceOf(Date)
  expect(accessed?.getTime()).toBe(new Date('2026-11-23').getTime())
})

test('quoted and unquoted dates load to the same instant', async () => {
  const path = join(dir, 'variants/e46/e46-us-coupe.yaml')
  const text = await readFile(path, 'utf8')
  expect(text).toContain('accessed: 2026-11-23')
  await writeFile(path, text.replace('accessed: 2026-11-23', "accessed: '2026-11-23'"))
  const { set, issues } = await loadDataSet(dir)
  expect(issues).toEqual([])
  expect(set.variants[0]?.data.sources[0]?.accessed.getTime()).toBe(
    new Date('2026-11-23').getTime(),
  )
})

test('a schema failure comes back as code schema, with the Zod path in the message', async () => {
  const path = join(dir, 'parts/e46/fixture-wheel.yaml')
  const text = await readFile(path, 'utf8')
  await writeFile(
    path,
    text.replace(
      'seller: Fixture Seller\n        checked: 2026-11-23\n        url',
      "seller: ''\n        checked: soon\n        url",
    ),
  )
  const { set, issues } = await loadDataSet(dir)
  expect(issues.every((issue) => issue.code === 'schema')).toBe(true)
  expect(issues.every((issue) => issue.file === 'parts/e46/fixture-wheel.yaml')).toBe(true)
  const messages = issues.map((issue) => issue.message)
  expect(messages.some((message) => message.startsWith('options.0.prices.0.seller: '))).toBe(true)
  expect(messages.some((message) => message.startsWith('options.0.prices.0.checked: '))).toBe(true)
  // The broken file is left out of the set; its neighbours still load.
  expect(set.parts.map((entry) => entry.data.id)).not.toContain('fixture-wheel')
  expect(set.parts).toHaveLength(3)
})

test('invalid YAML, duplicate keys and empty files come back as schema issues', async () => {
  await put('parts/e46/fixture-broken.yaml', 'id: [unclosed\n')
  await put('parts/e46/fixture-dupe.yaml', 'id: a\nid: b\n')
  await put('parts/e46/fixture-empty.yaml', '')
  const { issues } = await loadDataSet(dir)
  const byFile = (file: string) => issues.filter((issue) => issue.file === file)
  expect(byFile('parts/e46/fixture-broken.yaml')[0]?.message).toMatch(/^YAML parse error: /)
  expect(byFile('parts/e46/fixture-dupe.yaml')[0]?.message).toMatch(/^YAML parse error: .*unique/i)
  expect(byFile('parts/e46/fixture-empty.yaml')[0]?.code).toBe('schema')
})

test('files outside the layout are reported instead of silently skipped', async () => {
  await put('parts/stray.yaml', 'id: stray\n')
  await put('parts/e46/nested/deep.yaml', 'id: deep\n')
  await put('generations/nested/e47.yaml', 'id: e47\n')
  await put('parts/e46/fixture-typo.yml', 'id: fixture-typo\n')
  const { issues } = await loadDataSet(dir)
  const flagged = issues.map((issue) => `${issue.file}|${issue.code}`).sort()
  expect(flagged).toEqual([
    'generations/nested/e47.yaml|directory-generation-mismatch',
    'parts/e46/fixture-typo.yml|schema',
    'parts/e46/nested/deep.yaml|directory-generation-mismatch',
    'parts/stray.yaml|directory-generation-mismatch',
  ])
})

test('.gitkeep files and other non-yaml files are ignored', async () => {
  await put('parts/e46/.gitkeep', '')
  await put('parts/e46/README.md', '# notes')
  expect((await loadDataSet(dir)).issues).toEqual([])
})

test('a missing collection directory is an empty collection, a missing data directory throws', async () => {
  await rm(join(dir, 'issues'), { recursive: true })
  const { set, issues } = await loadDataSet(dir)
  expect(issues).toEqual([])
  expect(set.issues).toEqual([])
  await expect(loadDataSet(join(dir, 'nope'))).rejects.toThrow(/data directory not found/)
})
