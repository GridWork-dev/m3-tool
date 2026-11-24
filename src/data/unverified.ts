// The grammar for the `unverified` field on generations and variants (data.md, "Unverified
// values"). Each entry is a path of dot-separated keys from the top of the file to one value:
//
//   - an object field or a record key is named as it is written (`fitment.front.stock.offsetMm`,
//     `render.modules.trunk_lid`);
//   - an element of a list is named by its `id`, or by its `code` when it has no `id`
//     (`factoryWheels.optional-19`, `paints.A08`, `engines.S54B32`), never by its position;
//   - a fixed-length list, a tuple such as `years`, is the one exception: its values are named by
//     position, from 0 (`years.1`);
//   - a list with no key (`transmissions`, `sources`) is named whole, because nothing stable
//     tells its elements apart;
//   - a path may stop at an object, a list or a list element, and then marks everything under it.
//
// The grammar follows the schema, so this reads the schema's own description of each value (keyed
// list, tuple, record, object) next to the parsed data. It needs no list of field names of its own.
import type { z } from 'astro/zod'

type Schema = z.ZodType
interface Def {
  type: string
  [key: string]: unknown
}

const defOf = (schema: Schema): Def => schema.def as unknown as Def

// Wrappers that make a value optional or give it a default, but do not change its shape.
const WRAPPERS = new Set(['optional', 'nullable', 'default', 'prefault', 'readonly', 'nonoptional'])

const peel = (schema: Schema): Schema => {
  let current = schema
  while (WRAPPERS.has(defOf(current).type)) current = defOf(current).innerType as Schema
  return current
}

// A list's elements are named by `id`, or by `code` when there is no `id`. A list of anything else
// (text, numbers, objects with neither) has no key.
const keyFieldOf = (element: Schema): 'id' | 'code' | undefined => {
  const def = defOf(element)
  if (def.type !== 'object') return undefined
  const shape = def.shape as Record<string, Schema>
  if (Object.hasOwn(shape, 'id')) return 'id'
  if (Object.hasOwn(shape, 'code')) return 'code'
  return undefined
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

// A position as written: no sign, no leading zero.
const POSITION = /^(0|[1-9][0-9]*)$/

type Step = { schema: Schema; value: unknown } | string

// One segment further down. A string is the reason the segment leads nowhere.
function step(node: Schema, value: unknown, segment: string, here: string, at: string): Step {
  const def = defOf(node)
  switch (def.type) {
    case 'object': {
      const shape = def.shape as Record<string, Schema>
      const child = shape[segment]
      if (!Object.hasOwn(shape, segment) || child === undefined) {
        return `${here} has no field "${segment}"`
      }
      const found = isRecord(value) ? value[segment] : undefined
      if (found === undefined) return `${at} is not set`
      return { schema: peel(child), value: found }
    }
    case 'record': {
      if (!isRecord(value) || !Object.hasOwn(value, segment)) {
        return `${here} has no key "${segment}"`
      }
      return { schema: peel(def.valueType as Schema), value: value[segment] }
    }
    case 'array': {
      const element = peel(def.element as Schema)
      const keyField = keyFieldOf(element)
      if (keyField === undefined) {
        return `${here} is a list with no key: name the whole list ("${here}"), not a position or an element of it`
      }
      const matches = (Array.isArray(value) ? value : []).filter(
        (item) => isRecord(item) && item[keyField] === segment,
      )
      if (matches.length === 0) {
        const hint = POSITION.test(segment)
          ? `: address an element by its ${keyField}, not by its position`
          : ''
        return `${here} has no element with ${keyField} "${segment}"${hint}`
      }
      if (matches.length > 1) {
        return `${here} has more than one element with ${keyField} "${segment}", so the path is ambiguous`
      }
      return { schema: element, value: matches[0] }
    }
    case 'tuple': {
      const items = def.items as Schema[]
      if (!POSITION.test(segment)) {
        return `${here} is a fixed-length list: address a value by its position, 0 to ${items.length - 1}`
      }
      const item = items[Number(segment)]
      if (item === undefined) {
        return `${here} has no position ${segment} (positions are 0 to ${items.length - 1})`
      }
      return {
        schema: peel(item),
        value: Array.isArray(value) ? value[Number(segment)] : undefined,
      }
    }
    default:
      return `${here} is a value, with nothing under it`
  }
}

// Returns why `path` does not point at a value in `data`, or undefined when it does. `schema` is
// the schema `data` was parsed with.
export function unresolvedReason(schema: Schema, data: unknown, path: string): string | undefined {
  const segments = path.split('.')
  if (segments[0] === 'unverified') {
    return '`unverified` is the list itself, not a value in the file'
  }
  let node = peel(schema)
  let value: unknown = data
  const trail: string[] = []
  for (const segment of segments) {
    const here = trail.length === 0 ? 'the file' : trail.join('.')
    const at = [...trail, segment].join('.')
    const next = step(node, value, segment, here, at)
    if (typeof next === 'string') return next
    node = next.schema
    value = next.value
    trail.push(segment)
  }
  return undefined
}
