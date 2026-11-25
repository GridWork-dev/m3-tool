import { readFileSync } from 'node:fs'
import { expect, test } from 'vitest'
import { NOTICE } from '../../src/lib/notice.ts'

// The notice is pinned to the rulebook, not just to itself.
test('NOTICE is the exact text in AGENTS.md and the legal standard', () => {
  expect(NOTICE).toBe(
    'Independent fan project. Not affiliated with, endorsed by, or sponsored by BMW AG. BMW and M3 are trademarks of BMW AG, used here only to describe the cars.',
  )
  for (const file of ['AGENTS.md', 'docs/standards/legal.md']) {
    expect(readFileSync(file, 'utf8')).toContain(NOTICE)
  }
})
