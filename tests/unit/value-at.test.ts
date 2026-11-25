import { expect, test } from 'vitest'
import { loadDataSet } from '../../src/data/load.ts'
import { Generation, Variant } from '../../src/data/schemas.ts'
import { unresolvedReason } from '../../src/data/unverified.ts'
import { isUnverified } from '../../src/lib/unverified-marks.ts'
import { valueAt } from '../support/value-at.ts'

test('marks use dot boundaries', () => {
  expect(isUnverified(['paints.A08'], 'paints.A08.code')).toBe(true)
  expect(isUnverified(['paints.A08'], 'paints.A080')).toBe(false)
  expect(isUnverified(undefined, 'name')).toBe(false)
})
for (const dir of ['data', 'tests/fixtures/site-data'])
  test(`value paths agree with contract in ${dir}`, async () => {
    const { set } = await loadDataSet(dir)
    for (const [schema, entries] of [
      [Generation, set.generations],
      [Variant, set.variants],
    ] as const)
      for (const { data } of entries)
        for (const path of data.unverified ?? []) {
          expect(unresolvedReason(schema, data, path)).toBeUndefined()
          expect(valueAt(data, path)).not.toBeUndefined()
        }
    for (const { data } of set.variants)
      for (const path of ['paints.0.code', 'paints.nope.code', 'years.2']) {
        expect(unresolvedReason(Variant, data, path)).toBeDefined()
        expect(valueAt(data, path)).toBeUndefined()
      }
  })
