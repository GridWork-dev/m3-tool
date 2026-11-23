import { spawnSync } from 'node:child_process'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { afterAll, beforeAll, describe, expect, test } from 'vitest'
import { runValidateAsset } from '../../../tools/validate-asset.ts'
import { makeProduct, toGlb } from './fixtures.ts'

const ROOT = fileURLToPath(new URL('../../..', import.meta.url))
let dir: string
let good: string
let bad: string

beforeAll(async () => {
  dir = await mkdtemp(join(tmpdir(), 'validate-asset-'))
  good = join(dir, 'good.glb')
  bad = join(dir, 'bad.glb')
  await writeFile(good, await toGlb(makeProduct()))
  await writeFile(bad, await toGlb(makeProduct({ roots: 2 })))
})
afterAll(() => rm(dir, { recursive: true }))

describe('runValidateAsset', () => {
  test('exits 0 for an asset that passes, and prints JSON on request', async () => {
    const plain = await runValidateAsset([good, '--kind', 'product'])
    expect(plain.exitCode).toBe(0)
    expect(plain.stdout).toEqual(['ok'])
    const json = await runValidateAsset([good, '--kind', 'product', '--json'])
    expect(json.exitCode).toBe(0)
    expect(JSON.parse(json.stdout.join('\n'))).toEqual({ ok: true, issues: [] })
  })

  test('exits 1 for any error, and prints one line per issue', async () => {
    const plain = await runValidateAsset([bad, '--kind', 'product'])
    expect(plain.exitCode).toBe(1)
    expect(plain.stdout).toEqual([expect.stringMatching(/^ERROR root-count: /)])
    const json = await runValidateAsset([bad, '--kind', 'product', '--json'])
    expect(json.exitCode).toBe(1)
    const report = JSON.parse(json.stdout.join('\n'))
    expect(report.ok).toBe(false)
    expect(report.issues).toEqual([
      { code: 'root-count', severity: 'error', message: expect.any(String) },
    ])
  })

  test.each([
    ['no arguments', []],
    ['no file', ['--kind', 'product']],
    ['no kind', ['x.glb']],
    ['an unknown kind', ['x.glb', '--kind', 'car']],
    ['an unknown flag', ['x.glb', '--kind', 'product', '--fast']],
    ['two files', ['a.glb', 'b.glb', '--kind', 'product']],
    ['a file that does not exist', [join(tmpdir(), 'does-not-exist.glb'), '--kind', 'product']],
  ])('exits 2 for %s', async (_label, args) => {
    const result = await runValidateAsset(args)
    expect(result.exitCode).toBe(2)
    expect(result.stdout).toEqual([])
    expect(result.stderr.join('\n')).toMatch(/usage|not found|unknown/i)
  })
})

describe('the CLI', () => {
  const run = (...args: string[]) =>
    spawnSync(process.execPath, ['tools/validate-asset.ts', ...args], {
      cwd: ROOT,
      encoding: 'utf8',
    })

  test('prints JSON on stdout and nothing else, and sets the exit code', () => {
    const ok = run(good, '--kind', 'product', '--json')
    expect(ok.status).toBe(0)
    expect(JSON.parse(ok.stdout)).toEqual({ ok: true, issues: [] })
    expect(ok.stderr).toBe('')
    const failed = run(bad, '--kind', 'product', '--json')
    expect(failed.status).toBe(1)
    expect(JSON.parse(failed.stdout).ok).toBe(false)
    expect(run().status).toBe(2)
  })
})
