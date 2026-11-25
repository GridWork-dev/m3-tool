import { expectMarks } from '../marks.ts'
import { test } from '../test.ts'

const root = {
  paints: [{ code: 'A08', name: 'Silver', finish: 'metallic' }],
  front: { offset: 47 },
  rear: { offset: 26 },
}
const mark = (path: string, value: string, flag = true) =>
  `<span data-value-path="${path}" ${flag ? 'data-unverified' : ''}><span data-value>${value}</span></span>`
test('mark inventory rejects omissions, wrong flags, swapped bindings and lost repeats', async ({
  page,
}) => {
  const cases = [
    {
      html: `${mark('paints.A08.code', 'A08')}Silver metallic`,
      paths: ['paints.A08.code', 'paints.A08.name', 'paints.A08.finish'],
      listed: ['paints.A08'],
    },
    {
      html: mark('paints.A08.name', 'Silver', false),
      paths: ['paints.A08.name'],
      listed: ['paints.A08'],
    },
    {
      html: mark('front.offset', '26') + mark('rear.offset', '47'),
      paths: ['front.offset', 'rear.offset'],
      listed: ['front', 'rear'],
    },
    {
      html: mark('paints.A08.code', 'A08'),
      paths: ['paints.A08.code', 'paints.A08.code'],
      listed: ['paints.A08'],
    },
  ]
  for (const c of cases) {
    await page.setContent(`<div id="scope">${c.html}</div>`)
    let rejected = false
    try {
      await expectMarks(page.locator('#scope'), {
        root,
        listed: c.listed,
        inventory: [...new Set(c.paths)].map((path) => ({
          path,
          times: c.paths.filter((p) => p === path).length,
        })),
        complete: false,
      })
    } catch {
      rejected = true
    }
    if (!rejected) throw new Error('invalid markup passed')
  }
})
test('completeness rejects unrendered flags and correct markup passes', async ({ page }) => {
  await page.setContent(`<div id="scope">${mark('paints.A08.code', 'A08')}</div>`)
  const args = {
    root,
    listed: ['paints.A08.code', 'front.offset'],
    inventory: [{ path: 'paints.A08.code', times: 1 }],
    complete: false,
  }
  await expectMarks(page.locator('#scope'), args)
  let rejected = false
  try {
    await expectMarks(page.locator('#scope'), { ...args, complete: true })
  } catch {
    rejected = true
  }
  if (!rejected) throw new Error('missing flag passed')
  await expectMarks(page.locator('#scope'), { ...args, listed: ['paints.A08'], complete: true })
})
