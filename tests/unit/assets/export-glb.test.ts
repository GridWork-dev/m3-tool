import { spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  Document,
  getBounds,
  Logger,
  NodeIO,
  type Primitive,
  type Scene,
} from '@gltf-transform/core'
import { ALL_EXTENSIONS } from '@gltf-transform/extensions'
import { MeshoptDecoder } from 'meshoptimizer'
import { afterAll, beforeAll, describe, expect, test } from 'vitest'
import { CONTRACTS } from '../../../src/lib/asset-contract.ts'
import { validateGlb } from '../../../src/lib/asset-validate.ts'
import {
  contractStructure,
  type ExportProxy,
  exportGlb,
  fitProxyBudget,
  runExportGlb,
  structureProblems,
} from '../../../tools/export-glb.ts'
import { makeBaseCar, makePng, makeProduct, toGlb } from './fixtures.ts'

const ROOT = fileURLToPath(new URL('../../..', import.meta.url))

const io = new NodeIO()
  .registerExtensions(ALL_EXTENSIONS)
  .registerDependencies({ 'meshopt.decoder': MeshoptDecoder })
io.setLogger(new Logger(Logger.Verbosity.SILENT))

async function read(glb: Uint8Array): Promise<Document> {
  await MeshoptDecoder.ready
  return io.readBinary(glb)
}

// The asset block of the GLB's own JSON chunk: what is stored in the file, before any reader
// interprets it.
async function assetOf(glb: Uint8Array): Promise<{ extras?: Record<string, unknown> }> {
  const { json } = await io.binaryToJSON(glb)
  return json.asset
}

const sceneOf = (doc: Document): Scene => {
  const scene = doc.getRoot().listScenes()[0]
  if (!scene) throw new Error('the document has no scene')
  return scene
}

const nodeNamed = (doc: Document, name: string) =>
  doc
    .getRoot()
    .listNodes()
    .find((node) => node.getName() === name)

// Positions as whole tenths of a millimeter, so two spellings of one point compare equal.
const key = (point: ArrayLike<number>): string =>
  [0, 1, 2].map((axis) => Math.round((point[axis] ?? Number.NaN) * 1e4)).join(',')

// Every vertex of every mesh node, in world space.
function worldVertexKeys(doc: Document): Set<string> {
  const keys = new Set<string>()
  const local = [0, 0, 0]
  for (const node of doc.getRoot().listNodes()) {
    const m = node.getWorldMatrix()
    for (const primitive of node.getMesh()?.listPrimitives() ?? []) {
      const position = primitive.getAttribute('POSITION')
      for (let i = 0; i < (position?.getCount() ?? 0); i++) {
        position?.getElement(i, local)
        const [x = 0, y = 0, z = 0] = local
        keys.add(
          key([
            (m[0] ?? 0) * x + (m[4] ?? 0) * y + (m[8] ?? 0) * z + (m[12] ?? 0),
            (m[1] ?? 0) * x + (m[5] ?? 0) * y + (m[9] ?? 0) * z + (m[13] ?? 0),
            (m[2] ?? 0) * x + (m[6] ?? 0) * y + (m[10] ?? 0) * z + (m[14] ?? 0),
          ]),
        )
      }
    }
  }
  return keys
}

const sha256 = (bytes: Uint8Array): string => createHash('sha256').update(bytes).digest('hex')

// A car whose `trunk_lid` is animated. quantize() moves the mesh of an animated node onto an
// unnamed child too, and the export has no way to put it back, so this is an input that makes the
// export lose a required mesh.
function carWithAnimatedTrunkLid(): Document {
  const doc = makeBaseCar({ triangles: 2_000 })
  const lid = nodeNamed(doc, 'trunk_lid')
  const buffer = doc.getRoot().listBuffers()[0]
  if (!(lid && buffer)) throw new Error('the fixture car lost its trunk lid')
  const times = doc
    .createAccessor()
    .setType('SCALAR')
    .setArray(new Float32Array([0, 1]))
    .setBuffer(buffer)
  const values = doc
    .createAccessor()
    .setType('VEC3')
    .setArray(new Float32Array([0, 0, 0, 0, 0.1, 0]))
    .setBuffer(buffer)
  const sampler = doc.createAnimationSampler().setInput(times).setOutput(values)
  const channel = doc
    .createAnimationChannel()
    .setTargetNode(lid)
    .setTargetPath('translation')
    .setSampler(sampler)
  doc.createAnimation('open').addSampler(sampler).addChannel(channel)
  return doc
}

const ANCHORS = CONTRACTS['base-car'].requiredAnchors
const MATERIALS = CONTRACTS['base-car'].requiredMaterials
const MODULES = ['bumper_front', 'bumper_rear', 'trunk_lid', 'roof']

// A base car at its contract size, exported once and shared by the tests that only read it. The
// exporter works on the bytes it is given, so the source document is kept to compare with.
let source: Document
let car: { glb: Uint8Array; proxy: ExportProxy; doc: Document }

beforeAll(async () => {
  source = makeBaseCar()
  const { glb, proxy } = await exportGlb(await toGlb(makeBaseCar()), { kind: 'base-car' })
  car = { glb, proxy, doc: await read(glb) }
}, 120_000)

describe('exportGlb', () => {
  test('keeps every wheel and mount anchor when pruning', () => {
    expect(ANCHORS).toHaveLength(10)
    for (const name of ANCHORS) {
      const node = nodeNamed(car.doc, name)
      expect(node, name).toBeDefined()
      expect(node?.getMesh(), name).toBeNull()
    }
  })

  test('writes EXT_meshopt_compression and no draco or instancing', () => {
    const used = car.doc
      .getRoot()
      .listExtensionsUsed()
      .map((extension) => extension.extensionName)
    expect(used).toContain('EXT_meshopt_compression')
    expect(used).not.toContain('KHR_draco_mesh_compression')
    expect(used).not.toContain('EXT_mesh_gpu_instancing')
  })

  test('keeps the five required materials and the four module meshes', () => {
    const names = car.doc
      .getRoot()
      .listMaterials()
      .map((material) => material.getName())
    expect([...names].sort()).toEqual([...MATERIALS].sort())
    for (const name of MODULES) expect(nodeNamed(car.doc, name)?.getMesh(), name).not.toBeNull()
  })

  test('keeps required names unique', async () => {
    const nodeNames = car.doc
      .getRoot()
      .listNodes()
      .map((node) => node.getName())
    for (const name of [...ANCHORS, 'body', ...MODULES]) {
      expect(
        nodeNames.filter((n) => n === name),
        name,
      ).toHaveLength(1)
    }
    const { issues } = await validateGlb(car.glb, 'base-car')
    expect(issues.map((issue) => issue.code)).not.toContain('duplicate-name')
  })

  test('passes validateGlb for the base-car kind', async () => {
    const { ok, issues } = await validateGlb(car.glb, 'base-car')
    expect(issues.filter((issue) => issue.severity === 'error')).toEqual([])
    expect(ok).toBe(true)
  })

  test('carries the generator markers into asset.extras.sourceAsset', async () => {
    const markers = {
      generator: 'hunyuan-3.1',
      parts: { dash: { watermark: 'sig-1' } },
      score: 0.5,
    }
    const { glb } = await exportGlb(await toGlb(makeBaseCar({ triangles: 2_000 })), {
      kind: 'base-car',
      markers,
    })
    expect((await assetOf(glb)).extras?.sourceAsset).toEqual(markers)
  })

  test('sets asset.extras.aiGenerated to true', async () => {
    expect((await assetOf(car.glb)).extras?.aiGenerated).toBe(true)
  })

  test('leaves sourceAsset out when no markers are given', async () => {
    const extras = (await assetOf(car.glb)).extras
    expect(extras).toBeDefined()
    expect(extras).not.toHaveProperty('sourceAsset')
  })

  test('keeps the asset extras the input already had', async () => {
    const doc = makeBaseCar({ triangles: 2_000 })
    doc.getRoot().getAsset().extras = { exporter: 'blender', aiGenerated: false }
    const { glb } = await exportGlb(await toGlb(doc), { kind: 'base-car', markers: { a: 1 } })
    expect((await assetOf(glb)).extras).toEqual({
      exporter: 'blender',
      aiGenerated: true,
      sourceAsset: { a: 1 },
    })
  })

  test('leaves a 2048 PNG texture untouched and adds no KHR_texture_basisu', async () => {
    const input = await toGlb(makeBaseCar({ texture: { size: 2048, material: 'paint' } }))
    const { glb } = await exportGlb(input, { kind: 'base-car' })
    const doc = await read(glb)
    const textures = doc.getRoot().listTextures()
    expect(textures).toHaveLength(1)
    expect(textures[0]?.getMimeType()).toBe('image/png')
    expect(Buffer.from(textures[0]?.getImage() ?? new Uint8Array()).equals(makePng(2048))).toBe(
      true,
    )
    const used = doc
      .getRoot()
      .listExtensionsUsed()
      .map((extension) => extension.extensionName)
    expect(used).not.toContain('KHR_texture_basisu')
    const { ok, issues } = await validateGlb(glb, 'base-car')
    expect(issues.filter((issue) => issue.severity === 'error')).toEqual([])
    expect(ok).toBe(true)
  }, 60_000)

  test('writes a proxy of at most 31,000 triangles whose bbox, triangle count and node positions are the full mesh', () => {
    const { proxy } = car
    expect(proxy.faces.length).toBeLessThanOrEqual(31_000)
    expect(proxy.faces.length).toBeGreaterThan(10_000)
    expect(proxy.triangles).toBe(120_000)

    const bounds = getBounds(sceneOf(source))
    for (let axis = 0; axis < 3; axis++) {
      expect(proxy.bbox_min[axis]).toBeCloseTo(bounds.min[axis] ?? Number.NaN, 5)
      expect(proxy.bbox_max[axis]).toBeCloseTo(bounds.max[axis] ?? Number.NaN, 5)
    }
    for (const name of [...ANCHORS, 'body', ...MODULES]) {
      const expected = nodeNamed(source, name)?.getWorldTranslation()
      const got = proxy.node_positions[name]
      expect(got, name).toBeDefined()
      for (let axis = 0; axis < 3; axis++) {
        expect(got?.[axis], name).toBeCloseTo(expected?.[axis] ?? Number.NaN, 5)
      }
    }
    // Every face points at a vertex that exists.
    const highest = Math.max(...proxy.faces.flat())
    expect(highest).toBeLessThan(proxy.vertices.length)
  })

  test('writes a proxy whose sha256 equals the output file', async () => {
    expect(car.proxy.sha256).toBe(sha256(car.glb))
    expect(car.proxy.sha256).toMatch(/^[0-9a-f]{64}$/)
  })

  test('builds the proxy in world space, from before quantize rewrites the transforms', async () => {
    // The origin moved to the front axle puts a translation on the car's root node, and the
    // proxy must still land where the contract frame puts the car.
    const moved = makeBaseCar({ originAtFrontAxle: true, scale: 1, triangles: 40_000 })
    const bounds = getBounds(sceneOf(moved))
    const { proxy } = await exportGlb(await toGlb(moved), { kind: 'base-car' })
    for (let axis = 0; axis < 3; axis++) {
      expect(proxy.bbox_min[axis]).toBeCloseTo(bounds.min[axis] ?? Number.NaN, 5)
      expect(proxy.bbox_max[axis]).toBeCloseTo(bounds.max[axis] ?? Number.NaN, 5)
    }
    // The decimated vertices are in that same frame: inside the full bounding box, and spread
    // over most of it (a quantized or local-space copy would be nowhere near).
    for (let axis = 0; axis < 3; axis++) {
      const values = proxy.vertices.map((vertex) => vertex[axis] ?? Number.NaN)
      const low = proxy.bbox_min[axis] ?? Number.NaN
      const high = proxy.bbox_max[axis] ?? Number.NaN
      expect(Math.min(...values)).toBeGreaterThanOrEqual(low - 1e-5)
      expect(Math.max(...values)).toBeLessThanOrEqual(high + 1e-5)
      expect(Math.max(...values) - Math.min(...values)).toBeGreaterThan(0.9 * (high - low))
    }
    const wheel = proxy.node_positions.wheel_FL
    const expected = nodeNamed(moved, 'wheel_FL')?.getWorldTranslation()
    expect(wheel?.[2]).toBeCloseTo(expected?.[2] ?? Number.NaN, 5)
    // Simplifying only drops vertices, so each one is still a vertex of the source in world
    // space, to a tenth of a millimeter. A proxy cut from the quantized geometry is off by more
    // than that: 14 bits over a 4.5 m car is 0.27 mm.
    const source = worldVertexKeys(moved)
    const strays = proxy.vertices.filter((vertex) => !source.has(key(vertex)))
    expect(strays).toEqual([])
  }, 60_000)

  test('keeps a small asset whole in its proxy', async () => {
    const { glb, proxy } = await exportGlb(await toGlb(makeProduct()), { kind: 'product' })
    expect(proxy.triangles).toBe(1_200)
    expect(proxy.faces).toHaveLength(1_200)
    const { ok } = await validateGlb(glb, 'product')
    expect(ok).toBe(true)
  })

  test('fails, and writes nothing, when it would lose a required mesh', async () => {
    const input = await toGlb(carWithAnimatedTrunkLid())
    await expect(exportGlb(input, { kind: 'base-car' })).rejects.toThrow(
      "the export would break the asset's structure: trunk_lid lost its mesh",
    )
  })
})

// A flat-shaded mesh has a vertex for every corner of every triangle, and its normals and UVs
// differ at each, so only the positions can say which vertices are one.
describe('a flat-shaded mesh', () => {
  // A sphere of `latitudes` x `longitudes` quads, two triangles each with their own three
  // vertices, a face normal and UVs, on a textured material (an untextured one would lose its UVs
  // in `prune`). Triangles that collapse at a pole are left out.
  function flatShadedSphere(latitudes: number, longitudes: number): Document {
    const radius = 0.2
    const point = (i: number, j: number): number[] => {
      const theta = (Math.PI * i) / latitudes
      const phi = (2 * Math.PI * j) / longitudes
      return [
        radius * Math.sin(theta) * Math.cos(phi),
        radius + radius * Math.cos(theta),
        radius * Math.sin(theta) * Math.sin(phi),
      ]
    }
    const positions: number[] = []
    const normals: number[] = []
    const uvs: number[] = []
    for (let i = 0; i < latitudes; i++) {
      for (let j = 0; j < longitudes; j++) {
        const corners = [
          [point(i, j), j, i],
          [point(i, j + 1), j + 1, i],
          [point(i + 1, j), j, i + 1],
          [point(i + 1, j + 1), j + 1, i + 1],
        ] as const
        for (const [first, second, third] of [
          [0, 2, 1],
          [1, 2, 3],
        ] as const) {
          const [a, b, c] = [corners[first], corners[second], corners[third]]
          const u = [0, 1, 2].map((axis) => (b[0][axis] ?? 0) - (a[0][axis] ?? 0))
          const v = [0, 1, 2].map((axis) => (c[0][axis] ?? 0) - (a[0][axis] ?? 0))
          const cross = [
            (u[1] ?? 0) * (v[2] ?? 0) - (u[2] ?? 0) * (v[1] ?? 0),
            (u[2] ?? 0) * (v[0] ?? 0) - (u[0] ?? 0) * (v[2] ?? 0),
            (u[0] ?? 0) * (v[1] ?? 0) - (u[1] ?? 0) * (v[0] ?? 0),
          ]
          const length = Math.hypot(...cross)
          if (length < 1e-12) continue
          for (const corner of [a, b, c]) {
            positions.push(...corner[0])
            normals.push(...cross.map((value) => value / length))
            uvs.push(corner[1] / longitudes, corner[2] / latitudes)
          }
        }
      }
    }
    const doc = new Document()
    doc.setLogger(new Logger(Logger.Verbosity.SILENT))
    const buffer = doc.createBuffer()
    const attribute = (type: 'VEC2' | 'VEC3', values: number[]) =>
      doc.createAccessor().setType(type).setArray(new Float32Array(values)).setBuffer(buffer)
    const material = doc
      .createMaterial('surface')
      .setBaseColorTexture(doc.createTexture('t').setImage(makePng(8)).setMimeType('image/png'))
    const primitive = doc
      .createPrimitive()
      .setAttribute('POSITION', attribute('VEC3', positions))
      .setAttribute('NORMAL', attribute('VEC3', normals))
      .setAttribute('TEXCOORD_0', attribute('VEC2', uvs))
      .setMaterial(material)
    doc
      .createScene('scene')
      .addChild(doc.createNode('ball').setMesh(doc.createMesh('ball').addPrimitive(primitive)))
    return doc
  }

  test('still gets a proxy within the budget, and the GLB keeps its normals and UVs', async () => {
    // 160 x 320 quads: about 102,000 triangles, and a vertex split at nearly every corner.
    const { glb, proxy } = await exportGlb(await toGlb(flatShadedSphere(160, 320)), {
      kind: 'product',
    })
    expect(proxy.triangles).toBeGreaterThan(100_000)
    expect(proxy.faces.length).toBeLessThanOrEqual(31_000)
    expect(proxy.faces.length).toBeGreaterThan(10_000)
    // Coincident corners are one vertex in the proxy, so it stays small.
    expect(proxy.vertices.length).toBeLessThan(20_000)
    expect(JSON.stringify(proxy).length).toBeLessThan(2_000_000)

    const primitive = (await read(glb)).getRoot().listMeshes()[0]?.listPrimitives()[0]
    // The two triangles of a quad share their normal, so welding joins two of their six corners:
    // four vertices a quad stay in the GLB, and none of them lost its normal or UV to the proxy.
    const normals = primitive?.getAttribute('NORMAL')?.getCount()
    expect(normals).toBeGreaterThan(200_000)
    expect(primitive?.getAttribute('TEXCOORD_0')?.getCount()).toBe(normals)
    expect(primitive?.getAttribute('POSITION')?.getCount()).toBe(normals)
  }, 120_000)
})

// What the proxy does when decimation does not reach the budget in one pass.
describe('fitProxyBudget', () => {
  test('does not simplify a mesh that is already at the target', async () => {
    const ratios: number[] = []
    const left = await fitProxyBudget(30_000, async (ratio) => {
      ratios.push(ratio)
      return 0
    })
    expect(ratios).toEqual([])
    expect(left).toBe(30_000)
  })

  test('stops after the first pass that lands within the budget', async () => {
    const ratios: number[] = []
    const left = await fitProxyBudget(120_000, async (ratio) => {
      ratios.push(ratio)
      return 30_080
    })
    expect(ratios).toEqual([0.25])
    expect(left).toBe(30_080)
  })

  test('tightens the ratio and tries again when a pass lands over the budget', async () => {
    const ratios: number[] = []
    const counts = [60_000, 45_000, 30_900]
    const left = await fitProxyBudget(120_000, async (ratio) => {
      ratios.push(ratio)
      return counts[ratios.length - 1] ?? 0
    })
    expect(ratios).toEqual([0.25, 0.5, 30_000 / 45_000])
    expect(left).toBe(30_900)
  })

  test('fails, naming the count it is stuck at, when it never gets within the budget', async () => {
    let passes = 0
    await expect(
      fitProxyBudget(120_000, async () => {
        passes++
        return 50_000
      }),
    ).rejects.toThrow(/31,?000 triangles or fewer.*50,?000 left after 4 passes/)
    expect(passes).toBe(4)
  })
})

// quantize() scales a mesh through its node's matrix, and for a node with children it moves the
// mesh onto a new unnamed child instead, which would leave `trunk_lid` without a mesh.
describe('a mesh node that has children', () => {
  // `trunk_lid` and `roof` each carry an anchor as a child, and sit off the origin, so the
  // children's local transforms have to change for them to stay where they were.
  function carWithChildAnchors(): Document {
    const doc = makeBaseCar()
    const lid = nodeNamed(doc, 'trunk_lid')
    const roof = nodeNamed(doc, 'roof')
    const trunk = nodeNamed(doc, 'mount_trunk')
    const interior = nodeNamed(doc, 'mount_interior')
    if (!(lid && roof && trunk && interior)) throw new Error('the fixture car lost a node')
    lid.setTranslation([0, 0.1, 0]).addChild(trunk.setTranslation([0, 0.9, 1.9]))
    roof.setTranslation([0.05, 0, 0]).addChild(interior.setTranslation([-0.05, 0.8, 0]))
    return doc
  }

  test('keeps its own mesh, its children and where they are, and passes validateGlb', async () => {
    const source = carWithChildAnchors()
    const { glb } = await exportGlb(await toGlb(carWithChildAnchors()), { kind: 'base-car' })
    const out = await read(glb)

    for (const [parent, child] of [
      ['trunk_lid', 'mount_trunk'],
      ['roof', 'mount_interior'],
    ] as const) {
      const node = nodeNamed(out, parent)
      expect(node?.getMesh(), parent).not.toBeNull()
      expect(nodeNamed(out, child)?.getParentNode()?.getName(), child).toBe(parent)
    }
    for (const name of ANCHORS) {
      const expected = nodeNamed(source, name)?.getWorldTranslation() ?? []
      const got = nodeNamed(out, name)?.getWorldTranslation() ?? []
      for (let axis = 0; axis < 3; axis++) {
        expect(got[axis], name).toBeCloseTo(expected[axis] ?? Number.NaN, 4)
      }
    }
    // The mesh itself did not move: the same box, to a tenth of a millimeter.
    for (const name of ['trunk_lid', 'roof']) {
      const was = getBounds(nodeNamed(source, name) ?? sceneOf(source))
      const now = getBounds(nodeNamed(out, name) ?? sceneOf(out))
      for (let axis = 0; axis < 3; axis++) {
        expect(now.min[axis], name).toBeCloseTo(was.min[axis] ?? Number.NaN, 3)
        expect(now.max[axis], name).toBeCloseTo(was.max[axis] ?? Number.NaN, 3)
      }
    }
    const { ok, issues } = await validateGlb(glb, 'base-car')
    expect(issues.filter((issue) => issue.severity === 'error')).toEqual([])
    expect(ok).toBe(true)
  })

  test('leaves no unnamed node behind', async () => {
    const { glb } = await exportGlb(await toGlb(carWithChildAnchors()), { kind: 'base-car' })
    const nodes = (await read(glb)).getRoot().listNodes()
    expect(nodes.filter((node) => node.getName() === '')).toEqual([])
  })

  // quantize()'s correction is folded into the parent and its inverse into the children, so the
  // children's whole world matrices (rotation and scale as well as position) must come out as
  // they went in, whatever the parent's own rotation, scale and mirroring are.
  function carWithTransformedParents(): Document {
    const unit = (q: number[]): [number, number, number, number] => {
      const length = Math.hypot(...q)
      return [
        (q[0] ?? 0) / length,
        (q[1] ?? 0) / length,
        (q[2] ?? 0) / length,
        (q[3] ?? 0) / length,
      ]
    }
    const doc = makeBaseCar()
    const lid = nodeNamed(doc, 'trunk_lid')
    const roof = nodeNamed(doc, 'roof')
    const trunk = nodeNamed(doc, 'mount_trunk')
    const interior = nodeNamed(doc, 'mount_interior')
    if (!(lid && roof && trunk && interior)) throw new Error('the fixture car lost a node')
    lid
      .setTranslation([0.1, 0.05, -0.2])
      .setRotation(unit([0.1, 0.25, -0.3, 0.9]))
      .setScale([1.2, 0.8, 1.1])
      .addChild(
        trunk
          .setTranslation([0.3, -0.2, 0.5])
          .setRotation(unit([0.4, -0.1, 0.2, 0.8]))
          .setScale([0.9, 1.3, 0.7]),
      )
    roof
      .setTranslation([-0.05, 0.02, 0.1])
      .setRotation(unit([-0.2, 0.1, 0.3, 0.9]))
      .setScale([-1.1, 1, 0.9]) // mirrored along X
      .addChild(
        interior
          .setTranslation([0.2, 0.4, -0.3])
          .setRotation(unit([0.3, 0.3, -0.1, 0.7]))
          .setScale([1.4, 0.6, 1]),
      )
    return doc
  }

  test('keeps the children whole world matrices under a rotated, scaled and mirrored parent', async () => {
    const source = carWithTransformedParents()
    const { glb } = await exportGlb(await toGlb(carWithTransformedParents()), {
      kind: 'base-car',
    })
    const out = await read(glb)
    for (const name of ['mount_trunk', 'mount_interior']) {
      const was = nodeNamed(source, name)?.getWorldMatrix() ?? []
      const now = nodeNamed(out, name)?.getWorldMatrix() ?? []
      expect(now, name).toHaveLength(16)
      for (let index = 0; index < 16; index++) {
        expect(now[index], `${name}[${index}]`).toBeCloseTo(was[index] ?? Number.NaN, 5)
      }
    }
    // The parents still draw their meshes where they were drawn, mirrored one included.
    for (const name of ['trunk_lid', 'roof']) {
      expect(nodeNamed(out, name)?.getMesh(), name).not.toBeNull()
      const was = getBounds(nodeNamed(source, name) ?? sceneOf(source))
      const now = getBounds(nodeNamed(out, name) ?? sceneOf(out))
      for (let axis = 0; axis < 3; axis++) {
        expect(now.min[axis], name).toBeCloseTo(was.min[axis] ?? Number.NaN, 3)
        expect(now.max[axis], name).toBeCloseTo(was.max[axis] ?? Number.NaN, 3)
      }
    }
  })

  test('puts the children in the proxy where they are', async () => {
    const { proxy } = await exportGlb(await toGlb(carWithChildAnchors()), { kind: 'base-car' })
    expect(proxy.node_positions.mount_trunk).toEqual([0, 1, 1.9])
    expect(proxy.node_positions.mount_interior).toEqual([0, 0.8, 0])
  })
})

// The checks the export runs on its own result, so a broken structure fails the export instead of
// the stage after it.
describe('the structure check', () => {
  const intact = () => contractStructure(sceneOf(makeBaseCar()), 'base-car')

  test('finds nothing to report when the structure is as it was', () => {
    expect(structureProblems(intact(), intact())).toEqual([])
  })

  test('names a module that lost its mesh, an anchor that is gone, and an anchor that got a mesh', () => {
    const car = makeBaseCar()
    const mesh = nodeNamed(car, 'body')?.getMesh() ?? null
    nodeNamed(car, 'trunk_lid')?.setMesh(null)
    nodeNamed(car, 'wheel_FL')?.dispose()
    nodeNamed(car, 'mount_wing')?.setMesh(mesh)
    expect(structureProblems(intact(), contractStructure(sceneOf(car), 'base-car'))).toEqual([
      'trunk_lid lost its mesh',
      'wheel_FL is gone',
      'mount_wing is no longer an empty leaf',
    ])
  })

  test('counts a mesh below an anchor as a mesh on it', () => {
    const car = makeBaseCar()
    const child = car.createNode('lid_copy').setMesh(nodeNamed(car, 'roof')?.getMesh() ?? null)
    nodeNamed(car, 'mount_trunk')?.addChild(child)
    expect(structureProblems(intact(), contractStructure(sceneOf(car), 'base-car'))).toEqual([
      'mount_trunk is no longer an empty leaf',
    ])
  })

  test('does not blame the export for a defect the input already had', () => {
    const car = makeBaseCar()
    nodeNamed(car, 'mount_wing')?.setMesh(nodeNamed(car, 'body')?.getMesh() ?? null)
    nodeNamed(car, 'roof')?.setMesh(null)
    const input = contractStructure(sceneOf(car), 'base-car')
    expect(structureProblems(input, contractStructure(sceneOf(car), 'base-car'))).toEqual([])
  })

  test('has nothing to check for a product', () => {
    const product = contractStructure(sceneOf(makeProduct()), 'product')
    expect(product).toEqual({ nodes: [], meshNodes: [], anchors: [], emptyAnchors: [] })
  })
})

// Triangle strips and fans stay in the exported GLB, so they have to reach the proxy too: the
// triangle count includes them.
describe('triangle strips and fans', () => {
  type Mode = Parameters<Primitive['setMode']>[0]
  const STRIP: Mode = 5
  const FAN: Mode = 6

  function singlePrimitive(mode: Mode, corners: number[][]): Document {
    const doc = new Document()
    doc.setLogger(new Logger(Logger.Verbosity.SILENT))
    const buffer = doc.createBuffer()
    const position = doc
      .createAccessor()
      .setType('VEC3')
      .setArray(new Float32Array(corners.flat()))
      .setBuffer(buffer)
    const primitive = doc
      .createPrimitive()
      .setMode(mode)
      .setAttribute('POSITION', position)
      .setMaterial(doc.createMaterial('surface'))
    const node = doc.createNode('piece').setMesh(doc.createMesh('piece').addPrimitive(primitive))
    doc.createScene('scene').addChild(node)
    return doc
  }

  const STRIP_CORNERS = [
    [0, 0, 0],
    [0.3, 0, 0],
    [0, 0.3, 0],
    [0.3, 0.3, 0],
  ]
  const FAN_CORNERS = [
    [0, 0, 0],
    [0.3, 0, 0],
    [0.3, 0.3, 0],
    [0, 0.3, 0],
  ]

  test.each([
    ['a four-vertex strip', STRIP, STRIP_CORNERS],
    ['a four-vertex fan', FAN, FAN_CORNERS],
  ])('puts %s in the proxy as two faces', async (_label, mode, corners) => {
    const { glb, proxy } = await exportGlb(await toGlb(singlePrimitive(mode, corners)), {
      kind: 'product',
    })
    expect(proxy.triangles).toBe(2)
    expect(proxy.faces).toHaveLength(2)
    for (const face of proxy.faces) {
      expect(new Set(face).size).toBe(3)
      for (const index of face) expect(proxy.vertices[index]).toBeDefined()
    }
    // The two faces cover the whole square, in world space.
    const used = proxy.faces.flat().map((index) => proxy.vertices[index] ?? [])
    for (let axis = 0; axis < 3; axis++) {
      const values = used.map((vertex) => vertex[axis] ?? Number.NaN)
      expect(Math.min(...values)).toBeCloseTo(proxy.bbox_min[axis] ?? Number.NaN, 5)
      expect(Math.max(...values)).toBeCloseTo(proxy.bbox_max[axis] ?? Number.NaN, 5)
    }
    // The exported GLB itself keeps the strip or fan.
    const modes = (await read(glb))
      .getRoot()
      .listMeshes()
      .flatMap((mesh) => mesh.listPrimitives().map((primitive) => primitive.getMode()))
    expect(modes).toEqual([mode])
  })

  test('decimates a strip-built mesh like any other', async () => {
    // 40 strips of 1,000 vertices each: 39,920 triangles, over the proxy's 30,000.
    const doc = new Document()
    doc.setLogger(new Logger(Logger.Verbosity.SILENT))
    const buffer = doc.createBuffer()
    const material = doc.createMaterial('surface')
    const mesh = doc.createMesh('grid')
    for (let strip = 0; strip < 40; strip++) {
      const corners: number[] = []
      for (let i = 0; i < 1_000; i++) {
        corners.push((i >> 1) * 0.0005, (i % 2) * 0.0005, strip * 0.0005)
      }
      const position = doc
        .createAccessor()
        .setType('VEC3')
        .setArray(new Float32Array(corners))
        .setBuffer(buffer)
      mesh.addPrimitive(
        doc
          .createPrimitive()
          .setMode(STRIP)
          .setAttribute('POSITION', position)
          .setMaterial(material),
      )
    }
    doc.createScene('scene').addChild(doc.createNode('grid').setMesh(mesh))
    const { proxy } = await exportGlb(await toGlb(doc), { kind: 'product' })
    expect(proxy.triangles).toBe(39_920)
    expect(proxy.faces.length).toBeGreaterThan(0)
    expect(proxy.faces.length).toBeLessThanOrEqual(31_000)
  })
})

describe('runExportGlb', () => {
  let dir: string
  let input: string

  beforeAll(async () => {
    dir = await mkdtemp(join(tmpdir(), 'export-glb-'))
    input = join(dir, 'in.glb')
    await writeFile(input, await toGlb(makeProduct()))
  })
  afterAll(() => rm(dir, { recursive: true }))

  test('writes the GLB and, next to it, <name>.proxy.json for the same bytes', async () => {
    const out = join(dir, 'out', 'car.glb')
    const markersFile = join(dir, 'markers.json')
    await writeFile(markersFile, JSON.stringify({ generator: 'tripo' }))
    const result = await runExportGlb([input, out, '--kind', 'product', '--markers', markersFile])
    expect(result.stderr).toEqual([])
    expect(result.exitCode).toBe(0)
    const glb = new Uint8Array(await readFile(out))
    const proxy = JSON.parse(await readFile(join(dir, 'out', 'car.proxy.json'), 'utf8'))
    expect(proxy.sha256).toBe(sha256(glb))
    expect(proxy.triangles).toBe(1_200)
    expect(Object.keys(proxy).sort()).toEqual(
      ['bbox_max', 'bbox_min', 'faces', 'node_positions', 'sha256', 'triangles', 'vertices'].sort(),
    )
    expect((await assetOf(glb)).extras?.sourceAsset).toEqual({ generator: 'tripo' })
  })

  test.each([
    ['no arguments', []],
    ['no output', ['in.glb', '--kind', 'product']],
    ['no kind', ['in.glb', 'out.glb']],
    ['an unknown kind', ['in.glb', 'out.glb', '--kind', 'car']],
    ['an output that is not a .glb', ['in.glb', 'out.gltf', '--kind', 'product']],
    ['an unknown flag', ['in.glb', 'out.glb', '--kind', 'product', '--fast']],
  ])('exits 2 for %s', async (_label, args) => {
    const result = await runExportGlb(args)
    expect(result.exitCode).toBe(2)
    expect(result.stderr.join('\n')).toMatch(/usage|unknown|required|\.glb/i)
  })

  test('exits 2 for an input or markers file that cannot be read, and writes nothing', async () => {
    const out = join(dir, 'never.glb')
    const missing = await runExportGlb([join(dir, 'nope.glb'), out, '--kind', 'product'])
    expect(missing.exitCode).toBe(2)
    expect(missing.stderr.join('\n')).toMatch(/not found/)
    const junk = join(dir, 'junk.json')
    await writeFile(junk, 'not json')
    const bad = await runExportGlb([input, out, '--kind', 'product', '--markers', junk])
    expect(bad.exitCode).toBe(2)
    expect(bad.stderr.join('\n')).toMatch(/markers/)
    expect(spawnSync('test', ['-e', out]).status).not.toBe(0)
  })

  test('exits 1, naming the node, and writes nothing when it would lose a required mesh', async () => {
    const animated = join(dir, 'animated.glb')
    await writeFile(animated, await toGlb(carWithAnimatedTrunkLid()))
    const out = join(dir, 'animated-out.glb')
    const result = await runExportGlb([animated, out, '--kind', 'base-car'])
    expect(result.exitCode).toBe(1)
    expect(result.stdout).toEqual([])
    expect(result.stderr.join('\n')).toContain('trunk_lid lost its mesh')
    expect(spawnSync('test', ['-e', out]).status).not.toBe(0)
    expect(spawnSync('test', ['-e', join(dir, 'animated-out.proxy.json')]).status).not.toBe(0)
  })

  test('exits 1 and writes nothing for bytes that are not a GLB', async () => {
    const junk = join(dir, 'junk.glb')
    await writeFile(junk, new Uint8Array([1, 2, 3, 4]))
    const out = join(dir, 'junk-out.glb')
    const result = await runExportGlb([junk, out, '--kind', 'product'])
    expect(result.exitCode).toBe(1)
    expect(spawnSync('test', ['-e', out]).status).not.toBe(0)
  })

  test('runs directly under node and sets the exit code', () => {
    const out = join(dir, 'direct.glb')
    const run = spawnSync(
      process.execPath,
      ['tools/export-glb.ts', input, out, '--kind', 'product'],
      { cwd: ROOT, encoding: 'utf8' },
    )
    expect(run.stderr).toBe('')
    expect(run.status).toBe(0)
    expect(spawnSync(process.execPath, ['tools/export-glb.ts'], { cwd: ROOT }).status).toBe(2)
  })
})
