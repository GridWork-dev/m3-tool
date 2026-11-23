import { expect, test } from 'vitest'
import { meetsVerificationRule } from '../../../src/data/sources.ts'

const s = (tier: 1 | 2 | 3, publisher: string) => ({
  title: 't',
  publisher,
  tier,
  accessed: new Date(),
})

test('one tier-1 source verifies', () => expect(meetsVerificationRule([s(1, 'BMW')])).toBe(true))

test('two tier-2 sources from different publishers verify', () =>
  expect(meetsVerificationRule([s(2, 'Shop A'), s(2, 'Mag B')])).toBe(true))

test('two tier-2 sources from the same publisher do not verify', () =>
  expect(meetsVerificationRule([s(2, 'Shop A'), s(2, ' shop a ')])).toBe(false))

test('tier-3 sources never verify', () =>
  expect(meetsVerificationRule([s(3, 'F1'), s(3, 'F2'), s(3, 'F3')])).toBe(false))

test('no sources do not verify', () => expect(meetsVerificationRule([])).toBe(false))

test('one tier-2 source does not verify', () =>
  expect(meetsVerificationRule([s(2, 'Shop A')])).toBe(false))

test('a tier-1 source verifies alongside weaker ones', () =>
  expect(meetsVerificationRule([s(3, 'Forum'), s(1, 'BMW')])).toBe(true))

test('tier-3 sources do not count toward the two independent tier-2 sources', () =>
  expect(meetsVerificationRule([s(2, 'Shop A'), s(3, 'Forum')])).toBe(false))

test('three tier-2 sources need only two distinct publishers', () =>
  expect(meetsVerificationRule([s(2, 'Shop A'), s(2, 'SHOP A'), s(2, 'Mag B')])).toBe(true))
