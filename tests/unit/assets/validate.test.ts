import { readFileSync } from 'node:fs'
import { type Document, getBounds, type Mesh, type Node } from '@gltf-transform/core'
import { describe, expect, test } from 'vitest'
import {
  ASSET_KINDS,
  type AssetKind,
  BODY_MODULES,
  CONTRACTS,
} from '../../../src/lib/asset-contract.ts'
import {
  type ContractIssue,
  validateDocument,
  validateGlb,
} from '../../../src/lib/asset-validate.ts'
import {
  jsonOnlyGlb,
  makeBaseCar,
  makeBodyModule,
  makeInterior,
  makePng,
  makeProduct,
  toGlb,
} from './fixtures.ts'

const errs = (i: ContractIssue[]) => i.filter((x) => x.severity === 'error').map((x) => x.code)
const check = (doc: Document, kind: AssetKind, bytes = 1e6) =>
  validateDocument(doc, { kind, bytes })

const wheelYs = (doc: Document): number[] =>
  ['wheel_FL', 'wheel_FR', 'wheel_RL', 'wheel_RR'].map(
    (name) =>
      doc
        .getRoot()
        .listNodes()
        .find((n) => n.getName() === name)
        ?.getWorldTranslation()[1] ?? Number.NaN,
  )

test('a well-formed base car passes', () =>
  expect(errs(validateDocument(makeBaseCar(), { kind: 'base-car', bytes: 1e6 }))).toEqual([]))

test('names each missing anchor', () => {
  const i = validateDocument(makeBaseCar({ omitAnchor: 'wheel_RR' }), {
    kind: 'base-car',
    bytes: 1e6,
  })
  expect(i).toContainEqual(
    expect.objectContaining({
      code: 'missing-anchor',
      message: expect.stringContaining('wheel_RR'),
    }),
  )
})

test('reports a missing paint material', () => {
  const i = check(makeBaseCar({ omitMaterial: 'paint' }), 'base-car')
  expect(i).toContainEqual(
    expect.objectContaining({
      code: 'missing-material',
      message: expect.stringContaining('paint'),
    }),
  )
})

test('a material no mesh uses does not count', () => {
  const doc = makeBaseCar()
  for (const mesh of doc.getRoot().listMeshes()) {
    for (const primitive of mesh.listPrimitives()) {
      if (primitive.getMaterial()?.getName() === 'glass') primitive.setMaterial(null)
    }
  }
  expect(check(doc, 'base-car')).toContainEqual(
    expect.objectContaining({
      code: 'missing-material',
      message: expect.stringContaining('glass'),
    }),
  )
})

test('a node that has a mesh is not an anchor', () => {
  const doc = makeBaseCar()
  const wheel = doc
    .getRoot()
    .listNodes()
    .find((n) => n.getName() === 'wheel_FL')
  const mesh = doc.getRoot().listMeshes()[0]
  wheel?.setMesh(mesh ?? null)
  expect(check(doc, 'base-car')).toContainEqual(
    expect.objectContaining({
      code: 'missing-anchor',
      message: expect.stringContaining('wheel_FL'),
    }),
  )
})

test('names are case-sensitive', () => {
  const doc = makeBaseCar()
  doc
    .getRoot()
    .listNodes()
    .find((n) => n.getName() === 'body')
    ?.setName('Body')
  expect(check(doc, 'base-car')).toContainEqual(
    expect.objectContaining({ code: 'missing-node', message: expect.stringContaining('body') }),
  )
})

describe('units and orientation', () => {
  test('flags a base car exported in centimeters', () => {
    const i = check(makeBaseCar({ scale: 100 }), 'base-car')
    expect(errs(i)).toContain('units')
    expect(i).toContainEqual(
      expect.objectContaining({ code: 'units', message: expect.stringContaining('449') }),
    )
  })

  test('flags a base car exported in millimeters', () => {
    expect(errs(check(makeBaseCar({ scale: 1000 }), 'base-car'))).toContain('units')
  })

  test('flags a Z-up base car', () => {
    expect(errs(check(makeBaseCar({ zUp: true }), 'base-car'))).toContain('orientation')
  })

  test('flags a base car whose nose points toward +Z', () => {
    const doc = makeBaseCar()
    const car = doc
      .getRoot()
      .listNodes()
      .find((n) => n.getName() === 'car')
    car?.setRotation([0, 1, 0, 0]) // 180 degrees about Y
    expect(errs(check(doc, 'base-car'))).toContain('orientation')
  })

  test('flags a base car whose left and right are swapped', () => {
    const doc = makeBaseCar()
    const car = doc
      .getRoot()
      .listNodes()
      .find((n) => n.getName() === 'car')
    car?.setScale([-1, 1, 1])
    expect(errs(check(doc, 'base-car'))).toContain('orientation')
  })

  test('flags a car whose origin is at the front axle', () => {
    const i = check(makeBaseCar({ originAtFrontAxle: true }), 'base-car')
    expect(errs(i)).toContain('origin') // the front wheels also sit at z = 0, not z < 0
  })

  test('flags a car that floats above the ground', () => {
    const doc = makeBaseCar()
    const car = doc
      .getRoot()
      .listNodes()
      .find((n) => n.getName() === 'car')
    car?.setTranslation([0, 0.2, 0])
    // The wheel anchors move up with it, to 0.52 m. The body's lowest point, 0.32 m, still passes.
    expect(errs(check(doc, 'base-car'))).toEqual(['origin'])
  })

  test('accepts the origin within 2% of the wheelbase', () => {
    const doc = makeBaseCar()
    const car = doc
      .getRoot()
      .listNodes()
      .find((n) => n.getName() === 'car')
    car?.setTranslation([0, 0, 0.05]) // 5 cm is 1.8% of a 2.731 m wheelbase
    expect(errs(check(doc, 'base-car'))).toEqual([])
    car?.setTranslation([0, 0, 0.06]) // 2.2%
    expect(errs(check(doc, 'base-car'))).toEqual(['origin'])
  })

  test('measures in world space, through every parent', () => {
    const doc = makeBaseCar()
    const car = doc
      .getRoot()
      .listNodes()
      .find((n) => n.getName() === 'car')
    const wrapper = doc.createNode('wrapper').setScale([100, 100, 100])
    for (const scene of doc.getRoot().listScenes()) scene.removeChild(car ?? doc.createNode())
    wrapper.addChild(car ?? doc.createNode())
    doc.getRoot().listScenes()[0]?.addChild(wrapper)
    expect(errs(check(doc, 'base-car'))).toContain('units')
  })

  test('an interior and a product must be between 5 cm and 4 m', () => {
    expect(errs(check(makeInterior(), 'interior'))).toEqual([])
    expect(errs(check(makeProduct(), 'product'))).toEqual([])
    const big = makeProduct()
    big.getRoot().listNodes()[0]?.setScale([20, 20, 20]) // 6 m
    expect(errs(check(big, 'product'))).toContain('units')
    const tiny = makeProduct()
    tiny.getRoot().listNodes()[0]?.setScale([0.1, 0.1, 0.1]) // 3 cm
    expect(errs(check(tiny, 'product'))).toContain('units')
  })

  test('an asset with no geometry cannot be measured', () => {
    const empty = makeProduct()
    for (const mesh of empty.getRoot().listMeshes()) mesh.dispose()
    expect(errs(check(empty, 'product'))).toContain('units')
  })
})

describe('ground and wheel heights (R32)', () => {
  const originIssues = (doc: Document) =>
    check(doc, 'base-car').filter((issue) => issue.code === 'origin')
  const lowestPoint = (doc: Document): number => {
    const scene = doc.getRoot().listScenes()[0]
    if (!scene) throw new Error('no scene')
    return getBounds(scene).min[1]
  }

  test('the fixture is a wheel-less body 0.12 m off the ground, with its anchors at 0.32 m', () => {
    const doc = makeBaseCar()
    expect(lowestPoint(doc)).toBeCloseTo(0.12, 6)
    expect(wheelYs(doc)).toEqual([0.32, 0.32, 0.32, 0.32])
    expect(errs(check(doc, 'base-car'))).toEqual([])
  })

  test('a wheel-less body about 0.12 m off the ground, with anchors at about 0.33 m, passes', () => {
    const doc = makeBaseCar({ bodyBottom: 0.12, wheelY: 0.33 })
    expect(lowestPoint(doc)).toBeCloseTo(0.12, 6)
    expect(check(doc, 'base-car')).toEqual([])
  })

  test('a body that rests on the ground, as one with wheels would, passes too', () => {
    expect(check(makeBaseCar({ bodyBottom: 0 }), 'base-car')).toEqual([])
  })

  describe('wheel anchors sit 0.25 to 0.45 m up, where the wheel centers are', () => {
    test('anchors at 0.10 m fail, and the message names the range and the anchors', () => {
      const issues = originIssues(makeBaseCar({ wheelY: 0.1 }))
      expect(issues).toHaveLength(1)
      expect(issues[0]?.severity).toBe('error')
      expect(issues[0]?.message).toContain('0.1')
      expect(issues[0]?.message).toMatch(/0\.25 to 0\.45/)
      for (const name of ['wheel_FL', 'wheel_FR', 'wheel_RL', 'wheel_RR']) {
        expect(issues[0]?.message).toContain(name)
      }
    })

    test('anchors at 0.60 m fail', () => {
      expect(errs(check(makeBaseCar({ wheelY: 0.6 }), 'base-car'))).toEqual(['origin'])
    })

    test('one anchor out of range is the only one named', () => {
      const issues = originIssues(makeBaseCar({ wheelYBy: { wheel_RR: 0.1 } }))
      // It is out of range, and 0.22 m below the others.
      expect(issues.map((i) => i.message).join(' ')).toContain('wheel_RR')
      expect(issues[0]?.message).not.toContain('wheel_FL')
    })

    test.each([
      [0.25, true],
      [0.45, true],
      [0.2499, false],
      [0.4501, false],
    ])('all four anchors at %s m: passes is %s', (wheelY, passes) => {
      expect(errs(check(makeBaseCar({ wheelY }), 'base-car'))).toEqual(passes ? [] : ['origin'])
    })
  })

  describe('wheel anchors are within 0.02 m of each other', () => {
    test('one anchor 0.05 m off from the others fails', () => {
      const doc = makeBaseCar({ wheelYBy: { wheel_FL: 0.37 } }) // 0.37 is in range; the spread is not
      const issues = originIssues(doc)
      expect(issues).toHaveLength(1)
      expect(issues[0]?.message).toMatch(/0\.05/)
      expect(issues[0]?.message).toMatch(/0\.02/)
    })

    test.each([
      [0.02, true],
      [0.0201, false],
      [0.01, true],
    ])('a spread of %s m: passes is %s', (spread, passes) => {
      const doc = makeBaseCar({ wheelYBy: { wheel_RL: 0.32 + spread } })
      expect(errs(check(doc, 'base-car'))).toEqual(passes ? [] : ['origin'])
    })

    test('the front axle may sit lower than the rear, as long as the spread stays within 0.02 m', () => {
      const doc = makeBaseCar({
        wheelYBy: { wheel_FL: 0.31, wheel_FR: 0.31, wheel_RL: 0.33, wheel_RR: 0.33 },
      })
      expect(errs(check(doc, 'base-car'))).toEqual([])
    })

    test('a missing wheel anchor reports only the missing anchor, not a spread', () => {
      const doc = makeBaseCar({ omitAnchor: 'wheel_RR', wheelYBy: { wheel_FL: 0.4 } })
      expect(errs(check(doc, 'base-car'))).toEqual(['missing-anchor'])
    })
  })

  describe('the body sits between -0.03 m and 0.35 m', () => {
    test('a body sunk to -0.10 m fails, and the message gives the height', () => {
      const issues = originIssues(makeBaseCar({ bodyBottom: -0.1 }))
      expect(issues).toHaveLength(1)
      expect(issues[0]?.message).toContain('-0.1')
      expect(issues[0]?.message).toMatch(/-0\.03/)
    })

    test('a body floating at 0.40 m fails', () => {
      const issues = originIssues(makeBaseCar({ bodyBottom: 0.4 }))
      expect(issues).toHaveLength(1)
      expect(issues[0]?.message).toContain('0.35')
    })

    test.each([
      [-0.03, true],
      [0.35, true],
      [-0.0301, false],
      [0.3501, false],
    ])('a lowest point at %s m: passes is %s', (bodyBottom, passes) => {
      expect(errs(check(makeBaseCar({ bodyBottom }), 'base-car'))).toEqual(passes ? [] : ['origin'])
    })

    test('the lowest mesh counts, not just the node named body', () => {
      const doc = makeBaseCar()
      doc
        .getRoot()
        .listNodes()
        .find((n) => n.getName() === 'bumper_front')
        ?.setTranslation([0, -0.5, 0]) // a bumper hanging below the ground
      expect(errs(check(doc, 'base-car'))).toEqual(['origin'])
    })
  })

  test('the wheel heights are measured in world space', () => {
    const doc = makeBaseCar()
    const car = doc
      .getRoot()
      .listNodes()
      .find((n) => n.getName() === 'car')
    car?.setTranslation([0, -0.1, 0]) // anchors at 0.22 m
    expect(errs(check(doc, 'base-car'))).toEqual(['origin'])
  })

  test('the checks hold for a GLB read back from bytes', async () => {
    const good = await validateGlb(await toGlb(makeBaseCar({ wheelY: 0.33 })), 'base-car')
    expect(errs(good.issues)).toEqual([])
    const low = await validateGlb(await toGlb(makeBaseCar({ wheelY: 0.1 })), 'base-car')
    expect(errs(low.issues)).toEqual(['origin'])
    const sunk = await validateGlb(await toGlb(makeBaseCar({ bodyBottom: -0.1 })), 'base-car')
    expect(errs(sunk.issues)).toEqual(['origin'])
  }, 60_000)
})

describe('triangle budget', () => {
  test('enforces the triangle budget both ways', () => {
    const over = validateDocument(makeBaseCar({ triangles: 210_000 }), {
      kind: 'base-car',
      bytes: 1e6,
    })
    expect(errs(over)).toContain('triangles')
    const under = validateDocument(makeBaseCar({ triangles: 90_000 }), {
      kind: 'base-car',
      bytes: 1e6,
    })
    expect(errs(under)).toContain('triangles')
  })

  test('the limits themselves pass', () => {
    expect(errs(check(makeBaseCar({ triangles: 100_000 }), 'base-car'))).toEqual([])
    expect(errs(check(makeBaseCar({ triangles: 200_000 }), 'base-car'))).toEqual([])
    expect(errs(check(makeProduct({ triangles: 30_000 }), 'product'))).toEqual([])
    expect(errs(check(makeProduct({ triangles: 30_012 }), 'product'))).toContain('triangles')
  })

  test('counts a mesh once per node that uses it', () => {
    const doc = makeProduct({ triangles: 16_000 })
    const root = doc.getRoot().listNodes()[0]
    const mesh = doc.getRoot().listMeshes()[0]
    root?.addChild(doc.createNode('copy').setMesh(mesh ?? null))
    expect(errs(check(doc, 'product'))).toContain('triangles') // 32,000 > 30,000
  })

  // Primitive modes: 4 is a triangle list, 5 a strip, 6 a fan. A product may have 30,000 triangles.
  test.each<{ mode: 4 | 5 | 6; vertices: number; triangles: number; label: string }>([
    { mode: 4, vertices: 90_000, triangles: 30_000, label: 'a triangle list without indices' },
    { mode: 4, vertices: 90_003, triangles: 30_001, label: 'a triangle list without indices' },
    { mode: 5, vertices: 30_002, triangles: 30_000, label: 'a triangle strip' },
    { mode: 5, vertices: 30_003, triangles: 30_001, label: 'a triangle strip' },
    { mode: 6, vertices: 30_002, triangles: 30_000, label: 'a triangle fan' },
    { mode: 6, vertices: 30_003, triangles: 30_001, label: 'a triangle fan' },
  ])(
    'counts $label of $vertices vertices as $triangles triangles',
    ({ mode, vertices, triangles }) => {
      const doc = makeProduct({ triangles: 12 })
      const primitive = doc.getRoot().listMeshes()[0]?.listPrimitives()[0]
      primitive?.setIndices(null).setMode(mode)
      primitive?.getAttribute('POSITION')?.setArray(new Float32Array(vertices * 3))
      const found = check(doc, 'product').find((i) => i.code === 'triangles')
      if (triangles > 30_000) expect(found?.message).toContain(triangles.toLocaleString('en-US'))
      else expect(found).toBeUndefined()
    },
  )

  test('skips points and lines with a warning', () => {
    const doc = makeProduct()
    doc.getRoot().listMeshes()[0]?.listPrimitives()[0]?.setMode(0)
    const i = check(doc, 'product')
    expect(i).toContainEqual(expect.objectContaining({ code: 'triangles', severity: 'warning' }))
    expect(errs(i)).not.toContain('triangles')
  })
})

describe('textures', () => {
  test('allows 4K textures only on paint', () => {
    const onPaint = check(makeBaseCar({ texture: { size: 4096, material: 'paint' } }), 'base-car')
    expect(errs(onPaint)).toEqual([])
    const onTrim = check(makeBaseCar({ texture: { size: 4096, material: 'trim' } }), 'base-car')
    expect(errs(onTrim)).toContain('texture-size')
  })

  test('a texture shared by paint and another material is held to 2K', () => {
    const doc = makeBaseCar({ texture: { size: 4096, material: 'paint' } })
    const paint = doc
      .getRoot()
      .listMaterials()
      .find((m) => m.getName() === 'paint')
    const trim = doc
      .getRoot()
      .listMaterials()
      .find((m) => m.getName() === 'trim')
    trim?.setBaseColorTexture(paint?.getBaseColorTexture() ?? null)
    expect(errs(check(doc, 'base-car'))).toContain('texture-size')
  })

  test('paint is held to 4K', () => {
    expect(
      errs(check(makeBaseCar({ texture: { size: 8192, material: 'paint' } }), 'base-car')),
    ).toContain('texture-size')
  })

  test('2K is fine anywhere on a base car', () => {
    expect(
      errs(check(makeBaseCar({ texture: { size: 2048, material: 'trim' } }), 'base-car')),
    ).toEqual([])
  })

  test('a texture that cannot be measured is an error', () => {
    const doc = makeBaseCar()
    const trim = doc
      .getRoot()
      .listMaterials()
      .find((m) => m.getName() === 'trim')
    trim?.setBaseColorTexture(
      doc
        .createTexture('junk')
        .setImage(new Uint8Array([1, 2, 3]))
        .setMimeType('image/png'),
    )
    expect(errs(check(doc, 'base-car'))).toContain('texture-size')
  })
})

describe('interior and product', () => {
  test('a well-formed interior passes', () =>
    expect(errs(check(makeInterior(), 'interior'))).toEqual([]))

  test('interior requires camera_driver_eye', () => {
    const i = check(makeInterior({ omitAnchor: 'camera_driver_eye' }), 'interior')
    expect(i).toContainEqual(
      expect.objectContaining({
        code: 'missing-anchor',
        message: expect.stringContaining('camera_driver_eye'),
      }),
    )
  })

  test('interior requires each named node', () => {
    const i = check(makeInterior({ omitNode: 'dash' }), 'interior')
    expect(i).toContainEqual(
      expect.objectContaining({ code: 'missing-node', message: expect.stringContaining('dash') }),
    )
  })

  test('an interior needs no particular materials and may use 4K textures', () => {
    const doc = makeInterior()
    doc
      .getRoot()
      .listMaterials()[0]
      ?.setBaseColorTexture(
        doc.createTexture('dash').setImage(makePng(4096)).setMimeType('image/png'),
      )
    expect(errs(check(doc, 'interior'))).toEqual([])
    doc
      .getRoot()
      .listMaterials()[0]
      ?.setBaseColorTexture(
        doc.createTexture('huge').setImage(makePng(8192)).setMimeType('image/png'),
      )
    expect(errs(check(doc, 'interior'))).toContain('texture-size')
  })

  test('a well-formed product passes', () =>
    expect(errs(check(makeProduct(), 'product'))).toEqual([]))

  test('product must have exactly one root', () => {
    expect(errs(check(makeProduct({ roots: 2 }), 'product'))).toContain('root-count')
    const none = makeProduct()
    for (const node of none.getRoot().listNodes()) node.dispose()
    expect(errs(check(none, 'product'))).toContain('root-count')
  })

  test('a product with no scene has no root', () => {
    const doc = makeProduct()
    for (const scene of doc.getRoot().listScenes()) scene.dispose()
    expect(errs(check(doc, 'product'))).toContain('root-count')
  })
})

describe('body modules in a base car', () => {
  const MODULES = ['bumper_front', 'bumper_rear', 'trunk_lid', 'roof'] as const

  test('the module names are exactly these four', () => {
    expect(BODY_MODULES).toEqual(MODULES)
  })

  test('a base car requires the body node and one node per module', () => {
    expect(CONTRACTS['base-car'].requiredNodes).toEqual(['body', ...MODULES])
  })

  test.each(MODULES)('a base car without %s fails with missing-node, naming it', (name) => {
    const i = check(makeBaseCar({ omitNode: name }), 'base-car')
    expect(errs(i)).toEqual(['missing-node'])
    expect(i).toContainEqual(
      expect.objectContaining({ code: 'missing-node', message: expect.stringContaining(name) }),
    )
  })

  test('the fixture builder refuses a node that is not a module', () => {
    expect(() => makeBaseCar({ omitNode: 'hood' })).toThrow(/body module/)
  })

  test('a module node with no mesh fails, and the message says it must be a mesh node', () => {
    const doc = makeBaseCar()
    doc
      .getRoot()
      .listNodes()
      .find((n) => n.getName() === 'roof')
      ?.setMesh(null)
    const i = check(doc, 'base-car')
    expect(errs(i)).toEqual(['missing-node'])
    expect(i).toContainEqual(
      expect.objectContaining({
        code: 'missing-node',
        message: expect.stringMatching(/roof.*must be a mesh node|mesh node.*roof/),
      }),
    )
  })

  test('module names are case-sensitive', () => {
    const doc = makeBaseCar()
    doc
      .getRoot()
      .listNodes()
      .find((n) => n.getName() === 'roof')
      ?.setName('Roof')
    expect(check(doc, 'base-car')).toContainEqual(
      expect.objectContaining({ code: 'missing-node', message: expect.stringContaining('roof') }),
    )
  })

  test('a module node is not an anchor, so a module with a mesh raises no anchor error', () => {
    expect(errs(check(makeBaseCar(), 'base-car'))).not.toContain('missing-anchor')
    for (const name of MODULES) expect(CONTRACTS['base-car'].requiredAnchors).not.toContain(name)
  })

  test('the module meshes count toward the base car budget', () => {
    expect(errs(check(makeBaseCar({ triangles: 100_000 }), 'base-car'))).toEqual([])
    expect(errs(check(makeBaseCar({ triangles: 99_999 }), 'base-car'))).toContain('triangles')
    expect(errs(check(makeBaseCar({ triangles: 200_000 }), 'base-car'))).toEqual([])
  })
})

const nodeNamed = (doc: Document, name: string): Node => {
  const found = doc
    .getRoot()
    .listNodes()
    .find((n) => n.getName() === name)
  if (!found) throw new Error(`no node named ${name}`)
  return found
}
// The smallest mesh in the document, so a node that reuses it adds next to no triangles.
const smallestMesh = (doc: Document) => {
  const triangles = (mesh: Mesh) =>
    mesh.listPrimitives().reduce((sum, p) => sum + (p.getIndices()?.getCount() ?? 0), 0)
  const smallest = doc
    .getRoot()
    .listMeshes()
    .sort((a, b) => triangles(a) - triangles(b))[0]
  if (!smallest) throw new Error('no mesh')
  return smallest
}

describe('frames and structure (R36)', () => {
  describe('required node, anchor and module names are unique', () => {
    test('a second roof is an error, and the message names the node and the count', () => {
      const doc = makeBaseCar()
      nodeNamed(doc, 'car').addChild(doc.createNode('roof').setMesh(smallestMesh(doc)))
      const issues = check(doc, 'base-car')
      expect(errs(issues)).toEqual(['duplicate-name'])
      expect(issues[0]?.message).toContain('roof')
      expect(issues[0]?.message).toContain('2')
    })

    test.each(['body', ...BODY_MODULES])('a second %s node is an error', (name) => {
      const doc = makeBaseCar()
      nodeNamed(doc, 'car').addChild(doc.createNode(name).setMesh(smallestMesh(doc)))
      expect(errs(check(doc, 'base-car'))).toEqual(['duplicate-name'])
    })

    test.each([
      ['without a mesh', false],
      ['with a mesh', true],
    ])('a second wheel_FL anchor %s is a duplicate, and only a duplicate', (_label, withMesh) => {
      const doc = makeBaseCar()
      const copy = doc.createNode('wheel_FL').setTranslation([-0.75, 0.32, -1.3655])
      if (withMesh) copy.setMesh(smallestMesh(doc))
      nodeNamed(doc, 'car').addChild(copy)
      const issues = check(doc, 'base-car')
      expect(errs(issues)).toEqual(['duplicate-name'])
      expect(issues[0]?.message).toContain('wheel_FL')
      expect(issues[0]?.message).toContain('2')
    })

    test('a duplicate nested deep in the scene is found, and three copies are counted', () => {
      const doc = makeBaseCar()
      const wrapper = doc.createNode('wrapper')
      const inner = doc.createNode('inner')
      wrapper.addChild(inner)
      inner.addChild(doc.createNode('roof').setMesh(smallestMesh(doc)))
      inner.addChild(doc.createNode('roof').setMesh(smallestMesh(doc)))
      nodeNamed(doc, 'car').addChild(wrapper)
      const issues = check(doc, 'base-car')
      expect(errs(issues)).toEqual(['duplicate-name'])
      expect(issues[0]?.message).toContain('3')
    })

    test('an interior with two dash nodes, or two camera anchors, fails', () => {
      const doc = makeInterior()
      nodeNamed(doc, 'interior').addChild(doc.createNode('dash').setMesh(smallestMesh(doc)))
      nodeNamed(doc, 'interior').addChild(doc.createNode('camera_driver_eye'))
      const issues = check(doc, 'interior').filter((i) => i.code === 'duplicate-name')
      expect(issues).toHaveLength(2)
    })

    test('each duplicated name is one issue, not one per copy', () => {
      const doc = makeBaseCar()
      for (const name of ['roof', 'body']) {
        nodeNamed(doc, 'car').addChild(doc.createNode(name).setMesh(smallestMesh(doc)))
      }
      expect(errs(check(doc, 'base-car'))).toEqual(['duplicate-name', 'duplicate-name'])
    })

    test('names the contract does not require may repeat, and names are compared with case', () => {
      const doc = makeBaseCar()
      const car = nodeNamed(doc, 'car')
      car.addChild(doc.createNode('detail'))
      car.addChild(doc.createNode('detail'))
      car.addChild(doc.createNode('Roof').setMesh(smallestMesh(doc)))
      expect(errs(check(doc, 'base-car'))).toEqual([])
    })

    test('a product has no required names, so it has no duplicates to find', () => {
      const doc = makeProduct()
      const root = nodeNamed(doc, 'product-0')
      root.addChild(doc.createNode('part'))
      root.addChild(doc.createNode('part'))
      expect(errs(check(doc, 'product'))).toEqual([])
    })
  })

  describe('anchors are empty leaves', () => {
    test('an anchor with a mesh on a descendant fails, and the message names it', () => {
      const doc = makeBaseCar()
      nodeNamed(doc, 'wheel_FL').addChild(doc.createNode('rim').setMesh(smallestMesh(doc)))
      const issues = check(doc, 'base-car')
      expect(errs(issues)).toEqual(['missing-anchor'])
      expect(issues[0]?.message).toContain('wheel_FL')
      expect(issues[0]?.message).toContain('rim')
    })

    test('a mesh several levels below the anchor counts', () => {
      const doc = makeBaseCar()
      const inner = doc.createNode('inner')
      inner.addChild(doc.createNode('rim').setMesh(smallestMesh(doc)))
      const middle = doc.createNode('middle')
      middle.addChild(inner)
      nodeNamed(doc, 'mount_wing').addChild(middle)
      expect(errs(check(doc, 'base-car'))).toEqual(['missing-anchor'])
    })

    test('an anchor whose children carry no mesh is still an empty leaf for the contract', () => {
      const doc = makeBaseCar()
      nodeNamed(doc, 'wheel_FL').addChild(doc.createNode('marker'))
      expect(errs(check(doc, 'base-car'))).toEqual([])
    })

    test('the interior anchors follow the same rule', () => {
      const doc = makeInterior()
      nodeNamed(doc, 'camera_driver_eye').addChild(doc.createNode('rim').setMesh(smallestMesh(doc)))
      expect(errs(check(doc, 'interior'))).toEqual(['missing-anchor'])
    })
  })

  describe('an interior has exactly one root, named interior', () => {
    test('a second root fails with root-count, naming the interior kind', () => {
      const doc = makeInterior()
      doc
        .getRoot()
        .listScenes()[0]
        ?.addChild(doc.createNode('extra').setMesh(smallestMesh(doc)))
      const issues = check(doc, 'interior')
      expect(errs(issues)).toEqual(['root-count'])
      expect(issues[0]?.message).toContain('interior')
      expect(issues[0]?.message).toContain('2')
    })

    test('a single root with another name fails, and the message says what it is called', () => {
      const doc = makeInterior()
      nodeNamed(doc, 'interior').setName('cabin')
      const issues = check(doc, 'interior')
      expect(errs(issues)).toContain('root-count')
      const rootIssue = issues.find((i) => i.code === 'root-count')
      expect(rootIssue?.message).toContain('cabin')
      expect(rootIssue?.message).toContain('interior')
    })

    test('an interior nested under a wrapper root fails', () => {
      const doc = makeInterior()
      const scene = doc.getRoot().listScenes()[0]
      const wrapper = doc.createNode('wrapper')
      scene?.removeChild(nodeNamed(doc, 'interior'))
      wrapper.addChild(nodeNamed(doc, 'interior'))
      scene?.addChild(wrapper)
      const issues = check(doc, 'interior')
      expect(errs(issues)).toEqual(['root-count'])
      expect(issues[0]?.message).toContain('wrapper')
    })

    test('an interior with no root at all fails', () => {
      const doc = makeInterior()
      for (const scene of doc.getRoot().listScenes()) scene.dispose()
      expect(errs(check(doc, 'interior'))).toContain('root-count')
    })

    test('the root must be named exactly interior, with case', () => {
      const doc = makeInterior()
      nodeNamed(doc, 'interior').setName('Interior')
      expect(errs(check(doc, 'interior'))).toContain('root-count')
    })
  })

  describe('a body module sits no lower than -0.03 m', () => {
    const lowestY = (doc: Document): number => {
      const scene = doc.getRoot().listScenes()[0]
      if (!scene) throw new Error('no scene')
      return getBounds(scene).min[1]
    }
    const lowerBy = (doc: Document, y: number) => {
      nodeNamed(doc, 'module-0').setTranslation([0, y, 0])
    }

    test('a module sunk below the ground fails with origin, and the message gives the height', () => {
      const doc = makeBodyModule()
      lowerBy(doc, -0.5)
      const issues = check(doc, 'body-module')
      expect(errs(issues)).toEqual(['origin'])
      expect(issues[0]?.message).toContain(String(Number(lowestY(doc).toFixed(3))))
      expect(issues[0]?.message).toContain('-0.03')
    })

    test.each([
      [-0.03, true],
      [-0.0299, true],
      [-0.0301, false],
    ])('a module whose lowest point is at %s m: passes is %s', (target, passes) => {
      const doc = makeBodyModule()
      lowerBy(doc, target - lowestY(doc))
      expect(lowestY(doc)).toBeCloseTo(target, 6)
      expect(errs(check(doc, 'body-module'))).toEqual(passes ? [] : ['origin'])
    })

    test('a module high above the ground, like a roof, passes', () => {
      const doc = makeBodyModule()
      lowerBy(doc, 1)
      expect(errs(check(doc, 'body-module'))).toEqual([])
    })

    test('a product is not held to it: its pivot is its anchor, not the ground', () => {
      const doc = makeProduct()
      nodeNamed(doc, 'product-0').setTranslation([0, -1, 0])
      expect(errs(check(doc, 'product'))).toEqual([])
    })
  })

  describe('a module node needs a mesh with at least one primitive', () => {
    test.each(BODY_MODULES)('%s with an empty mesh fails with missing-node', (name) => {
      const doc = makeBaseCar()
      nodeNamed(doc, name).setMesh(doc.createMesh('empty'))
      const issues = check(doc, 'base-car')
      expect(errs(issues)).toEqual(['missing-node'])
      expect(issues[0]?.message).toContain(name)
      expect(issues[0]?.message).toMatch(/primitive/)
    })

    test('a module with a mesh of one primitive passes', () => {
      expect(errs(check(makeBaseCar(), 'base-car'))).toEqual([])
    })
  })
})

describe('the body-module kind', () => {
  test('a well-formed body module passes', () =>
    expect(errs(check(makeBodyModule(), 'body-module'))).toEqual([]))

  test('a module with 2 roots fails with root-count', () => {
    const i = check(makeBodyModule({ roots: 2 }), 'body-module')
    expect(errs(i)).toEqual(['root-count'])
    expect(i[0]?.message).toContain('body-module')
  })

  test('a module with no scene, or an empty one, has no root', () => {
    const empty = makeBodyModule()
    for (const node of empty.getRoot().listNodes()) node.dispose()
    expect(errs(check(empty, 'body-module'))).toContain('root-count')
    const noScene = makeBodyModule()
    for (const scene of noScene.getRoot().listScenes()) scene.dispose()
    expect(errs(check(noScene, 'body-module'))).toContain('root-count')
  })

  test('20,000 triangles pass, and 31,000 fail with the count in the message', () => {
    expect(errs(check(makeBodyModule({ triangles: 20_000 }), 'body-module'))).toEqual([])
    const over = check(makeBodyModule({ triangles: 31_000 }), 'body-module')
    expect(errs(over)).toEqual(['triangles'])
    expect(over[0]?.message).toContain('31,000')
  })

  test('the triangle limit is the product limit, 30,000', () => {
    expect(errs(check(makeBodyModule({ triangles: 30_000 }), 'body-module'))).toEqual([])
    expect(errs(check(makeBodyModule({ triangles: 30_012 }), 'body-module'))).toContain('triangles')
  })

  test('the file is held to the product size, 1,000,000 bytes', () => {
    expect(errs(check(makeBodyModule(), 'body-module', 1_000_000))).toEqual([])
    expect(errs(check(makeBodyModule(), 'body-module', 1_000_001))).toContain('bytes')
  })

  test('textures are held to 2K, with no 4K exception', () => {
    const doc = makeBodyModule()
    const paint = doc.getRoot().listMaterials()[0]
    const big = doc.createTexture('detail').setImage(makePng(4096)).setMimeType('image/png')
    paint?.setBaseColorTexture(big)
    expect(errs(check(doc, 'body-module'))).toContain('texture-size')
    big.dispose()
    paint?.setBaseColorTexture(
      doc.createTexture('ok').setImage(makePng(2048)).setMimeType('image/png'),
    )
    expect(errs(check(doc, 'body-module'))).toEqual([])
  })

  test('a module exported in centimeters fails with units', () => {
    const doc = makeBodyModule()
    doc.getRoot().listNodes()[0]?.setScale([100, 100, 100])
    expect(errs(check(doc, 'body-module'))).toContain('units')
  })

  test('a module needs no particular nodes, anchors or materials', () => {
    expect(CONTRACTS['body-module'].requiredNodes).toEqual([])
    expect(CONTRACTS['body-module'].requiredAnchors).toEqual([])
    expect(CONTRACTS['body-module'].requiredMaterials).toEqual([])
  })

  test('a base car is not held to a single root', () => {
    const doc = makeBaseCar()
    doc.getRoot().listScenes()[0]?.addChild(doc.createNode('extra'))
    expect(errs(check(doc, 'base-car'))).toEqual([])
  })
})

describe('unsupported extensions', () => {
  const instancing = expect.objectContaining({
    code: 'unsupported-extension',
    severity: 'error',
    message: expect.stringContaining('EXT_mesh_gpu_instancing'),
  })

  test('rejects a product that draws its mesh with GPU instancing', () => {
    // 26 instances of 1,200 triangles render 31,200 triangles, over the 30,000 budget, while the
    // file stores one mesh. Instancing would hide that from the triangle count.
    const i = check(makeProduct({ instances: 26 }), 'product')
    expect(i).toContainEqual(instancing)
    expect(i.find((x) => x.code === 'unsupported-extension')?.message).toContain(
      'gltf-transform optimize --instance false',
    )
  })

  test('rejects instancing however few instances there are', () => {
    expect(errs(check(makeProduct({ instances: 2 }), 'product'))).toContain('unsupported-extension')
  })

  test('a product without instancing has no such error', () => {
    expect(errs(check(makeProduct(), 'product'))).not.toContain('unsupported-extension')
  })

  test('rejects an instanced GLB read back from bytes', async () => {
    const result = await validateGlb(await toGlb(makeProduct({ instances: 26 })), 'product')
    expect(result.ok).toBe(false)
    expect(result.issues).toContainEqual(instancing)
  })

  test('a GLB that needs Draco says to re-export with meshopt, not to install a decoder', async () => {
    const glb = jsonOnlyGlb({
      asset: { version: '2.0' },
      extensionsUsed: ['KHR_draco_mesh_compression'],
      extensionsRequired: ['KHR_draco_mesh_compression'],
      scene: 0,
      scenes: [{ nodes: [0] }],
      nodes: [{ name: 'product' }],
    })
    const result = await validateGlb(glb, 'product')
    expect(result.ok).toBe(false)
    const issue = result.issues.find((i) => i.code === 'unsupported-extension')
    expect(issue?.message).toContain("Draco compression isn't supported; re-export with meshopt")
    expect(issue?.message).toContain('KHR_draco_mesh_compression')
    expect(result.issues.map((i) => i.message).join('\n')).not.toMatch(/draco3d|DT_FLOAT32/)
  })
})

describe('file size', () => {
  test('file size over budget', () => {
    const i = validateDocument(makeBaseCar(), { kind: 'base-car', bytes: 8_000_001 })
    expect(errs(i)).toContain('bytes')
  })

  test('each kind has its own limit, and the limit itself passes', () => {
    expect(errs(check(makeBaseCar(), 'base-car', 8_000_000))).toEqual([])
    expect(errs(check(makeInterior(), 'interior', 6_000_000))).toEqual([])
    expect(errs(check(makeInterior(), 'interior', 6_000_001))).toContain('bytes')
    expect(errs(check(makeProduct(), 'product', 1_000_000))).toEqual([])
    expect(errs(check(makeProduct(), 'product', 1_000_001))).toContain('bytes')
    expect(errs(check(makeBodyModule(), 'body-module', 1_000_000))).toEqual([])
    expect(errs(check(makeBodyModule(), 'body-module', 1_000_001))).toContain('bytes')
  })
})

describe('contract values', () => {
  test('match spec section 9.6', () => {
    expect(CONTRACTS['base-car']).toEqual({
      kind: 'base-car',
      requiredNodes: ['body', 'bumper_front', 'bumper_rear', 'trunk_lid', 'roof'],
      requiredAnchors: [
        'wheel_FL',
        'wheel_FR',
        'wheel_RL',
        'wheel_RR',
        'mount_front_lip',
        'mount_trunk',
        'mount_wing',
        'mount_exhaust_L',
        'mount_exhaust_R',
        'mount_interior',
      ],
      requiredMaterials: ['paint', 'glass', 'trim', 'lights_front', 'lights_rear'],
      triangles: { min: 100_000, max: 200_000 },
      maxBytes: 8_000_000,
      maxTextureSize: 2048,
      detailTexture: { materials: ['paint'], maxSize: 4096 },
    })
    expect(CONTRACTS.interior).toEqual({
      kind: 'interior',
      requiredNodes: [
        'interior',
        'cabin_shell',
        'dash',
        'console',
        'door_L',
        'door_R',
        'seat_driver',
        'seat_passenger',
        'steering_wheel',
      ],
      requiredAnchors: ['mount_seat_L', 'mount_seat_R', 'mount_steering', 'camera_driver_eye'],
      requiredMaterials: [],
      triangles: { min: 0, max: 150_000 },
      maxBytes: 6_000_000,
      maxTextureSize: 4096,
    })
    expect(CONTRACTS.product).toEqual({
      kind: 'product',
      requiredNodes: [],
      requiredAnchors: [],
      requiredMaterials: [],
      triangles: { min: 0, max: 30_000 },
      maxBytes: 1_000_000,
      maxTextureSize: 2048,
    })
    expect(CONTRACTS['body-module']).toEqual({
      kind: 'body-module',
      requiredNodes: [],
      requiredAnchors: [],
      requiredMaterials: [],
      triangles: { min: 0, max: 30_000 },
      maxBytes: 1_000_000,
      maxTextureSize: 2048,
    })
  })

  test('a body module has the budgets of a product, whatever they are', () => {
    expect({ ...CONTRACTS['body-module'], kind: 'product' }).toEqual(CONTRACTS.product)
  })

  test('the kinds are base-car, interior, product and body-module, each with a contract', () => {
    expect(ASSET_KINDS).toEqual(['base-car', 'interior', 'product', 'body-module'])
    for (const kind of ASSET_KINDS) expect(CONTRACTS[kind].kind).toBe(kind)
  })

  // schemas.ts imports this file, and tools/check-data.ts loads schemas.ts, so a heavy import
  // here would slow every data check down. It holds contract data only.
  test('the contract file imports nothing', () => {
    const source = readFileSync(
      new URL('../../../src/lib/asset-contract.ts', import.meta.url),
      'utf8',
    )
    expect(source).not.toMatch(/^\s*import\b/m)
    expect(source).not.toMatch(/\bimport\s*\(/)
    expect(source).not.toMatch(/\brequire\s*\(/)
  })
})

describe('stats (R35)', () => {
  test('a base car reports its triangle count and its size in bytes', async () => {
    const bytes = await toGlb(makeBaseCar({ triangles: 130_000 }))
    const result = await validateGlb(bytes, 'base-car')
    expect(result.stats).toEqual({ triangles: 130_000, bytes: bytes.byteLength })
  }, 30_000)

  test('the count is the one the budget check uses: a mesh counts once per node that uses it', async () => {
    const doc = makeProduct({ triangles: 1_200 })
    const mesh = smallestMesh(doc)
    doc.getRoot().listScenes()[0]?.addChild(doc.createNode('second').setMesh(mesh))
    const bytes = await toGlb(doc)
    const result = await validateGlb(bytes, 'product')
    expect(result.stats.triangles).toBe(2_400)
  })

  test('a failing asset still reports its stats', async () => {
    const bytes = await toGlb(makeProduct({ roots: 2, triangles: 1_200 }))
    const result = await validateGlb(bytes, 'product')
    expect(result.ok).toBe(false)
    expect(result.stats).toEqual({ triangles: 1_200, bytes: bytes.byteLength })
  })

  test('the stats follow the bytes that were checked, padding included', async () => {
    const padded = new Uint8Array(1_000_001)
    padded.set(await toGlb(makeProduct()))
    expect((await validateGlb(padded, 'product')).stats.bytes).toBe(1_000_001)
  })

  test('a file that cannot be read has a size and no triangle count', async () => {
    const result = await validateGlb(new Uint8Array([1, 2, 3, 4]), 'product')
    expect(result.ok).toBe(false)
    expect(result.stats).toEqual({ triangles: null, bytes: 4 })
  })

  test('a Draco file has a size and no triangle count, because it cannot be decoded here', async () => {
    const glb = jsonOnlyGlb({
      asset: { version: '2.0' },
      extensionsUsed: ['KHR_draco_mesh_compression'],
      extensionsRequired: ['KHR_draco_mesh_compression'],
      scene: 0,
      scenes: [{ nodes: [] }],
    })
    const result = await validateGlb(glb, 'product')
    expect(result.stats).toEqual({ triangles: null, bytes: glb.byteLength })
  })
})

describe('validateGlb', () => {
  test('a well-formed product GLB passes the Khronos validator and the contract', async () => {
    const bytes = await toGlb(makeProduct())
    const result = await validateGlb(bytes, 'product')
    expect(result).toEqual({
      ok: true,
      issues: [],
      stats: { triangles: 1_200, bytes: bytes.byteLength },
    })
  })

  test('a well-formed body module GLB passes the Khronos validator and the contract', async () => {
    const bytes = await toGlb(makeBodyModule())
    const result = await validateGlb(bytes, 'body-module')
    expect(result).toEqual({
      ok: true,
      issues: [],
      stats: { triangles: 1_200, bytes: bytes.byteLength },
    })
  })

  test('a body module GLB with 2 roots fails', async () => {
    const result = await validateGlb(await toGlb(makeBodyModule({ roots: 2 })), 'body-module')
    expect(result.ok).toBe(false)
    expect(errs(result.issues)).toEqual(['root-count'])
  })

  test('a well-formed base car GLB passes', async () => {
    const result = await validateGlb(await toGlb(makeBaseCar()), 'base-car')
    expect(errs(result.issues)).toEqual([])
    expect(result.ok).toBe(true)
  }, 30_000)

  test('a GLB exported in centimeters fails', async () => {
    const result = await validateGlb(await toGlb(makeBaseCar({ scale: 100 })), 'base-car')
    expect(result.ok).toBe(false)
    expect(errs(result.issues)).toContain('units')
  }, 30_000)

  test('a Z-up GLB fails', async () => {
    const result = await validateGlb(await toGlb(makeBaseCar({ zUp: true })), 'base-car')
    expect(result.ok).toBe(false)
    expect(errs(result.issues)).toContain('orientation')
  }, 30_000)

  test('decodes meshopt GLBs and measures KTX2 textures', async () => {
    const ok = await validateGlb(
      await toGlb(makeBaseCar(), { meshopt: true, ktx2Size: 2048 }),
      'base-car',
    )
    expect(errs(ok.issues).filter((c) => c !== 'khronos')).toEqual([])
    const big = await validateGlb(
      await toGlb(makeBaseCar(), { meshopt: true, ktx2Size: 8192 }),
      'base-car',
    )
    expect(errs(big.issues)).toContain('texture-size')
  }, 60_000)

  test('a meshopt GLB keeps its measurements', async () => {
    const bytes = await toGlb(makeBaseCar({ scale: 100 }), { meshopt: true })
    expect(errs((await validateGlb(bytes, 'base-car')).issues)).toContain('units')
  }, 30_000)

  test('reports the file size against the budget', async () => {
    const bytes = await toGlb(makeProduct())
    const padded = new Uint8Array(1_000_001)
    padded.set(bytes)
    // The padding sits after the last chunk, so the GLB still parses, but the file is over budget.
    const result = await validateGlb(padded, 'product')
    expect(errs(result.issues)).toContain('bytes')
  })

  test('quotes the first five Khronos errors and counts the rest', async () => {
    const result = await validateGlb(glbWithBadNodes(8), 'product')
    expect(result.ok).toBe(false)
    const khronos = result.issues.filter((i) => i.code === 'khronos' && i.severity === 'error')
    expect(khronos[0]?.message).toMatch(/8 errors/)
    expect(khronos[0]?.message).toContain('/nodes/0/mesh')
    expect(khronos[0]?.message).toContain('/nodes/4/mesh')
    expect(khronos[0]?.message).not.toContain('/nodes/5/mesh')
    expect(khronos[0]?.message).toMatch(/3 more/)
  })

  test('bytes that are not a GLB are an error, not a crash', async () => {
    const result = await validateGlb(new Uint8Array([1, 2, 3, 4]), 'product')
    expect(result.ok).toBe(false)
    expect(errs(result.issues)).toContain('khronos')
  })
})

// A GLB whose nodes point at meshes that do not exist.
function glbWithBadNodes(count: number): Uint8Array {
  return jsonOnlyGlb({
    asset: { version: '2.0' },
    scene: 0,
    scenes: [{ nodes: Array.from({ length: count }, (_, i) => i) }],
    nodes: Array.from({ length: count }, (_, i) => ({ name: `n${i}`, mesh: 99 })),
  })
}
