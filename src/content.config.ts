import { defineCollection } from 'astro:content'
import { glob } from 'astro/loaders'
import { Generation, KnownIssue, MaintenanceItem, Part, Variant } from './data/schemas.ts'

// One YAML file per entry, under data/<collection>. The schemas are shared with tools/check-data.ts,
// which also runs the cross-file rules in src/data/quality.ts.
const yaml = (collection: string) => glob({ pattern: '**/*.yaml', base: `./data/${collection}` })

export const collections = {
  generations: defineCollection({ loader: yaml('generations'), schema: Generation }),
  variants: defineCollection({ loader: yaml('variants'), schema: Variant }),
  parts: defineCollection({ loader: yaml('parts'), schema: Part }),
  maintenance: defineCollection({ loader: yaml('maintenance'), schema: MaintenanceItem }),
  issues: defineCollection({ loader: yaml('issues'), schema: KnownIssue }),
}
