import { describe, expect, test } from 'vitest'
import { loadDataSet } from '../../../src/data/load.ts'
import {
  Generation,
  KnownIssue,
  MaintenanceItem,
  Part,
  PriceObservation,
  Source,
  Variant,
} from '../../../src/data/schemas.ts'
import { edit, issueMessages, issuePaths, readFixture, VALID_FIXTURES } from './helpers.ts'

const generation = () => readFixture('generations/e46.yaml')
const variant = () => readFixture('variants/e46/e46-us-coupe.yaml')
const wheel = () => readFixture('parts/e46/fixture-wheel.yaml')
const generic = () => readFixture('parts/e46/fixture-generic-wheels.yaml')
const coilovers = () => readFixture('parts/e46/fixture-coilovers.yaml')
const maintenance = () => readFixture('maintenance/e46/fixture-oil-service.yaml')
const issue = () => readFixture('issues/e46/fixture-rod-bearings.yaml')

// The unmutated fixtures must pass, so a failing mutation below is the mutation's doing.
describe('valid fixtures', () => {
  test('the valid fixture set loads with no issues', async () => {
    expect((await loadDataSet(VALID_FIXTURES)).issues).toEqual([])
  })

  test.each([
    ['generation', Generation, generation],
    ['variant', Variant, variant],
    ['branded part with options', Part, wheel],
    ['generic part', Part, generic],
    ['branded part with attributes', Part, coilovers],
    ['maintenance item', MaintenanceItem, maintenance],
    ['known issue', KnownIssue, issue],
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

  test('accepts ISO dates and datetimes, and rejects strings V8 would misread', () => {
    const checked = (value: unknown) => PriceObservation.safeParse({ ...base, checked: value })
    expect(checked('2026-11-23').success).toBe(true)
    expect(checked('2026-11-23T10:30:00Z').success).toBe(true)
    expect(checked('2026-11-23T10:30:00.000+01:00').success).toBe(true)
    expect(checked(new Date('2026-11-23')).success).toBe(true)
    expect(checked('2026-02-31').success).toBe(false) // would roll over into March
    expect(checked('2026-13-01').success).toBe(false)
    expect(checked('1').success).toBe(false) // new Date('1') is the year 2001
    expect(checked('Nov 23 2026').success).toBe(false)
    expect(checked(20261123).success).toBe(false) // a bare YAML number, not a date
    expect(checked(null).success).toBe(false)
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

  test('rejects a maintenance interval with neither miles nor months', () => {
    const none = MaintenanceItem.safeParse(edit(maintenance(), 'interval', {}))
    expect(none.success).toBe(false)
    expect(issuePaths(none)).toContain('interval')
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

  test('require sources, a sorted cost range and a known frequency', () => {
    expect(MaintenanceItem.safeParse(edit(maintenance(), 'sources', [])).success).toBe(false)
    expect(MaintenanceItem.safeParse(edit(maintenance(), 'cost.shop', [100, 60])).success).toBe(
      false,
    )
    expect(MaintenanceItem.safeParse(edit(maintenance(), 'cost.currency', 'EUR')).success).toBe(
      false,
    )
    expect(KnownIssue.safeParse(edit(issue(), 'sources', [])).success).toBe(false)
    expect(KnownIssue.safeParse(edit(issue(), 'symptoms', [])).success).toBe(false)
    expect(KnownIssue.safeParse(edit(issue(), 'frequency', 'very common')).success).toBe(false)
    expect(KnownIssue.safeParse(edit(issue(), 'frequency', 'rare')).success).toBe(true)
    expect(KnownIssue.safeParse(edit(issue(), 'cost.diy', undefined)).success).toBe(true)
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
