// Cross-file checks over a loaded DataSet. Per-file rules live in the Zod schemas (schemas.ts);
// these are the rules that need to see more than one file at once.
import type {
  Generation,
  KnownIssue,
  MaintenanceItem,
  Part,
  PriceObservation,
  Source,
  Variant,
} from './schemas.ts'
import {
  Generation as GenerationSchema,
  isNoScheduleTrigger,
  Variant as VariantSchema,
} from './schemas.ts'
import { hasTier1Or2Source, meetsVerificationRule } from './sources.ts'
import { unresolvedReason } from './unverified.ts'

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
  | 'safety-advice-without-evidence'
  | 'no-schedule-without-tier1'
  | 'multiple-generic-in-category'
  | 'variant-body-not-in-generation'
  | 'variant-years-outside-generation'
  | 'part-years-outside-generation'
  | 'part-bodies-outside-generation'
  | 'fits-list-empty'
  | 'unknown-engine'
  | 'model-years-outside-generation'
  | 'future-date'
  | 'unverified-path-missing'
  | 'unverified-path-duplicate'

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

export interface CheckOptions {
  // The date that source and price dates may not pass. Defaults to the clock; tests inject one.
  // Only its calendar date in UTC counts, because data dates are calendar dates at UTC midnight.
  // A date may be one day ahead of it: a contributor east of UTC writes their own date in the
  // early morning, while it is still yesterday in UTC.
  today?: Date
}

const isoDay = (date: Date): string => date.toISOString().slice(0, 10)

export function checkDataSet(set: DataSet, options: CheckOptions = {}): QualityIssue[] {
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
  // and issues. A manufacturer product page is Tier 1. Labor never counts toward it when it is
  // marked `estimated: true`, so a part whose sizes rest on a Tier 1 page can be verified with
  // estimated labor; the rule reads the part's sources only.
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

  // Safety advice never rests on a forum post alone (spec section 7.6): a maintenance item needs
  // one Tier 1 or Tier 2 source, and so does a known issue that publishes a fix. An issue without
  // a fix publishes symptoms, cause and frequency only, so Tier 3 is enough for it.
  for (const { file, data } of set.maintenance) {
    if (!hasTier1Or2Source(data.sources)) {
      add(
        file,
        'safety-advice-without-evidence',
        `maintenance item "${data.id}" has no Tier 1 or Tier 2 source; a service interval never rests on forum posts alone`,
      )
    }
  }
  // A maintenance item that says there is no scheduled service (`lifetime-fill`, `condition-based`)
  // is the strongest negative advice the data can hold: it tells an owner not to change something.
  // It needs a Tier 1 source, whatever its `verified` flag says, because one retailer's article
  // must not be able to publish it (ADR 0016). The coolant is the live example: BMW's US booklet
  // says lifetime fill, and shops recommend an overhaul. The trigger set is shared with the schema.
  for (const { file, data } of set.maintenance) {
    const noSchedule = (data.interval.triggers ?? []).filter(isNoScheduleTrigger)
    if (noSchedule.length > 0 && !data.sources.some((source) => source.tier === 1)) {
      add(
        file,
        'no-schedule-without-tier1',
        `maintenance item "${data.id}" says ${noSchedule.join(' and ')} but has no Tier 1 source; advice that nothing needs changing needs a Tier 1 source, and a retailer or a forum alone is not enough`,
      )
    }
  }
  for (const { file, data } of set.issues) {
    if (data.fix !== undefined && !hasTier1Or2Source(data.sources)) {
      add(
        file,
        'safety-advice-without-evidence',
        `known issue "${data.id}" publishes a fix but has no Tier 1 or Tier 2 source; add one, or remove the fix`,
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

  checkAgainstGeneration(set, add)
  checkUnverified(set, add)
  checkDates(set, options.today ?? new Date(), add)

  return found
}

type Add = (file: string, code: QualityCode, message: string) => void

const list = (values: readonly string[]): string => values.map((value) => `"${value}"`).join(', ')

const outside = (years: readonly [number, number], range: readonly [number, number]): boolean =>
  years[0] < range[0] || years[1] > range[1]

// What a variant, part, maintenance item or issue says about the car must fit the generation it
// belongs to: its body, its years (or model years) and its engine. An entry whose generation does
// not exist is skipped, because `unknown-generation` already covers it.
function checkAgainstGeneration(set: DataSet, add: Add): void {
  const generations = new Map(set.generations.map(({ data }) => [data.id, data]))

  for (const { file, data } of set.variants) {
    const generation = generations.get(data.generation)
    if (!generation) continue
    if (!generation.bodies.includes(data.body)) {
      add(
        file,
        'variant-body-not-in-generation',
        `"${data.id}" is a ${data.body}, but generation "${generation.id}" builds only ${generation.bodies.join(', ')}`,
      )
    }
    if (outside(data.years, generation.years)) {
      add(
        file,
        'variant-years-outside-generation',
        `"${data.id}" runs ${data.years[0]} to ${data.years[1]}, outside generation "${generation.id}" (${generation.years[0]} to ${generation.years[1]})`,
      )
    }
  }

  for (const { file, data } of set.parts) {
    const generation = generations.get(data.fits.generation)
    if (!generation) continue
    const { years, bodies, transmissions } = data.fits
    if (years !== undefined && outside(years, generation.years)) {
      add(
        file,
        'part-years-outside-generation',
        `"${data.id}" fits ${years[0]} to ${years[1]}, outside generation "${generation.id}" (${generation.years[0]} to ${generation.years[1]})`,
      )
    }
    // An empty list would fit nothing, while a missing one fits everything.
    for (const [field, values] of [
      ['bodies', bodies],
      ['transmissions', transmissions],
    ] as const) {
      if (values !== undefined && values.length === 0) {
        add(
          file,
          'fits-list-empty',
          `fits.${field} is empty, which fits nothing; list at least one, or leave it out to fit all`,
        )
      }
    }
    const missing = (bodies ?? []).filter((body) => !generation.bodies.includes(body))
    if (missing.length > 0) {
      add(
        file,
        'part-bodies-outside-generation',
        `fits.bodies has ${list(missing)}, which generation "${generation.id}" does not build (it builds ${generation.bodies.join(', ')})`,
      )
    }
  }

  // A maintenance item or an issue may narrow itself to one engine and to some model years.
  const scopedOwners = [
    ...set.maintenance.map(({ file, data }) => ({
      file,
      id: data.id,
      generation: data.generation,
      engine: data.engine,
      modelYears: data.modelYears,
      kind: 'maintenance item',
    })),
    ...set.issues.map(({ file, data }) => ({
      file,
      id: data.id,
      generation: data.generation,
      engine: data.engine,
      modelYears: data.modelYears,
      kind: 'known issue',
    })),
  ]
  for (const { file, id, generation: generationId, engine, modelYears, kind } of scopedOwners) {
    const generation = generations.get(generationId)
    if (!generation) continue
    if (engine !== undefined) {
      const codes = generation.engines.map((candidate) => candidate.code)
      if (!codes.includes(engine)) {
        add(
          file,
          'unknown-engine',
          `${kind} "${id}" names engine "${engine}", but generation "${generation.id}" has ${list(codes)}`,
        )
      }
    }
    // A model year can run one ahead of the calendar year of production, so the generation's last
    // production year admits a model year one later (data.md, "Model years").
    const [first, last] = generation.years
    if (modelYears !== undefined && outside(modelYears, [first, last + 1])) {
      add(
        file,
        'model-years-outside-generation',
        `${kind} "${id}" is scoped to model years ${modelYears[0]} to ${modelYears[1]}, outside generation "${generation.id}" (${first} to ${last}, plus one at the end for a model year that runs ahead)`,
      )
    }
  }
}

// `unverified` lists paths to values in the same file (data.md, "Unverified values"). Each path
// must point at a value, which unverified.ts decides from the schema and the parsed data, and none
// may be listed twice. A repeated path is reported once for each extra copy and is not resolved
// again, so a duplicate of a bad path reports one of each.
function checkUnverified(set: DataSet, add: Add): void {
  const lists = [
    [set.generations, GenerationSchema],
    [set.variants, VariantSchema],
  ] as const
  for (const [entries, schema] of lists) {
    for (const { file, data } of entries) {
      const seen = new Set<string>()
      for (const path of data.unverified ?? []) {
        if (seen.has(path)) {
          add(file, 'unverified-path-duplicate', `unverified lists "${path}" more than once`)
          continue
        }
        seen.add(path)
        const reason = unresolvedReason(schema, data, path)
        if (reason !== undefined) {
          add(
            file,
            'unverified-path-missing',
            `unverified path "${path}" does not point at a value: ${reason}`,
          )
        }
      }
    }
  }
}

// A source cannot have been accessed, and a price cannot have been checked, after today, with a
// day of slack for time zones east of UTC. Every date is compared as a calendar date: data dates
// are UTC midnights.
function checkDates(set: DataSet, now: Date, add: Add): void {
  const DAY = 24 * 60 * 60 * 1000
  const today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate())
  const latest = today + DAY
  const flag = (file: string, what: string, date: Date) => {
    if (date.getTime() > latest) {
      add(
        file,
        'future-date',
        `${what} is dated ${isoDay(date)}, more than a day after today (${isoDay(new Date(today))})`,
      )
    }
  }
  const sources = (file: string, owner: string, entries: readonly Source[]) => {
    for (const source of entries) {
      flag(file, `source "${source.title}" of ${owner} (accessed)`, source.accessed)
    }
  }
  const prices = (file: string, owner: string, entries: readonly PriceObservation[] = []) => {
    for (const price of entries) {
      flag(file, `price from ${price.seller} on ${owner} (checked)`, price.checked)
    }
  }

  for (const { file, data } of set.generations) {
    const owner = `generation "${data.id}"`
    sources(file, owner, data.sources)
    for (const dimensions of Object.values(data.dimensions))
      sources(file, owner, dimensions.sources)
    sources(file, owner, data.driverEyePoint.sources)
    sources(file, owner, data.fitment.sources)
  }
  for (const { file, data } of set.variants) sources(file, `variant "${data.id}"`, data.sources)
  for (const { file, data } of set.parts) {
    const owner = `part "${data.id}"`
    sources(file, owner, data.sources)
    prices(file, owner, data.prices)
    for (const option of data.options ?? [])
      prices(file, `${owner} option "${option.id}"`, option.prices)
  }
  for (const { file, data } of set.maintenance) {
    sources(file, `maintenance item "${data.id}"`, data.sources)
  }
  for (const { file, data } of set.issues) sources(file, `known issue "${data.id}"`, data.sources)
}
