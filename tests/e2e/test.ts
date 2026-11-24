// The e2e test object. Every spec imports `test` and `expect` from here, except
// tests/shots/shoot.spec.ts, which imports @playwright/test directly: the `shots` project has no
// baseURL, and its "before" visit is to production.
//
// Fixtures added to Playwright's:
// - `dataSet`: the data set the build under test was made from, loaded from the project's
//   `metadata.dataDir` (relative to the repo root) and cached per directory. Its lists hold
//   `Entry<T>` objects (`{ file, data }`), not the entries themselves. Unwrap with `.data` before
//   reading a field: `dataSet.issues.map((entry) => entry.data)`, never `dataSet.issues[0].verified`.
// - `page`: Playwright's page, which fails the test at teardown on any request to another origin
//   (a `data:` URL is fine) and on any failed request except `net::ERR_ABORTED`, the error a
//   navigation produces when it leaves a page before that page finishes loading. Specs wait for
//   load before they leave a page, so an abort that is not that is a real failure.
import { dirname, resolve } from 'node:path'
import { test as base, expect } from '@playwright/test'
import { loadDataSet } from '../../src/data/load.ts'
import type { DataSet } from '../../src/data/quality.ts'

const dataSets = new Map<string, Promise<DataSet>>()

async function load(dataDir: string): Promise<DataSet> {
  const { set, issues } = await loadDataSet(dataDir)
  if (issues.length > 0) {
    const lines = issues.map((issue) => `${issue.file}: ${issue.message}`)
    throw new Error(`data set ${dataDir} does not load cleanly:\n${lines.join('\n')}`)
  }
  return set
}

export const test = base.extend<{ dataSet: DataSet }>({
  // biome-ignore lint/correctness/noEmptyPattern: Playwright reads a fixture's dependencies from the destructuring pattern, and this one needs none.
  dataSet: async ({}, use, testInfo) => {
    const { dataDir } = testInfo.project.metadata as { dataDir?: unknown }
    if (typeof dataDir !== 'string') {
      throw new Error(`project ${testInfo.project.name} sets no metadata.dataDir`)
    }
    const root = testInfo.config.configFile ? dirname(testInfo.config.configFile) : process.cwd()
    const dir = resolve(root, dataDir)
    let pending = dataSets.get(dir)
    if (!pending) {
      pending = load(dir)
      dataSets.set(dir, pending)
    }
    await use(await pending)
  },

  page: async ({ page, baseURL }, use) => {
    if (!baseURL) throw new Error('these specs need a baseURL')
    const origin = new URL(baseURL).origin
    const problems: string[] = []
    page.on('request', (request) => {
      const { protocol, origin: requested } = new URL(request.url())
      if (protocol !== 'data:' && requested !== origin) {
        problems.push(`request to another origin: ${request.url()}`)
      }
    })
    page.on('requestfailed', (request) => {
      const reason = request.failure()?.errorText
      if (reason !== 'net::ERR_ABORTED')
        problems.push(`request failed (${reason}): ${request.url()}`)
    })
    await use(page)
    expect(problems, 'requests the page should not make').toEqual([])
  },
})

export { expect }
