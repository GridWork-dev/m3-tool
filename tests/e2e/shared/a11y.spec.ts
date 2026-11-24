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

// Every keyboard stop shows an outline: the global :focus-visible rule, or a surface's own.
test('every focus stop shows a focus ring on keyboard focus', async ({ page, dataSet }) => {
  for (const route of routesFor(dataSet)) {
    await test.step(route, async () => {
      await page.goto(route)
      const seen: string[] = []
      for (let stop = 0; stop < 80; stop++) {
        await page.keyboard.press('Tab')
        const state = await page.evaluate(() => {
          const el = document.activeElement
          if (!el || el === document.body) return undefined
          const style = getComputedStyle(el)
          return {
            name: `${el.tagName.toLowerCase()} ${el.getAttribute('href') ?? el.textContent?.trim().slice(0, 30) ?? ''}`,
            focusVisible: el.matches(':focus-visible'),
            outlineStyle: style.outlineStyle,
            outlineWidth: Number.parseFloat(style.outlineWidth),
          }
        })
        if (!state || seen.includes(state.name)) break
        seen.push(state.name)
        expect(state.focusVisible, `${state.name} matches :focus-visible`).toBe(true)
        expect(state.outlineStyle, `${state.name} outline style`).not.toBe('none')
        expect(state.outlineWidth, `${state.name} outline width`).toBeGreaterThan(0)
      }
      expect(seen.length, 'focus stops found').toBeGreaterThan(0)
    })
  }
})
