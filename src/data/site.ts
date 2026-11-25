import { getCollection } from 'astro:content'
import type { Generation, KnownIssue, MaintenanceItem, Variant } from './schemas.ts'
export type GenerationData = {
  generation: Generation
  variants: Variant[]
  issues: KnownIssue[]
  maintenance: MaintenanceItem[]
}
export async function generationIds(): Promise<string[]> {
  return (await getCollection('generations')).map((e) => e.data.id).sort()
}
export async function loadGeneration(id: string): Promise<GenerationData> {
  const [generations, variants, issues, maintenance] = await Promise.all([
    getCollection('generations'),
    getCollection('variants'),
    getCollection('issues'),
    getCollection('maintenance'),
  ])
  const generation = generations.find((e) => e.data.id === id)?.data
  if (!generation) throw new Error(`no generation "${id}"`)
  const sort = <T extends { id: string; generation: string }>(entries: { data: T }[]): T[] =>
    entries
      .map((e) => e.data)
      .filter((e) => e.generation === id)
      .sort((a, b) => a.id.localeCompare(b.id))
  return {
    generation,
    variants: sort(variants),
    issues: sort(issues),
    maintenance: sort(maintenance),
  }
}
