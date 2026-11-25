import { isAllowedHref } from '../../../src/lib/link-policy.ts'
import { NOTICE } from '../../../src/lib/notice.ts'
import { routesFor } from '../../../src/lib/route-list.ts'
import { SITE_NAME } from '../../../src/lib/site.ts'
import { expect, test } from '../test.ts'

// Each invariant is one test that loops over every route of the data set, so a page that
// registers in src/lib/route-list.ts is covered the moment it exists.

test('footer carries the notice word for word', async ({ page, dataSet }) => {
  for (const route of routesFor(dataSet)) {
    await test.step(route, async () => {
      await page.goto(route)
      await expect(page.getByRole('contentinfo')).toContainText(NOTICE)
    })
  }
  await page.goto('/about/')
  await expect(page.locator('main')).toContainText(NOTICE)
})

test('/about/ shows the code and data licenses', async ({ page }) => {
  await page.goto('/about/')
  for (const license of ['MIT', 'CC BY-SA 4.0']) {
    await expect(page.locator('main')).toContainText(license)
  }
})

test('every route is noindex', async ({ page, dataSet }) => {
  for (const route of routesFor(dataSet)) {
    await test.step(route, async () => {
      await page.goto(route)
      await expect(page.locator('meta[name="robots"]')).toHaveAttribute('content', 'noindex')
    })
  }
})

test('every route has a title that names the site', async ({ page, dataSet }) => {
  for (const route of routesFor(dataSet)) {
    await test.step(route, async () => {
      await page.goto(route)
      expect(await page.title()).toMatch(new RegExp(`${SITE_NAME}$`))
    })
  }
})

// The locator is the tag: the home hero is an <svg role="img">, which is allowed.
test('no route renders an img', async ({ page, dataSet }) => {
  for (const route of routesFor(dataSet)) {
    await test.step(route, async () => {
      await page.goto(route)
      await expect(page.locator('img')).toHaveCount(0)
    })
  }
})

test('every route has exactly one h1', async ({ page, dataSet }) => {
  for (const route of routesFor(dataSet)) {
    await test.step(route, async () => {
      await page.goto(route)
      await expect(page.locator('h1')).toHaveCount(1)
    })
  }
})

// With the slash: under trailingSlash 'always', preview answers /no-such-page with Astro's own
// message and not the site's 404 page.
test('unknown paths return the 404 page', async ({ page }) => {
  const response = await page.goto('/no-such-page/')
  expect(response?.status()).toBe(404)
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Page not found')
})

test('the skip link is the first focus stop and targets main', async ({ page, dataSet }) => {
  for (const route of routesFor(dataSet)) {
    await test.step(route, async () => {
      await page.goto(route)
      await page.keyboard.press('Tab')
      const focused = page.locator(':focus')
      await expect(focused).toHaveAttribute('href', '#main')
      await expect(page.locator('main#main')).toHaveCount(1)
      // Hidden until focused, then a real target: not the 1px clipped box.
      const box = await focused.boundingBox()
      expect(box?.width, 'skip link width when focused').toBeGreaterThan(40)
      expect(box?.height, 'skip link height when focused').toBeGreaterThanOrEqual(44)
      expect(box?.y, 'skip link position when focused').toBeGreaterThanOrEqual(0)
    })
  }
})

test('the fonts are self-hosted', async ({ page }) => {
  const fonts: string[] = []
  page.on('request', (request) => {
    const { pathname } = new URL(request.url())
    if (pathname.startsWith('/_astro/fonts/') && pathname.endsWith('.woff2')) fonts.push(pathname)
  })
  await page.goto('/')
  await page.evaluate(() => document.fonts.ready)
  expect(fonts.length, 'woff2 requests under /_astro/fonts/').toBeGreaterThan(0)
})

// The only check that a dead internal link fails: check:links never follows one.
test('every internal link has a trailing slash and resolves', async ({
  page,
  request,
  baseURL,
  dataSet,
}) => {
  const origin = new URL(baseURL ?? '').origin
  const checked = new Map<string, number>()
  for (const route of routesFor(dataSet)) {
    await test.step(route, async () => {
      await page.goto(route)
      const hrefs = await page
        .locator('a[href]')
        .evaluateAll((anchors) => anchors.map((a) => a.getAttribute('href') ?? ''))
      for (const href of hrefs) {
        if (href.startsWith('#')) continue
        const url = new URL(href, page.url())
        if (url.origin !== origin) continue
        const { pathname } = url
        if (pathname.startsWith('/_astro/')) continue
        if (/\.[a-z0-9]+$/i.test(pathname)) continue // a file link, such as /version.txt
        expect(pathname.endsWith('/'), `${route} links to ${href} without a trailing slash`).toBe(
          true,
        )
        let status = checked.get(pathname)
        if (status === undefined) {
          status = (await request.get(pathname)).status()
          checked.set(pathname, status)
        }
        expect(status, `${route} links to ${href}`).toBe(200)
      }
    })
  }
})

test('every external anchor passes isAllowedHref', async ({ page, baseURL, dataSet }) => {
  const origin = new URL(baseURL ?? '').origin
  for (const route of routesFor(dataSet)) {
    await test.step(route, async () => {
      await page.goto(route)
      const hrefs = await page
        .locator('a[href]')
        .evaluateAll((anchors) => anchors.map((a) => a.getAttribute('href') ?? ''))
      for (const href of hrefs) {
        if (new URL(href, page.url()).origin === origin) continue
        expect(isAllowedHref(href), `${route} links to ${href}`).toBe(true)
      }
    })
  }
})
