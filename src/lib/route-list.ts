import type { DataSet } from '../data/quality.ts'

// Every route of the site for a data set, each with a trailing slash. The e2e gates loop over this
// list, so a page that registers its routes here is covered the moment it exists. It does not
// include /404/: that page answers any unknown path and has no route of its own.
//
// Each page task adds its routes here (and a case in tests/unit/route-list.test.ts).
export function routesFor(_set: DataSet): string[] {
  return ['/', '/about/']
}
