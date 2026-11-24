import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, test } from 'vitest'
import { contrastRatio } from './helpers/contrast.ts'

const TOKENS_CSS = 'src/styles/tokens.css'

// Every `--name: value;` declaration in tokens.css, by name. The colour tokens are literal hex.
function readTokens(): Map<string, string> {
  const tokens = new Map<string, string>()
  for (const [, name, value] of readFileSync(TOKENS_CSS, 'utf8').matchAll(
    /^\s*(--[\w-]+)\s*:\s*([^;]+);/gm,
  )) {
    if (name !== undefined && value !== undefined) tokens.set(name, value.trim())
  }
  return tokens
}

const tokens = readTokens()
const colour = (name: string): string => {
  const value = tokens.get(name)
  if (value === undefined) throw new Error(`tokens.css has no ${name}`)
  return value
}
const ratio = (foreground: string, background: string): number =>
  contrastRatio(colour(foreground), colour(background))

test('contrastRatio is the WCAG ratio', () => {
  expect(contrastRatio('#000000', '#ffffff')).toBe(21)
  expect(contrastRatio('#fff', '#fff')).toBe(1)
})

describe('text contrast is at least 4.5 (WCAG AA)', () => {
  const pairs: [foreground: string, background: string][] = [
    ['--text', '--floor'],
    ['--muted', '--floor'],
    ['--dim', '--floor'],
    ['--muted', '--steel-2'],
    ['--dim', '--steel-2'],
    ['--board-ink', '--board'],
    ['--board', '--floor'],
    ['--canary-ink', '--canary'],
    ['--canary-muted', '--canary'],
    ['--canary-muted', '--canary-2'],
    ['--stale', '--canary'],
    ['--stale', '--canary-2'],
    ['--hot', '--floor'],
    ['--hot', '--steel-2'],
  ]
  test.each(pairs)('%s on %s', (foreground, background) => {
    expect(ratio(foreground, background)).toBeGreaterThanOrEqual(4.5)
  })
})

test('--edge on --floor is at least 3 (non-text contrast)', () => {
  expect(ratio('--edge', '--floor')).toBeGreaterThanOrEqual(3)
})

// Tailwind's own palette would let bg-white or text-neutral-500 compile to an off-design colour.
test("theme.css drops Tailwind's default palette", () => {
  expect(readFileSync('src/styles/theme.css', 'utf8')).toMatch(/^\s*--color-\*\s*:\s*initial;/m)
})

// Colours live in tokens.css and nowhere else; everything else reads a token.
describe('no raw colour literals outside tokens.css', () => {
  const LITERAL = /(?<!&)#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsl|hwb|oklch)\(/

  const filesUnder = (dir: string): string[] =>
    readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
      const path = join(dir, entry.name)
      return entry.isDirectory() ? filesUnder(path) : [path]
    })

  const files = ['pages', 'components', 'layouts', 'styles']
    .flatMap((dir) => filesUnder(join('src', dir)))
    .filter((file) => file !== TOKENS_CSS)

  test('the scan sees the site files', () => {
    expect(files).toContain('src/styles/global.css')
    expect(files).toContain('src/layouts/Base.astro')
  })

  test.each(files)('%s', (file) => {
    const hit = readFileSync(file, 'utf8').match(LITERAL)
    expect(hit?.[0]).toBeUndefined()
  })
})
