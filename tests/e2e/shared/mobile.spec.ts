import type { Page } from '@playwright/test'
import { routesFor } from '../../../src/lib/route-list.ts'
import { expect, test } from '../test.ts'

test.use({ viewport: { width: 390, height: 844 } })

// What a thumb has to hit: disclosures, the top bar and footer links, filter controls, a hero's
// action links and the links in an issue or problem entry. A selector matching nothing is fine:
// the page that adds the element is covered the moment it exists.
const TARGETS = [
  'summary',
  'nav a',
  'footer a',
  '[data-filter-scope] label',
  '[data-filter-scope] select',
  '[data-generation-specs] a',
  'main [data-entry] a',
].join(', ')

const MIN_TARGET = 44

const noSidewaysScroll = (page: Page) =>
  page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)

test('no sideways scroll, and every tap target is at least 44 px high', async ({
  page,
  dataSet,
}) => {
  for (const route of routesFor(dataSet)) {
    await test.step(route, async () => {
      await page.goto(route)
      expect(await noSidewaysScroll(page), 'no sideways scroll').toBe(true)

      await page.evaluate(() => {
        for (const d of document.querySelectorAll('details')) d.open = true
      })
      const targets = await page.locator(TARGETS).evaluateAll((elements) =>
        elements
          .map((el) => ({ el, box: el.getBoundingClientRect() }))
          .filter(({ box }) => box.width > 0 && box.height > 0)
          .map(({ el, box }) => ({
            name: `${el.tagName.toLowerCase()} ${el.getAttribute('href') ?? el.textContent?.trim().slice(0, 30) ?? ''}`,
            height: box.height,
          })),
      )
      for (const { name, height } of targets) {
        expect(height, `${name} is ${height} px high`).toBeGreaterThanOrEqual(MIN_TARGET)
      }
      expect(await noSidewaysScroll(page), 'no sideways scroll with every disclosure open').toBe(
        true,
      )
    })
  }
})
