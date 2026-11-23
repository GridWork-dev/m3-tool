import { execSync } from 'node:child_process'
import { readFileSync, readlinkSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { expect, test } from 'vitest'

const root = fileURLToPath(new URL('../../', import.meta.url))
const tracked = execSync('git ls-files', { cwd: root, encoding: 'utf8' })
  .split('\n')
  .filter(Boolean)

test('CLAUDE.md is a symlink to AGENTS.md', () => {
  expect(readlinkSync(`${root}CLAUDE.md`)).toBe('AGENTS.md')
})

test('no images or GLBs are tracked outside allowed folders', () => {
  const media = tracked.filter((f) => /\.(jpe?g|png|webp|avif|heic|glb|gltf|blend)$/i.test(f))
  expect(media.filter((f) => !/^(public\/|tests\/fixtures\/)/.test(f))).toEqual([])
})

test('no env files are tracked', () => {
  expect(tracked.filter((f) => /(^|\/)\.env/.test(f))).toEqual([])
})

test('no forbidden secret names appear in tracked config', () => {
  for (const f of tracked.filter((f) => /\.(json|jsonc|toml|ya?ml|sh)$/.test(f))) {
    expect(readFileSync(`${root}${f}`, 'utf8'), f).not.toMatch(/\b(ANTHROPIC|OPENAI)_API_KEY\b/)
  }
})
