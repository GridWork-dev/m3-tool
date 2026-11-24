// The data contract: one Zod schema per collection, plus the shared pieces they are built from.
// Cross-file rules (duplicate ids, references between parts, ...) live in quality.ts.
import { z } from 'astro/zod'
import { BODY_MODULES } from '../lib/asset-contract.ts'

// ---------------------------------------------------------------------------------------------
// Building blocks
// ---------------------------------------------------------------------------------------------

export const ID_PATTERN = /^[a-z0-9]+(-[a-z0-9]+)*$/

export const Id = z
  .string()
  .regex(ID_PATTERN, 'must be kebab-case: lowercase letters and digits joined by single hyphens')
// Required text: non-empty once trimmed, so "   " is refused. The value itself is kept as written.
export const Text = z.string().refine((value) => value.trim() !== '', 'must not be empty')
const Year = z.int().min(1985).max(2035)
const YearRange = z
  .tuple([Year, Year])
  .refine(([first, last]) => first <= last, 'first year must not be after the last year')
const Range = z
  .tuple([z.number().min(0), z.number().min(0)])
  .refine(([min, max]) => min <= max, 'min must not exceed max')
export const HttpsUrl = z.url({ protocol: /^https$/ })

// A date is a calendar date, with no time of day: `YYYY-MM-DD`, or a Date at exactly UTC midnight.
// YAML dates reach us two ways. `yaml` (YAML 1.2) keeps `2026-11-23` a string, while Astro's loader
// turns it into a Date at UTC midnight. Both validate to that same instant.
//
// Times are refused on purpose. `new Date('2026-11-23T10:30')` is read in the host's time zone, so
// the same file would mean different instants on different machines, and V8 rolls impossible
// values over (2026-02-31 is March 3, T24:00 is the next day). Strings are checked by hand for the
// same reason, so nothing here goes through the host-dependent Date parser.
const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/
const DATE_MESSAGE = 'must be a calendar date such as 2026-11-23, with no time of day'

const parseCalendarDate = (text: string): Date | undefined => {
  const match = DATE_ONLY.exec(text)
  if (!match) return undefined
  const [year, month, day] = [Number(match[1]), Number(match[2]), Number(match[3])]
  const date = new Date(0)
  date.setUTCFullYear(year, month - 1, day) // setUTCFullYear, so years below 100 stay as written
  const real =
    date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day
  return real ? date : undefined
}

const isUtcMidnight = (date: Date): boolean =>
  date.getUTCHours() === 0 &&
  date.getUTCMinutes() === 0 &&
  date.getUTCSeconds() === 0 &&
  date.getUTCMilliseconds() === 0

// A year outside this range is a typo (a swapped digit, a missing century), not a date in the data.
const DATE_YEARS = { min: 1900, max: 2100 } as const

export const DateLike = z
  .union([z.string(), z.date()], { error: DATE_MESSAGE })
  .transform((value, ctx): Date => {
    const fail = (message: string) => {
      ctx.addIssue({ code: 'custom', message })
      return z.NEVER
    }
    let date: Date
    if (typeof value === 'string') {
      if (!DATE_ONLY.test(value)) return fail(DATE_MESSAGE)
      const parsed = parseCalendarDate(value)
      if (!parsed) return fail('is not a real calendar date')
      date = parsed
    } else {
      if (!isUtcMidnight(value)) return fail('must be at UTC midnight, with no time of day')
      date = value
    }
    const year = date.getUTCFullYear()
    if (year < DATE_YEARS.min || year > DATE_YEARS.max) {
      return fail(`year ${year} is outside ${DATE_YEARS.min} to ${DATE_YEARS.max}`)
    }
    return date
  })

const Body = z.enum(['coupe', 'convertible', 'sedan'])
const Transmission = z.enum(['6mt', 'smg', 'dct', 'auto', '7mt'])
const TIRE_PATTERN = /^\d{3}\/\d{2}Z?R\d{2}$/
const Tire = z.string().regex(TIRE_PATTERN, 'must look like 225/45ZR18 or 225/45R18')
const BoltPattern = z.string().regex(/^\d+x\d+(\.\d+)?$/, 'must look like 5x120')
const Axle = z.enum(['front', 'rear', 'both'])

// A swappable part of the base car (see BODY_MODULES in asset-contract.ts).
const BodyModule = z.enum(BODY_MODULES, {
  error: (issue) => `"${String(issue.input)}" is not a body module; use ${BODY_MODULES.join(', ')}`,
})

// ---------------------------------------------------------------------------------------------
// Sources and prices
// ---------------------------------------------------------------------------------------------

export const Source = z.strictObject({
  title: Text,
  publisher: Text,
  url: HttpsUrl.optional(),
  tier: z.literal([1, 2, 3]),
  accessed: DateLike,
  note: Text.optional(),
})
export type Source = z.infer<typeof Source>

export const PriceObservation = z.strictObject({
  amount: z.number().positive(),
  currency: z.enum(['USD', 'EUR']),
  seller: Text,
  checked: DateLike,
  // Stored only so the price updater can check the price again. Never rendered as a link.
  url: HttpsUrl.optional(),
})
export type PriceObservation = z.infer<typeof PriceObservation>

// ---------------------------------------------------------------------------------------------
// Generation
// ---------------------------------------------------------------------------------------------

const WheelSize = z.strictObject({
  diameterIn: z.number().positive(),
  widthIn: z.number().positive(),
  offsetMm: z.number(),
  tire: Tire,
})

// Mounting-face geometry, in mm from the hub face:
//   inner = widthIn * 25.4 / 2 + offsetMm,  outer = widthIn * 25.4 / 2 - offsetMm
const AxleFitment = z.strictObject({
  boltPattern: BoltPattern,
  centerBoreMm: z.number().positive(),
  stock: WheelSize,
  // May be empty: the Phase 1 rules then report "fitment unknown".
  envelopes: z.array(
    z.strictObject({
      rideDropMm: z.number(),
      maxInnerMm: z.number(),
      maxOuterMm: z.number(),
      maxOuterWithFenderWorkMm: z.number(),
    }),
  ),
})

const Dimensions = z.strictObject({
  lengthMm: z.number().positive(),
  widthMm: z.number().positive(),
  heightMm: z.number().positive(),
  wheelbaseMm: z.number().positive(),
  trackFrontMm: z.number().positive(),
  trackRearMm: z.number().positive(),
  sources: z.array(Source).min(1),
})

export const Generation = z
  .strictObject({
    id: Id,
    name: Text,
    chassis: Text,
    years: YearRange, // production years
    engines: z
      .array(
        z.strictObject({
          code: Text,
          displacementCc: z.number().positive(),
          cylinders: z.int().positive(),
        }),
      )
      .min(1),
    bodies: z.array(Body).min(1),
    dimensions: z.partialRecord(Body, Dimensions),
    // Asset-contract frame in mm: origin on the ground under mid-wheelbase, +Y up, nose toward -Z,
    // left-hand-drive driver at -X.
    driverEyePoint: z.strictObject({
      xMm: z.number(),
      yMm: z.number(),
      zMm: z.number(),
      basis: z.enum(['measured', 'estimated']),
      note: Text,
      sources: z.array(Source),
    }),
    fitment: z.strictObject({
      front: AxleFitment,
      rear: AxleFitment,
      sources: z.array(Source).min(1),
    }),
    // Covers the identity fields: name, chassis, years, engines and bodies. Dimensions, the eye
    // point and fitment carry their own.
    sources: z.array(Source).min(1),
  })
  .superRefine((generation, ctx) => {
    const bodies: readonly string[] = generation.bodies
    const keys = Object.keys(generation.dimensions)
    if (keys.length === 0) {
      ctx.addIssue({
        code: 'custom',
        path: ['dimensions'],
        message: 'at least one body needs dimensions',
      })
    }
    for (const key of keys) {
      if (!bodies.includes(key)) {
        ctx.addIssue({
          code: 'custom',
          path: ['dimensions', key],
          message: `dimensions are keyed by "${key}", which is not in bodies (${bodies.join(', ')})`,
        })
      }
    }
    if (
      generation.driverEyePoint.basis === 'measured' &&
      generation.driverEyePoint.sources.length === 0
    ) {
      ctx.addIssue({
        code: 'custom',
        path: ['driverEyePoint', 'sources'],
        message: 'a measured eye point needs at least one source',
      })
    }
  })
export type Generation = z.infer<typeof Generation>

// ---------------------------------------------------------------------------------------------
// Variant
// ---------------------------------------------------------------------------------------------

export const Variant = z.strictObject({
  id: Id,
  generation: Id,
  name: Text,
  market: z.enum(['us', 'euro']),
  body: Body,
  transmissions: z.array(Transmission).min(1),
  years: YearRange,
  packages: z.array(z.strictObject({ id: Id, name: Text, summary: Text })),
  paints: z.array(
    z.strictObject({
      code: Text,
      name: Text,
      finish: z.enum(['solid', 'metallic', 'pearl']),
      baseColor: z.string().regex(/^#[0-9a-f]{6}$/, 'must be a lowercase hex colour like #c0c0c0'),
    }),
  ),
  factoryWheels: z.array(
    z.strictObject({
      id: Id,
      name: Text,
      front: WheelSize,
      rear: WheelSize,
      asset: Id.optional(),
    }),
  ),
  interiors: z.array(
    z.strictObject({
      id: Id,
      name: Text,
      color: Text,
      material: z.enum(['leather', 'cloth', 'alcantara', 'mixed']),
    }),
  ),
  render: z.strictObject({
    baseAsset: Id,
    interiorAsset: Id,
    // The factory module assets this variant uses in place of the base car's own, such as a CSL's
    // trunk lid and roof. A module left out keeps the base car's. Keys are body modules only.
    modules: z.partialRecord(BodyModule, Id).optional(),
    note: Text.optional(),
  }),
  sources: z.array(Source).min(1),
})
export type Variant = z.infer<typeof Variant>

// ---------------------------------------------------------------------------------------------
// Part
// ---------------------------------------------------------------------------------------------

export const PartCategory = z.enum([
  'wheels',
  'tires',
  'brakes',
  'suspension',
  'exhaust',
  'intake',
  'aero',
  'lighting',
  'interior',
  'seats',
  'steering',
  'drivetrain',
  'engine',
  'tuning',
  'cooling',
  'protection',
  'tint',
])
export type PartCategory = z.infer<typeof PartCategory>

const PartAttributes = z.discriminatedUnion('kind', [
  z.strictObject({
    kind: z.literal('wheel'),
    diameterIn: z.number().positive(),
    widthIn: z.number().positive(),
    offsetMm: z.number(),
    boltPattern: BoltPattern,
    centerBoreMm: z.number().positive(),
    axle: Axle,
  }),
  z.strictObject({
    kind: z.literal('tire'),
    size: Tire,
    approvedRimWidthIn: Range,
    axle: Axle,
  }),
  z.strictObject({
    kind: z.literal('brake-kit'),
    axle: z.enum(['front', 'rear']),
    minWheelDiameterIn: z.number().positive(),
  }),
  z.strictObject({
    kind: z.literal('hub-ring'),
    outerMm: z.number().positive(),
    innerMm: z.number().positive(),
  }),
  z.strictObject({ kind: z.literal('suspension'), rideDropMm: Range }),
])
type PartAttributes = z.infer<typeof PartAttributes>

// Each attribute kind describes one category of part.
const CATEGORY_FOR_KIND = {
  wheel: 'wheels',
  'hub-ring': 'wheels',
  tire: 'tires',
  'brake-kit': 'brakes',
  suspension: 'suspension',
} as const satisfies Record<PartAttributes['kind'], PartCategory>

const ModelParams = z.record(z.string(), z.union([z.number(), z.string(), z.boolean()]))

// The base car modules a part's model takes the place of. Naming one hides that module on the car
// and shows the part's own model there, so an aftermarket bumper or trunk lid swaps in the same
// way a factory variant's does (Variant.render.modules).
const Replaces = z
  .array(BodyModule)
  .min(1, 'must name at least one body module, or be left out')
  .refine(
    (modules) => new Set(modules).size === modules.length,
    'names a body module more than once',
  )

export const Part = z
  .strictObject({
    id: Id,
    name: Text,
    brand: Text.optional(),
    category: PartCategory,
    visible: z.boolean(),
    fits: z.strictObject({
      generation: Id,
      years: YearRange.optional(),
      bodies: z.array(Body).optional(),
      transmissions: z.array(Transmission).optional(),
    }),
    attributes: PartAttributes.optional(),
    options: z
      .array(
        z.strictObject({
          id: Id,
          label: Text,
          attributes: PartAttributes.optional(),
          prices: z.array(PriceObservation).optional(),
        }),
      )
      .min(1)
      .optional(),
    requires: z.array(Id).optional(),
    conflicts: z.array(Id).optional(),
    labor: z.strictObject({ hours: Range, diy: z.enum(['easy', 'intermediate', 'pro']) }),
    prices: z.array(PriceObservation).optional(),
    // `asset` once the product's own model exists; `standIn` (a style id) until then.
    model: z
      .union(
        [
          z.strictObject({
            asset: Id,
            params: ModelParams.optional(),
            replaces: Replaces.optional(),
          }),
          z.strictObject({
            standIn: Id,
            params: ModelParams.optional(),
            replaces: Replaces.optional(),
          }),
        ],
        {
          // Both shapes fail on a bad `replaces`, which would hide it behind the generic message,
          // so say what is wrong with it.
          error: (issue) => {
            if (issue.code !== 'invalid_union') return undefined
            const found = issue.errors.flat().find((inner) => inner.path[0] === 'replaces')
            if (found) return `${found.path.join('.')}: ${found.message}`
            return 'a model is { asset: <id> } or { standIn: <id> }, optionally with params and replaces'
          },
        },
      )
      .optional(),
    claims: z.array(Text).optional(),
    sources: z.array(Source),
    verified: z.boolean(),
  })
  .superRefine((part, ctx) => {
    const fail = (path: (string | number)[], message: string) =>
      ctx.addIssue({ code: 'custom', path, message })

    // The generic tier (no brand) is priced by computing over real products, never by hand.
    if (part.brand === undefined) {
      const why =
        'a part without a brand is the generic tier, whose price is computed, so it has no prices'
      if (part.prices?.length) fail(['prices'], why)
      part.options?.forEach((option, index) => {
        if (option.prices?.length) fail(['options', index, 'prices'], why)
      })
    }

    if (part.visible && part.model === undefined) {
      fail(['model'], 'a visible part needs a model ({ asset } or { standIn })')
    }
    if (!part.visible && part.model !== undefined) {
      fail(['model'], 'a part that is not visible must not have a model')
    }

    if (part.options !== undefined) {
      if (part.attributes !== undefined) {
        fail(['attributes'], 'a part with options keeps attributes on each option, not on the part')
      }
      if (part.prices?.length) {
        fail(['prices'], 'a part with options keeps prices on each option, not on the part')
      }
      const seen = new Set<string>()
      part.options.forEach((option, index) => {
        if (seen.has(option.id))
          fail(['options', index, 'id'], `duplicate option id "${option.id}"`)
        seen.add(option.id)
      })
    }

    const checkKind = (attributes: PartAttributes | undefined, path: (string | number)[]) => {
      if (attributes === undefined) return
      const expected = CATEGORY_FOR_KIND[attributes.kind]
      if (part.category !== expected) {
        fail(
          [...path, 'kind'],
          `"${attributes.kind}" attributes belong to the ${expected} category, not ${part.category}`,
        )
      }
    }
    checkKind(part.attributes, ['attributes'])
    part.options?.forEach((option, index) => {
      checkKind(option.attributes, ['options', index, 'attributes'])
    })
  })
export type Part = z.infer<typeof Part>

// ---------------------------------------------------------------------------------------------
// Maintenance item and known issue
// ---------------------------------------------------------------------------------------------

const requireHowToCheck = (
  item: { inspectWhenBuying: boolean; howToCheck?: string | undefined },
  ctx: z.RefinementCtx,
) => {
  if (item.inspectWhenBuying && !item.howToCheck?.trim()) {
    ctx.addIssue({
      code: 'custom',
      path: ['howToCheck'],
      message: 'inspectWhenBuying needs a non-empty howToCheck',
    })
  }
}

export const MaintenanceItem = z
  .strictObject({
    id: Id,
    generation: Id,
    engine: Text.optional(),
    title: Text,
    interval: z
      .strictObject({
        miles: z.int().positive().optional(),
        months: z.int().positive().optional(),
      })
      .refine(
        (interval) => interval.miles !== undefined || interval.months !== undefined,
        'an interval needs miles, months or both',
      ),
    parts: z.array(Text),
    fluids: z.array(Text),
    cost: z.strictObject({ currency: z.literal('USD'), diy: Range, shop: Range }),
    inspectWhenBuying: z.boolean(),
    howToCheck: Text.optional(),
    sources: z.array(Source).min(1),
    verified: z.boolean(),
    notes: Text.optional(),
  })
  .superRefine(requireHowToCheck)
export type MaintenanceItem = z.infer<typeof MaintenanceItem>

export const KnownIssue = z
  .strictObject({
    id: Id,
    generation: Id,
    engine: Text.optional(),
    title: Text,
    symptoms: z.array(Text).min(1),
    cause: Text,
    // Optional (spec 7.6, amended 2026-11-23): an issue known only from forum reports publishes its
    // symptoms, cause and frequency, and no fix. A fix needs a Tier 1 or Tier 2 source, which
    // quality.ts checks, and a cost, which the refinement below checks.
    fix: Text.optional(),
    prevention: Text.optional(),
    cost: z
      .strictObject({ currency: z.literal('USD'), diy: Range.optional(), shop: Range })
      .optional(),
    // Kebab-case like ids, so the YAML value is `very-common`. The UI renders it with a space.
    frequency: z.enum(['rare', 'common', 'very-common']),
    inspectWhenBuying: z.boolean(),
    howToCheck: Text.optional(),
    sources: z.array(Source).min(1),
    verified: z.boolean(),
  })
  .superRefine((issue, ctx) => {
    requireHowToCheck(issue, ctx)
    if (issue.fix !== undefined && issue.cost === undefined) {
      ctx.addIssue({
        code: 'custom',
        path: ['cost'],
        message: 'a known issue with a fix needs a cost; leave out both, or give both',
      })
    }
  })
export type KnownIssue = z.infer<typeof KnownIssue>
