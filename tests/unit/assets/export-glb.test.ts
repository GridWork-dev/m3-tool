import { spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { type Document, getBounds, Logger, NodeIO, type Scene } from '@gltf-transform/core'
import { ALL_EXTENSIONS } from '@gltf-transform/extensions'
import { MeshoptDecoder } from 'meshoptimizer'
import { afterAll, beforeAll, describe, expect, test } from 'vitest'
import { CONTRACTS } from '../../../src/lib/asset-contract.ts'
import { validateGlb } from '../../../src/lib/asset-validate.ts'
import { type ExportProxy, exportGlb, runExportGlb } from '../../../tools/export-glb.ts'
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
