import { isCitationLinkable } from '../../../src/lib/link-policy.ts'
import { generationPath } from '../../../src/lib/routes.ts'
import { generationInventory } from '../inventories.ts'
import { expectMarks } from '../marks.ts'
import { expect, test } from '../test.ts'

test('generation specs bind every value, flag and citation to its data', async ({
  page,
  dataSet,
}) => {
  for (const { data: g } of dataSet.generations) {
    await page.goto(generationPath(g.id))
    await expect(page.locator('h1')).toContainText(g.name)
    await expect(page).toHaveTitle(`${g.name} · m3-tool`)
    const scope = page.locator('[data-generation-specs]')
    await expectMarks(scope, {
      root: g,
      listed: g.unverified,
      inventory: generationInventory(g, { hero: false, drawing: false }),
      complete: true,
    })
    const lists = [
      ['sources', g.sources],
      ...Object.entries(g.dimensions).flatMap(([body, d]) =>
        d ? [[`dimensions.${body}`, d.sources] as const] : [],
      ),
      ['fitment', g.fitment.sources],
      ['driverEyePoint', g.driverEyePoint.sources],
    ] as const
    const expectedHrefs = lists
      .flatMap(([, sources]) =>
        sources.flatMap((source) =>
          source.url && isCitationLinkable(source.url) ? [source.url] : [],
        ),
      )
      .sort()
    const actualHrefs = await scope
      .locator('[data-sources] a[href^="http"]')
      .evaluateAll((anchors) =>
        anchors.map((anchor) => anchor.getAttribute('href') as string).sort(),
      )
    expect(actualHrefs).toEqual(expectedHrefs)
    await expect(scope.locator('[data-source-index]')).toHaveCount(
      lists.reduce((total, [, sources]) => total + sources.length, 0),
    )
    for (const [list, sources] of lists) {
      await expect(scope.locator(`[data-source-list="${list}"] [data-source-index]`)).toHaveCount(
        sources.length,
      )
      for (const [i, s] of sources.entries()) {
        const row = scope.locator(`[data-source-list="${list}"] [data-source-index="${i}"]`)
        await expect(row).toContainText(s.title)
        await expect(row).toContainText(s.publisher)
        if (s.url && isCitationLinkable(s.url))
          await expect(row.locator('a')).toHaveAttribute('href', s.url)
        else await expect(row.locator('a')).toHaveCount(0)
      }
    }
    for (const axle of ['front', 'rear'] as const) {
      const limits = scope.locator(`[data-value-path="fitment.${axle}.envelopes"]`)
      await expect(limits).toHaveJSProperty('tagName', 'DIV')
      await expect(limits.locator(':scope > [data-value]')).toHaveJSProperty('tagName', 'DIV')
      if (g.fitment[axle].envelopes.length) await expect(limits.locator('table')).toHaveCount(1)
      else await expect(limits).toContainText('Fit limits not yet sourced')
    }
    if (g.driverEyePoint.basis === 'estimated') await expect(scope).toContainText('no source')
    await expect(
      page.getByRole('navigation', { name: 'Generation' }).getByRole('link', { name: 'Overview' }),
    ).toHaveAttribute('aria-current', 'page')
  }
})
