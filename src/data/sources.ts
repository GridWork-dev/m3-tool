import type { Source } from './schemas.ts'

// Spec section 7.6: a claim counts as verified with one Tier 1 source, or two independent Tier 2
// sources. Independent means different publishers, compared without regard to case or spacing.
// Tier 3 sources (forums, owner reports) never verify anything.
const normalizePublisher = (publisher: string): string =>
  publisher.trim().replace(/\s+/g, ' ').toLowerCase()

export function meetsVerificationRule(sources: readonly Source[]): boolean {
  if (sources.some((source) => source.tier === 1)) return true
  const tier2Publishers = new Set(
    sources
      .filter((source) => source.tier === 2)
      .map((source) => normalizePublisher(source.publisher)),
  )
  return tier2Publishers.size >= 2
}
