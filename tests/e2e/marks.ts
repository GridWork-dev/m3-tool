import type { Locator } from '@playwright/test'
import { formatNumber } from '../../src/lib/format.ts'
import { isUnverified } from '../../src/lib/unverified-marks.ts'
import { valueAt } from '../support/value-at.ts'
import { expect } from './test.ts'
export async function expectMarks(
  scope: Locator,
  args: {
    root: unknown
    listed: readonly string[] | undefined
    inventory: readonly { path: string; times: number }[]
    complete: boolean
    exempt?: readonly string[] | undefined
  },
): Promise<void> {
  const actual = await scope
    .locator('[data-value-path]')
    .evaluateAll((nodes) => nodes.map((n) => n.getAttribute('data-value-path')))
  expect(actual.slice().sort()).toEqual(
    args.inventory.flatMap((p) => Array.from({ length: p.times }, () => p.path)).sort(),
  )
  for (const { path, times } of args.inventory) {
    const wrappers = scope.locator(`[data-value-path="${path}"]`)
    expect(await wrappers.count()).toBe(times)
    for (const wrapper of await wrappers.all()) {
      expect((await wrapper.getAttribute('data-unverified')) !== null, path).toBe(
        isUnverified(args.listed, path),
      )
      const value = valueAt(args.root, path)
      const key = path.split('.').at(-1)
      if (
        (typeof value === 'number' || typeof value === 'string') &&
        !['market', 'body', 'finish', 'material', 'basis'].includes(key ?? '')
      ) {
        const rendered = await wrapper.locator(':scope > [data-value]').textContent()
        expect(
          typeof value === 'number' ? [String(value), formatNumber(value)] : [value],
          path,
        ).toContain(rendered)
      }
    }
  }
  if (args.complete)
    for (const path of args.listed ?? [])
      if (!args.exempt?.some((p) => path === p || path.startsWith(`${p}.`)))
        expect(
          args.inventory.some((p) => p.path === path || p.path.startsWith(`${path}.`)),
          `unrendered flag ${path}`,
        ).toBe(true)
}
