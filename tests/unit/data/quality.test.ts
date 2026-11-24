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
    expect(codes(maintenance)).toEqual(['verified-without-tier', 'safety-advice-without-evidence'])

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
    find(set.maintenance, 'fixture-oil-service').data.sources = [source(2, 'Shop A')]
    expect(codes(set)).toEqual([])
  })
})

describe('safety evidence (spec 7.6)', () => {
  const source = (tier: 1 | 2 | 3, publisher = 'Pub') => ({
    title: 't',
    publisher,
    tier,
    accessed: new Date('2026-11-23'),
  })
  const oil = (set: DataSet) => find(set.maintenance, 'fixture-oil-service').data
  const rod = (set: DataSet) => find(set.issues, 'fixture-rod-bearings').data
  const guide = (set: DataSet) => find(set.issues, 'fixture-guide-wear').data

  test('the fixtures show both shapes: a forum-only issue without a fix, and a Tier 2 fix', () => {
    const set = fresh()
    expect(rod(set).fix).toBeUndefined()
    expect(rod(set).sources.every((s) => s.tier === 3)).toBe(true)
    expect(guide(set).fix).toBeDefined()
    expect(guide(set).sources.some((s) => s.tier === 2)).toBe(true)
    expect(codes(set)).toEqual([])
  })

  test.each([
    ['Tier 1', [source(1)]],
    ['Tier 2', [source(2)]],
    ['Tier 3 plus Tier 2', [source(3), source(2)]],
    ['Tier 3 plus Tier 1', [source(3), source(1)]],
  ] as const)('a maintenance item with %s evidence passes', (_label, sources) => {
    const set = fresh()
    oil(set).verified = false
    oil(set).sources = [...sources]
    expect(codes(set)).toEqual([])
  })

  test('a maintenance item with only Tier 3 sources fails, even when unverified', () => {
    const set = fresh()
    oil(set).verified = false
    oil(set).sources = [source(3), source(3, 'Other forum')]
    const issues = checkDataSet(set)
    expect(issues.map((issue) => issue.code)).toEqual(['safety-advice-without-evidence'])
    expect(issues[0]?.file).toBe('maintenance/e46/fixture-oil-service.yaml')
    expect(issues[0]?.message).toContain('fixture-oil-service')
    expect(issues[0]?.message).toMatch(/Tier 1 or Tier 2/)
  })

  test('an issue with a fix and only Tier 3 sources fails', () => {
    const set = fresh()
    guide(set).sources = [source(3)]
    const issues = checkDataSet(set)
    expect(issues.map((issue) => issue.code)).toEqual(['safety-advice-without-evidence'])
    expect(issues[0]?.file).toBe('issues/e46/fixture-guide-wear.yaml')
    expect(issues[0]?.message).toContain('fixture-guide-wear')
    expect(issues[0]?.message).toMatch(/fix/)
  })

  test('an issue with a fix and a Tier 2 or Tier 1 source passes', () => {
    const set = fresh()
    guide(set).sources = [source(2)]
    expect(codes(set)).toEqual([])
    guide(set).sources = [source(1)]
    expect(codes(set)).toEqual([])
  })

  test('an issue with no fix may rest on Tier 3 alone, for its symptoms, cause and frequency', () => {
    const set = fresh()
    expect(rod(set).fix).toBeUndefined()
    rod(set).sources = [source(3), source(3, 'Another forum')]
    expect(codes(set)).toEqual([])
  })

  test('adding a fix to a Tier 3 only issue is what trips the rule', () => {
    const set = fresh()
    rod(set).fix = 'Replace them.'
    rod(set).cost = { currency: 'USD', shop: [500, 900] }
    expect(codes(set)).toEqual(['safety-advice-without-evidence'])
  })

  test('a Tier 3 only fix is refused whether or not it is marked verified', () => {
    const set = fresh()
    guide(set).sources = [source(3)]
    guide(set).verified = true
    expect(codes(set)).toEqual(['verified-without-tier', 'safety-advice-without-evidence'])
  })
})

describe('cross-file checks against the generation', () => {
  // The fixture generation: years 2000 to 2006, bodies coupe and convertible, engine FIXTURE-ENGINE.
  const variant = (set: DataSet) => find(set.variants, 'e46-us-coupe').data
  const wheel = (set: DataSet) => find(set.parts, 'fixture-wheel').data
  const coilovers = (set: DataSet) => find(set.parts, 'fixture-coilovers').data
  const oil = (set: DataSet) => find(set.maintenance, 'fixture-oil-service').data
  const rod = (set: DataSet) => find(set.issues, 'fixture-rod-bearings').data

  describe('variants', () => {
    test('a variant body the generation does not build is refused', () => {
      const set = fresh()
      variant(set).body = 'sedan'
      const issues = checkDataSet(set)
      expect(issues.map((issue) => issue.code)).toEqual(['variant-body-not-in-generation'])
      expect(issues[0]?.file).toBe('variants/e46/e46-us-coupe.yaml')
      expect(issues[0]?.message).toContain('sedan')
      expect(issues[0]?.message).toContain('coupe, convertible')
    })

    test('a body the generation builds passes', () => {
      const set = fresh()
      variant(set).body = 'convertible'
      expect(codes(set)).toEqual([])
    })

    test.each([
      ['starts before the generation', [1999, 2006]],
      ['ends after the generation', [2001, 2007]],
      ['is entirely outside it', [2010, 2012]],
    ] as const)('variant years that %s are refused', (_label, years) => {
      const set = fresh()
      variant(set).years = [years[0], years[1]]
      const issues = checkDataSet(set)
      expect(issues.map((issue) => issue.code)).toEqual(['variant-years-outside-generation'])
      expect(issues[0]?.message).toContain('2000')
    })

    test('years equal to the generation range, or inside it, pass', () => {
      const set = fresh()
      variant(set).years = [2000, 2006]
      expect(codes(set)).toEqual([])
      variant(set).years = [2003, 2003]
      expect(codes(set)).toEqual([])
    })
  })

  describe('part fitment', () => {
    test.each([[[1999, 2006]], [[2000, 2007]]] as const)(
      'fits.years %j outside the generation is refused',
      (years) => {
        const set = fresh()
        wheel(set).fits.years = [years[0], years[1]]
        const issues = checkDataSet(set)
        expect(issues.map((issue) => issue.code)).toEqual(['part-years-outside-generation'])
        expect(issues[0]?.file).toBe('parts/e46/fixture-wheel.yaml')
      },
    )

    test('fits.years inside the generation, or left out, pass', () => {
      const set = fresh()
      wheel(set).fits.years = [2001, 2004]
      expect(codes(set)).toEqual([])
      wheel(set).fits.years = undefined
      expect(codes(set)).toEqual([])
    })

    test('fits.bodies the generation does not build are refused, naming them', () => {
      const set = fresh()
      wheel(set).fits.bodies = ['coupe', 'sedan']
      const issues = checkDataSet(set)
      expect(issues.map((issue) => issue.code)).toEqual(['part-bodies-outside-generation'])
      expect(issues[0]?.message).toContain('sedan')
      expect(issues[0]?.message).not.toContain('"coupe"')
    })

    test('fits.bodies that are a subset, or all of the generation, pass', () => {
      const set = fresh()
      wheel(set).fits.bodies = ['coupe', 'convertible']
      expect(codes(set)).toEqual([])
    })

    test('an empty fits.bodies is refused, because it would fit nothing', () => {
      const set = fresh()
      wheel(set).fits.bodies = []
      const issues = checkDataSet(set)
      expect(issues.map((issue) => issue.code)).toEqual(['fits-list-empty'])
      expect(issues[0]?.message).toContain('bodies')
    })

    test('an empty fits.transmissions is refused', () => {
      const set = fresh()
      coilovers(set).fits.transmissions = []
      const issues = checkDataSet(set)
      expect(issues.map((issue) => issue.code)).toEqual(['fits-list-empty'])
      expect(issues[0]?.message).toContain('transmissions')
    })

    test('a missing fits.bodies or fits.transmissions means all, and passes', () => {
      const set = fresh()
      expect(coilovers(set).fits.bodies).toBeUndefined()
      expect(wheel(set).fits.transmissions).toBeUndefined()
      expect(codes(set)).toEqual([])
    })
  })

  describe('engines', () => {
    test('a maintenance item for an engine the generation lacks is refused', () => {
      const set = fresh()
      oil(set).engine = 'OTHER-ENGINE'
      const issues = checkDataSet(set)
      expect(issues.map((issue) => issue.code)).toEqual(['unknown-engine'])
      expect(issues[0]?.file).toBe('maintenance/e46/fixture-oil-service.yaml')
      expect(issues[0]?.message).toContain('OTHER-ENGINE')
      expect(issues[0]?.message).toContain('FIXTURE-ENGINE')
    })

    test('a known issue for an engine the generation lacks is refused', () => {
      const set = fresh()
      rod(set).engine = 'OTHER-ENGINE'
      expect(codes(set)).toEqual(['unknown-engine'])
    })

    test('an engine code is matched exactly', () => {
      const set = fresh()
      oil(set).engine = 'fixture-engine'
      expect(codes(set)).toEqual(['unknown-engine'])
    })

    test('a missing engine means every engine, and passes', () => {
      const set = fresh()
      oil(set).engine = undefined
      rod(set).engine = undefined
      expect(codes(set)).toEqual([])
    })

    test('the generation is looked up first: an unknown generation reports only that', () => {
      const set = fresh()
      oil(set).generation = 'e99'
      oil(set).engine = 'OTHER-ENGINE'
      expect(codes(set)).toEqual(['unknown-generation'])
    })
  })

  test('nothing is checked against a generation that does not exist, beyond unknown-generation', () => {
    const set = fresh()
    variant(set).generation = 'e99'
    variant(set).body = 'sedan'
    variant(set).years = [1990, 1991]
    expect(codes(set)).toEqual(['unknown-generation'])
  })
})

// "Not after today" has a day of slack: a contributor east of UTC writes their own date in the
// early morning, while it is still yesterday in UTC.
describe('dates that are not more than a day after today (UTC)', () => {
  const TODAY = new Date('2026-11-23') // injected, so the tests do not depend on the clock
  const day = (iso: string) => new Date(iso)
  const issuesAt = (set: DataSet, today: Date = TODAY) =>
    checkDataSet(set, { today }).filter((issue) => issue.code === 'future-date')

  test('the fixtures are dated today at the latest, so they pass on the day they were written', () => {
    expect(checkDataSet(fresh(), { today: TODAY })).toEqual([])
  })

  test('a source accessed today or tomorrow passes, and one accessed the day after is refused', () => {
    const set = fresh()
    const source = find(set.parts, 'fixture-wheel').data.sources[0]
    if (!source) throw new Error('fixture has a source')
    source.accessed = day('2026-11-23') // today
    expect(issuesAt(set)).toEqual([])
    source.accessed = day('2026-11-24') // tomorrow: still today somewhere east of UTC
    expect(issuesAt(set)).toEqual([])
    source.accessed = day('2026-11-25') // two days ahead: a typo, not a time zone
    const issues = issuesAt(set)
    expect(issues).toHaveLength(1)
    expect(issues[0]?.file).toBe('parts/e46/fixture-wheel.yaml')
    expect(issues[0]?.message).toContain('2026-11-25')
    expect(issues[0]?.message).toContain('2026-11-23')
    expect(issues[0]?.message).toMatch(/more than a day/)
  })

  test('the slack is one day across a month and a year boundary', () => {
    const set = fresh()
    const source = find(set.parts, 'fixture-wheel').data.sources[0]
    if (!source) throw new Error('fixture has a source')
    for (const [today, ok, bad] of [
      ['2026-11-30', '2026-12-01', '2026-12-02'],
      ['2026-12-31', '2027-01-01', '2027-01-02'],
      ['2028-02-28', '2028-02-29', '2028-03-01'],
    ] as const) {
      source.accessed = day(ok)
      expect(issuesAt(set, day(today)), `${ok} after ${today}`).toEqual([])
      source.accessed = day(bad)
      expect(issuesAt(set, day(today)), `${bad} after ${today}`).toHaveLength(1)
    }
  })

  test('a price checked a day ahead passes, and two days ahead is refused, on a part and an option', () => {
    const set = fresh()
    const coil = find(set.parts, 'fixture-coilovers').data
    const price = coil.prices?.[0]
    if (!price) throw new Error('fixture has a part price')
    price.checked = day('2026-11-24')
    expect(issuesAt(set)).toEqual([])
    price.checked = day('2026-11-25')
    expect(issuesAt(set).map((issue) => issue.file)).toEqual(['parts/e46/fixture-coilovers.yaml'])

    const optioned = fresh()
    const option = find(optioned.parts, 'fixture-wheel').data.options?.[1]?.prices?.[0]
    if (!option) throw new Error('fixture has an option price')
    option.checked = day('2027-01-01')
    const found = issuesAt(optioned)
    expect(found).toHaveLength(1)
    expect(found[0]?.message).toContain('price')
    expect(found[0]?.message).toContain('2027-01-01')
  })

  test.each([
    ['generation sources', (set: DataSet) => find(set.generations, 'e46').data.sources],
    [
      'dimension sources',
      (set: DataSet) => find(set.generations, 'e46').data.dimensions.coupe?.sources ?? [],
    ],
    ['fitment sources', (set: DataSet) => find(set.generations, 'e46').data.fitment.sources],
    ['variant sources', (set: DataSet) => find(set.variants, 'e46-us-coupe').data.sources],
    [
      'maintenance sources',
      (set: DataSet) => find(set.maintenance, 'fixture-oil-service').data.sources,
    ],
    ['issue sources', (set: DataSet) => find(set.issues, 'fixture-rod-bearings').data.sources],
  ])('a future access date in %s is refused', (_label, pick) => {
    const set = fresh()
    const source = pick(set)[0]
    if (!source) throw new Error('fixture has a source')
    source.accessed = day('2030-01-01')
    expect(issuesAt(set).map((issue) => issue.code)).toEqual(['future-date'])
  })

  test('an eye point source with a future date is refused too', () => {
    const set = fresh()
    const generation = find(set.generations, 'e46').data
    generation.driverEyePoint.sources.push({
      title: 't',
      publisher: 'p',
      tier: 2,
      accessed: day('2030-01-01'),
    })
    expect(issuesAt(set)).toHaveLength(1)
  })

  test('every future date is reported, one issue each', () => {
    const set = fresh()
    for (const part of set.parts) {
      for (const source of part.data.sources) source.accessed = day('2030-01-01')
    }
    expect(issuesAt(set).length).toBeGreaterThan(1)
  })

  test('today moves with the clock that is passed in', () => {
    const set = fresh() // its dates are 2026-11-23
    expect(issuesAt(set, day('2026-11-21'))).not.toEqual([])
    expect(issuesAt(set, day('2026-11-22'))).toEqual([]) // 11-23 is a day ahead of 11-22
    expect(issuesAt(set, day('2026-11-23'))).toEqual([])
    expect(issuesAt(set, day('2030-01-01'))).toEqual([])
  })

  test('with no clock passed in, the real date is used', () => {
    const set = fresh()
    expect(checkDataSet(set).filter((issue) => issue.code === 'future-date')).toEqual([])
    const source = find(set.parts, 'fixture-wheel').data.sources[0]
    if (!source) throw new Error('fixture has a source')
    source.accessed = day('2999-01-01')
    expect(checkDataSet(set).map((issue) => issue.code)).toEqual(['future-date'])
  })

  test('a time of day on the clock does not matter: only the calendar date counts', () => {
    const set = fresh()
    const source = find(set.parts, 'fixture-wheel').data.sources[0]
    if (!source) throw new Error('fixture has a source')
    source.accessed = day('2026-11-23')
    expect(issuesAt(set, new Date('2026-11-23T00:00:00.000Z'))).toEqual([])
    expect(issuesAt(set, new Date('2026-11-23T23:59:59.999Z'))).toEqual([])
    expect(issuesAt(set, new Date('2026-11-22T23:59:59.999Z'))).toEqual([]) // today is the 22nd
    expect(issuesAt(set, new Date('2026-11-21T23:59:59.999Z'))).not.toEqual([]) // today is the 21st
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
