import { expect, test } from 'vitest'
import { loadDataSet } from '../../src/data/load.ts'
import { keyRoutes, routesFor } from '../../src/lib/route-list.ts'

test('the routes of the real data set include the home page and /about/', async () => {
  const { set } = await loadDataSet('data')
  const routes = routesFor(set)
  expect(routes).toContain('/')
  expect(routes).toContain('/about/')
})

test('every route starts and ends with a slash, and none repeats', async () => {
  const { set } = await loadDataSet('data')
  const routes = routesFor(set)
  for (const route of routes) {
    expect(route.startsWith('/'), route).toBe(true)
    expect(route.endsWith('/'), route).toBe(true)
  }
  expect(new Set(routes).size).toBe(routes.length)
})

for (const dataDir of ['data', 'tests/fixtures/site-data']) {
  test(`key routes are registered routes for ${dataDir}`, async () => {
    const { set } = await loadDataSet(dataDir)
    const routes = keyRoutes(set)
    expect(routes).toContain('/')
    expect(routes).toContain('/about/')
    for (const route of routes) expect(routesFor(set)).toContain(route)
  })
}
