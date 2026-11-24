// Builders for the asset tests. Every GLB is made in code, so no binary file is committed.
//
// The base car is a subdivided box of 4.49 x 1.37 x 1.78 m (an E46 coupe's length, height and
// width), Y up, nose toward -Z, centered on the middle of the wheelbase. It is a wheel-less body,
// as the generated ones are (spec 9.3): its lowest point is 0.12 m above the ground, and the wheel
// anchors sit 0.32 m up, where the wheel centers would be. The box is subdivided so no triangle is
// degenerate, which the Khronos validator flags. Four small boxes inside it stand in for the body
// modules (bumpers, trunk lid and roof), so the car's bounding box stays the box's.
import { crc32, deflateSync } from 'node:zlib'
import {
  Document,
  Logger,
  type Material,
  type Mesh,
  type Node,
  NodeIO,
  type Scene,
} from '@gltf-transform/core'
import {
  ALL_EXTENSIONS,
  EXTMeshGPUInstancing,
  EXTMeshoptCompression,
  KHRTextureBasisu,
} from '@gltf-transform/extensions'
import { quantize, reorder } from '@gltf-transform/functions'
import { createDefaultContainer, write as writeKtx2 } from 'ktx-parse'
import { MeshoptEncoder } from 'meshoptimizer'

type Vec3 = [number, number, number]

const SILENT = new Logger(Logger.Verbosity.SILENT)

const WHEEL_X = 0.75
const WHEEL_Y = 0.32
// How far the lowest point of a wheel-less body sits above the ground.
const BODY_BOTTOM = 0.12
const WHEEL_Z = 1.3655 // half of the 2.731 m wheelbase
const TINY_BOX_TRIANGLES = 12

// ---------------------------------------------------------------------------------------------
// Geometry
// ---------------------------------------------------------------------------------------------

interface Geometry {
  positions: Float32Array<ArrayBuffer>
  normals: Float32Array<ArrayBuffer>
  uvs: Float32Array<ArrayBuffer>
  indices: Uint32Array<ArrayBuffer>
}

const component = (values: readonly number[], index: number): number => values[index] ?? 0

// A box surface made of `triangles` triangles: each face is a grid of cells, and the last
// triangles are dropped to land on the exact count. The faces are ordered so the dropped ones
// never hold the box's only extreme vertices, so the bounding box stays the full size.
function box(size: Vec3, center: Vec3, triangles: number): Geometry {
  const n = Math.max(1, Math.ceil(Math.sqrt(triangles / 12)))
  const side = n + 1
  const positions = new Float32Array(6 * side * side * 3)
  const normals = new Float32Array(positions.length)
  const uvs = new Float32Array(6 * side * side * 2)
  const indices = new Uint32Array(6 * n * n * 6)
  let vertex = 0
  let index = 0
  for (const [w, u, v] of [
    [0, 1, 2],
    [1, 2, 0],
    [2, 0, 1],
  ] as const) {
    for (const sign of [-1, 1]) {
      const first = vertex
      for (let j = 0; j <= n; j++) {
        for (let i = 0; i <= n; i++) {
          const p: Vec3 = [0, 0, 0]
          p[w] = (sign * component(size, w)) / 2
          p[u] = (i / n - 0.5) * component(size, u)
          p[v] = (j / n - 0.5) * component(size, v)
          positions.set(
            [p[0] + component(center, 0), p[1] + component(center, 1), p[2] + component(center, 2)],
            vertex * 3,
          )
          normals[vertex * 3 + w] = sign
          uvs.set([i / n, j / n], vertex * 2)
          vertex++
        }
      }
      for (let j = 0; j < n; j++) {
        for (let i = 0; i < n; i++) {
          const a = first + j * side + i
          const b = a + 1
          const c = a + side
          const d = c + 1
          indices.set(sign > 0 ? [a, b, c, b, d, c] : [a, c, b, b, c, d], index)
          index += 6
        }
      }
    }
  }
  return { positions, normals, uvs, indices: indices.slice(0, triangles * 3) }
}

function newDocument(): Document {
  const doc = new Document()
  doc.setLogger(SILENT)
  doc.createBuffer()
  return doc
}

type AccessorArray = Float32Array<ArrayBuffer> | Uint32Array<ArrayBuffer>

function accessorOf(doc: Document, type: 'VEC2' | 'VEC3' | 'SCALAR', array: AccessorArray) {
  return doc
    .createAccessor()
    .setType(type)
    .setArray(array)
    .setBuffer(doc.getRoot().listBuffers()[0] ?? null)
}

function meshOf(doc: Document, name: string, parts: [Material, Geometry][]): Mesh {
  const mesh = doc.createMesh(name)
  for (const [material, geometry] of parts) {
    mesh.addPrimitive(
      doc
        .createPrimitive()
        .setAttribute('POSITION', accessorOf(doc, 'VEC3', geometry.positions))
        .setAttribute('NORMAL', accessorOf(doc, 'VEC3', geometry.normals))
        .setAttribute('TEXCOORD_0', accessorOf(doc, 'VEC2', geometry.uvs))
        .setIndices(accessorOf(doc, 'SCALAR', geometry.indices))
        .setMaterial(material),
    )
  }
  return mesh
}

const anchor = (doc: Document, name: string, at: Vec3): Node =>
  doc.createNode(name).setTranslation(at)

function sceneOf(doc: Document): Scene {
  return doc.createScene('scene')
}

// ---------------------------------------------------------------------------------------------
// Textures
// ---------------------------------------------------------------------------------------------

// A valid size x size PNG: 1-bit greyscale, so a 4096 x 4096 one stays about 2 MB before deflate.
export function makePng(size: number): Uint8Array {
  const chunk = (type: string, data: Buffer): Buffer => {
    const body = Buffer.concat([Buffer.from(type, 'latin1'), data])
    const out = Buffer.alloc(12 + data.length)
    out.writeUInt32BE(data.length, 0)
    body.copy(out, 4)
    out.writeUInt32BE(crc32(body), 8 + data.length)
    return out
  }
  const header = Buffer.alloc(13)
  header.writeUInt32BE(size, 0)
  header.writeUInt32BE(size, 4)
  header[8] = 1 // bit depth
  header[9] = 0 // greyscale
  const rows = Buffer.alloc(size * (Math.ceil(size / 8) + 1)) // filter byte 0, all pixels black
  const signature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])
  return new Uint8Array(
    Buffer.concat([
      signature,
      chunk('IHDR', header),
      chunk('IDAT', deflateSync(rows)),
      chunk('IEND', Buffer.alloc(0)),
    ]),
  )
}

// A KTX2 container with the given size and a few bytes of level data. It is not a real Basis
// payload, so the Khronos validator may reject it, but readers can measure it.
export function makeKtx2(size: number): Uint8Array {
  const container = createDefaultContainer()
  container.pixelWidth = size
  container.pixelHeight = size
  container.levelCount = 1
  container.levels = [{ levelData: new Uint8Array(16), uncompressedByteLength: 16 }]
  return writeKtx2(container)
}

// ---------------------------------------------------------------------------------------------
// Assets
// ---------------------------------------------------------------------------------------------

export interface BaseCarOptions {
  // Scales the whole car, so 100 is a car exported in centimeters.
  scale?: number
  // Lays the car on its back as a Z-up export would: height along Z, nose toward +Y.
  zUp?: boolean
  // Moves the origin from the middle of the wheelbase to the front axle.
  originAtFrontAxle?: boolean
  omitAnchor?: string
  // The y of the body's lowest point, in meters. Every mesh moves with it, the anchors do not.
  // Default 0.12, a wheel-less body above the ground.
  bodyBottom?: number
  // The y of all four wheel anchors. Default 0.32.
  wheelY?: number
  // The y of single wheel anchors, by name, such as { wheel_FL: 0.37 }. Beats `wheelY`.
  wheelYBy?: Record<string, number>
  // Leaves out one body module node, such as `trunk_lid`. Any other name throws.
  omitNode?: string
  omitMaterial?: string
  // Total triangles. Default 120_000.
  triangles?: number
  // Puts a PNG of size x size on the base color of `material`.
  texture?: { size: number; material: string }
}

const CAR_MATERIALS = ['paint', 'glass', 'trim', 'lights_front', 'lights_rear']
// The anchors, with the y of the wheel anchors left to the caller.
const CAR_ANCHORS: [string, Vec3][] = [
  ['wheel_FL', [-WHEEL_X, WHEEL_Y, -WHEEL_Z]],
  ['wheel_FR', [WHEEL_X, WHEEL_Y, -WHEEL_Z]],
  ['wheel_RL', [-WHEEL_X, WHEEL_Y, WHEEL_Z]],
  ['wheel_RR', [WHEEL_X, WHEEL_Y, WHEEL_Z]],
  ['mount_front_lip', [0, 0.25, -2.2]],
  ['mount_trunk', [0, 1.0, 1.9]],
  ['mount_wing', [0, 1.3, 2.1]],
  ['mount_exhaust_L', [-0.5, 0.3, 2.2]],
  ['mount_exhaust_R', [0.5, 0.3, 2.2]],
  ['mount_interior', [0, 0.8, 0]],
]

// The body modules, with the size and center of the small box that stands in for each. The y is
// measured up from the body's lowest point. The boxes sit inside the car's 4.49 x 1.37 x 1.78 m
// box, so they don't change its bounds.
const MODULE_NODES: [string, Vec3, Vec3][] = [
  ['bumper_front', [1.6, 0.4, 0.2], [0, 0.4, -2.1]],
  ['bumper_rear', [1.6, 0.4, 0.2], [0, 0.4, 2.1]],
  ['trunk_lid', [1.2, 0.05, 0.8], [0, 1.0, 1.6]],
  ['roof', [1.2, 0.05, 1.2], [0, 1.3, 0.1]],
]

export function makeBaseCar(o: BaseCarOptions = {}): Document {
  if (o.omitNode !== undefined && !MODULE_NODES.some(([name]) => name === o.omitNode)) {
    throw new Error(`omitNode takes a body module name, not ${o.omitNode}`)
  }
  const doc = newDocument()
  const total = o.triangles ?? 120_000
  const materials = new Map<string, Material>()
  for (const name of CAR_MATERIALS) {
    if (name !== o.omitMaterial) materials.set(name, doc.createMaterial(name))
  }
  // Every material but paint gets a tiny piece inside the car. Paint takes the rest of the budget.
  const small = CAR_MATERIALS.filter((name) => name !== 'paint' && materials.has(name))
  const main = materials.get('paint') ?? doc.createMaterial('other')
  const modules = MODULE_NODES.filter(([name]) => name !== o.omitNode)
  const tiny = small.length + modules.length
  const floor = o.bodyBottom ?? BODY_BOTTOM
  const parts: [Material, Geometry][] = [
    [main, box([1.78, 1.37, 4.49], [0, floor + 0.685, 0], total - tiny * TINY_BOX_TRIANGLES)],
  ]
  small.forEach((name, i) => {
    const material = materials.get(name)
    if (material) {
      parts.push([
        material,
        box([0.1, 0.1, 0.1], [0, floor + 0.6 + i * 0.1, 0], TINY_BOX_TRIANGLES),
      ])
    }
  })
  if (o.texture) {
    const material = materials.get(o.texture.material)
    if (!material) throw new Error(`no material ${o.texture.material} to put a texture on`)
    material.setBaseColorTexture(
      doc.createTexture('detail').setImage(makePng(o.texture.size)).setMimeType('image/png'),
    )
  }

  const root = doc.createNode('car')
  root.addChild(doc.createNode('body').setMesh(meshOf(doc, 'body', parts)))
  for (const [name, size, center] of modules) {
    root.addChild(
      doc
        .createNode(name)
        .setMesh(
          meshOf(doc, name, [
            [main, box(size, [center[0], floor + center[1], center[2]], TINY_BOX_TRIANGLES)],
          ]),
        ),
    )
  }
  for (const [name, at] of CAR_ANCHORS) {
    if (name === o.omitAnchor) continue
    const y = o.wheelYBy?.[name] ?? (name.startsWith('wheel_') ? o.wheelY : undefined) ?? at[1]
    root.addChild(anchor(doc, name, [at[0], y, at[2]]))
  }
  if (o.scale !== undefined) root.setScale([o.scale, o.scale, o.scale])
  if (o.originAtFrontAxle) root.setTranslation([0, 0, WHEEL_Z * (o.scale ?? 1)])
  if (o.zUp) root.setRotation([Math.SQRT1_2, 0, 0, Math.SQRT1_2]) // +90 degrees about X
  sceneOf(doc).addChild(root)
  return doc
}

export interface InteriorOptions {
  omitAnchor?: string
  omitNode?: string
}

const INTERIOR_NODES: [string, Vec3, Vec3][] = [
  ['cabin_shell', [1.6, 1.2, 2.4], [0, 0.6, 0]],
  ['dash', [1.4, 0.3, 0.4], [0, 0.8, -0.9]],
  ['console', [0.3, 0.3, 0.8], [0, 0.4, -0.2]],
  ['door_L', [0.05, 0.9, 1.0], [-0.78, 0.7, 0]],
  ['door_R', [0.05, 0.9, 1.0], [0.78, 0.7, 0]],
  ['seat_driver', [0.5, 0.9, 0.5], [-0.4, 0.45, 0.2]],
  ['seat_passenger', [0.5, 0.9, 0.5], [0.4, 0.45, 0.2]],
  ['steering_wheel', [0.36, 0.36, 0.05], [-0.4, 0.9, -0.5]],
]
const INTERIOR_ANCHORS: [string, Vec3][] = [
  ['mount_seat_L', [-0.4, 0.1, 0.2]],
  ['mount_seat_R', [0.4, 0.1, 0.2]],
  ['mount_steering', [-0.4, 0.9, -0.5]],
  ['camera_driver_eye', [-0.4, 1.1, 0.1]],
]

export function makeInterior(o: InteriorOptions = {}): Document {
  const doc = newDocument()
  const material = doc.createMaterial('fabric')
  const root = doc.createNode('interior')
  for (const [name, size, center] of INTERIOR_NODES) {
    if (name === o.omitNode) continue
    root.addChild(
      doc.createNode(name).setMesh(meshOf(doc, name, [[material, box(size, center, 48)]])),
    )
  }
  for (const [name, at] of INTERIOR_ANCHORS) {
    if (name !== o.omitAnchor) root.addChild(anchor(doc, name, at))
  }
  sceneOf(doc).addChild(root)
  return doc
}

export interface ProductOptions {
  // Number of root nodes in the scene. Default 1.
  roots?: number
  // Total triangles. Default 1_200.
  triangles?: number
  // Draws the first root this many times with EXT_mesh_gpu_instancing, so the file stores
  // `triangles` but renders `triangles * instances`.
  instances?: number
}

export function makeProduct(o: ProductOptions = {}): Document {
  const doc = newDocument()
  const material = doc.createMaterial('product')
  const roots = o.roots ?? 1
  const total = o.triangles ?? 1_200
  const scene = sceneOf(doc)
  for (let i = 0; i < roots; i++) {
    // The first root holds the budget, and any other root is a small box.
    const triangles = i === 0 ? total - (roots - 1) * TINY_BOX_TRIANGLES : TINY_BOX_TRIANGLES
    const geometry = box([0.3, 0.3, 0.3], [i * 0.4, 0.15, 0], triangles)
    const node = doc
      .createNode(`product-${i}`)
      .setMesh(meshOf(doc, `product-${i}`, [[material, geometry]]))
    if (i === 0 && o.instances !== undefined) {
      const translations = new Float32Array(o.instances * 3)
      for (let n = 0; n < o.instances; n++) translations[n * 3] = n * 0.4
      node.setExtension(
        'EXT_mesh_gpu_instancing',
        doc
          .createExtension(EXTMeshGPUInstancing)
          .createInstancedMesh()
          .setAttribute('TRANSLATION', accessorOf(doc, 'VEC3', translations)),
      )
    }
    scene.addChild(node)
  }
  return doc
}

export interface BodyModuleOptions {
  // Number of root nodes in the scene. Default 1.
  roots?: number
  // Total triangles. Default 1_200.
  triangles?: number
}

// A body module is authored in the base car's frame, so this one is a front bumper sized and
// placed where a real one sits, with the car's origin as its own.
export function makeBodyModule(o: BodyModuleOptions = {}): Document {
  const doc = newDocument()
  const material = doc.createMaterial('paint')
  const roots = o.roots ?? 1
  const total = o.triangles ?? 1_200
  const scene = sceneOf(doc)
  for (let i = 0; i < roots; i++) {
    // The first root holds the budget, and any other root is a small box.
    const triangles = i === 0 ? total - (roots - 1) * TINY_BOX_TRIANGLES : TINY_BOX_TRIANGLES
    const geometry = box([1.7, 0.4, 0.3], [i * 0.4, 0.4, -2.1], triangles)
    scene.addChild(
      doc.createNode(`module-${i}`).setMesh(meshOf(doc, `module-${i}`, [[material, geometry]])),
    )
  }
  return doc
}

// A GLB that holds only a JSON chunk, so a test can declare whatever the glTF should say.
export function jsonOnlyGlb(json: object): Uint8Array {
  const text = JSON.stringify(json)
  const body = Buffer.from(text + ' '.repeat((4 - (text.length % 4)) % 4), 'utf8')
  const header = Buffer.alloc(12)
  header.writeUInt32LE(0x46546c67, 0) // 'glTF'
  header.writeUInt32LE(2, 4)
  header.writeUInt32LE(12 + 8 + body.length, 8)
  const chunk = Buffer.alloc(8)
  chunk.writeUInt32LE(body.length, 0)
  chunk.writeUInt32LE(0x4e4f534a, 4) // 'JSON'
  return new Uint8Array(Buffer.concat([header, chunk, body]))
}

// ---------------------------------------------------------------------------------------------
// Export
// ---------------------------------------------------------------------------------------------

export interface GlbOptions {
  // Quantizes and reorders the geometry, then compresses it with EXT_meshopt_compression.
  meshopt?: boolean
  // Adds a KTX2 texture of this size on the first material that isn't paint.
  ktx2Size?: number
}

// Writes `doc` to a GLB. Mutates the document when `meshopt` is set, so build a new one per call.
export async function toGlb(doc: Document, o: GlbOptions = {}): Promise<Uint8Array> {
  const io = new NodeIO().registerExtensions(ALL_EXTENSIONS)
  io.setLogger(SILENT)
  if (o.ktx2Size !== undefined) {
    const materials = doc.getRoot().listMaterials()
    const target = materials.find((m) => m.getName() !== 'paint') ?? materials[0]
    if (!target) throw new Error('no material to put the KTX2 texture on')
    doc.createExtension(KHRTextureBasisu).setRequired(true)
    target.setBaseColorTexture(
      doc.createTexture('ktx2').setImage(makeKtx2(o.ktx2Size)).setMimeType('image/ktx2'),
    )
  }
  if (o.meshopt) {
    await MeshoptEncoder.ready
    await doc.transform(reorder({ encoder: MeshoptEncoder }), quantize())
    doc
      .createExtension(EXTMeshoptCompression)
      .setRequired(true)
      .setEncoderOptions({ method: EXTMeshoptCompression.EncoderMethod.QUANTIZE })
    io.registerDependencies({ 'meshopt.encoder': MeshoptEncoder })
  }
  return io.writeBinary(doc)
}
