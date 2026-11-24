import { expect, test } from '@playwright/test'

const NOTICE = 'Not affiliated with, endorsed by, or sponsored by BMW AG'

test('home page shows the not-affiliated notice', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('contentinfo')).toContainText(NOTICE)
})
test('about page states the notice and licenses', async ({ page }) => {
  await page.goto('/about/')
  for (const t of [NOTICE, 'MIT', 'CC BY-SA 4.0'])
    await expect(page.locator('main')).toContainText(t)
})
test('unknown paths return the 404 page', async ({ page }) => {
  const res = await page.goto('/no-such-page/')
  expect(res?.status()).toBe(404)
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Page not found')
})
test('every page is noindex before the beta', async ({ page }) => {
  for (const p of ['/', '/about/']) {
    await page.goto(p)
    await expect(page.locator('meta[name="robots"]')).toHaveAttribute('content', 'noindex')
  }
})
