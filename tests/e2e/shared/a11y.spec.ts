import AxeBuilder from '@axe-core/playwright'
import { routesFor } from '../../../src/lib/route-list.ts'
import { expect, test } from '../test.ts'

test('no axe violations on any route', async ({ page, dataSet }) => {
  for (const route of routesFor(dataSet)) {
    await test.step(route, async () => {
      await page.goto(route)
      const { violations } = await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
        .analyze()
      expect(
        violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`),
      ).toEqual([])
    })
  }
})

// Every keyboard stop shows an outline: the global :focus-visible rule, or a surface's own. The loop
// walks the tab order until focus returns to the first stop or leaves the document.
test('every focus stop shows a focus ring on keyboard focus', async ({ page, dataSet }) => {
  for (const route of routesFor(dataSet)) {
    await test.step(route, async () => {
      await page.goto(route)
      await page.keyboard.press('Tab')
      const first = await page.evaluateHandle(() => document.activeElement)
      let stops = 0
      let ended = false
      for (; stops < 200 && !ended; stops++) {
        if (stops > 0) await page.keyboard.press('Tab')
        const state = await page.evaluate(
          ([first, stop]) => {
            const el = document.activeElement
            if (!el || el === document.body || (stop > 0 && el === first)) return undefined
            const style = getComputedStyle(el)
            return {
              name: `${el.tagName.toLowerCase()} ${el.getAttribute('href') ?? el.textContent?.trim().slice(0, 30) ?? ''}`,
              focusVisible: el.matches(':focus-visible'),
              outlineStyle: style.outlineStyle,
              outlineWidth: Number.parseFloat(style.outlineWidth),
            }
          },
          [first, stops] as const,
        )
        if (!state) {
          ended = true
          break
        }
        expect(state.focusVisible, `${state.name} matches :focus-visible`).toBe(true)
        expect(state.outlineStyle, `${state.name} outline style`).not.toBe('none')
        expect(state.outlineWidth, `${state.name} outline width`).toBeGreaterThan(0)
      }
      expect(ended, 'the tab order ends within 200 stops').toBe(true)
      expect(stops, 'focus stops found').toBeGreaterThan(0)
    })
  }
})
