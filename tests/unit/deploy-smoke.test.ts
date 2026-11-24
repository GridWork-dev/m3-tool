// The smoke test that follows a production deploy (ADR 0011). It can't run before a merge on a
// runner, so its logic runs here, against a local server that plays the live site.
import { spawn } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { createServer, type Server } from 'node:http'
import type { AddressInfo } from 'node:net'
import { fileURLToPath } from 'node:url'
import { afterEach, describe, expect, test } from 'vitest'

const root = fileURLToPath(new URL('../../', import.meta.url))
const SCRIPT = `${root}infra/deploy/smoke.sh`
const SHA = '0123456789abcdef0123456789abcdef01234567'
const NOTICE = 'Not affiliated with, endorsed by, or sponsored by BMW AG'

interface Site {
  version?: (request: number) => string | undefined // the body of /version.txt, or a 404 when undefined
  home?: string
  homeStatus?: number
  nope?: number
}

let server: Server | undefined
afterEach(() => {
  server?.close()
  server = undefined
})

// A site that serves what the production Worker would: a home page, a version marker, a 404 page.
async function serve(site: Site): Promise<{ url: string; hits: () => string[] }> {
  const seen: string[] = []
  let versionRequests = 0
  const listening = createServer((req, res) => {
    const path = (req.url ?? '/').split('?')[0] ?? '/'
    seen.push(path)
    if (path === '/version.txt') {
      const body = site.version?.(versionRequests++)
      if (body === undefined) {
        res.writeHead(404, { 'content-type': 'text/html' }).end('<h1>Page not found</h1>')
      } else {
        res.writeHead(200, { 'content-type': 'text/plain' }).end(`${body}\n`)
      }
    } else if (path === '/') {
      res
        .writeHead(site.homeStatus ?? 200, { 'content-type': 'text/html' })
        .end(site.home ?? `<footer>Independent fan project. ${NOTICE}.</footer>`)
    } else {
      res
        .writeHead(site.nope ?? 404, { 'content-type': 'text/html' })
        .end('<h1>Page not found</h1>')
    }
  })
  server = listening
  await new Promise<void>((resolve) => listening.listen(0, '127.0.0.1', resolve))
  const { port } = listening.address() as AddressInfo
  return { url: `http://127.0.0.1:${port}`, hits: () => seen }
}

// Runs the script the way the workflow does (bash -eo pipefail), with a short wait between tries.
function run(url: string, env: Record<string, string> = {}) {
  return new Promise<{ code: number | null; out: string }>((resolve) => {
    const child = spawn('bash', ['-eo', 'pipefail', SCRIPT], {
      env: {
        PATH: process.env.PATH ?? '',
        SMOKE_BASE_URL: url,
        EXPECTED_SHA: SHA,
        SMOKE_SLEEP: '0.05',
        SMOKE_ATTEMPTS: '6',
        ...env,
      },
    })
    let out = ''
    child.stdout.on('data', (chunk) => {
      out += String(chunk)
    })
    child.stderr.on('data', (chunk) => {
      out += String(chunk)
    })
    child.on('close', (code) => resolve({ code, out }))
  })
}

describe('the smoke test of a production deploy', () => {
  test('passes when the live site serves this commit, the notice, and a 404 for an unknown path', async () => {
    const site = await serve({ version: () => SHA })
    const result = await run(site.url)
    expect(result.code).toBe(0)
    expect(site.hits()).toContain('/version.txt')
    expect(site.hits()).toContain('/')
    expect(site.hits()).toContain('/__nope')
  })

  test('waits for the new version: the old one is served first, then this commit', async () => {
    const old = 'f'.repeat(40)
    const site = await serve({ version: (request) => (request < 3 ? old : SHA) })
    const result = await run(site.url)
    expect(result.code).toBe(0)
    expect(site.hits().filter((path) => path === '/version.txt')).toHaveLength(4)
  })

  test('fails when only an older commit is ever served, which a deploy that did nothing would look like', async () => {
    const site = await serve({ version: () => 'f'.repeat(40) })
    const result = await run(site.url)
    expect(result.code).toBe(1)
    expect(result.out).toContain('::error::')
    expect(result.out).toContain(SHA)
  })

  test('fails when /version.txt is not served at all', async () => {
    const site = await serve({ version: () => undefined })
    const result = await run(site.url)
    expect(result.code).toBe(1)
    expect(result.out).toContain('::error::')
  })

  test('does not take a page that merely contains the commit for the marker', async () => {
    const site = await serve({ version: () => `<p>not ${SHA}, a page</p>` })
    expect((await run(site.url)).code).toBe(1)
  })

  test('fails when the home page lacks the not-affiliated notice', async () => {
    const site = await serve({ version: () => SHA, home: '<footer>hello</footer>' })
    const result = await run(site.url)
    expect(result.code).toBe(1)
    expect(result.out).toContain('::error::')
  })

  test('fails when the home page is not a 200', async () => {
    const site = await serve({ version: () => SHA, homeStatus: 500 })
    expect((await run(site.url)).code).toBe(1)
  })

  test('fails when an unknown path is a 200 instead of a 404', async () => {
    const site = await serve({ version: () => SHA, nope: 200 })
    const result = await run(site.url)
    expect(result.code).toBe(1)
    expect(result.out).toContain('/__nope')
  })

  test('fails when the site is not reachable', async () => {
    const result = await run('http://127.0.0.1:1', { SMOKE_ATTEMPTS: '2' })
    expect(result.code).toBe(1)
    expect(result.out).toContain('::error::')
  })

  test('fails when it was not told which commit to expect', async () => {
    const site = await serve({ version: () => SHA })
    const result = await run(site.url, { EXPECTED_SHA: '' })
    expect(result.code).not.toBe(0)
  })

  test('is bounded: it gives up in about two minutes at its defaults, and the loop is not unbounded', () => {
    const script = readFileSync(SCRIPT, 'utf8')
    expect(script).toMatch(/SMOKE_ATTEMPTS:-12/)
    expect(script).toMatch(/SMOKE_SLEEP:-10/)
  })

  test('asks the production URL by default, and for the sentence the e2e test checks', () => {
    const script = readFileSync(SCRIPT, 'utf8')
    expect(script).toContain('https://m3-tool.broken-wood-97a9.workers.dev')
    const e2e = readFileSync(`${root}tests/e2e/smoke.spec.ts`, 'utf8')
    const sentence = /const NOTICE = '([^']+)'/.exec(e2e)?.[1]
    expect(sentence).toBe(NOTICE)
    expect(script).toContain(NOTICE)
    expect(
      readFileSync(`${root}src/components/SiteFooter.astro`, 'utf8').replace(/\s+/g, ' '),
    ).toContain(NOTICE)
  })
})
