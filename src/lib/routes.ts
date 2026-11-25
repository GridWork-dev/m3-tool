export const generationPath = (gen: string): string => `/${gen}/`
export const issuesPath = (gen: string): string => `/${gen}/issues/`
export const issuePath = (gen: string, id: string): string => `${issuesPath(gen)}${id}/`
export const maintenancePath = (gen: string): string => `/${gen}/maintenance/`
export const buyingPath = (gen: string): string => `/${gen}/buying/`
export type GenerationSection = {
  key: 'overview' | 'maintenance' | 'issues' | 'buying'
  label: string
  path: (gen: string) => string
}
export const GENERATION_SECTIONS: readonly GenerationSection[] = [
  { key: 'overview', label: 'Overview', path: generationPath },
]
