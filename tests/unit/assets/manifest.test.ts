import { cp, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { afterEach, beforeEach, describe, expect, test } from 'vitest'
import { AssetManifest } from '../../../src/lib/asset-manifest.ts'
import { runCheckData } from '../../../tools/check-data.ts'
import { VALID_FIXTURES } from '../data/helpers.ts'

const MANIFEST_PATH = fileURLToPath(new URL('../../../src/assets/manifest.json', import.meta.url))

const entry = (over: Record<string, unknown> = {}) => ({
  kind: 'base-car',
  url: 'https://assets.example.com/e46-coupe-body.3f2a.glb',
  sha256: 'a'.repeat(64),
  bytes: 5_242_880,
  triangles: 150_000,
  license: 'CC BY 4.0',
  sources: ['https://commons.wikimedia.org/wiki/File:Example.jpg'],
  publishedAt: '2026-11-23',
  ...over,
})
const manifest = (assets: Record<string, unknown>) => ({ version: 1, assets })
const issuePaths = (result: ReturnType<typeof AssetManifest.safeParse>) =>
  (result.error?.issues ?? []).map((i) => i.path.map(String).join('.'))

test('the committed manifest parses', async () => {
  const json: unknown = JSON.parse(await readFile(MANIFEST_PATH, 'utf8'))
  expect(AssetManifest.parse(json)).toEqual({ version: 1, assets: {} })
})

test('accepts a full entry and turns publishedAt into a date', () => {
  const parsed = AssetManifest.parse(manifest({ 'e46-coupe-body': entry() }))
  expect(parsed.assets['e46-coupe-body']?.publishedAt).toEqual(new Date('2026-11-23'))
})

test('rejects a bad sha256 and a non-https url', () => {
  const badHash = AssetManifest.safeParse(manifest({ a: entry({ sha256: 'A'.repeat(64) }) }))
  expect(issuePaths(badHash)).toEqual(['assets.a.sha256'])
  expect(AssetManifest.safeParse(manifest({ a: entry({ sha256: 'a'.repeat(63) }) })).success).toBe(
    false,
  )
  const http = AssetManifest.safeParse(
    manifest({ a: entry({ url: 'http://assets.example.com/a.glb' }) }),
  )
  expect(issuePaths(http)).toEqual(['assets.a.url'])
})

describe('the rest of the shape', () => {
  test.each([
    ['an asset id that is not kebab-case', manifest({ E46_Body: entry() })],
    ['version 2', { version: 2, assets: {} }],
    ['a missing version', { assets: {} }],
    ['an unknown kind', manifest({ a: entry({ kind: 'wheel' }) })],
    ['zero bytes', manifest({ a: entry({ bytes: 0 }) })],
    ['fractional bytes', manifest({ a: entry({ bytes: 1.5 }) })],
    ['negative triangles', manifest({ a: entry({ triangles: -1 }) })],
    ['a time in publishedAt', manifest({ a: entry({ publishedAt: '2026-11-23T10:00:00Z' }) })],
    ['an empty license', manifest({ a: entry({ license: '' }) })],
    ['sources that are not strings', manifest({ a: entry({ sources: [1] }) })],
    ['an unknown key', manifest({ a: entry({ price: 1 }) })],
    ['an unknown top-level key', { version: 1, assets: {}, extra: true }],
  ])('rejects %s', (_label, value) => {
    expect(AssetManifest.safeParse(value).success).toBe(false)
  })

  test('accepts zero triangles and no sources', () => {
    const parsed = AssetManifest.safeParse(
      manifest({ a: entry({ kind: 'product', triangles: 0, sources: [] }) }),
    )
    expect(parsed.success).toBe(true)
  })

  test('accepts a Date at UTC midnight for publishedAt', () => {
    const parsed = AssetManifest.safeParse(
      manifest({ a: entry({ publishedAt: new Date('2026-11-23') }) }),
    )
    expect(parsed.success).toBe(true)
  })
})

describe('check-data and the manifest', () => {
  let dir: string
  beforeEach(async () => {
    dir = await mkdtemp(join(tmpdir(), 'check-manifest-'))
    await cp(VALID_FIXTURES, dir, { recursive: true })
  })
  afterEach(() => rm(dir, { recursive: true }))

  test('a valid manifest adds nothing', async () => {
    expect(await runCheckData(dir, { manifestPath: MANIFEST_PATH })).toEqual({
      exitCode: 0,
      lines: [],
    })
  })

  test('an invalid manifest is reported with the file and the field path', async () => {
    const path = join(dir, 'manifest.json')
    await writeFile(path, JSON.stringify(manifest({ a: entry({ sha256: 'nope' }) })))
    const result = await runCheckData(dir, { manifestPath: path })
    expect(result.exitCode).toBe(1)
    expect(result.lines).toHaveLength(1)
    expect(result.lines[0]).toMatch(/manifest\.json: schema: assets\.a\.sha256: /)
  })

  test('a bad asset id is reported with the reason', async () => {
    const path = join(dir, 'manifest.json')
    await writeFile(path, JSON.stringify(manifest({ E46_Body: entry() })))
    const result = await runCheckData(dir, { manifestPath: path })
    expect(result.exitCode).toBe(1)
    expect(result.lines).toEqual([
      expect.stringMatching(/manifest\.json: schema: assets\.E46_Body: .*kebab-case/),
    ])
  })

  test('a manifest that is not JSON, or is missing, is reported', async () => {
    const path = join(dir, 'manifest.json')
    await writeFile(path, '{ nope')
    const broken = await runCheckData(dir, { manifestPath: path })
    expect(broken.exitCode).toBe(1)
    expect(broken.lines[0]).toMatch(/manifest\.json: schema: .*JSON/)
    const missing = await runCheckData(dir, { manifestPath: join(dir, 'absent.json') })
    expect(missing.exitCode).toBe(1)
    expect(missing.lines[0]).toMatch(/absent\.json: schema: .*not found/)
  })
})
