import type { KnownIssue, Variant } from '../data/schemas.ts'

const numbers = new Intl.NumberFormat('en-US', { maximumFractionDigits: 10 })
export const formatNumber = (value: number): string => numbers.format(value)
export const formatDate = (date: Date): string => date.toISOString().slice(0, 10)
export const formatYears = ([a, b]: readonly [number, number]): string =>
  a === b ? String(a) : `${a}–${b}`
export const frequencyLabel = (f: KnownIssue['frequency']): string =>
  ({ rare: 'Rare', common: 'Common', 'very-common': 'Very common' })[f]
export const transmissionLabel = (t: Variant['transmissions'][number]): string =>
  ({ '6mt': '6-speed manual', smg: 'SMG', dct: 'DCT', auto: 'Automatic', '7mt': '7-speed manual' })[
    t
  ]
export const bodyLabel = (b: Variant['body']): string =>
  ({ coupe: 'Coupe', convertible: 'Convertible', sedan: 'Sedan' })[b]
type Wheel = { diameterIn: number; widthIn: number; offsetMm: number; tire: string }
export const wheelParts = (w: Wheel) => ({
  diameter: formatNumber(w.diameterIn),
  width: formatNumber(w.widthIn),
  offset: formatNumber(w.offsetMm),
  tire: w.tire,
})
export const wheelLabel = (w: Wheel): string => {
  const p = wheelParts(w)
  return `${p.diameter} × ${p.width} ET${p.offset}`
}
