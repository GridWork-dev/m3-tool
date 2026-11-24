// The `unverified` field on generations and variants: a list of paths to the values that fall below
// data.md's verification rule. The schema checks the shape of each path, and check-data checks
// that it points at something and that none is listed twice.
import { cp, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { beforeAll, describe, expect, test } from 'vitest'
import { loadDataSet } from '../../../src/data/load.ts'
import { checkDataSet, type DataSet } from '../../../src/data/quality.ts'
import { Generation, Variant } from '../../../src/data/schemas.ts'
import { runCheckData } from '../../../tools/check-data.ts'
import { edit, issuePaths, readFixture, VALID_FIXTURES } from './helpers.ts'

let valid: DataSet
beforeAll(async () => {
  const loaded = await loadDataSet(VALID_FIXTURES)
  expect(loaded.issues).toEqual([])
  valid = loaded.set
})

const fresh = (): DataSet => structuredClone(valid)

const find = <T extends { file: string }>(entries: T[], stem: string): T => {
  const entry = entries.find((candidate) => candidate.file.endsWith(`/${stem}.yaml`))
  if (!entry) throw new Error(`fixture ${stem} not found`)
  return entry
}

// The fixture variants and generation, with `unverified` set to `paths` and nothing else changed.
// The US coupe has no render.modules; the CSL has trunk_lid and roof.
const checkVariant = (paths: string[], stem = 'e46-us-coupe') => {
  const set = fresh()
  find(set.variants, stem).data.unverified = paths
  return checkDataSet(set)
}
const checkGeneration = (paths: string[]) => {
  const set = fresh()
  find(set.generations, 'e46').data.unverified = paths
  return checkDataSet(set)
}

const variant = () => readFixture('variants/e46/e46-us-coupe.yaml')
const generation = () => readFixture('generations/e46.yaml')

describe('the unverified field in the schemas', () => {
  const paths = ['paints.FX1.code', 'years.1', 'factoryWheels.fixture-factory-wheel.front.offsetMm']

  test('a variant and a generation accept a list of paths, and keep it as written', () => {
    expect(Variant.parse(edit(variant(), 'unverified', paths)).unverified).toEqual(paths)
    expect(
      Generation.parse(edit(generation(), 'unverified', ['fitment.front.stock.offsetMm']))
        .unverified,
    ).toEqual(['fitment.front.stock.offsetMm'])
  })

  test('the field is optional: an entry with nothing unverified leaves it out', () => {
    expect(Variant.parse(edit(variant(), 'unverified', undefined)).unverified).toBeUndefined()
    expect(Generation.parse(edit(generation(), 'unverified', undefined)).unverified).toBeUndefined()
  })

  test.each([
    ['empty', ''],
    ['blank', '   '],
    ['a leading dot', '.paints.FX1'],
    ['a trailing dot', 'paints.FX1.'],
    ['an empty segment', 'paints..code'],
    ['a space', 'paints.FX1 .code'],
    ['brackets for a position', 'paints[0].code'],
    ['a slash', 'paints/FX1/code'],
    ['a wildcard', 'paints.*.code'],
  ])('refuses a path that is %s', (_label, path) => {
    const result = Variant.safeParse(edit(variant(), 'unverified', [path]))
    expect(result.success).toBe(false)
    expect(issuePaths(result)).toContain('unverified.0')
    expect(Generation.safeParse(edit(generation(), 'unverified', [path])).success).toBe(false)
  })

  test.each([
    ['a string', 'paints.FX1.code'],
    ['an object', { paths: [] }],
    ['a list with a number', ['paints.FX1.code', 7]],
  ])('refuses an unverified field that is %s', (_label, value) => {
    expect(Variant.safeParse(edit(variant(), 'unverified', value)).success).toBe(false)
  })
})

describe('path forms that resolve', () => {
  test.each([
    ['a top-level value', 'market'],
    ['a field of an element addressed by its code', 'paints.FX1.finish'],
    ['a field of an element addressed by its id', 'interiors.fixture-interior.material'],
    ['a nested field of an element', 'factoryWheels.fixture-factory-wheel.front.offsetMm'],
    ['a whole element', 'paints.FX1'],
    ['a whole object inside an element', 'factoryWheels.fixture-factory-wheel.rear'],
    ['a whole object', 'render'],
    ['a whole list of keyed elements', 'paints'],
    ['a whole list with no key', 'transmissions'],
    ['a position in a fixed-length list', 'years.1'],
    ['a whole fixed-length list', 'years'],
    ['a text field that carries a claim', 'packages.fixture-package.summary'],
  ])('a variant path: %s', (_label, path) => {
    expect(checkVariant([path])).toEqual([])
  })

  test('a variant path through a record key', () => {
    expect(checkVariant(['render.modules.trunk_lid'], 'fixture-csl-coupe')).toEqual([])
    expect(checkVariant(['render.modules'], 'fixture-csl-coupe')).toEqual([])
  })

  test.each([
    ['a nested field', 'fitment.front.stock.offsetMm'],
    ['an element addressed by its code', 'engines.FIXTURE-ENGINE.displacementCc'],
    ['a whole element', 'engines.FIXTURE-ENGINE'],
    ['a record key', 'dimensions.coupe.lengthMm'],
    ['a whole record entry', 'dimensions.coupe'],
    ['a whole object', 'driverEyePoint'],
    ['a position in a fixed-length list', 'years.0'],
    ['a whole list with no key', 'fitment.front.envelopes'],
  ])('a generation path: %s', (_label, path) => {
    expect(checkGeneration([path])).toEqual([])
  })

  test('several paths together, in any order', () => {
    expect(
      checkVariant(['years.1', 'paints.FX1.code', 'paints.FX1', 'interiors.fixture-interior.name']),
    ).toEqual([])
  })

  test('a path under another listed path is allowed, and so is an empty list', () => {
    expect(checkVariant(['paints.FX1', 'paints.FX1.code', 'paints'])).toEqual([])
    expect(checkVariant([])).toEqual([])
  })
})

describe('an element is addressed by its id or code, never by its position', () => {
  const withPaints = (codes: string[], path: string) => {
    const set = fresh()
    const entry = find(set.variants, 'e46-us-coupe').data
    const template = structuredClone(entry.paints[0])
    if (!template) throw new Error('fixture paint missing')
    entry.paints = codes.map((code) => ({ ...template, code }))
    entry.unverified = [path]
    return checkDataSet(set)
  }

  test('the same path resolves wherever the element sits in the list', () => {
    expect(withPaints(['FX1', 'FX2'], 'paints.FX2.name')).toEqual([])
    expect(withPaints(['FX2', 'FX1'], 'paints.FX2.name')).toEqual([])
    expect(withPaints(['FX2', 'FX3', 'FX1'], 'paints.FX1')).toEqual([])
  })

  test('a path stops resolving once the element it names is gone', () => {
    const issues = withPaints(['FX2'], 'paints.FX1.code')
    expect(issues.map((issue) => issue.code)).toEqual(['unverified-path-missing'])
    expect(issues[0]?.message).toContain('FX1')
  })

  test('a position is refused on a list of keyed elements, whatever the list holds', () => {
    for (const path of ['paints.0', 'paints.0.code', 'factoryWheels.0.name', 'interiors.1']) {
      const issues = checkVariant([path])
      expect(issues.map((issue) => issue.code)).toEqual(['unverified-path-missing'])
      expect(issues[0]?.message).toMatch(/by its (id|code), not by its position/)
    }
    expect(checkGeneration(['engines.0.code']).map((issue) => issue.code)).toEqual([
      'unverified-path-missing',
    ])
  })

  test('a position is refused on a variable-length list with no key', () => {
    for (const path of ['transmissions.0', 'transmissions.smg', 'sources.0.title']) {
      const issues = checkVariant([path])
      expect(issues.map((issue) => issue.code)).toEqual(['unverified-path-missing'])
      expect(issues[0]?.message).toContain('whole list')
    }
    expect(checkGeneration(['bodies.0', 'sources.0']).map((issue) => issue.code)).toEqual([
      'unverified-path-missing',
      'unverified-path-missing',
    ])
  })

  test('a key is refused on a fixed-length list', () => {
    for (const path of ['years.first', 'years.start', 'years.01', 'years.-1']) {
      const issues = checkVariant([path])
      expect(issues.map((issue) => issue.code)).toEqual(['unverified-path-missing'])
      expect(issues[0]?.message).toContain('position')
    }
  })

  test('two elements with one code make the path ambiguous, so it is refused', () => {
    const issues = withPaints(['FX1', 'FX1'], 'paints.FX1.code')
    expect(issues.map((issue) => issue.code)).toEqual(['unverified-path-missing'])
    expect(issues[0]?.message).toContain('more than one')
  })
})

describe('a path that does not resolve', () => {
  test.each([
    ['a field the schema does not have', 'paints.FX1.nope', 'no field "nope"'],
    ['a field name in the wrong case', 'Paints.FX1', 'no field "Paints"'],
    ['an element that does not exist', 'paints.NOPE', 'no element with code "NOPE"'],
    ['an element id that does not exist', 'factoryWheels.nope.front', 'no element with id "nope"'],
    ['a field with nothing set', 'render.modules', 'is not set'],
    ['a key under a field with nothing set', 'render.modules.trunk_lid', 'is not set'],
    ['a position past the end', 'years.2', 'position 2'],
    ['a path below a value', 'paints.FX1.code.length', 'nothing under it'],
    ['a path below a whole-list value', 'market.us', 'nothing under it'],
    ['the list itself', 'unverified', 'the list itself'],
  ])('a variant path to %s', (_label, path, reason) => {
    const issues = checkVariant([path])
    expect(issues.map((issue) => issue.code)).toEqual(['unverified-path-missing'])
    expect(issues[0]?.file).toBe('variants/e46/e46-us-coupe.yaml')
    expect(issues[0]?.message).toContain(`"${path}"`)
    expect(issues[0]?.message).toContain(reason)
  })

  test.each([
    ['a field the schema does not have', 'fitment.front.stock.nope', 'no field "nope"'],
    ['an engine that does not exist', 'engines.S54B32.cylinders', 'no element with code "S54B32"'],
    ['a record key that does not exist', 'dimensions.sedan', 'no key "sedan"'],
    ['a body the generation lists but has no dimensions for', 'dimensions.convertible', 'no key'],
  ])('a generation path to %s', (_label, path, reason) => {
    const issues = checkGeneration([path])
    expect(issues.map((issue) => issue.code)).toEqual(['unverified-path-missing'])
    expect(issues[0]?.file).toBe('generations/e46.yaml')
    expect(issues[0]?.message).toContain(reason)
  })

  test('every bad path is reported, one issue each', () => {
    const issues = checkVariant(['paints.NOPE', 'years.1', 'interiors.nope.name'])
    expect(issues.map((issue) => issue.code)).toEqual([
      'unverified-path-missing',
      'unverified-path-missing',
    ])
  })
})

describe('a path listed twice', () => {
  test('is a duplicate, reported once for the repeat', () => {
    const issues = checkVariant(['paints.FX1.code', 'years.1', 'paints.FX1.code'])
    expect(issues.map((issue) => issue.code)).toEqual(['unverified-path-duplicate'])
    expect(issues[0]?.file).toBe('variants/e46/e46-us-coupe.yaml')
    expect(issues[0]?.message).toContain('"paints.FX1.code"')
  })

  test('is a duplicate in a generation too', () => {
    const issues = checkGeneration(['fitment.rear.stock.offsetMm', 'fitment.rear.stock.offsetMm'])
    expect(issues.map((issue) => issue.code)).toEqual(['unverified-path-duplicate'])
    expect(issues[0]?.file).toBe('generations/e46.yaml')
  })

  test('is reported for each extra copy', () => {
    const issues = checkVariant(['years.1', 'years.1', 'years.1'])
    expect(issues.map((issue) => issue.code)).toEqual([
      'unverified-path-duplicate',
      'unverified-path-duplicate',
    ])
  })

  test('a duplicate of a bad path reports the repeat and the bad path once', () => {
    const issues = checkVariant(['paints.NOPE', 'paints.NOPE'])
    expect(issues.map((issue) => issue.code).sort()).toEqual([
      'unverified-path-duplicate',
      'unverified-path-missing',
    ])
  })

  test('paths that differ only by being nested are not duplicates', () => {
    expect(checkVariant(['paints.FX1', 'paints.FX1.code'])).toEqual([])
  })
})

describe('check-data', () => {
  const withVariantPaths = async (paths: string[]) => {
    const dir = await mkdtemp(join(tmpdir(), 'check-data-unverified-'))
    await cp(VALID_FIXTURES, dir, { recursive: true })
    const file = join(dir, 'variants/e46/e46-us-coupe.yaml')
    // The fixture ends with its own `unverified` list. Replace it, so the key appears once.
    const text = await readFile(file, 'utf8')
    const head = text.slice(0, text.indexOf('unverified:'))
    await writeFile(file, `${head}unverified:\n${paths.map((path) => `  - ${path}\n`).join('')}`)
    return dir
  }

  test('prints nothing for a list that resolves', async () => {
    const dir = await withVariantPaths(['years.1', 'paints.FX1', 'paints.FX1.code'])
    try {
      expect(await runCheckData(dir)).toEqual({ exitCode: 0, lines: [] })
    } finally {
      await rm(dir, { recursive: true })
    }
  })

  test('prints one file: code: message line for each problem and exits 1', async () => {
    const dir = await withVariantPaths(['paints.NOPE', 'years.1', 'years.1'])
    try {
      const result = await runCheckData(dir)
      expect(result.exitCode).toBe(1)
      expect(result.lines).toHaveLength(2)
      expect(result.lines.join('\n')).toMatch(
        /e46-us-coupe\.yaml: unverified-path-missing: .*"paints\.NOPE"/,
      )
      expect(result.lines.join('\n')).toMatch(
        /e46-us-coupe\.yaml: unverified-path-duplicate: .*"years\.1"/,
      )
    } finally {
      await rm(dir, { recursive: true })
    }
  })

  test('a path with a bad shape is a schema error, not a missing path', async () => {
    const dir = await withVariantPaths(['paints..code'])
    try {
      const result = await runCheckData(dir)
      expect(result.exitCode).toBe(1)
      expect(result.lines.join('\n')).toMatch(/e46-us-coupe\.yaml: schema: unverified\.0: /)
      expect(result.lines.join('\n')).not.toContain('unverified-path-missing')
    } finally {
      await rm(dir, { recursive: true })
    }
  })
})
