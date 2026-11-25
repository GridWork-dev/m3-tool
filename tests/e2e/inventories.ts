import type { Generation, Variant } from '../../src/data/schemas.ts'
export type Inventory = { path: string; times: number }[]
export function generationInventory(
  g: Generation,
  stage: { hero: boolean; drawing: boolean },
): Inventory {
  const values: Inventory = []
  const add = (path: string, times = 1) => values.push({ path, times })
  for (const path of ['name', 'chassis', 'years.0', 'years.1', 'bodies'])
    add(path, stage.hero && ['years.0', 'years.1', 'bodies'].includes(path) ? 2 : 1)
  for (const e of g.engines)
    for (const f of ['code', 'displacementCc', 'cylinders'])
      add(`engines.${e.code}.${f}`, stage.hero ? 2 : 1)
  const heroBody = g.dimensions.coupe ? 'coupe' : Object.keys(g.dimensions)[0]
  for (const body of Object.keys(g.dimensions))
    for (const f of [
      'lengthMm',
      'widthMm',
      'heightMm',
      'wheelbaseMm',
      'trackFrontMm',
      'trackRearMm',
    ])
      add(
        `dimensions.${body}.${f}`,
        1 +
          (body === heroBody && stage.hero && f === 'wheelbaseMm' ? 1 : 0) +
          (body === heroBody && stage.drawing && ['lengthMm', 'heightMm', 'wheelbaseMm'].includes(f)
            ? 1
            : 0),
      )
  for (const axle of ['front', 'rear']) {
    for (const f of ['boltPattern', 'centerBoreMm', 'envelopes']) add(`fitment.${axle}.${f}`)
    for (const f of ['diameterIn', 'widthIn', 'offsetMm', 'tire']) add(`fitment.${axle}.stock.${f}`)
  }
  for (const f of ['xMm', 'yMm', 'zMm', 'basis', 'note']) add(`driverEyePoint.${f}`)
  return values
}
export const homeCardInventory = (_g: Generation): Inventory =>
  ['name', 'chassis', 'years.0', 'years.1', 'bodies'].map((path) => ({ path, times: 1 }))
export function variantInventory(v: Variant): Inventory {
  const paths = ['name', 'market', 'body', 'years.0', 'years.1', 'transmissions']
  for (const p of v.packages)
    for (const f of ['name', 'summary']) paths.push(`packages.${p.id}.${f}`)
  for (const p of v.paints)
    for (const f of ['code', 'name', 'finish']) paths.push(`paints.${p.code}.${f}`)
  for (const p of v.factoryWheels) {
    paths.push(`factoryWheels.${p.id}.name`)
    for (const a of ['front', 'rear'])
      for (const f of ['diameterIn', 'widthIn', 'offsetMm', 'tire'])
        paths.push(`factoryWheels.${p.id}.${a}.${f}`)
  }
  for (const p of v.interiors)
    for (const f of ['name', 'color', 'material']) paths.push(`interiors.${p.id}.${f}`)
  return paths.map((path) => ({ path, times: 1 }))
}
