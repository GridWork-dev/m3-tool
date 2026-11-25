import type { MaintenanceItem } from '../data/schemas.ts'
import { formatYears } from './format.ts'
export type ModelYears = NonNullable<MaintenanceItem['modelYears']>
type Scoped = { modelYears?: ModelYears | undefined }
export const appliesToYear = (entry: Scoped, year: number): boolean =>
  !entry.modelYears || (year >= entry.modelYears[0] && year <= entry.modelYears[1])
export const modelYearsLabel = (entry: Scoped): string =>
  !entry.modelYears
    ? 'All model years'
    : entry.modelYears[0] === entry.modelYears[1]
      ? `${entry.modelYears[0]} only`
      : formatYears(entry.modelYears)
export const yearsAttr = (entry: Scoped, run: readonly [number, number]): string => {
  const [a, b] = entry.modelYears ?? run
  return Array.from({ length: b - a + 1 }, (_, i) => a + i).join(' ')
}
