import { pathToFileURL } from 'node:url'
import { glob } from 'astro/loaders'
import { expect, test } from 'vitest'
import { parse } from 'yaml'
import { entryId } from '../../../src/data/entry-id.ts'
import { Part } from '../../../src/data/schemas.ts'
import { readFixture, VALID_FIXTURES } from './helpers.ts'

test('a nested file gets the bare YAML id, not its path', () => {
  expect(entryId({ entry: 'e46/fixture-wheel.yaml', data: { id: 'fixture-wheel' } })).toBe(
    'fixture-wheel',
  )
  expect(entryId({ entry: 'e46.yaml', data: { id: 'e46' } })).toBe('e46')
})

test('the YAML id wins over the file name, so a misnamed file is reported by id-filename-mismatch', () => {
  expect(entryId({ entry: 'e46/renamed.yaml', data: { id: 'fixture-wheel' } })).toBe(
    'fixture-wheel',
  )
})

test('every fixture id is what its file says, with and without a generation directory', () => {
  for (const [entry, file] of [
    ['e46/fixture-wheel.yaml', 'parts/e46/fixture-wheel.yaml'],
    ['e46/fixture-coilovers.yaml', 'parts/e46/fixture-coilovers.yaml'],
    ['e46/fixture-oil-service.yaml', 'maintenance/e46/fixture-oil-service.yaml'],
    ['e46.yaml', 'generations/e46.yaml'],
  ] as const) {
    const data = readFixture(file)
    expect(entryId({ entry, data })).toBe(data.id)
  }
})

test('a file with no usable id falls back to its stem, so the schema reports the missing id', () => {
  expect(entryId({ entry: 'e46/fixture-wheel.yaml', data: {} })).toBe('fixture-wheel')
  expect(entryId({ entry: 'e46/fixture-wheel.yaml', data: { id: 46 } })).toBe('fixture-wheel')
  expect(entryId({ entry: 'e46/fixture-wheel.yaml', data: { id: '' } })).toBe('fixture-wheel')
  expect(entryId({ entry: 'fixture-wheel.yaml', data: {} })).toBe('fixture-wheel')
})

// Runs Astro's own glob loader over the nested fixture directory, with the minimum of the loader
// context it needs, and reads back the ids it stored. This is the id `requires` has to match.
async function loadedIds(generateId?: typeof entryId): Promise<string[]> {
  const store = new Map<string, unknown>()
  const loader = glob({
    pattern: '**/*.yaml',
    base: `${VALID_FIXTURES}/parts`,
    ...(generateId ? { generateId } : {}),
  })
  const root = pathToFileURL(`${VALID_FIXTURES}/`)
  await loader.load({
    config: { root, srcDir: new URL('src/', root) },
    collection: 'parts',
    logger: { warn: () => {}, error: () => {}, info: () => {}, debug: () => {} },
    parseData: async ({ data }: { data: unknown }) => Part.parse(data),
    store: {
      keys: () => store.keys(),
      get: (id: string) => store.get(id),
      set: (entry: { id: string }) => {
        store.set(entry.id, entry)
        return true
      },
      delete: (id: string) => store.delete(id),
    },
    generateDigest: (data: unknown) => JSON.stringify(data),
    entryTypes: new Map([
      [
        '.yaml',
        {
          getEntryInfo: async ({ contents }: { contents: string }) => ({
            data: parse(contents),
            body: '',
          }),
        },
      ],
    ]),
    // biome-ignore lint/suspicious/noExplicitAny: the loader context is larger than this test needs
  } as any)
  return [...store.keys()].sort()
}

test("Astro's glob loader stores parts under their bare ids", async () => {
  expect(await loadedIds(entryId)).toEqual([
    'fixture-coilovers',
    'fixture-generic-wheels',
    'fixture-wheel',
  ])
})

test("without generateId, Astro's default ids carry the generation directory", async () => {
  // The control: this is the mismatch `requires: [fixture-wheel]` would hit.
  expect(await loadedIds()).toEqual([
    'e46/fixture-coilovers',
    'e46/fixture-generic-wheels',
    'e46/fixture-wheel',
  ])
})
