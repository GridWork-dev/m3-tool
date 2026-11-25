import type { Variant } from '../data/schemas.ts'
export type Market = Variant['market']
export const MARKETS: readonly ['us', 'euro'] = ['us', 'euro']
type Scoped = { markets?: readonly Market[] | undefined }
export const marketLabel = (market: Market): 'US' | 'Euro' => (market === 'us' ? 'US' : 'Euro')
export const marketsOf = (entry: Scoped): readonly Market[] => entry.markets ?? MARKETS
export const marketsLabel = (entry: Scoped): string =>
  !entry.markets
    ? 'All markets'
    : entry.markets.length === 2
      ? 'US and Euro'
      : `${marketLabel(entry.markets[0] as Market)} only`
export const marketsAttr = (entry: Scoped): string => marketsOf(entry).join(' ')
