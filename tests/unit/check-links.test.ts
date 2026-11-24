import { spawnSync } from 'node:child_process'
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { afterEach, beforeEach, expect, test } from 'vitest'
import { checkLinks } from '../../tools/check-links.ts'

const CLI = fileURLToPath(new URL('../../tools/check-links.ts', import.meta.url))
const STORE_LINK = 'https://www.example-store.com/p/123'

let dist: string

beforeEach(async () => {
  dist = await mkdtemp(join(tmpdir(), 'check-links-'))
})
afterEach(async () => {
  await rm(dist, { recursive: true, force: true })
})

async function write(relPath: string, content: string): Promise<void> {
  const path = join(dist, relPath)
  await mkdir(dirname(path), { recursive: true })
  await writeFile(path, content)
}

function runCli(dir: string) {
  const result = spawnSync(process.execPath, [CLI, dir], { encoding: 'utf8' })
  return { code: result.status, stdout: result.stdout, stderr: result.stderr }
}

test('checkLinks finds a violation in a nested page and ignores allowed pages and non-HTML files', async () => {
  await write(
    'index.html',
    '<a href="/about">About</a><a href="https://github.com/GridWork-dev">g</a>',
  )
  await write('e46/mods/index.html', `<a href="/">Home</a><a href="${STORE_LINK}">Buy</a>`)
  await write('notes.txt', `<a href="${STORE_LINK}">not html, not scanned</a>`)
  expect(await checkLinks(dist)).toEqual([
    { file: join('e46', 'mods', 'index.html'), href: STORE_LINK },
  ])
})

test('the CLI exits 1 and prints "<file>: <href>" for each violation', async () => {
  await write('index.html', '<a href="//shop.example.com/wheels">Wheels</a>')
  const { code, stdout } = runCli(dist)
  expect(code).toBe(1)
  expect(stdout).toBe('index.html: //shop.example.com/wheels\n')
})

test('the CLI exits 0 and prints nothing when every link is allowed', async () => {
  await write('index.html', '<a href="/about">About</a>')
  const { code, stdout, stderr } = runCli(dist)
  expect({ code, stdout, stderr }).toEqual({ code: 0, stdout: '', stderr: '' })
})

test('the CLI exits 2 with a message when the dist directory does not exist', async () => {
  const { code, stdout, stderr } = runCli(join(dist, 'missing'))
  expect(code).toBe(2)
  expect(stdout).toBe('')
  expect(stderr).toContain('dist directory not found')
})

test('the CLI exits 2 when dist has no HTML files, so an empty build cannot pass', async () => {
  await write('notes.txt', 'nothing to scan')
  const { code, stdout, stderr } = runCli(dist)
  expect(code).toBe(2)
  expect(stdout).toBe('')
  expect(stderr).toContain('no .html files')
})

test('checkLinks accepts a link to each citation host, and still flags a retailer', async () => {
  await write(
    'index.html',
    [
      '<a href="https://archive.org/details/x">a</a>',
      '<a href="https://web.archive.org/web/2026/https://example.org/">w</a>',
      '<a href="https://newsroom.bmwgroup.com/emea/x">b</a>',
      '<a href="https://en.wikipedia.org/wiki/BMW_M3">e</a>',
      '<a href="https://commons.wikimedia.org/wiki/File:X.jpg">c</a>',
      '<a href="https://www.hubcaphaven.com/p/3015/x.html">retailer</a>',
    ].join(''),
  )
  expect(await checkLinks(dist)).toEqual([
    { file: 'index.html', href: 'https://www.hubcaphaven.com/p/3015/x.html' },
  ])
})
