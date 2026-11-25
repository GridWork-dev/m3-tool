import { expect, test } from 'vitest'
import {
  bodyLabel,
  formatDate,
  formatNumber,
  formatYears,
  frequencyLabel,
  transmissionLabel,
  wheelLabel,
  wheelParts,
} from '../../src/lib/format.ts'
import { marketsAttr, marketsLabel } from '../../src/lib/markets.ts'
import { appliesToYear, modelYearsLabel, yearsAttr } from '../../src/lib/model-years.ts'
import { describeCost, formatUsdRange, sourcedShopMax } from '../../src/lib/money.ts'
import {
  buyingPath,
  GENERATION_SECTIONS,
  generationPath,
  issuePath,
  issuesPath,
  maintenancePath,
} from '../../src/lib/routes.ts'

test('formatting preserves units, dates and readable labels', () => {
  expect(formatDate(new Date('2026-11-23'))).toBe('2026-11-23')
  expect(formatNumber(4492)).toBe('4,492')
  expect(formatNumber(-370)).toBe('-370')
  expect(formatYears([2004, 2004])).toBe('2004')
  expect(frequencyLabel('very-common')).toBe('Very common')
  expect(transmissionLabel('6mt')).toBe('6-speed manual')
  expect(bodyLabel('coupe')).toBe('Coupe')
  const wheel = { diameterIn: 18, widthIn: 9.5, offsetMm: 26, tire: '255/40ZR18' }
  expect(wheelParts(wheel)).toEqual({
    diameter: '18',
    width: '9.5',
    offset: '26',
    tire: '255/40ZR18',
  })
  expect(wheelLabel(wheel)).toBe('18 × 9.5 ET26')
})
test('describeCost never shows zero', () => {
  const none = { kind: 'none', label: 'no sourced cost' }
  for (const c of [
    undefined,
    { shop: [0, 0] as const },
    { diy: [20, 40] as const, shop: [0, 0] as const },
  ])
    expect(describeCost(c)).toEqual(none)
  expect(describeCost({ shop: [60, 100], diy: [0, 0] })).toEqual({
    kind: 'sourced',
    shop: '$60–100',
  })
  expect(describeCost({ shop: [60, 100], diy: [20, 40] })).toEqual({
    kind: 'sourced',
    shop: '$60–100',
    diy: '$20–40',
  })
  expect(sourcedShopMax({ shop: [0, 0] })).toBeUndefined()
  expect(sourcedShopMax({ shop: [60, 100] })).toBe(100)
  expect(formatUsdRange([1200, 3400])).toBe('$1,200–3,400')
  expect(formatUsdRange([60, 60])).toBe('$60')
})
test('market and inclusive model year scope', () => {
  expect(marketsAttr({})).toBe('us euro')
  expect(marketsLabel({ markets: ['us', 'euro'] })).toBe('US and Euro')
  expect(marketsLabel({ markets: ['euro'] })).toBe('Euro only')
  for (const year of [2004, 2005, 2006])
    expect(appliesToYear({ modelYears: [2004, 2006] }, year)).toBe(true)
  for (const year of [2003, 2007])
    expect(appliesToYear({ modelYears: [2004, 2006] }, year)).toBe(false)
  expect(appliesToYear({}, 1999)).toBe(true)
  expect(modelYearsLabel({})).toBe('All model years')
  expect(modelYearsLabel({ modelYears: [2004, 2004] })).toBe('2004 only')
  expect(yearsAttr({}, [2000, 2002])).toBe('2000 2001 2002')
})
test('route builders have trailing slashes', () => {
  expect(GENERATION_SECTIONS.map((s) => s.key)).toEqual(['overview'])
  for (const route of [
    generationPath('e46'),
    issuesPath('e46'),
    issuePath('e46', 'test'),
    maintenancePath('e46'),
    buyingPath('e46'),
  ])
    expect(route).toMatch(/^\/.*\/$/)
})
