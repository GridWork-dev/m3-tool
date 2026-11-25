import type { Source } from '../data/schemas.ts'
import { formatDate } from './format.ts'
import { isCitationLinkable } from './link-policy.ts'
export type CitationView = {
  publisher: string
  title: string
  accessed: string
  tier: 1 | 2 | 3
  note?: string
  href?: string
}
export const TIER_LABEL: Record<1 | 2 | 3, string> = {
  1: 'Primary source',
  2: 'Specialist source',
  3: 'Community source',
}
export const citationView = (source: Source): CitationView => ({
  publisher: source.publisher,
  title: source.title,
  accessed: formatDate(source.accessed),
  tier: source.tier,
  ...(source.note ? { note: source.note } : {}),
  ...(source.url && isCitationLinkable(source.url) ? { href: source.url } : {}),
})
export const latestAccessed = (sources: readonly Source[]): string | undefined =>
  sources
    .map((s) => formatDate(s.accessed))
    .sort()
    .at(-1)
