import { formatNumber } from './format.ts'
export const NO_SOURCED_COST = 'no sourced cost'
export const formatUsdRange = ([a, b]: readonly [number, number]): string =>
  a === b ? `$${formatNumber(a)}` : `$${formatNumber(a)}–${formatNumber(b)}`
type Cost = { diy?: readonly [number, number] | undefined; shop: readonly [number, number] }
export type CostView =
  | { kind: 'sourced'; shop: string; diy?: string }
  | { kind: 'none'; label: typeof NO_SOURCED_COST }
export const sourcedShopMax = (cost: Cost | undefined): number | undefined =>
  cost && cost.shop[1] > 0 ? cost.shop[1] : undefined
export function describeCost(cost: Cost | undefined): CostView {
  if (!cost || sourcedShopMax(cost) === undefined) return { kind: 'none', label: NO_SOURCED_COST }
  return {
    kind: 'sourced',
    shop: formatUsdRange(cost.shop),
    ...(cost.diy && cost.diy[1] > 0 ? { diy: formatUsdRange(cost.diy) } : {}),
  }
}
