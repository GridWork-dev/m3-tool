// Cross-file checks over a loaded DataSet. Per-file rules live in the Zod schemas (schemas.ts);
// these are the rules that need to see more than one file at once.
import type { Generation, KnownIssue, MaintenanceItem, Part, Source, Variant } from './schemas.ts'
import { meetsVerificationRule } from './sources.ts'

export type QualityCode =
  | 'schema'
  | 'duplicate-id'
  | 'id-filename-mismatch'
  | 'unknown-generation'
  | 'directory-generation-mismatch'
  | 'unknown-ref'
  | 'self-ref'
  | 'requires-conflicts-overlap'
  | 'verified-without-tier'
  | 'multiple-generic-in-category'

export interface QualityIssue {
  file: string
  code: QualityCode
  message: string
}

// `file` is the path relative to the data directory, with forward slashes (parts/e46/x.yaml).
export interface Entry<T> {
  file: string
  data: T
}

export interface DataSet {
  generations: Entry<Generation>[]
  variants: Entry<Variant>[]
  parts: Entry<Part>[]
  maintenance: Entry<MaintenanceItem>[]
  issues: Entry<KnownIssue>[]
}

const stemOf = (file: string): string => {
  const name = file.split('/').pop() ?? file
  return name.replace(/\.yaml$/, '')
}

// For parts/e46/x.yaml this is "e46"; undefined when the file is not under a generation directory.
const directoryOf = (file: string): string | undefined => {
  const segments = file.split('/')
  return segments.length >= 3 ? segments[1] : undefined
}

export function checkDataSet(set: DataSet): QualityIssue[] {
  const found: QualityIssue[] = []
  const add = (file: string, code: QualityCode, message: string) =>
    found.push({ file, code, message })

  const collections: [string, Entry<{ id: string }>[]][] = [
    ['generation', set.generations],
    ['variant', set.variants],
    ['part', set.parts],
    ['maintenance item', set.maintenance],
    ['known issue', set.issues],
  ]

  // Ids are unique within a collection (across generations), and each file is named for its id.
  for (const [label, entries] of collections) {
    const firstFile = new Map<string, string>()
    for (const { file, data } of entries) {
      const first = firstFile.get(data.id)
      if (first !== undefined) {
        add(file, 'duplicate-id', `${label} id "${data.id}" is already used by ${first}`)
      } else {
        firstFile.set(data.id, file)
      }
      if (stemOf(file) !== data.id) {
        add(
          file,
          'id-filename-mismatch',
          `file is named "${stemOf(file)}" but the id is "${data.id}"; they must match`,
        )
      }
    }
  }

  // Everything below a generation names it, and sits in that generation's directory.
  const generationIds = new Set(set.generations.map(({ data }) => data.id))
  const owned: [string, string, string][] = [
    ...set.variants.map(({ file, data }): [string, string, string] => [
      file,
      data.id,
      data.generation,
    ]),
    ...set.parts.map(({ file, data }): [string, string, string] => [
      file,
      data.id,
      data.fits.generation,
    ]),
    ...set.maintenance.map(({ file, data }): [string, string, string] => [
      file,
      data.id,
      data.generation,
    ]),
    ...set.issues.map(({ file, data }): [string, string, string] => [
      file,
      data.id,
      data.generation,
    ]),
  ]
  for (const [file, id, generation] of owned) {
    if (!generationIds.has(generation)) {
      // Skip the directory check: against a generation that doesn't exist it would only add noise.
      add(
        file,
        'unknown-generation',
        `"${id}" belongs to generation "${generation}", which does not exist`,
      )
      continue
    }
    const directory = directoryOf(file)
    if (directory !== undefined && directory !== generation) {
      add(
        file,
        'directory-generation-mismatch',
        `file is under ${directory}/ but "${id}" belongs to generation "${generation}"`,
      )
    }
  }

  // requires and conflicts name other parts.
  const partIds = new Set(set.parts.map(({ data }) => data.id))
  for (const { file, data } of set.parts) {
    const requires = data.requires ?? []
    const conflicts = data.conflicts ?? []
    for (const [field, ids] of [
      ['requires', requires],
      ['conflicts', conflicts],
    ] as const) {
      for (const ref of ids) {
        if (ref === data.id) add(file, 'self-ref', `"${data.id}" lists itself in ${field}`)
        else if (!partIds.has(ref))
          add(file, 'unknown-ref', `${field} names "${ref}", but no part has that id`)
      }
    }
    for (const ref of requires) {
      if (conflicts.includes(ref)) {
        add(file, 'requires-conflicts-overlap', `"${ref}" is in both requires and conflicts`)
      }
    }
  }

  // Verified means one Tier 1 source or two independent Tier 2 sources (spec section 7.6), and it
  // means that on every collection that has a `verified` flag: parts as much as maintenance items
  // and issues. A manufacturer product page is Tier 1.
  const verifiable: [string, string, boolean, readonly Source[]][] = [
    ...set.parts.map(({ file, data }): [string, string, boolean, readonly Source[]] => [
      file,
      data.id,
      data.verified,
      data.sources,
    ]),
    ...set.maintenance.map(({ file, data }): [string, string, boolean, readonly Source[]] => [
      file,
      data.id,
      data.verified,
      data.sources,
    ]),
    ...set.issues.map(({ file, data }): [string, string, boolean, readonly Source[]] => [
      file,
      data.id,
      data.verified,
      data.sources,
    ]),
  ]
  for (const [file, id, verified, sources] of verifiable) {
    if (verified && !meetsVerificationRule(sources)) {
      add(
        file,
        'verified-without-tier',
        `"${id}" is verified but its sources are not one Tier 1 or two independent Tier 2 sources`,
      )
    }
  }

  // Each category has at most one generic (brandless) part per generation, because the generic
  // tier's price is computed for the category as a whole.
  const firstGeneric = new Map<string, string>()
  for (const { file, data } of set.parts) {
    if (data.brand !== undefined) continue
    const key = `${data.fits.generation}/${data.category}`
    const first = firstGeneric.get(key)
    if (first !== undefined) {
      add(
        file,
        'multiple-generic-in-category',
        `generation "${data.fits.generation}" already has a generic ${data.category} part (${first}); each category has one`,
      )
    } else {
      firstGeneric.set(key, file)
    }
  }

  return found
}
