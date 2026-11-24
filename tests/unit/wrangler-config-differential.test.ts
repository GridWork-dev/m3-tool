// A differential test of the config check against wrangler itself (review N1). The check parses
// wrangler.jsonc with its own small JSONC reader, so it can disagree with the reader wrangler
// uses (jsonc-parser, bundled inside wrangler and not installed as a package of its own). Here
// both read the same corpus: wrangler through its own `unstable_readConfig`, which runs nothing,
// and the check. Wherever wrangler reads something that would run a command, ship code or change
// what the Worker is, the check has to refuse the file.
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterAll, beforeAll, describe, expect, test } from 'vitest'
import { unstable_readConfig } from 'wrangler'
import { checkWranglerConfig, parseJsonc } from '../../infra/deploy/check-config.ts'

// Built from code points: a formatter turns a \u escape into the invisible character itself.
const LS = String.fromCharCode(0x2028)
const PS = String.fromCharCode(0x2029)
const BOM = String.fromCharCode(0xfeff)
const NEL = String.fromCharCode(0x85)
const NBSP = String.fromCharCode(0xa0)
const IDEO = String.fromCharCode(0x3000)

let dir: string
beforeAll(async () => {
  dir = await mkdtemp(join(tmpdir(), 'wrangler-differential-'))
})
afterAll(() => rm(dir, { recursive: true, force: true }))

interface Read {
  ok: boolean
  name?: string | undefined
  dangerous: string[]
}

let counter = 0
async function readWithWrangler(text: string): Promise<Read> {
  const file = join(dir, `wrangler-${counter++}.jsonc`)
  await writeFile(file, text)
  try {
    const config = unstable_readConfig({ config: file }, {})
    const dangerous: string[] = []
    if (config.build?.command) dangerous.push('build.command')
    if (config.main) dangerous.push('main')
    if (config.triggers?.crons?.length) dangerous.push('triggers')
    if (config.routes?.length) dangerous.push('routes')
    if (config.kv_namespaces?.length) dangerous.push('kv_namespaces')
    if (config.d1_databases?.length) dangerous.push('d1_databases')
    if (config.r2_buckets?.length) dangerous.push('r2_buckets')
    if (Object.keys(config.vars ?? {}).length) dangerous.push('vars')
    return { ok: true, name: config.name, dangerous }
  } catch {
    return { ok: false, dangerous: [] } // wrangler refuses the file, so nothing runs
  }
}

const BASE = '{"name":"m3-tool","compatibility_date":"2026-11-23"'
const BUILD = '"build":{"command":"echo hi"}'
const MAIN = '"main":"x.js"'
const VARS = '"vars":{"A":"1"}'

const CORPUS: [string, string][] = [
  ['a plain config', `${BASE}}`],
  ['a build key', `${BASE},${BUILD}}`],
  ['a main key', `${BASE},${MAIN}}`],
  ['vars', `${BASE},${VARS}}`],
  ['a comment ended by LF', `${BASE}, // c\n${BUILD}\n}`],
  ['a comment ended by CRLF', `${BASE}, // c\r\n${BUILD}\n}`],
  ['a comment ended by a lone CR (the review reproduction)', `${BASE}, // c\r${BUILD}\n}`],
  ['a main hidden after a lone CR', `${BASE}, // c\r${MAIN}\n}`],
  ['a comment ended by U+2028', `${BASE}, // c${LS}${BUILD}\n}`],
  ['a comment ended by U+2029', `${BASE}, // c${PS}${BUILD}\n}`],
  ['a comment ended by a vertical tab', `${BASE}, // c\u000b${BUILD}\n}`],
  ['a comment ended by a form feed', `${BASE}, // c\u000c${BUILD}\n}`],
  ['a comment ended by NEL (U+0085)', `${BASE}, // c${NEL}${BUILD}\n}`],
  ['a block comment that hides a build', `${BASE} /* ${BUILD} */}`],
  ['a block comment before a build', `${BASE}, /* c */ ${BUILD}}`],
  ['a block comment containing a lone CR', `${BASE}, /* a\rb */ ${BUILD}}`],
  ['a nested comment opener', `${BASE}, /* /* */ ${BUILD}}`],
  ['a line comment inside a block comment', `${BASE}, /* // */ ${BUILD}}`],
  ['a block comment inside a line comment', `${BASE}, // /*\n${BUILD}\n}`],
  ['an unterminated block comment', `${BASE} /* ${BUILD}}`],
  [
    'comment markers in a string',
    `{"name":"// m3-tool /* x */","compatibility_date":"2026-11-23",${BUILD}}`,
  ],
  ['an escaped quote then a comment marker', `{"name":"a\\"// b",${BUILD}}`],
  ['a trailing comma', `${BASE},}`],
  ['a trailing comma before a build', `${BASE},${BUILD},}`],
  ['two trailing commas', `${BASE},,}`],
  ['a duplicate name', '{"name":"a","name":"b"}'],
  ['a duplicate build', `${BASE},"build":{},${BUILD}}`],
  ['an escaped duplicate', '{"name":"a","\\u006eame":"b"}'],
  ['a duplicate in assets', `${BASE},"assets":{"directory":"./a","directory":"./b"}}`],
  ['__proto__', `${BASE},"__proto__":{"command":"x"}}`],
  ['a byte order mark first', `${BOM}${BASE}}`],
  ['two byte order marks first', `${BOM}${BOM}${BASE}}`],
  ['a byte order mark in the middle', `${BASE},${BOM}${BUILD}}`],
  ['a NUL before a build', `${BASE},\u0000${BUILD}}`],
  ['a non-breaking space between tokens', `${BASE},${NBSP}${BUILD}}`],
  ['an ideographic space between tokens', `${BASE},${IDEO}${BUILD}}`],
  [
    'tabs and CRLF throughout',
    `{\r\n\t"name": "m3-tool",\r\n\t"compatibility_date": "2026-11-23",\r\n\t${BUILD}\r\n}`,
  ],
  ['single-quoted keys', `{'name':'m3-tool',${BUILD}}`],
  ['unquoted keys', `{name:"m3-tool",${BUILD}}`],
  ['a build with a number command', `${BASE},"build":{"command":1}}`],
  ['an array at the top', `[${BASE}}]`],
  ['two documents', `${BASE}} ${BASE},${BUILD}}`],
  ['a leading comment', `// config\n${BASE}}`],
  ['a leading comment ended by CR', `// config\r${BASE},${BUILD}}`],
]

describe('the config check against wrangler, on a fixed corpus', () => {
  test('the corpus is not trivially small, and wrangler reads most of it', async () => {
    const reads = await Promise.all(CORPUS.map(([, text]) => readWithWrangler(text)))
    expect(CORPUS.length).toBeGreaterThanOrEqual(40)
    expect(reads.filter((read) => read.ok).length).toBeGreaterThan(10)
    expect(reads.filter((read) => read.dangerous.length > 0).length).toBeGreaterThan(5)
  })

  test.each(CORPUS)(
    '%s: when wrangler would run or ship something, the check refuses the file',
    async (_label, text) => {
      const read = await readWithWrangler(text)
      if (read.dangerous.length > 0) {
        expect(
          checkWranglerConfig(text),
          `wrangler reads ${read.dangerous.join(', ')}`,
        ).not.toEqual([])
      }
    },
  )

  test.each(CORPUS)(
    '%s: when the check accepts the file, it reads the same name as wrangler',
    async (_label, text) => {
      if (checkWranglerConfig(text).length > 0) return
      const read = await readWithWrangler(text)
      if (read.ok) expect(read.name).toBe((parseJsonc(text) as { name: string }).name)
    },
  )

  test('the review reproduction is the case that tells the two readers apart', async () => {
    const text = `${BASE}, // c\r${BUILD}\n}`
    expect((await readWithWrangler(text)).dangerous).toContain('build.command')
    expect(checkWranglerConfig(text)).not.toEqual([])
  })
})
