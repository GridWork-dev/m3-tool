import { describe, expect, test } from 'vitest'
import { loadDataSet } from '../../../src/data/load.ts'
import {
  DateLike,
  Generation,
  isNoScheduleTrigger,
  KnownIssue,
  MAINTENANCE_TRIGGERS,
  MaintenanceItem,
  NO_SCHEDULE_TRIGGERS,
  Part,
  PriceObservation,
  Source,
  Variant,
} from '../../../src/data/schemas.ts'
import { edit, issueMessages, issuePaths, readFixture, VALID_FIXTURES } from './helpers.ts'

const generation = () => readFixture('generations/e46.yaml')
const variant = () => readFixture('variants/e46/e46-us-coupe.yaml')
const cslVariant = () => readFixture('variants/e46/fixture-csl-coupe.yaml')
const wheel = () => readFixture('parts/e46/fixture-wheel.yaml')
const generic = () => readFixture('parts/e46/fixture-generic-wheels.yaml')
const coilovers = () => readFixture('parts/e46/fixture-coilovers.yaml')
const trunkLid = () => readFixture('parts/e46/fixture-trunk-lid.yaml')
// Miles, months, a cost and no triggers or markets.
const maintenance = () => readFixture('maintenance/e46/fixture-oil-service.yaml')
// Two triggers (break-in and inspection-ii) and no miles, months or cost, for one market.
const inspectionService = () => readFixture('maintenance/e46/fixture-inspection-service.yaml')
// A lifetime-fill trigger alone, with no markets (every market).
const lifetimeFluid = () => readFixture('maintenance/e46/fixture-lifetime-fluid.yaml')
// A forum-only issue: no fix and no cost.
const issue = () => readFixture('issues/e46/fixture-rod-bearings.yaml')
// An issue with a fix, a cost and a Tier 2 source.
const issueWithFix = () => readFixture('issues/e46/fixture-guide-wear.yaml')
// An issue with a fix and a Tier 2 source, and no cost.
const issueFixNoCost = () => readFixture('issues/e46/fixture-fix-without-cost.yaml')

// The unmutated fixtures must pass, so a failing mutation below is the mutation's doing.
describe('valid fixtures', () => {
  test('the valid fixture set loads with no issues', async () => {
    expect((await loadDataSet(VALID_FIXTURES)).issues).toEqual([])
  })

  test.each([
    ['generation', Generation, generation],
    ['variant', Variant, variant],
    ['variant that swaps body modules', Variant, cslVariant],
    ['branded part with options', Part, wheel],
    ['generic part', Part, generic],
    ['branded part with attributes', Part, coilovers],
    ['part that replaces a body module', Part, trunkLid],
    ['maintenance item', MaintenanceItem, maintenance],
    [
      'maintenance item with two triggers, one market and no cost',
      MaintenanceItem,
      inspectionService,
    ],
    ['maintenance item with a lifetime-fill trigger alone', MaintenanceItem, lifetimeFluid],
    ['known issue without a fix', KnownIssue, issue],
    ['known issue with a fix and a cost', KnownIssue, issueWithFix],
    ['known issue with a fix and no cost', KnownIssue, issueFixNoCost],
  ])('%s parses', (_name, schema, read) => {
    expect(schema.safeParse(read()).success).toBe(true)
  })
})

describe('price observation', () => {
  const base = { amount: 1, currency: 'USD', seller: 'S' } as const

  test('YAML date strings and Date objects parse to the same instant', () => {
    expect(PriceObservation.parse({ ...base, checked: '2026-11-23' }).checked.getTime()).toBe(
      PriceObservation.parse({ ...base, checked: new Date('2026-11-23') }).checked.getTime(),
    )
  })

  test('rejects a price without a seller or with an unparseable date', () => {
    const ok = { ...base, checked: '2026-11-23' }
    expect(PriceObservation.safeParse(ok).success).toBe(true)
    const noSeller = PriceObservation.safeParse({ ...ok, seller: '' })
    expect(noSeller.success).toBe(false)
    expect(issuePaths(noSeller)).toContain('seller')
    const soon = PriceObservation.safeParse({ ...ok, checked: 'soon' })
    expect(soon.success).toBe(false)
    expect(issuePaths(soon)).toContain('checked')
    expect(PriceObservation.safeParse({ ...ok, checked: new Date('soon') }).success).toBe(false)
    expect(PriceObservation.safeParse({ amount: 1, currency: 'USD', seller: 'S' }).success).toBe(
      false,
    )
  })

  test('rejects a zero or negative amount, an unknown currency and a non-https url', () => {
    const ok = { ...base, checked: '2026-11-23' }
    expect(PriceObservation.safeParse({ ...ok, amount: 0 }).success).toBe(false)
    expect(PriceObservation.safeParse({ ...ok, amount: -5 }).success).toBe(false)
    expect(PriceObservation.safeParse({ ...ok, currency: 'GBP' }).success).toBe(false)
    expect(PriceObservation.safeParse({ ...ok, url: 'https://example.com/x' }).success).toBe(true)
    expect(PriceObservation.safeParse({ ...ok, url: 'http://example.com/x' }).success).toBe(false)
    expect(PriceObservation.safeParse({ ...ok, url: '//example.com/x' }).success).toBe(false)
  })
})

describe('DateLike', () => {
  const rejected = [
    // Datetimes depend on the host time zone or on a time zone suffix, so they are not dates.
    '2026-11-23T10:30',
    '2026-11-23 10:30',
    '2026-11-23T10:30:00Z',
    '2026-11-23T10:30:00.000+01:00',
    '2026-02-31T10:00:00Z', // would roll over into March
    '2026-11-23T24:00:00Z', // would roll over into the next day
    // Date-only strings that are not real calendar dates.
    '2026-02-31',
    '2026-02-29',
    '2026-13-01',
    '2026-00-10',
    '2026-11-00',
    '2026-11-31',
    // Anything else V8 would happily guess at.
    '1',
    'soon',
    'Nov 23 2026',
    '2026-4-5',
    '2026-11-23 ',
    '',
    // Years outside 1900 to 2100 are typos: a swapped digit, or a year with the century left off.
    '1899-12-31',
    '2101-01-01',
    '0001-01-01',
    '0026-11-23',
    '9999-12-31',
  ]

  test('accepts the first and last day of the years 1900 to 2100, as strings and as Dates', () => {
    for (const value of ['1900-01-01', '2100-12-31']) {
      expect(DateLike.safeParse(value).success).toBe(true)
      expect(DateLike.safeParse(new Date(value)).success).toBe(true)
    }
  })

  test('rejects a year outside 1900 to 2100, as a string and as a Date, and says why', () => {
    for (const value of ['1899-12-31', '2101-01-01']) {
      const asString = DateLike.safeParse(value)
      expect(asString.success).toBe(false)
      expect(issueMessages(asString).join(' ')).toMatch(/1900 to 2100/)
      expect(DateLike.safeParse(new Date(value)).success).toBe(false)
    }
    expect(DateLike.safeParse(new Date(Date.UTC(1850, 0, 1))).success).toBe(false)
  })

  test('accepts a calendar date string, and a Date at exactly UTC midnight', () => {
    expect(DateLike.safeParse('2026-11-23').success).toBe(true)
    expect(DateLike.safeParse('2024-02-29').success).toBe(true) // a real leap day
    expect(DateLike.safeParse(new Date('2026-11-23')).success).toBe(true)
    expect(DateLike.safeParse(new Date(Date.UTC(2026, 10, 23))).success).toBe(true)
  })

  test('YAML date strings and Date objects parse to the same instant', () => {
    const fromString = DateLike.parse('2026-11-23')
    const fromDate = DateLike.parse(new Date('2026-11-23'))
    expect(fromString.getTime()).toBe(Date.UTC(2026, 10, 23))
    expect(fromDate.getTime()).toBe(fromString.getTime())
  })

  test.each(rejected)('rejects the string %j', (value) => {
    expect(DateLike.safeParse(value).success).toBe(false)
  })

  test('says why a datetime string is refused', () => {
    const result = DateLike.safeParse('2026-11-23T10:30')
    expect(result.success).toBe(false)
    expect(issueMessages(result).join(' ')).toMatch(/no time of day/)
    const impossible = DateLike.safeParse('2026-02-31')
    expect(issueMessages(impossible).join(' ')).toMatch(/not a real calendar date/)
  })

  test('rejects a Date with a time of day, and an invalid Date', () => {
    expect(DateLike.safeParse(new Date('2026-11-23T10:30:00Z')).success).toBe(false)
    expect(DateLike.safeParse(new Date('2026-11-23T00:00:00.001Z')).success).toBe(false)
    expect(DateLike.safeParse(new Date('2026-11-22T23:59:59.999Z')).success).toBe(false)
    expect(DateLike.safeParse(new Date('soon')).success).toBe(false)
  })

  test('rejects values that are not strings or dates', () => {
    for (const value of [20261123, 0, null, undefined, true, {}, []]) {
      expect(DateLike.safeParse(value).success).toBe(false)
    }
  })

  // Re-run with TZ=Asia/Tokyo and TZ=America/Los_Angeles on the command line too. This test
  // switches the zone inside the process, so a regression shows up in a plain `pnpm test`.
  test.each([
    ['Asia/Tokyo', -540],
    ['America/Los_Angeles', 480],
    ['UTC', 0],
  ])('gives the same answers in %s', (zone, januaryOffsetMinutes) => {
    const previous = process.env.TZ
    process.env.TZ = zone
    try {
      expect(new Date(2026, 0, 15).getTimezoneOffset()).toBe(januaryOffsetMinutes) // zone took effect
      expect(DateLike.parse('2026-11-23').toISOString()).toBe('2026-11-23T00:00:00.000Z')
      expect(DateLike.parse(new Date('2026-11-23')).toISOString()).toBe('2026-11-23T00:00:00.000Z')
      for (const value of rejected) expect(DateLike.safeParse(value).success).toBe(false)
      expect(DateLike.safeParse(new Date('2026-11-23T10:30:00Z')).success).toBe(false)
    } finally {
      if (previous === undefined) delete process.env.TZ
      else process.env.TZ = previous
    }
  })
})

describe('source', () => {
  const ok = { title: 't', publisher: 'p', tier: 1, accessed: '2026-11-23' }

  test('accepts tiers 1 to 3 and rejects anything else', () => {
    for (const tier of [1, 2, 3]) expect(Source.safeParse({ ...ok, tier }).success).toBe(true)
    for (const tier of [0, 4, '1']) expect(Source.safeParse({ ...ok, tier }).success).toBe(false)
  })

  test('url must be https and the access date must parse', () => {
    expect(Source.safeParse({ ...ok, url: 'https://example.com' }).success).toBe(true)
    expect(Source.safeParse({ ...ok, url: 'http://example.com' }).success).toBe(false)
    expect(Source.safeParse({ ...ok, accessed: 'yesterday' }).success).toBe(false)
  })
})

describe('required text', () => {
  const ok = { amount: 1, currency: 'USD', seller: 'S', checked: '2026-11-23' }
  const blanks = ['', ' ', '   ', '\t', '\n', ' \t\n ', '\u00a0', '\u3000']

  test.each(blanks)('rejects the blank seller %j', (seller) => {
    const r = PriceObservation.safeParse({ ...ok, seller })
    expect(r.success).toBe(false)
    expect(issuePaths(r)).toContain('seller')
  })

  test('rejects whitespace-only fields wherever Text is used', () => {
    const cases: [string, unknown, string][] = [
      [
        'source title',
        Source.safeParse({ title: ' ', publisher: 'p', tier: 1, accessed: '2026-11-23' }),
        'title',
      ],
      [
        'source publisher',
        Source.safeParse({ title: 't', publisher: '  ', tier: 1, accessed: '2026-11-23' }),
        'publisher',
      ],
      [
        'optional source note',
        Source.safeParse({
          title: 't',
          publisher: 'p',
          tier: 1,
          accessed: '2026-11-23',
          note: ' ',
        }),
        'note',
      ],
      ['generation name', Generation.safeParse(edit(generation(), 'name', '   ')), 'name'],
      ['part name', Part.safeParse(edit(wheel(), 'name', ' ')), 'name'],
      ['maintenance title', MaintenanceItem.safeParse(edit(maintenance(), 'title', '  ')), 'title'],
      ['issue cause', KnownIssue.safeParse(edit(issue(), 'cause', '\t')), 'cause'],
      [
        'issue symptom',
        KnownIssue.safeParse(edit(issue(), 'symptoms', ['Knock', '  '])),
        'symptoms.1',
      ],
    ]
    for (const [name, result, path] of cases) {
      const parsed = result as Parameters<typeof issuePaths>[0]
      expect(parsed.success, name).toBe(false)
      expect(issuePaths(parsed), name).toContain(path)
    }
  })

  test('keeps the original value: nothing is trimmed or transformed', () => {
    const padded = ' Bosch \n'
    expect(PriceObservation.parse({ ...ok, seller: padded }).seller).toBe(padded)
    expect(PriceObservation.parse({ ...ok, seller: 'a  b' }).seller).toBe('a  b')
  })

  test('an optional text field may still be left out', () => {
    expect(
      Source.safeParse({ title: 't', publisher: 'p', tier: 1, accessed: '2026-11-23' }).success,
    ).toBe(true)
  })
})

describe('part', () => {
  test('rejects prices on a generic (brandless) part, including option prices', () => {
    const price = { amount: 5, currency: 'USD', seller: 'S', checked: '2026-11-23' }
    const partLevel = edit(generic(), 'prices', [price])
    const r1 = Part.safeParse(partLevel)
    expect(r1.success).toBe(false)
    expect(issuePaths(r1)).toContain('prices')

    const optionLevel = edit(wheel(), 'brand', undefined)
    const r2 = Part.safeParse(optionLevel)
    expect(r2.success).toBe(false)
    expect(issuePaths(r2)).toContain('options.0.prices')
    expect(issuePaths(r2)).toContain('options.1.prices')

    const coil = Part.safeParse(edit(coilovers(), 'brand', undefined))
    expect(coil.success).toBe(false)
    expect(issuePaths(coil)).toContain('prices')
  })

  test('requires model when visible and forbids it when not', () => {
    const noModel = Part.safeParse(edit(wheel(), 'model', undefined))
    expect(noModel.success).toBe(false)
    expect(issuePaths(noModel)).toContain('model')

    const hiddenWithModel = Part.safeParse(edit(generic(), 'model', { standIn: 'fixture-style' }))
    expect(hiddenWithModel.success).toBe(false)
    expect(issuePaths(hiddenWithModel)).toContain('model')

    // The flip side of both stays valid.
    expect(Part.safeParse(edit(wheel(), 'visible', false)).success).toBe(false)
    expect(Part.safeParse(edit(edit(wheel(), 'visible', false), 'model', undefined)).success).toBe(
      true,
    )
  })

  test('a model names exactly one of asset or standIn', () => {
    const both = edit(wheel(), 'model', { asset: 'a-1', standIn: 's-1' })
    expect(Part.safeParse(both).success).toBe(false)
    expect(Part.safeParse(edit(wheel(), 'model', {})).success).toBe(false)
    expect(
      Part.safeParse(edit(wheel(), 'model', { asset: 'a-1', params: { size: 18 } })).success,
    ).toBe(true)
  })

  test('rejects part-level attributes or prices when options exist', () => {
    const attributes = {
      kind: 'wheel',
      diameterIn: 17,
      widthIn: 8,
      offsetMm: 35,
      boltPattern: '5x120',
      centerBoreMm: 72.6,
      axle: 'both',
    }
    const withAttributes = Part.safeParse(edit(wheel(), 'attributes', attributes))
    expect(withAttributes.success).toBe(false)
    expect(issuePaths(withAttributes)).toContain('attributes')

    const price = { amount: 5, currency: 'USD', seller: 'S', checked: '2026-11-23' }
    const withPrices = Part.safeParse(edit(wheel(), 'prices', [price]))
    expect(withPrices.success).toBe(false)
    expect(issuePaths(withPrices)).toContain('prices')
  })

  test('rejects duplicate option ids and an empty options list', () => {
    const dup = Part.safeParse(edit(wheel(), 'options.1.id', 'fixture-wheel-17x8'))
    expect(dup.success).toBe(false)
    expect(issuePaths(dup)).toContain('options.1.id')
    expect(Part.safeParse(edit(wheel(), 'options', [])).success).toBe(false)
  })

  test('rejects wheel attributes on a part outside the wheels category', () => {
    const wrongCategory = Part.safeParse(edit(wheel(), 'category', 'tires'))
    expect(wrongCategory.success).toBe(false)
    expect(issuePaths(wrongCategory)).toContain('options.0.attributes.kind')

    const wheelAttrsOnSuspension = edit(coilovers(), 'attributes', {
      kind: 'wheel',
      diameterIn: 17,
      widthIn: 8,
      offsetMm: 35,
      boltPattern: '5x120',
      centerBoreMm: 72.6,
      axle: 'both',
    })
    const r = Part.safeParse(wheelAttrsOnSuspension)
    expect(r.success).toBe(false)
    expect(issuePaths(r)).toContain('attributes.kind')
  })

  test.each([
    [
      'tire',
      'tires',
      { kind: 'tire', size: '225/45ZR18', approvedRimWidthIn: [7.5, 8.5], axle: 'front' },
    ],
    ['brake-kit', 'brakes', { kind: 'brake-kit', axle: 'front', minWheelDiameterIn: 18 }],
    ['hub-ring', 'wheels', { kind: 'hub-ring', outerMm: 72.6, innerMm: 66.6 }],
    ['suspension', 'suspension', { kind: 'suspension', rideDropMm: [10, 30] }],
  ])('%s attributes belong to the %s category only', (_kind, category, attributes) => {
    const good = edit(edit(coilovers(), 'category', category), 'attributes', attributes)
    expect(Part.safeParse(good).success).toBe(true)
    const bad = edit(good, 'category', 'interior')
    const r = Part.safeParse(bad)
    expect(r.success).toBe(false)
    expect(issuePaths(r)).toContain('attributes.kind')
  })

  test('rejects malformed attributes', () => {
    const bad = (path: string, value: unknown) =>
      Part.safeParse(edit(wheel(), `options.0.attributes.${path}`, value)).success
    expect(bad('boltPattern', '5-120')).toBe(false)
    expect(bad('axle', 'middle')).toBe(false)
    expect(bad('diameterIn', 'big')).toBe(false)
    const tire = (size: string, range: unknown) =>
      Part.safeParse(
        edit(edit(coilovers(), 'category', 'tires'), 'attributes', {
          kind: 'tire',
          size,
          approvedRimWidthIn: range,
          axle: 'both',
        }),
      ).success
    expect(tire('225/45ZR18', [7.5, 8.5])).toBe(true)
    expect(tire('225/45R18', [7.5, 8.5])).toBe(true)
    expect(tire('225-45-18', [7.5, 8.5])).toBe(false)
    expect(tire('225/45ZR18', [9, 8])).toBe(false)
    expect(tire('225/45ZR18', [-1, 8])).toBe(false)
  })

  test('rejects part fields that break the shape', () => {
    expect(Part.safeParse(edit(wheel(), 'labor.hours', [3, 1])).success).toBe(false)
    expect(Part.safeParse(edit(wheel(), 'labor.diy', 'expert')).success).toBe(false)
    expect(Part.safeParse(edit(wheel(), 'category', 'paint')).success).toBe(false)
    expect(Part.safeParse(edit(wheel(), 'fits.years', [2006, 2000])).success).toBe(false)
    expect(Part.safeParse(edit(wheel(), 'fits.bodies', ['hatchback'])).success).toBe(false)
    expect(Part.safeParse(edit(wheel(), 'verified', undefined)).success).toBe(false)
  })

  test('rejects unknown keys so a typo cannot silently drop a field', () => {
    const typo = Part.safeParse(edit(wheel(), 'brnad', 'Fixture Co'))
    expect(typo.success).toBe(false)
    expect(issueMessages(typo).join(' ')).toMatch(/brnad/)
  })

  test('rejects non-kebab ids', () => {
    for (const id of ['E46_Coupe', 'E46', 'e46_coupe', '-e46', 'e46-', 'e46--coupe', '', 'e 46']) {
      const r = Part.safeParse(edit(wheel(), 'id', id))
      expect(r.success, `id "${id}" should be rejected`).toBe(false)
      expect(issuePaths(r)).toContain('id')
    }
    expect(Part.safeParse(edit(wheel(), 'id', 'e46-coupe-2')).success).toBe(true)
    expect(Variant.safeParse(edit(variant(), 'id', 'E46_Coupe')).success).toBe(false)
    expect(Generation.safeParse(edit(generation(), 'id', 'E46_Coupe')).success).toBe(false)
    expect(MaintenanceItem.safeParse(edit(maintenance(), 'id', 'E46_Coupe')).success).toBe(false)
    expect(KnownIssue.safeParse(edit(issue(), 'id', 'E46_Coupe')).success).toBe(false)
    expect(Part.safeParse(edit(wheel(), 'requires', ['Not_Kebab'])).success).toBe(false)
  })
})

describe('part labor estimates (spec 7.3 and 7.6)', () => {
  test('estimated labor needs no source', () => {
    const noSources = edit(edit(wheel(), 'sources', []), 'labor.estimated', true)
    expect(Part.safeParse(noSources).success).toBe(true)
    expect(Part.safeParse(generic()).success).toBe(true) // no sources, estimated labor
  })

  test('labor that is not an estimate fails without a source on the part', () => {
    const r = Part.safeParse(edit(edit(wheel(), 'sources', []), 'labor.estimated', false))
    expect(r.success).toBe(false)
    expect(issuePaths(r)).toEqual(['labor.estimated'])
    expect(issueMessages(r).join(' ')).toMatch(/not an estimate needs at least one source/)
  })

  test('a generic part has no sources, so its labor has to be an estimate', () => {
    const r = Part.safeParse(edit(generic(), 'labor.estimated', false))
    expect(r.success).toBe(false)
    expect(issuePaths(r)).toEqual(['labor.estimated'])
  })

  test('labor that is not an estimate passes with a source, whatever its tier', () => {
    const sourced = edit(wheel(), 'labor.estimated', false)
    expect(Part.safeParse(sourced).success).toBe(true)
    const forum = edit(structuredClone(sourced), 'sources.0.tier', 3)
    expect(Part.safeParse(forum).success).toBe(true)
  })

  test('estimated is required and has no default', () => {
    const missing = Part.safeParse(edit(wheel(), 'labor.estimated', undefined))
    expect(missing.success).toBe(false)
    expect(issuePaths(missing)).toEqual(['labor.estimated'])
    expect(Part.safeParse(edit(wheel(), 'labor.estimated', 'yes')).success).toBe(false)
    expect(Part.safeParse(edit(wheel(), 'labor.estimated', null)).success).toBe(false)
  })
})

describe('part body module swaps', () => {
  const model = (m: Record<string, unknown>) => edit(wheel(), 'model', m)

  test('a stand-in model may replace body modules', () => {
    const parsed = Part.safeParse(model({ standIn: 's-1', replaces: ['trunk_lid'] }))
    expect(parsed.success).toBe(true)
    expect(Part.parse(trunkLid()).model).toEqual({
      standIn: 'fixture-style',
      replaces: ['trunk_lid'],
    })
  })

  test('an asset model may replace body modules, with params', () => {
    const parsed = Part.safeParse(
      model({
        asset: 'a-1',
        params: { finish: 'matte' },
        replaces: ['bumper_front', 'bumper_rear'],
      }),
    )
    expect(parsed.success).toBe(true)
    expect(parsed.data?.model).toEqual({
      asset: 'a-1',
      params: { finish: 'matte' },
      replaces: ['bumper_front', 'bumper_rear'],
    })
  })

  test('every module name is accepted', () => {
    for (const name of ['bumper_front', 'bumper_rear', 'trunk_lid', 'roof']) {
      expect(Part.safeParse(model({ standIn: 's-1', replaces: [name] })).success).toBe(true)
    }
  })

  test('replaces is optional', () => {
    expect(Part.safeParse(model({ standIn: 's-1' })).success).toBe(true)
  })

  test.each([
    ['an empty list', [], /at least one/],
    ['a repeated module', ['trunk_lid', 'trunk_lid'], /more than once|repeat/],
    ['a repeat after another module', ['roof', 'trunk_lid', 'roof'], /more than once|repeat/],
    ['a module that does not exist', ['hood'], /hood.*bumper_front, bumper_rear, trunk_lid, roof/],
    ['a name with the wrong case', ['Trunk_Lid'], /Trunk_Lid/],
    ['a good module beside a bad one', ['trunk_lid', 'hood'], /hood/],
    ['a string instead of a list', 'trunk_lid', /replaces/],
    ['a list of numbers', [1], /replaces/],
  ])('rejects replaces with %s, on either kind of model', (_label, replaces, reason) => {
    for (const base of [{ standIn: 's-1' }, { asset: 'a-1' }]) {
      const result = Part.safeParse(model({ ...base, replaces }))
      expect(result.success).toBe(false)
      // The failure names `replaces`: in the path, or in the message that sits at `model`.
      const where = issuePaths(result).join(' ')
      const said = issueMessages(result).join(' ')
      expect(where.includes('replaces') || said.includes('replaces')).toBe(true)
      expect(said).toMatch(reason)
    }
  })

  test('the error for an unknown module still names the model shape when replaces is fine', () => {
    const result = Part.safeParse(model({ replaces: ['trunk_lid'] }))
    expect(result.success).toBe(false)
    expect(issuePaths(result)).toContain('model')
    expect(issueMessages(result).join(' ')).toContain('a model is')
  })

  test('replaces does not unlock other keys on the model', () => {
    const result = Part.safeParse(model({ standIn: 's-1', replaces: ['roof'], swaps: ['roof'] }))
    expect(result.success).toBe(false)
  })

  test('a model still names exactly one of asset or standIn, with replaces present', () => {
    expect(
      Part.safeParse(model({ asset: 'a-1', standIn: 's-1', replaces: ['roof'] })).success,
    ).toBe(false)
  })

  test('a part that is not visible has no model, so it replaces nothing', () => {
    const hidden = edit(edit(generic(), 'model', undefined), 'visible', false)
    expect(Part.safeParse(hidden).success).toBe(true)
    expect(
      Part.safeParse(edit(hidden, 'model', { standIn: 's-1', replaces: ['roof'] })).success,
    ).toBe(false)
  })
})

describe('maintenance item and known issue', () => {
  test('rejects inspectWhenBuying without howToCheck', () => {
    const noCheck = edit(maintenance(), 'inspectWhenBuying', true)
    const r1 = MaintenanceItem.safeParse(noCheck)
    expect(r1.success).toBe(false)
    expect(issuePaths(r1)).toContain('howToCheck')
    const blank = MaintenanceItem.safeParse(edit(noCheck, 'howToCheck', ''))
    expect(blank.success).toBe(false)
    expect(MaintenanceItem.safeParse(edit(noCheck, 'howToCheck', 'Look at it.')).success).toBe(true)

    const r2 = KnownIssue.safeParse(edit(issue(), 'howToCheck', undefined))
    expect(r2.success).toBe(false)
    expect(issuePaths(r2)).toContain('howToCheck')
    const blank2 = KnownIssue.safeParse(edit(issue(), 'howToCheck', ''))
    expect(blank2.success).toBe(false)
    // Without inspectWhenBuying, howToCheck stays optional.
    expect(
      KnownIssue.safeParse(edit(edit(issue(), 'howToCheck', undefined), 'inspectWhenBuying', false))
        .success,
    ).toBe(true)
  })

  test('rejects a maintenance interval with none of miles, months or triggers', () => {
    const none = MaintenanceItem.safeParse(edit(maintenance(), 'interval', {}))
    expect(none.success).toBe(false)
    expect(issuePaths(none)).toContain('interval')
    expect(issueMessages(none).join(' ')).toMatch(/miles, months or triggers/)
    // A key that is present but undefined is as empty as no key.
    const undef = MaintenanceItem.safeParse(
      edit(maintenance(), 'interval', { miles: undefined, months: undefined, triggers: undefined }),
    )
    expect(undef.success).toBe(false)
    expect(issuePaths(undef)).toContain('interval')
    expect(MaintenanceItem.safeParse(edit(maintenance(), 'interval', { months: 12 })).success).toBe(
      true,
    )
    expect(
      MaintenanceItem.safeParse(edit(maintenance(), 'interval', { miles: 7500 })).success,
    ).toBe(true)
    expect(MaintenanceItem.safeParse(edit(maintenance(), 'interval', { miles: 0 })).success).toBe(
      false,
    )
    expect(
      MaintenanceItem.safeParse(edit(maintenance(), 'interval', { miles: 5000.5 })).success,
    ).toBe(false)
  })

  test('triggers is a non-empty list: an empty list or a bare string is rejected', () => {
    const empty = MaintenanceItem.safeParse(edit(maintenance(), 'interval', { triggers: [] }))
    expect(empty.success).toBe(false)
    expect(issuePaths(empty)).toContain('interval.triggers')
    // An empty list is not "a trigger" either, so it does not rescue an interval with a number.
    const emptyBesideMiles = MaintenanceItem.safeParse(
      edit(maintenance(), 'interval', { miles: 7500, triggers: [] }),
    )
    expect(emptyBesideMiles.success).toBe(false)
    expect(issuePaths(emptyBesideMiles)).toContain('interval.triggers')
    const bare = MaintenanceItem.safeParse(
      edit(maintenance(), 'interval', { triggers: 'oil-service' }),
    )
    expect(bare.success).toBe(false)
    expect(issuePaths(bare)).toContain('interval.triggers')
  })

  test('accepts each trigger alone in a one-item list, and rejects a value outside the list', () => {
    expect([...MAINTENANCE_TRIGGERS]).toEqual([
      'break-in',
      'oil-service',
      'inspection-i',
      'inspection-ii',
      'lifetime-fill',
      'condition-based',
    ])
    for (const trigger of MAINTENANCE_TRIGGERS) {
      expect(
        MaintenanceItem.safeParse(edit(maintenance(), 'interval', { triggers: [trigger] })).success,
        trigger,
      ).toBe(true)
    }
    for (const bad of ['Oil Service', 'oil_service', 'inspection-iii', '1200-mile-service', '']) {
      const r = MaintenanceItem.safeParse(edit(maintenance(), 'interval', { triggers: [bad] }))
      expect(r.success, bad).toBe(false)
      expect(issuePaths(r), bad).toContain('interval.triggers.0')
    }
  })

  test('one item may have several triggers: the booklet ties items to two services', () => {
    const lists = [
      ['oil-service', 'inspection-i'],
      ['break-in', 'inspection-ii'],
      ['break-in', 'oil-service', 'inspection-i'],
      ['inspection-ii', 'break-in'],
      ['inspection-ii', 'oil-service'],
    ]
    for (const triggers of lists) {
      expect(
        MaintenanceItem.safeParse(edit(maintenance(), 'interval', { triggers })).success,
        triggers.join(),
      ).toBe(true)
    }
    expect(inspectionService().interval).toEqual({ triggers: ['break-in', 'inspection-ii'] })
  })

  test('rejects a trigger named twice', () => {
    const twice = MaintenanceItem.safeParse(
      edit(maintenance(), 'interval', { triggers: ['oil-service', 'oil-service'] }),
    )
    expect(twice.success).toBe(false)
    expect(issuePaths(twice)).toContain('interval.triggers')
    expect(issueMessages(twice).join(' ')).toMatch(/more than once/)
    const apart = MaintenanceItem.safeParse(
      edit(maintenance(), 'interval', {
        triggers: ['inspection-i', 'oil-service', 'inspection-i'],
      }),
    )
    expect(apart.success).toBe(false)
    expect(issuePaths(apart)).toContain('interval.triggers')
  })

  test('lifetime-fill and condition-based must be the only trigger', () => {
    for (const alone of ['lifetime-fill', 'condition-based']) {
      expect(
        MaintenanceItem.safeParse(edit(maintenance(), 'interval', { triggers: [alone] })).success,
        alone,
      ).toBe(true)
    }
    const mixes = [
      ['lifetime-fill', 'oil-service'],
      ['oil-service', 'lifetime-fill'],
      ['condition-based', 'inspection-i'],
      ['inspection-ii', 'condition-based'],
      ['lifetime-fill', 'condition-based'],
      ['condition-based', 'lifetime-fill'],
      ['break-in', 'inspection-i', 'lifetime-fill'],
    ]
    for (const triggers of mixes) {
      const r = MaintenanceItem.safeParse(edit(maintenance(), 'interval', { triggers }))
      expect(r.success, triggers.join()).toBe(false)
      expect(issuePaths(r), triggers.join()).toContain('interval.triggers')
      expect(issueMessages(r).join(' '), triggers.join()).toMatch(/only trigger/)
    }
  })

  test('miles and months may sit beside a single trigger', () => {
    const both = { miles: 60000, months: 48, triggers: ['inspection-ii'] }
    expect(MaintenanceItem.safeParse(edit(maintenance(), 'interval', both)).success).toBe(true)
    const one = { miles: 60000, triggers: ['inspection-ii'] }
    expect(MaintenanceItem.safeParse(edit(maintenance(), 'interval', one)).success).toBe(true)
    // The other interval rules still apply beside a trigger.
    const zero = MaintenanceItem.safeParse(
      edit(maintenance(), 'interval', { miles: 0, triggers: ['inspection-ii'] }),
    )
    expect(zero.success).toBe(false)
    expect(issuePaths(zero)).toContain('interval.miles')
  })

  test('miles and months are rejected beside two or more triggers: a number is pinned to one', () => {
    // `miles: 1200` beside [break-in, inspection-ii] would read as the interval of both.
    const cases = [
      { miles: 1200, triggers: ['break-in', 'inspection-ii'] },
      { months: 12, triggers: ['oil-service', 'inspection-i'] },
      { miles: 60000, months: 48, triggers: ['break-in', 'inspection-ii'] },
      { miles: 15000, triggers: ['break-in', 'oil-service', 'inspection-i'] },
    ]
    for (const interval of cases) {
      const r = MaintenanceItem.safeParse(edit(maintenance(), 'interval', interval))
      expect(r.success, JSON.stringify(interval)).toBe(false)
      expect(issuePaths(r), JSON.stringify(interval)).toContain('interval')
      expect(issueMessages(r).join(' '), JSON.stringify(interval)).toMatch(/one trigger/)
    }
    // The same triggers without numbers are fine, and so is a number beside either one alone.
    expect(
      MaintenanceItem.safeParse(
        edit(maintenance(), 'interval', { triggers: ['break-in', 'inspection-ii'] }),
      ).success,
    ).toBe(true)
    for (const trigger of ['break-in', 'inspection-ii']) {
      const r = MaintenanceItem.safeParse(
        edit(maintenance(), 'interval', { miles: 1200, triggers: [trigger] }),
      )
      expect(r.success, trigger).toBe(true)
    }
  })

  test('inspection-i and inspection-ii are not listed together: inspection-ii repeats inspection-i', () => {
    const pairs = [
      ['inspection-i', 'inspection-ii'],
      ['inspection-ii', 'inspection-i'],
      ['oil-service', 'inspection-i', 'inspection-ii'],
      ['inspection-i', 'break-in', 'inspection-ii'],
    ]
    for (const triggers of pairs) {
      const r = MaintenanceItem.safeParse(edit(maintenance(), 'interval', { triggers }))
      expect(r.success, triggers.join()).toBe(false)
      expect(issuePaths(r), triggers.join()).toContain('interval.triggers')
      expect(issueMessages(r).join(' '), triggers.join()).toMatch(/lists 'inspection-i' only/)
    }
    // Each is fine alone and beside any other trigger, and an item due at both lists inspection-i.
    for (const triggers of [
      ['inspection-i'],
      ['inspection-ii'],
      ['inspection-i', 'oil-service'],
      ['inspection-i', 'break-in'],
      ['inspection-ii', 'break-in'],
      ['inspection-ii', 'oil-service'],
    ]) {
      expect(
        MaintenanceItem.safeParse(edit(maintenance(), 'interval', { triggers })).success,
        triggers.join(),
      ).toBe(true)
    }
  })

  test('the two no-schedule triggers are one shared constant', () => {
    expect([...NO_SCHEDULE_TRIGGERS]).toEqual(['lifetime-fill', 'condition-based'])
    for (const trigger of NO_SCHEDULE_TRIGGERS) {
      expect(MAINTENANCE_TRIGGERS).toContain(trigger)
      expect(isNoScheduleTrigger(trigger)).toBe(true)
    }
    for (const trigger of MAINTENANCE_TRIGGERS.filter(
      (t) => !NO_SCHEDULE_TRIGGERS.includes(t as never),
    )) {
      expect(isNoScheduleTrigger(trigger), trigger).toBe(false)
    }
    expect(isNoScheduleTrigger('annual')).toBe(false)
  })

  test('a lifetime-fill interval may not also carry miles or months', () => {
    expect(
      MaintenanceItem.safeParse(edit(maintenance(), 'interval', { triggers: ['lifetime-fill'] }))
        .success,
    ).toBe(true)
    for (const extra of [{ miles: 100000 }, { months: 48 }, { miles: 100000, months: 48 }]) {
      const r = MaintenanceItem.safeParse(
        edit(maintenance(), 'interval', { triggers: ['lifetime-fill'], ...extra }),
      )
      expect(r.success, JSON.stringify(extra)).toBe(false)
      expect(issuePaths(r), JSON.stringify(extra)).toContain('interval')
      expect(issueMessages(r).join(' '), JSON.stringify(extra)).toMatch(/lifetime-fill/)
    }
    // Every other trigger may still carry a number the source gives.
    for (const trigger of MAINTENANCE_TRIGGERS.filter((t) => t !== 'lifetime-fill')) {
      const withNumbers = { triggers: [trigger], miles: 60000, months: 48 }
      expect(
        MaintenanceItem.safeParse(edit(maintenance(), 'interval', withNumbers)).success,
        trigger,
      ).toBe(true)
    }
    // Miles or months without any trigger are unaffected.
    expect(
      MaintenanceItem.safeParse(edit(maintenance(), 'interval', { miles: 100000, months: 48 }))
        .success,
    ).toBe(true)
  })

  test('the interval takes no keys beyond miles, months and triggers', () => {
    const extra = MaintenanceItem.safeParse(
      edit(maintenance(), 'interval', { triggers: ['oil-service'], hours: 100 }),
    )
    expect(extra.success).toBe(false)
    // The old single-valued key is gone: a lone `trigger` is an unknown key now.
    const old = MaintenanceItem.safeParse(
      edit(maintenance(), 'interval', { trigger: 'oil-service' }),
    )
    expect(old.success).toBe(false)
  })

  test('a maintenance cost is optional, and never defaults to zero', () => {
    expect('cost' in inspectionService()).toBe(false)
    const parsed = MaintenanceItem.safeParse(inspectionService())
    expect(parsed.success).toBe(true)
    // Absent stays absent: the parser does not fill in a zero cost.
    expect(parsed.success && parsed.data.cost).toBeUndefined()
    expect(MaintenanceItem.safeParse(edit(maintenance(), 'cost', undefined)).success).toBe(true)
    // A cost that is given is still checked in full.
    expect(MaintenanceItem.safeParse(edit(maintenance(), 'cost', {})).success).toBe(false)
    expect(
      MaintenanceItem.safeParse(edit(maintenance(), 'cost', { currency: 'USD', shop: [60, 100] }))
        .success,
    ).toBe(false)
    expect(
      MaintenanceItem.safeParse(
        edit(maintenance(), 'cost', { currency: 'USD', diy: [100, 20], shop: [60, 100] }),
      ).success,
    ).toBe(false)
  })

  test('markets uses the same two values as a variant', () => {
    const variantMarket = Variant.safeParse(edit(variant(), 'market', 'uk'))
    expect(variantMarket.success).toBe(false)
    expect(Variant.safeParse(edit(variant(), 'market', 'euro')).success).toBe(true)
  })

  test('a maintenance item that names its markets keeps them', () => {
    expect(inspectionService().markets).toEqual(['us'])
    const parsed = MaintenanceItem.safeParse(inspectionService())
    expect(parsed.success && parsed.data.markets).toEqual(['us'])
  })

  test('require sources, a sorted cost range and a known frequency', () => {
    expect(MaintenanceItem.safeParse(edit(maintenance(), 'sources', [])).success).toBe(false)
    expect(MaintenanceItem.safeParse(edit(maintenance(), 'cost.shop', [100, 60])).success).toBe(
      false,
    )
    expect(MaintenanceItem.safeParse(edit(maintenance(), 'cost.currency', 'EUR')).success).toBe(
      false,
    )
    expect(KnownIssue.safeParse(edit(issueWithFix(), 'sources', [])).success).toBe(false)
    expect(KnownIssue.safeParse(edit(issueWithFix(), 'symptoms', [])).success).toBe(false)
    expect(KnownIssue.safeParse(edit(issueWithFix(), 'frequency', 'very common')).success).toBe(
      false,
    )
    expect(KnownIssue.safeParse(edit(issueWithFix(), 'frequency', 'rare')).success).toBe(true)
    expect(KnownIssue.safeParse(edit(issueWithFix(), 'cost.diy', undefined)).success).toBe(true)
    expect(KnownIssue.safeParse(edit(issueWithFix(), 'cost.shop', [900, 500])).success).toBe(false)
    expect(KnownIssue.safeParse(edit(issueWithFix(), 'cost.currency', 'EUR')).success).toBe(false)
  })
})

// `markets` is the same optional field, with the same rule, on both safety collections (R61): a
// document for one market supports that market only, and absent means every market.
describe.each([
  ['maintenance item', MaintenanceItem, maintenance],
  ['known issue', KnownIssue, issue],
] as const)('markets on a %s', (_name, schema, read) => {
  test('is optional, and absent stays absent: no market is filled in', () => {
    expect('markets' in read()).toBe(false)
    const parsed = schema.safeParse(read())
    expect(parsed.success).toBe(true)
    // Absent means every market. A default (such as ['us']) would turn it into a one-market claim.
    expect(parsed.success && parsed.data.markets).toBeUndefined()
    expect(parsed.success && 'markets' in parsed.data).toBe(false)
  })

  test('accepts one market or both, in either order', () => {
    for (const markets of [['us'], ['euro'], ['us', 'euro'], ['euro', 'us']]) {
      const parsed = schema.safeParse(edit(read(), 'markets', markets))
      expect(parsed.success, markets.join()).toBe(true)
      expect(parsed.success && parsed.data.markets, markets.join()).toEqual(markets)
    }
  })

  test('rejects an empty list, an unknown market, a repeated market and a bare string', () => {
    const empty = schema.safeParse(edit(read(), 'markets', []))
    expect(empty.success).toBe(false)
    expect(issuePaths(empty)).toContain('markets')
    const unknown = schema.safeParse(edit(read(), 'markets', ['uk']))
    expect(unknown.success).toBe(false)
    expect(issuePaths(unknown).join(' ')).toMatch(/markets/)
    const twice = schema.safeParse(edit(read(), 'markets', ['us', 'us']))
    expect(twice.success).toBe(false)
    expect(issuePaths(twice)).toContain('markets')
    expect(issueMessages(twice).join(' ')).toMatch(/more than once/)
    expect(schema.safeParse(edit(read(), 'markets', 'us')).success).toBe(false)
    expect(schema.safeParse(edit(read(), 'markets', ['us', 'euro', 'us'])).success).toBe(false)
  })
})

describe('known issue fix and cost (safety evidence, spec 7.6)', () => {
  test('a fix is optional: an issue may publish symptoms, cause and frequency only', () => {
    expect('fix' in issue()).toBe(false)
    expect(KnownIssue.safeParse(issue()).success).toBe(true)
  })

  test('without a fix, the cost is optional too, and may still be given', () => {
    expect('cost' in issue()).toBe(false)
    expect(KnownIssue.safeParse(issue()).success).toBe(true)
    const withCost = edit(issue(), 'cost', { currency: 'USD', shop: [500, 900] })
    expect(KnownIssue.safeParse(withCost).success).toBe(true)
  })

  test('a fix needs no cost: a sourced fix is not dropped for lack of a price', () => {
    expect('fix' in issueFixNoCost()).toBe(true)
    expect('cost' in issueFixNoCost()).toBe(false)
    const parsed = KnownIssue.safeParse(issueFixNoCost())
    expect(parsed.success).toBe(true)
    // Absent stays absent: the parser does not fill in a zero cost.
    expect(parsed.success && parsed.data.cost).toBeUndefined()
    const dropped = KnownIssue.safeParse(edit(issueWithFix(), 'cost', undefined))
    expect(dropped.success).toBe(true)
    const noCostNoFix = KnownIssue.safeParse(
      edit(edit(issueWithFix(), 'cost', undefined), 'fix', undefined),
    )
    expect(noCostNoFix.success).toBe(true)
  })

  test('a cost that is given beside a fix is still checked', () => {
    expect(KnownIssue.safeParse(issueWithFix()).success).toBe(true)
    expect(KnownIssue.safeParse(edit(issueWithFix(), 'cost', {})).success).toBe(false)
    expect(KnownIssue.safeParse(edit(issueWithFix(), 'cost.shop', [900, 500])).success).toBe(false)
  })

  test('a fix that is blank is still refused', () => {
    const r = KnownIssue.safeParse(edit(issueWithFix(), 'fix', '   '))
    expect(r.success).toBe(false)
    expect(issuePaths(r)).toContain('fix')
  })
})

describe('generation', () => {
  test('rejects a measured eye point without sources', () => {
    const measured = edit(generation(), 'driverEyePoint.basis', 'measured')
    const r = Generation.safeParse(measured)
    expect(r.success).toBe(false)
    expect(issuePaths(r)).toContain('driverEyePoint.sources')

    const source = { title: 't', publisher: 'p', tier: 1, accessed: '2026-11-23' }
    expect(Generation.safeParse(edit(measured, 'driverEyePoint.sources', [source])).success).toBe(
      true,
    )
  })

  test('requires at least one top-level source for the identity fields', () => {
    const missing = Generation.safeParse(edit(generation(), 'sources', undefined))
    expect(missing.success).toBe(false)
    expect(issuePaths(missing)).toContain('sources')
    const empty = Generation.safeParse(edit(generation(), 'sources', []))
    expect(empty.success).toBe(false)
    expect(issuePaths(empty)).toContain('sources')
    const badTier = Generation.safeParse(edit(generation(), 'sources.0.tier', 4))
    expect(badTier.success).toBe(false)
    expect(issuePaths(badTier)).toContain('sources.0.tier')
  })

  test('rejects dimensions keyed by a body the generation lacks', () => {
    const coupeOnly = edit(generation(), 'bodies', ['coupe'])
    expect(Generation.safeParse(coupeOnly).success).toBe(true)

    const dims = (generation().dimensions as Record<string, unknown>).coupe
    const wrongBody = edit(coupeOnly, 'dimensions', { convertible: dims })
    const r = Generation.safeParse(wrongBody)
    expect(r.success).toBe(false)
    expect(issuePaths(r)).toContain('dimensions.convertible')

    // Keys outside the Body union fail too.
    expect(
      Generation.safeParse(edit(generation(), 'dimensions', { hatchback: dims })).success,
    ).toBe(false)
  })

  test('requires at least one dimensions key', () => {
    const r = Generation.safeParse(edit(generation(), 'dimensions', {}))
    expect(r.success).toBe(false)
    expect(issuePaths(r)).toContain('dimensions')
  })

  test('requires sources on dimensions and on fitment', () => {
    expect(Generation.safeParse(edit(generation(), 'dimensions.coupe.sources', [])).success).toBe(
      false,
    )
    expect(Generation.safeParse(edit(generation(), 'fitment.sources', [])).success).toBe(false)
    expect(Generation.safeParse(edit(generation(), 'dimensions.coupe.lengthMm', 0)).success).toBe(
      false,
    )
  })

  test('rejects malformed fitment and years', () => {
    expect(
      Generation.safeParse(edit(generation(), 'fitment.front.boltPattern', '5-120')).success,
    ).toBe(false)
    expect(
      Generation.safeParse(edit(generation(), 'fitment.front.stock.tire', '225/45-18')).success,
    ).toBe(false)
    expect(Generation.safeParse(edit(generation(), 'years', [2006, 2000])).success).toBe(false)
    expect(Generation.safeParse(edit(generation(), 'years', [1980, 2000])).success).toBe(false)
    expect(Generation.safeParse(edit(generation(), 'years', [2000, 2040])).success).toBe(false)
    expect(Generation.safeParse(edit(generation(), 'engines', [])).success).toBe(false)
    expect(Generation.safeParse(edit(generation(), 'bodies', [])).success).toBe(false)
    expect(
      Generation.safeParse(edit(generation(), 'driverEyePoint.basis', 'guessed')).success,
    ).toBe(false)
  })

  test('fitment envelopes may be empty', () => {
    expect(Generation.safeParse(edit(generation(), 'fitment.front.envelopes', [])).success).toBe(
      true,
    )
  })
})

describe('variant', () => {
  test('rejects a bad market, paint colour, empty transmissions and missing sources', () => {
    expect(Variant.safeParse(edit(variant(), 'market', 'jp')).success).toBe(false)
    expect(Variant.safeParse(edit(variant(), 'paints.0.baseColor', '#C0C0C0')).success).toBe(false)
    expect(Variant.safeParse(edit(variant(), 'paints.0.baseColor', 'silver')).success).toBe(false)
    expect(Variant.safeParse(edit(variant(), 'transmissions', [])).success).toBe(false)
    expect(Variant.safeParse(edit(variant(), 'transmissions', ['cvt'])).success).toBe(false)
    expect(Variant.safeParse(edit(variant(), 'sources', [])).success).toBe(false)
    expect(Variant.safeParse(edit(variant(), 'render.baseAsset', 'Base_Asset')).success).toBe(false)
  })
})

describe('variant render modules', () => {
  const modules = (value: unknown) => edit(variant(), 'render.modules', value)

  test('a CSL names its own trunk lid and roof', () => {
    const parsed = Variant.safeParse(
      modules({ trunk_lid: 'e46-csl-trunk-lid', roof: 'e46-csl-roof' }),
    )
    expect(parsed.success).toBe(true)
    expect(parsed.data?.render.modules).toEqual({
      trunk_lid: 'e46-csl-trunk-lid',
      roof: 'e46-csl-roof',
    })
    expect(Variant.parse(cslVariant()).render.modules).toEqual({
      trunk_lid: 'fixture-csl-trunk-lid',
      roof: 'fixture-csl-roof',
    })
  })

  test('a variant that leaves the defaults has no modules', () => {
    expect(Variant.parse(variant()).render.modules).toBeUndefined()
  })

  test('each of the four modules is a valid key', () => {
    const all = {
      bumper_front: 'a-1',
      bumper_rear: 'a-2',
      trunk_lid: 'a-3',
      roof: 'a-4',
    }
    expect(Variant.safeParse(modules(all)).success).toBe(true)
  })

  test('rejects a key that is not a body module, and names it', () => {
    const result = Variant.safeParse(modules({ hood: 'x' }))
    expect(result.success).toBe(false)
    expect(issuePaths(result)).toContain('render.modules')
    expect(issueMessages(result).join(' ')).toContain('hood')
  })

  test('rejects an unknown key beside valid ones', () => {
    const result = Variant.safeParse(modules({ roof: 'e46-csl-roof', Roof: 'x' }))
    expect(result.success).toBe(false)
  })

  test('rejects a value that is not a kebab-case id', () => {
    for (const value of ['Trunk_Lid', '', 'a--b', 7, null]) {
      const result = Variant.safeParse(modules({ trunk_lid: value }))
      expect(result.success).toBe(false)
      expect(issuePaths(result)).toContain('render.modules.trunk_lid')
    }
  })

  test('rejects modules that are not an object', () => {
    for (const value of [['roof'], 'roof', 7, null]) {
      expect(Variant.safeParse(modules(value)).success).toBe(false)
    }
  })

  test('render stays strict', () => {
    expect(Variant.safeParse(edit(variant(), 'render.module', { roof: 'x' })).success).toBe(false)
  })
})
