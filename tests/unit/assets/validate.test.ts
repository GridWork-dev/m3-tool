import type { Document } from '@gltf-transform/core'
import { describe, expect, test } from 'vitest'
import { CONTRACTS } from '../../../src/lib/asset-contract.ts'
import {
  type ContractIssue,
  validateDocument,
  validateGlb,
} from '../../../src/lib/asset-validate.ts'
import { makeBaseCar, makeInterior, makePng, makeProduct, toGlb } from './fixtures.ts'

const errs = (i: ContractIssue[]) => i.filter((x) => x.severity === 'error').map((x) => x.code)
const check = (doc: Document, kind: 'base-car' | 'interior' | 'product', bytes = 1e6) =>
  validateDocument(doc, { kind, bytes })

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
    expect(errs(check(doc, 'base-car'))).toEqual(['origin'])
  })

  test('accepts the ground within 3 cm and the origin within 2% of the wheelbase', () => {
    const doc = makeBaseCar()
    const car = doc
      .getRoot()
      .listNodes()
      .find((n) => n.getName() === 'car')
    car?.setTranslation([0, -0.025, 0.05]) // 5 cm is 1.8% of a 2.731 m wheelbase
    expect(errs(check(doc, 'base-car'))).toEqual([])
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
  })
})

describe('contract values', () => {
  test('match spec section 9.6', () => {
    expect(CONTRACTS['base-car']).toEqual({
      kind: 'base-car',
      requiredNodes: ['body'],
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
  })
})

describe('validateGlb', () => {
  test('a well-formed product GLB passes the Khronos validator and the contract', async () => {
    const result = await validateGlb(await toGlb(makeProduct()), 'product')
    expect(result).toEqual({ ok: true, issues: [] })
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

// A GLB with only a JSON chunk, whose nodes point at meshes that do not exist.
function glbWithBadNodes(count: number): Uint8Array {
  const json = {
    asset: { version: '2.0' },
    scene: 0,
    scenes: [{ nodes: Array.from({ length: count }, (_, i) => i) }],
    nodes: Array.from({ length: count }, (_, i) => ({ name: `n${i}`, mesh: 99 })),
  }
  const text = JSON.stringify(json)
  const padded = text + ' '.repeat((4 - (text.length % 4)) % 4)
  const body = Buffer.from(padded, 'utf8')
  const header = Buffer.alloc(12)
  header.writeUInt32LE(0x46546c67, 0) // 'glTF'
  header.writeUInt32LE(2, 4)
  header.writeUInt32LE(12 + 8 + body.length, 8)
  const chunk = Buffer.alloc(8)
  chunk.writeUInt32LE(body.length, 0)
  chunk.writeUInt32LE(0x4e4f534a, 4) // 'JSON'
  return new Uint8Array(Buffer.concat([header, chunk, body]))
}
