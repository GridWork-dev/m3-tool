// Checks a GLB against the asset contract in `asset-contract.ts`.
//
// `validateDocument` runs the checks that need only the parsed glTF. `validateGlb` also runs the
// Khronos validator on the raw bytes, and reads the file the way the export stage writes it:
// meshopt-compressed geometry and KTX2 textures.
import {
  type Document,
  getBounds,
  ImageUtils,
  Logger,
  type Material,
  type Node,
  NodeIO,
  type Property,
  PropertyType,
  type Texture,
} from '@gltf-transform/core'
import { ALL_EXTENSIONS } from '@gltf-transform/extensions'
import { validateBytes } from 'gltf-validator'
import { MeshoptDecoder } from 'meshoptimizer'
import { type AssetContract, type AssetKind, CONTRACTS, MEASUREMENTS } from './asset-contract.ts'

export type IssueCode =
  | 'khronos'
  | 'missing-node'
  | 'missing-anchor'
  | 'missing-material'
  | 'triangles'
  | 'bytes'
  | 'texture-size'
  | 'units'
  | 'orientation'
  | 'origin'
  | 'root-count'

export interface ContractIssue {
  code: IssueCode
  severity: 'error' | 'warning'
  message: string
}

type Vec3 = readonly [number, number, number]

const error = (code: IssueCode, message: string): ContractIssue => ({
  code,
  severity: 'error',
  message,
})

const warning = (code: IssueCode, message: string): ContractIssue => ({
  code,
  severity: 'warning',
  message,
})

// Whole numbers get thousands separators, and measurements lose trailing zeros (4.490 -> 4.49).
const count = (n: number): string => n.toLocaleString('en-US')
const meters = (n: number): string => String(Number(n.toFixed(3)))
const point = ([x, y, z]: Vec3): string => `(${meters(x)}, ${meters(y)}, ${meters(z)})`
const list = (names: readonly string[]): string => names.join(', ')

// Reading with every extension registered also registers the image formats the extensions add,
// so `ImageUtils.getSize` can measure KTX2, WebP and AVIF textures.
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS)
io.registerDependencies({ 'meshopt.decoder': MeshoptDecoder })
io.setLogger(new Logger(Logger.Verbosity.SILENT))

// ---------------------------------------------------------------------------------------------
// Document checks
// ---------------------------------------------------------------------------------------------

// The contract covers the default scene, which is the one a viewer loads.
export function validateDocument(
  doc: Document,
  opts: { kind: AssetKind; bytes: number },
): ContractIssue[] {
  const contract = CONTRACTS[opts.kind]
  const root = doc.getRoot()
  const scene = root.getDefaultScene() ?? root.listScenes()[0] ?? null
  const nodes: Node[] = []
  scene?.traverse((node) => {
    nodes.push(node)
  })
  const bounds = scene
    ? getBounds(scene)
    : {
        min: [Infinity, Infinity, Infinity] as Vec3,
        max: [-Infinity, -Infinity, -Infinity] as Vec3,
      }

  return [
    ...checkBytes(contract, opts.bytes),
    ...checkNames(contract, nodes),
    ...checkMaterials(contract, nodes),
    ...checkTriangles(contract, nodes),
    ...checkTextures(contract, doc),
    ...checkUnits(contract, bounds),
    ...(contract.kind === 'base-car' ? checkCarPose(nodes, bounds) : []),
    ...(contract.kind === 'product' ? checkRootCount(scene?.listChildren().length ?? 0) : []),
  ]
}

function checkBytes(contract: AssetContract, bytes: number): ContractIssue[] {
  if (bytes <= contract.maxBytes) return []
  return [
    error(
      'bytes',
      `the file is ${count(bytes)} bytes, over the ${count(contract.maxBytes)} byte budget for a ${contract.kind}`,
    ),
  ]
}

// Names match exactly, with case, anywhere in the scene graph. An anchor is a node with no mesh.
function checkNames(contract: AssetContract, nodes: Node[]): ContractIssue[] {
  const issues: ContractIssue[] = []
  const named = (name: string) => nodes.filter((node) => node.getName() === name)
  for (const name of contract.requiredNodes) {
    if (named(name).length === 0)
      issues.push(error('missing-node', `required node ${name} is missing`))
  }
  for (const name of contract.requiredAnchors) {
    const found = named(name)
    if (found.length === 0) {
      issues.push(error('missing-anchor', `required anchor ${name} is missing`))
    } else if (found.every((node) => node.getMesh())) {
      issues.push(
        error('missing-anchor', `${name} has a mesh, but an anchor is an empty node with no mesh`),
      )
    }
  }
  return issues
}

// A material counts when a mesh in the scene uses it: the viewer finds paint, glass and the
// rest by material name on the meshes it draws.
function checkMaterials(contract: AssetContract, nodes: Node[]): ContractIssue[] {
  const used = new Set<string>()
  for (const node of nodes) {
    for (const primitive of node.getMesh()?.listPrimitives() ?? []) {
      const name = primitive.getMaterial()?.getName()
      if (name !== undefined) used.add(name)
    }
  }
  return contract.requiredMaterials
    .filter((name) => !used.has(name))
    .map((name) =>
      error(
        'missing-material',
        `required material ${name} is missing, or no mesh in the scene uses it`,
      ),
    )
}

// glTF primitive modes.
const POINTS = 0
const LINE_STRIP = 3
const TRIANGLES = 4
const TRIANGLE_STRIP = 5
const TRIANGLE_FAN = 6

// A mesh counts once for every node that uses it, because each use is drawn.
function checkTriangles(contract: AssetContract, nodes: Node[]): ContractIssue[] {
  let total = 0
  let skipped = 0
  for (const node of nodes) {
    for (const primitive of node.getMesh()?.listPrimitives() ?? []) {
      const mode = primitive.getMode()
      const vertices =
        primitive.getIndices()?.getCount() ?? primitive.getAttribute('POSITION')?.getCount() ?? 0
      if (mode === TRIANGLES) total += Math.floor(vertices / 3)
      else if (mode === TRIANGLE_STRIP || mode === TRIANGLE_FAN) total += Math.max(0, vertices - 2)
      else if (mode >= POINTS && mode <= LINE_STRIP) skipped++
    }
  }
  const issues: ContractIssue[] = []
  const { min, max } = contract.triangles
  if (total < min || total > max) {
    issues.push(
      error(
        'triangles',
        `the scene has ${count(total)} triangles, outside the ${count(min)} to ${count(max)} budget for a ${contract.kind}`,
      ),
    )
  }
  if (skipped > 0) {
    issues.push(
      warning('triangles', `${skipped} point or line primitives were not counted as triangles`),
    )
  }
  return issues
}

// The materials that use a texture. A texture in a material extension (clearcoat, sheen, ...)
// hangs off the extension property, so this walks up until it reaches materials.
function owningMaterials(texture: Texture): Material[] {
  const materials = new Set<Material>()
  const seen = new Set<Property>([texture])
  const queue: Property[] = [texture]
  for (let next = queue.pop(); next; next = queue.pop()) {
    for (const parent of next.listParents()) {
      if (seen.has(parent)) continue
      seen.add(parent)
      if (parent.propertyType === PropertyType.MATERIAL) materials.add(parent as Material)
      else if (parent.propertyType !== PropertyType.ROOT) queue.push(parent)
    }
  }
  return [...materials]
}

function checkTextures(contract: AssetContract, doc: Document): ContractIssue[] {
  const issues: ContractIssue[] = []
  for (const texture of doc.getRoot().listTextures()) {
    const label = texture.getName() || texture.getURI() || 'a texture'
    const image = texture.getImage()
    let size: number[] | null = null
    try {
      size = image ? ImageUtils.getSize(image, texture.getMimeType()) : null
    } catch (cause) {
      const reason = cause instanceof Error ? cause.message : String(cause)
      issues.push(
        error('texture-size', `the size of texture ${label} could not be read: ${reason}`),
      )
      continue
    }
    if (!size) {
      issues.push(error('texture-size', `the size of texture ${label} could not be read`))
      continue
    }
    const owners = owningMaterials(texture)
    const detail = contract.detailTexture
    const detailOnly =
      detail !== undefined &&
      owners.length > 0 &&
      owners.every((material) => detail.materials.includes(material.getName()))
    const limit = detail && detailOnly ? detail.maxSize : contract.maxTextureSize
    const longest = Math.max(...size)
    if (longest > limit) {
      issues.push(
        error(
          'texture-size',
          `texture ${label} is ${size[0]} x ${size[1]}, over the ${limit} pixel limit for a ${contract.kind}${detail && !detailOnly ? ` (${list(detail.materials)} only may go to ${detail.maxSize})` : ''}`,
        ),
      )
    }
  }
  return issues
}

interface Box {
  min: Vec3
  max: Vec3
}

const isEmpty = (box: Box): boolean =>
  !(box.min.every(Number.isFinite) && box.max.every(Number.isFinite))

function checkUnits(contract: AssetContract, bounds: Box): ContractIssue[] {
  if (isEmpty(bounds)) {
    return [error('units', 'the scene has no geometry, so its size cannot be measured')]
  }
  const [dx, dy, dz] = [0, 1, 2].map((i) => (bounds.max[i] ?? 0) - (bounds.min[i] ?? 0))
  if (dx === undefined || dy === undefined || dz === undefined) return []
  if (contract.kind === 'base-car') {
    const issues: ContractIssue[] = []
    const { carLength, carHeight } = MEASUREMENTS
    if (dz < carLength.min || dz > carLength.max) {
      issues.push(
        error(
          'units',
          `Z length ${meters(dz)} m is outside ${carLength.min} to ${carLength.max} m, so the units are not meters or the car is not along Z`,
        ),
      )
    }
    if (dy < carHeight.min || dy > carHeight.max) {
      issues.push(
        error(
          'units',
          `Y height ${meters(dy)} m is outside ${carHeight.min} to ${carHeight.max} m, so the units are not meters or Y is not up`,
        ),
      )
    }
    return issues
  }
  const largest = Math.max(dx, dy, dz)
  const { min, max } = MEASUREMENTS.otherSize
  if (largest < min || largest > max) {
    return [
      error(
        'units',
        `the largest dimension is ${meters(largest)} m, outside ${min} to ${max} m, so the units are not meters`,
      ),
    ]
  }
  return []
}

// Left is -X and the nose points toward -Z, so each wheel sits in a known quadrant.
const WHEELS = [
  { name: 'wheel_FL', x: -1, z: -1 },
  { name: 'wheel_FR', x: 1, z: -1 },
  { name: 'wheel_RL', x: -1, z: 1 },
  { name: 'wheel_RR', x: 1, z: 1 },
] as const

function checkCarPose(nodes: Node[], bounds: Box): ContractIssue[] {
  const issues: ContractIssue[] = []
  const position = (name: string): Vec3 | undefined =>
    nodes.find((node) => node.getName() === name && !node.getMesh())?.getWorldTranslation()
  const found = WHEELS.flatMap((wheel) => {
    const at = position(wheel.name)
    return at ? [{ ...wheel, at }] : []
  })

  for (const { name, x, z, at } of found) {
    if (at[0] * x > 0 && at[2] * z > 0 && at[1] > 0) continue
    issues.push(
      error(
        'orientation',
        `${name} is at ${point(at)}, but a Y-up car with its nose toward -Z has it at x ${x < 0 ? '<' : '>'} 0, z ${z < 0 ? '<' : '>'} 0, y > 0`,
      ),
    )
  }

  if (found.length === WHEELS.length) {
    const mean = (pick: (w: (typeof found)[number]) => boolean) => {
      const zs = found.filter(pick).map((w) => w.at[2])
      return zs.reduce((a, b) => a + b, 0) / zs.length
    }
    const wheelbase = mean((w) => w.z > 0) - mean((w) => w.z < 0)
    if (wheelbase > 0) {
      const offset = mean(() => true)
      const limit = MEASUREMENTS.originWheelbaseFraction
      if (Math.abs(offset) > limit * wheelbase) {
        issues.push(
          error(
            'origin',
            `the wheel anchors' mean Z is ${meters(offset)} m, ${meters((Math.abs(offset) / wheelbase) * 100)}% of the ${meters(wheelbase)} m wheelbase, but the origin belongs under the middle of the wheelbase (within ${limit * 100}%)`,
          ),
        )
      }
    }
  }

  if (!isEmpty(bounds) && Math.abs(bounds.min[1]) > MEASUREMENTS.groundTolerance) {
    issues.push(
      error(
        'origin',
        `the lowest point is at y = ${meters(bounds.min[1])} m, but the car must sit on the ground (within ${MEASUREMENTS.groundTolerance} m of y = 0)`,
      ),
    )
  }
  return issues
}

function checkRootCount(roots: number): ContractIssue[] {
  if (roots === 1) return []
  return [error('root-count', `a product has exactly one root node, and this scene has ${roots}`)]
}

// ---------------------------------------------------------------------------------------------
// GLB
// ---------------------------------------------------------------------------------------------

const KHRONOS_QUOTED = 5
const KHRONOS_ERROR = 0

// One `khronos` error that quotes the first five messages, or nothing when the file is valid.
async function khronosIssues(bytes: Uint8Array): Promise<ContractIssue[]> {
  let report: Awaited<ReturnType<typeof validateBytes>>
  try {
    report = await validateBytes(bytes, { maxIssues: 0, writeTimestamp: false })
  } catch (cause) {
    // The validator rejects bytes it cannot tell apart from a glTF or GLB.
    return [error('khronos', `the Khronos validator could not read the file: ${String(cause)}`)]
  }
  const errors = report.issues.messages.filter((m) => m.severity === KHRONOS_ERROR)
  if (report.issues.numErrors === 0) return []
  const quoted = errors
    .slice(0, KHRONOS_QUOTED)
    .map((m) => `${m.pointer ? `${m.pointer}: ` : ''}${m.message} (${m.code})`)
  const rest = report.issues.numErrors - quoted.length
  const noun = report.issues.numErrors === 1 ? 'error' : 'errors'
  return [
    error(
      'khronos',
      `the Khronos validator reported ${report.issues.numErrors} ${noun}: ${quoted.join('; ')}${rest > 0 ? `; and ${rest} more` : ''}`,
    ),
  ]
}

export async function validateGlb(
  bytes: Uint8Array,
  kind: AssetKind,
): Promise<{ ok: boolean; issues: ContractIssue[] }> {
  const issues = await khronosIssues(bytes)
  try {
    await MeshoptDecoder.ready
    const doc = await io.readBinary(bytes)
    issues.push(...validateDocument(doc, { kind, bytes: bytes.byteLength }))
  } catch (cause) {
    // The Khronos validator has usually said why already, so only add this when it has not.
    if (issues.length === 0) {
      const reason = cause instanceof Error ? cause.message : String(cause)
      issues.push(error('khronos', `the file could not be read as a GLB: ${reason}`))
    }
    issues.push(...checkBytes(CONTRACTS[kind], bytes.byteLength))
  }
  return { ok: !issues.some((issue) => issue.severity === 'error'), issues }
}
