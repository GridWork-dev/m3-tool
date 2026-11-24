import { execSync } from 'node:child_process'
import { readFileSync, readlinkSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, test } from 'vitest'

const root = fileURLToPath(new URL('../../', import.meta.url))
// -z keeps non-ASCII names unquoted, so a file named `é.png` still ends in `.png`.
const tracked = execSync('git ls-files -z', { cwd: root, encoding: 'utf8' })
  .split('\0')
  .filter(Boolean)

// Images, models, textures, camera raws and archives. Only the places in ALLOWED_MEDIA may hold them.
const MEDIA =
  /\.(jpe?g|png|webp|avif|gif|tiff?|bmp|heic|heif|hdr|exr|ktx2|basis|psd|cr2|nef|arw|dng|glb|gltf|blend|fbx|obj|usd|usdz|zip|7z|tar)$/i
// `public/` holds the favicon and the icons, nothing else. Fixtures may hold any media.
const ALLOWED_MEDIA = /^(public\/favicon\.[^/]+|public\/icons\/.+|tests\/fixtures\/.+)$/

const misplacedMedia = (files: string[]): string[] =>
  files.filter((f) => MEDIA.test(f) && !ALLOWED_MEDIA.test(f))

// A tracked file can be deleted in the working tree before the deletion is staged.
const readIfPresent = (path: string): string | undefined => {
  try {
    return readFileSync(path, 'utf8')
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return undefined
    throw error
  }
}

test('CLAUDE.md is a symlink to AGENTS.md', () => {
  expect(readlinkSync(`${root}CLAUDE.md`)).toBe('AGENTS.md')
})

test('no images, models or archives are tracked outside allowed folders', () => {
  expect(misplacedMedia(tracked)).toEqual([])
})

describe('the media rule', () => {
  test.each([
    'gif',
    'tif',
    'tiff',
    'bmp',
    'heic',
    'heif',
    'hdr',
    'exr',
    'ktx2',
    'basis',
    'fbx',
    'obj',
    'usd',
    'usdz',
    'psd',
    'cr2',
    'nef',
    'arw',
    'dng',
    'zip',
    '7z',
    'tar',
    // The original list, which must keep working.
    'jpg',
    'jpeg',
    'png',
    'webp',
    'avif',
    'glb',
    'gltf',
    'blend',
  ])('flags .%s outside the allowed folders', (extension) => {
    expect(misplacedMedia([`src/assets/file.${extension}`])).toEqual([
      `src/assets/file.${extension}`,
    ])
    expect(misplacedMedia([`public/file.${extension}`])).toEqual([`public/file.${extension}`])
  })

  test('is case-insensitive', () => {
    expect(misplacedMedia(['src/Photo.PNG', 'docs/model.GlB'])).toEqual([
      'src/Photo.PNG',
      'docs/model.GlB',
    ])
  })

  test('allows the favicon, the icons and the test fixtures', () => {
    expect(
      misplacedMedia([
        'public/favicon.png',
        'public/favicon.ico',
        'public/favicon.svg',
        'public/icons/apple-touch-icon.png',
        'public/icons/maskable/512.png',
        'tests/fixtures/assets/e46.glb',
        'tests/fixtures/data/valid/sample.zip',
      ]),
    ).toEqual([])
  })

  test('limits public/ media to the favicon and the icons', () => {
    const rejected = [
      'public/hero.png',
      'public/images/car.jpg',
      'public/models/e46.glb',
      'public/favicon/large.png', // a folder, not a favicon file
      'public/icons-extra/x.png', // shares a prefix with public/icons/
      'public/iconsx.png',
      'public/nested/favicon.png',
      'public/downloads/refs.zip',
    ]
    expect(misplacedMedia(rejected)).toEqual(rejected)
  })

  test('ignores files that are not media', () => {
    expect(
      misplacedMedia(['public/robots.txt', 'public/favicon', 'src/objects.ts', 'docs/tarball.md']),
    ).toEqual([])
  })
})

describe('readIfPresent', () => {
  test('treats a missing file as absent', () => {
    expect(readIfPresent(`${root}no-such-file.json`)).toBeUndefined()
  })

  test('reads a file that exists', () => {
    expect(readIfPresent(`${root}package.json`)).toContain('"name"')
  })

  test('still throws for errors other than a missing file', () => {
    expect(() => readIfPresent(root)).toThrow(/EISDIR/)
  })
})

test('no env files are tracked', () => {
  expect(tracked.filter((f) => /(^|\/)\.env/.test(f))).toEqual([])
})

test('no forbidden secret names appear in tracked config', () => {
  for (const f of tracked.filter((f) => /\.(json|jsonc|toml|ya?ml|sh)$/.test(f))) {
    const text = readIfPresent(`${root}${f}`)
    if (text === undefined) continue
    expect(text, f).not.toMatch(/\b(ANTHROPIC|OPENAI)_API_KEY\b/)
  }
})
