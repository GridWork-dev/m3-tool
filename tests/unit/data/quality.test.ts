import { spawnSync } from 'node:child_process'
import { cp, mkdtemp, rename, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { beforeAll, describe, expect, test } from 'vitest'
import { loadDataSet } from '../../../src/data/load.ts'
import { checkDataSet, type DataSet } from '../../../src/data/quality.ts'
import { runCheckData } from '../../../tools/check-data.ts'
import { VALID_FIXTURES } from './helpers.ts'

let valid: DataSet
beforeAll(async () => {
  const loaded = await loadDataSet(VALID_FIXTURES)
  expect(loaded.issues).toEqual([])
  valid = loaded.set
})

const fresh = (): DataSet => structuredClone(valid)
const codes = (set: DataSet) => checkDataSet(set).map((issue) => issue.code)

const find = <T extends { file: string }>(entries: T[], stem: string): T => {
  const entry = entries.find((candidate) => candidate.file.endsWith(`/${stem}.yaml`))
  if (!entry) throw new Error(`fixture ${stem} not found`)
  return entry
}

// A second generation, so a test can point something at "another generation" that exists.
const withGeneration = (set: DataSet, id: string): DataSet => {
  const source = structuredClone(find(set.generations, 'e46'))
  source.file = `generations/${id}.yaml`
  source.data.id = id
  set.generations.push(source)
  return set
}

test('the valid fixture set has no quality issues', () => {
  expect(checkDataSet(valid)).toEqual([])
})

describe('ids and files', () => {
  test('duplicate ids across files', () => {
    const set = withGeneration(fresh(), 'e47')
    const copy = structuredClone(find(set.parts, 'fixture-wheel'))
    copy.file = 'parts/e47/fixture-wheel.yaml' // same stem and id, different generation directory
    copy.data.fits.generation = 'e47'
    set.parts.push(copy)
    const issues = checkDataSet(set)
    expect(issues.map((issue) => issue.code)).toEqual(['duplicate-id'])
    expect(issues[0]?.file).toBe('parts/e47/fixture-wheel.yaml')
    expect(issues[0]?.message).toContain('parts/e46/fixture-wheel.yaml')
  })

  test.each([
    ['generations', 'e46'],
    ['variants', 'e46-us-coupe'],
    ['maintenance', 'fixture-oil-service'],
    ['issues', 'fixture-rod-bearings'],
  ] as const)('duplicate ids are caught in %s too', (collection, stem) => {
    const set = fresh()
    const entries = set[collection] as { file: string; data: { id: string } }[]
    entries.push(structuredClone(find(entries, stem)))
    expect(codes(set)).toContain('duplicate-id')
  })

  test('file stem differs from id', () => {
    const set = fresh()
    find(set.parts, 'fixture-wheel').file = 'parts/e46/renamed-wheel.yaml'
    const issues = checkDataSet(set)
    expect(issues.map((issue) => issue.code)).toEqual(['id-filename-mismatch'])
    expect(issues[0]?.message).toContain('fixture-wheel')
    expect(issues[0]?.message).toContain('renamed-wheel')
  })

  test.each([
    ['generations', 'e46', 'generations/other.yaml'],
    ['variants', 'e46-us-coupe', 'variants/e46/other.yaml'],
    ['maintenance', 'fixture-oil-service', 'maintenance/e46/other.yaml'],
    ['issues', 'fixture-rod-bearings', 'issues/e46/other.yaml'],
  ] as const)('file stem is checked in %s too', (collection, stem, file) => {
    const set = fresh()
    ;(set[collection] as { file: string }[]).forEach((entry) => {
      if (entry.file.endsWith(`/${stem}.yaml`)) entry.file = file
    })
    expect(codes(set)).toEqual(['id-filename-mismatch'])
  })
})

describe('generations', () => {
  test('part fits an unknown generation', () => {
    const set = fresh()
    find(set.parts, 'fixture-wheel').data.fits.generation = 'e99'
    expect(codes(set)).toEqual(['unknown-generation'])
  })

  test.each([
    ['variants', 'e46-us-coupe'],
    ['maintenance', 'fixture-oil-service'],
    ['issues', 'fixture-rod-bearings'],
  ] as const)('%s name a generation that exists', (collection, stem) => {
    const set = fresh()
    const entries = set[collection] as { file: string; data: { generation: string } }[]
    find(entries, stem).data.generation = 'e99'
    expect(codes(set)).toEqual(['unknown-generation'])
  })

  test('part file under parts/e46 fits another generation', () => {
    const set = withGeneration(fresh(), 'e47')
    find(set.parts, 'fixture-wheel').data.fits.generation = 'e47'
    const issues = checkDataSet(set)
    expect(issues.map((issue) => issue.code)).toEqual(['directory-generation-mismatch'])
    expect(issues[0]?.message).toContain('e46')
    expect(issues[0]?.message).toContain('e47')
  })

  test.each([
    ['variants', 'e46-us-coupe'],
    ['maintenance', 'fixture-oil-service'],
    ['issues', 'fixture-rod-bearings'],
  ] as const)('%s must sit under their generation directory', (collection, stem) => {
    const set = withGeneration(fresh(), 'e47')
    const entries = set[collection] as { file: string; data: { generation: string } }[]
    find(entries, stem).data.generation = 'e47'
    expect(codes(set)).toEqual(['directory-generation-mismatch'])
  })
})

describe('part references', () => {
  test('requires or conflicts names a missing part', () => {
    const requires = fresh()
    find(requires.parts, 'fixture-coilovers').data.requires = ['fixture-ghost']
    const issues = checkDataSet(requires)
    expect(issues.map((issue) => issue.code)).toEqual(['unknown-ref'])
    expect(issues[0]?.message).toContain('fixture-ghost')

    const conflicts = fresh()
    find(conflicts.parts, 'fixture-coilovers').data.conflicts = ['fixture-phantom']
    const issues2 = checkDataSet(conflicts)
    expect(issues2.map((issue) => issue.code)).toEqual(['unknown-ref'])
    expect(issues2[0]?.message).toContain('fixture-phantom')
  })

  test('part requires itself', () => {
    const set = fresh()
    find(set.parts, 'fixture-coilovers').data.requires = ['fixture-wheel', 'fixture-coilovers']
    expect(codes(set)).toEqual(['self-ref'])
  })

  test('part conflicts with itself', () => {
    const set = fresh()
    find(set.parts, 'fixture-coilovers').data.conflicts = ['fixture-coilovers']
    expect(codes(set)).toEqual(['self-ref'])
  })

  test('same id in requires and conflicts', () => {
    const set = fresh()
    find(set.parts, 'fixture-coilovers').data.conflicts = ['fixture-wheel']
    const issues = checkDataSet(set)
    expect(issues.map((issue) => issue.code)).toEqual(['requires-conflicts-overlap'])
    expect(issues[0]?.message).toContain('fixture-wheel')
  })
})

describe('verification', () => {
  const source = (tier: 1 | 2 | 3, publisher: string) => ({
    title: 't',
    publisher,
    tier,
    accessed: new Date('2026-11-23'),
  })

  test('verified maintenance or issue fails the tier rule', () => {
    const maintenance = fresh()
    find(maintenance.maintenance, 'fixture-oil-service').data.sources = [source(3, 'Forum')]
    expect(codes(maintenance)).toEqual(['verified-without-tier'])

    const issue = fresh()
    const rod = find(issue.issues, 'fixture-rod-bearings').data
    rod.verified = true // the fixture's only source is Tier 3
    expect(codes(issue)).toEqual(['verified-without-tier'])
  })

  test('a verified part follows the same rule', () => {
    const weak = fresh()
    find(weak.parts, 'fixture-wheel').data.verified = true
    find(weak.parts, 'fixture-wheel').data.sources = [source(3, 'Forum')]
    const issues = checkDataSet(weak)
    expect(issues.map((issue) => issue.code)).toEqual(['verified-without-tier'])
    expect(issues[0]?.file).toBe('parts/e46/fixture-wheel.yaml')

    // The generic fixture has no sources at all.
    const none = fresh()
    find(none.parts, 'fixture-generic-wheels').data.verified = true
    expect(codes(none)).toEqual(['verified-without-tier'])

    const samePublisher = fresh()
    find(samePublisher.parts, 'fixture-wheel').data.verified = true
    find(samePublisher.parts, 'fixture-wheel').data.sources = [
      source(2, 'Shop A'),
      source(2, ' shop a'),
    ]
    expect(codes(samePublisher)).toEqual(['verified-without-tier'])
  })

  test('a verified part passes with one tier-1 source or two independent tier-2 sources', () => {
    const set = fresh()
    const wheel = find(set.parts, 'fixture-wheel').data
    wheel.verified = true // the fixture's own source is Tier 1 (a manufacturer product page)
    expect(codes(set)).toEqual([])
    wheel.sources = [source(2, 'Shop A'), source(2, 'Mag B')]
    expect(codes(set)).toEqual([])
  })

  test('an unverified part is not held to the rule', () => {
    const set = fresh()
    find(set.parts, 'fixture-wheel').data.sources = [source(3, 'Forum')]
    expect(codes(set)).toEqual([])
  })

  test('two tier-2 sources from the same publisher do not verify, whatever the case or spacing', () => {
    const set = fresh()
    find(set.maintenance, 'fixture-oil-service').data.sources = [
      source(2, 'Shop A'),
      source(2, '  SHOP   a '),
    ]
    expect(codes(set)).toEqual(['verified-without-tier'])
  })

  test('one tier-1 source, or two tier-2 sources from different publishers, verify', () => {
    const set = fresh()
    const item = find(set.maintenance, 'fixture-oil-service').data
    item.sources = [source(1, 'BMW')]
    expect(codes(set)).toEqual([])
    item.sources = [source(2, 'Shop A'), source(2, 'Mag B')]
    expect(codes(set)).toEqual([])
  })

  test('unverified entries are not held to the rule', () => {
    const set = fresh()
    find(set.maintenance, 'fixture-oil-service').data.verified = false
    find(set.maintenance, 'fixture-oil-service').data.sources = [source(3, 'Forum')]
    expect(codes(set)).toEqual([])
  })
})

describe('generic parts', () => {
  test('two generic parts in one category for one generation', () => {
    const set = fresh()
    const copy = structuredClone(find(set.parts, 'fixture-generic-wheels'))
    copy.file = 'parts/e46/fixture-generic-wheels-two.yaml'
    copy.data.id = 'fixture-generic-wheels-two'
    set.parts.push(copy)
    const issues = checkDataSet(set)
    expect(issues.map((issue) => issue.code)).toEqual(['multiple-generic-in-category'])
    expect(issues[0]?.message).toContain('wheels')
  })

  test('a generic part in another category, or another generation, is fine', () => {
    const set = withGeneration(fresh(), 'e47')
    const otherCategory = structuredClone(find(set.parts, 'fixture-generic-wheels'))
    otherCategory.file = 'parts/e46/fixture-generic-tires.yaml'
    otherCategory.data.id = 'fixture-generic-tires'
    otherCategory.data.category = 'tires'
    const otherGeneration = structuredClone(find(set.parts, 'fixture-generic-wheels'))
    otherGeneration.file = 'parts/e47/fixture-generic-wheels-e47.yaml'
    otherGeneration.data.id = 'fixture-generic-wheels-e47'
    otherGeneration.data.fits.generation = 'e47'
    set.parts.push(otherCategory, otherGeneration)
    expect(codes(set)).toEqual([])
  })

  test('branded parts do not count as generic', () => {
    const set = fresh()
    const copy = structuredClone(find(set.parts, 'fixture-wheel'))
    copy.file = 'parts/e46/fixture-wheel-two.yaml'
    copy.data.id = 'fixture-wheel-two'
    set.parts.push(copy)
    expect(codes(set)).toEqual([])
  })
})

describe('check-data', () => {
  const copyFixtures = async () => {
    const dir = await mkdtemp(join(tmpdir(), 'check-data-'))
    await cp(VALID_FIXTURES, dir, { recursive: true })
    return dir
  }

  test('exits 0 and prints nothing for valid data', async () => {
    const dir = await copyFixtures()
    try {
      expect(await runCheckData(dir)).toEqual({ exitCode: 0, lines: [] })
    } finally {
      await rm(dir, { recursive: true })
    }
  })

  test('check-data exits 1 and prints file: code: message', async () => {
    const dir = await copyFixtures()
    try {
      await rename(
        join(dir, 'parts/e46/fixture-wheel.yaml'),
        join(dir, 'parts/e46/fixture-renamed.yaml'),
      )
      const result = await runCheckData(dir)
      expect(result.exitCode).toBe(1)
      expect(result.lines.some((line) => /fixture-.*: id-filename-mismatch: /.test(line))).toBe(
        true,
      )
    } finally {
      await rm(dir, { recursive: true })
    }
  })

  test('reports schema failures with the Zod path, alongside cross-file issues', async () => {
    const dir = await copyFixtures()
    try {
      await writeFile(
        join(dir, 'maintenance/e46/fixture-oil-service.yaml'),
        'id: fixture-oil-service\n',
      )
      const result = await runCheckData(dir)
      expect(result.exitCode).toBe(1)
      expect(
        result.lines.some((line) => /fixture-oil-service\.yaml: schema: generation: /.test(line)),
      ).toBe(true)
    } finally {
      await rm(dir, { recursive: true })
    }
  })

  test('exits 1 for a directory that does not exist or holds no data', async () => {
    const missing = await runCheckData(join(tmpdir(), 'check-data-does-not-exist'))
    expect(missing.exitCode).toBe(1)
    expect(missing.lines[0]).toMatch(/not found/)

    const empty = await mkdtemp(join(tmpdir(), 'check-data-empty-'))
    try {
      const result = await runCheckData(empty)
      expect(result.exitCode).toBe(1)
      expect(result.lines[0]).toMatch(/nothing was checked/)
    } finally {
      await rm(empty, { recursive: true })
    }
  })

  test('the CLI prints one line per problem and sets the exit code', async () => {
    const root = fileURLToPath(new URL('../../..', import.meta.url))
    const run = (target: string) =>
      spawnSync(process.execPath, ['tools/check-data.ts', target], { cwd: root, encoding: 'utf8' })

    const dir = await copyFixtures()
    try {
      const clean = run(dir)
      expect(clean.status).toBe(0)
      expect(clean.stdout).toBe('')

      await rename(
        join(dir, 'parts/e46/fixture-wheel.yaml'),
        join(dir, 'parts/e46/fixture-renamed.yaml'),
      )
      const broken = run(dir)
      expect(broken.status).toBe(1)
      expect(broken.stdout).toMatch(/fixture-renamed\.yaml: id-filename-mismatch: /)
      expect(broken.stdout.trim().split('\n')).toHaveLength(1)
    } finally {
      await rm(dir, { recursive: true })
    }
    expect(run('').status).toBe(2)
  })
})
