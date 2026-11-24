// Checks that wrangler.jsonc is data and not code, before any step that holds the Cloudflare token.
//
// `wrangler deploy` runs `build.command` from the config in a shell with the token in its
// environment, `main` ships server code, and bindings, routes and triggers change what the Worker
// is. The site is static, so its config needs only a name, a date and where the assets are. Any
// other key fails the deploy job (ADR 0011). This file imports nothing but node: modules, because
// it runs before anything is installed.
//
// Usage: node infra/deploy/check-config.ts <wrangler.jsonc>
// Exit codes: 0 the config is acceptable, 1 it is not, 2 bad usage.
import { readFileSync } from 'node:fs'

export const ALLOWED_TOP_LEVEL_KEYS = [
  '$schema',
  'name',
  'compatibility_date',
  'assets',
  'workers_dev',
  'preview_urls',
] as const

// `binding` and `run_worker_first` need a Worker script, and `base_path` changes the routes.
export const ALLOWED_ASSETS_KEYS = ['directory', 'not_found_handling', 'html_handling'] as const

const NOT_FOUND_HANDLING = ['404-page', 'single-page-application', 'none']
const HTML_HANDLING = ['auto-trailing-slash', 'force-trailing-slash', 'drop-trailing-slash', 'none']

// Copies a string literal starting at `start` (a double quote) and returns where it ends.
function stringEnd(text: string, start: number): number {
  let end = start + 1
  while (end < text.length && text[end] !== '"') end += text[end] === '\\' ? 2 : 1
  return end + 1
}

// Removes // and /* */ comments, outside strings. An unclosed comment throws.
function stripComments(text: string): string {
  let out = ''
  let at = 0
  while (at < text.length) {
    const char = text[at]
    if (char === '"') {
      const end = stringEnd(text, at)
      out += text.slice(at, end)
      at = end
    } else if (char === '/' && text[at + 1] === '/') {
      const newline = text.indexOf('\n', at)
      at = newline === -1 ? text.length : newline
    } else if (char === '/' && text[at + 1] === '*') {
      const close = text.indexOf('*/', at + 2)
      if (close === -1) throw new Error('a /* comment is never closed')
      out += ' '
      at = close + 2
    } else {
      out += char
      at += 1
    }
  }
  return out
}

// Removes a comma that is followed, past whitespace, by } or ], outside strings.
function stripTrailingCommas(text: string): string {
  let out = ''
  let at = 0
  while (at < text.length) {
    const char = text[at]
    if (char === '"') {
      const end = stringEnd(text, at)
      out += text.slice(at, end)
      at = end
    } else if (char === ',') {
      let next = at + 1
      while (next < text.length && /\s/.test(text[next] ?? '')) next += 1
      if (text[next] !== '}' && text[next] !== ']') out += char
      at += 1
    } else {
      out += char
      at += 1
    }
  }
  return out
}

// Parses JSON with comments and trailing commas, the way wrangler reads wrangler.jsonc.
export function parseJsonc(text: string): unknown {
  const source = text.charCodeAt(0) === 0xfeff ? text.slice(1) : text
  return JSON.parse(stripTrailingCommas(stripComments(source)))
}

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

// One message for each way `text` is not an acceptable config. An empty list means it is.
export function checkWranglerConfig(text: string): string[] {
  let config: unknown
  try {
    config = parseJsonc(text)
  } catch (error) {
    return [`wrangler.jsonc is not valid JSONC: ${error instanceof Error ? error.message : error}`]
  }
  if (!isObject(config)) return ['wrangler.jsonc must be a JSON object']

  const problems: string[] = []
  const allowed: readonly string[] = ALLOWED_TOP_LEVEL_KEYS
  for (const key of Object.keys(config)) {
    if (!allowed.includes(key)) {
      problems.push(
        `${JSON.stringify(key)} is not allowed in wrangler.jsonc; the deploy job accepts only ${ALLOWED_TOP_LEVEL_KEYS.join(', ')}`,
      )
    }
  }
  if (typeof config.name !== 'string' || config.name === '') {
    problems.push('"name" must be a non-empty string: it names the Worker the token deploys')
  }
  const date = config.compatibility_date
  if (date !== undefined && !(typeof date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(date))) {
    problems.push('"compatibility_date" must be a date like 2026-11-23')
  }
  for (const key of ['workers_dev', 'preview_urls'] as const) {
    if (config[key] !== undefined && typeof config[key] !== 'boolean') {
      problems.push(`"${key}" must be true or false`)
    }
  }

  const assets = config.assets
  if (assets !== undefined) {
    if (!isObject(assets)) {
      problems.push('"assets" must be an object')
    } else {
      const allowedAssets: readonly string[] = ALLOWED_ASSETS_KEYS
      for (const key of Object.keys(assets)) {
        if (!allowedAssets.includes(key)) {
          problems.push(
            `assets.${key} is not allowed in wrangler.jsonc; the deploy job accepts only ${ALLOWED_ASSETS_KEYS.join(', ')}`,
          )
        }
      }
      if (assets.directory !== undefined && typeof assets.directory !== 'string') {
        problems.push('assets.directory must be a string')
      }
      const notFound = assets.not_found_handling
      if (notFound !== undefined && !NOT_FOUND_HANDLING.includes(String(notFound))) {
        problems.push(`assets.not_found_handling must be one of ${NOT_FOUND_HANDLING.join(', ')}`)
      }
      const html = assets.html_handling
      if (html !== undefined && !HTML_HANDLING.includes(String(html))) {
        problems.push(`assets.html_handling must be one of ${HTML_HANDLING.join(', ')}`)
      }
    }
  }
  return problems
}

if (import.meta.main) {
  const file = process.argv[2]
  if (!file) {
    console.error('usage: node infra/deploy/check-config.ts <wrangler.jsonc>')
    process.exit(2)
  }
  let text: string
  try {
    text = readFileSync(file, 'utf8')
  } catch {
    console.error(`check-config: cannot read ${file}`)
    process.exit(2)
  }
  const problems = checkWranglerConfig(text)
  for (const problem of problems) console.error(`${file}: ${problem}`)
  process.exitCode = problems.length > 0 ? 1 : 0
}
