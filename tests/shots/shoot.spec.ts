import { mkdir } from 'node:fs/promises'
import { test } from '@playwright/test'
import { loadDataSet } from '../../src/data/load.ts'
import { keyRoutes } from '../../src/lib/route-list.ts'

const targets = [
  { name: 'after', url: 'http://localhost:4321', dataDir: 'data', optional: false },
  {
    name: 'after-fixture',
    url: 'http://localhost:4322',
    dataDir: 'tests/fixtures/site-data',
    optional: false,
  },
  ...(process.env.SHOOT_BEFORE_URL
    ? [{ name: 'before', url: process.env.SHOOT_BEFORE_URL, dataDir: 'data', optional: true }]
    : []),
]

for (const target of targets) {
  const { set } = await loadDataSet(target.dataDir)
  for (const route of keyRoutes(set)) {
    for (const viewport of [
      { width: 390, height: 844 },
      { width: 1280, height: 800 },
    ]) {
      test(`${target.name} ${route} at ${viewport.width}`, async ({ page }) => {
        await page.setViewportSize(viewport)
        const url = new URL(route, target.url).href
        const response = await page
          .goto(url, { waitUntil: 'networkidle', timeout: 15_000 })
          .catch((error: unknown) => {
            if (!target.optional) throw error
            console.log(`Skipping before screenshot: ${url} is unreachable (${String(error)})`)
            return null
          })
        if (target.optional && response?.status() !== 200) {
          console.log(
            `Skipping before screenshot: ${url} returned ${response?.status() ?? 'no response'}`,
          )
          test.skip()
        }
        if (response?.status() !== 200) throw new Error(`${url} did not return 200`)
        await page.evaluate(() => document.fonts.ready)
        const directory = `screenshots/${target.name}`
        await mkdir(directory, { recursive: true })
        const slug = route === '/' ? 'home' : route.replace(/^\/|\/$/g, '').replaceAll('/', '-')
        await page.screenshot({
          path: `${directory}/${slug}-${viewport.width}.png`,
          fullPage: true,
        })
      })
    }
  }
}
