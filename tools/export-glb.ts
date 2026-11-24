import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { dirname } from 'node:path'
import { parseArgs } from 'node:util'
import {
  AnimationChannel,
  type Document,
  getBounds,
  Logger,
  type Mesh,
  type mat4,
  type Node,
  NodeIO,
  type Scene,
} from '@gltf-transform/core'
import { ALL_EXTENSIONS, EXTMeshoptCompression } from '@gltf-transform/extensions'
import {
  cloneDocument,
  convertPrimitiveToTriangles,
  dedup,
  getGLPrimitiveCount,
  prune,
  quantize,
  reorder,
  simplify,
  weld,
} from '@gltf-transform/functions'
import { MeshoptDecoder, MeshoptEncoder, MeshoptSimplifier } from 'meshoptimizer'
import { ASSET_KINDS, type AssetKind, CONTRACTS } from '../src/lib/asset-contract.ts'

const USAGE = `usage: node tools/export-glb.ts <in.glb> <out.glb> --kind <${ASSET_KINDS.join('|')}> [--markers <markers.json>]`

// The proxy keeps about this many triangles, for the scorer to render and compare.
const PROXY_TRIANGLES = 30_000
// The most triangles a proxy may keep. The simplifier lands a little over its target, so this
// leaves room for that, and a result above it is retried and then refused.
const PROXY_MAX_TRIANGLES = 31_000
// How many times the simplifier runs on the way to the budget.
const PROXY_PASSES = 4
// glTF primitive modes of a triangle list, a strip and a fan.
const TRIANGLES = 4
const TRIANGLE_STRIP = 5
const TRIANGLE_FAN = 6
// Proxy numbers are meters, written to the micrometer, so the JSON stays small.
const MICROMETER = 1e6

export interface ExportOptions {
  // The kind the file is meant to be. Export runs the same steps for every kind, and the kind
  // picks the required names its structure check watches. `validate-asset` applies the rest of
  // the contract afterwards.
  kind: AssetKind
  // Generator markers from the raw file. They are copied to `asset.extras.sourceAsset`. Absent
  // means there is nothing to carry, and the key is left out.
  markers?: Record<string, unknown>
  // Does the simplifying passes for the proxy. The default is `simplifyWithMeshopt`; a test swaps
  // in one that reduces too little, or nothing, to see what the export does about it.
  proxySimplifier?: ProxySimplifier
}

// Simplifies the proxy's copy of the document in place, to `ratio` of the triangles it has.
export type ProxySimplifier = (copy: Document, ratio: number) => Promise<void>

// The error limit is off (1 is the whole mesh radius): the target alone decides, and a curved car
// would otherwise stop far above it.
export const simplifyWithMeshopt: ProxySimplifier = async (copy, ratio) => {
  await MeshoptSimplifier.ready
  await copy.transform(simplify({ simplifier: MeshoptSimplifier, ratio, error: 1 }))
}

// What `score` loads instead of reading the GLB. `bbox_min`, `bbox_max`, `triangles` and
// `node_positions` describe the full mesh in the contract frame (glTF world space). `vertices` and
// `faces` are the same geometry in that frame, decimated to about PROXY_TRIANGLES (the export
// fails rather than write more than PROXY_MAX_TRIANGLES), so they must not be used to measure
// anything. `sha256` is the digest of the exported GLB's bytes.
export interface ExportProxy {
  sha256: string
  bbox_min: number[]
  bbox_max: number[]
  triangles: number
  node_positions: Record<string, number[]>
  vertices: number[][]
  faces: number[][]
}

const logger = new Logger(Logger.Verbosity.WARN)

const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({
  'meshopt.decoder': MeshoptDecoder,
  'meshopt.encoder': MeshoptEncoder,
})
io.setLogger(logger)

const micrometers = (value: number): number => Math.round(value * MICROMETER) / MICROMETER

function sceneOf(doc: Document): Scene {
  const root = doc.getRoot()
  const scene = root.getDefaultScene() ?? root.listScenes()[0]
  if (!scene) throw new Error('the GLB has no scene')
  return scene
}

function sceneNodes(scene: Scene): Node[] {
  const nodes: Node[] = []
  scene.traverse((node) => {
    nodes.push(node)
  })
  return nodes
}

// Triangles the way the contract counts them: a mesh counts once for every node that draws it.
function countTriangles(scene: Scene): number {
  let total = 0
  for (const node of sceneNodes(scene)) {
    for (const primitive of node.getMesh()?.listPrimitives() ?? []) {
      if (primitive.getMode() >= TRIANGLES) total += getGLPrimitiveCount(primitive)
    }
  }
  return total
}

// The world translation of every named node, which is where the anchors are. A name used twice
// keeps its first node, and `validate-asset` reports the duplicate.
function namedPositions(scene: Scene): Record<string, number[]> {
  const positions = new Map<string, number[]>()
  for (const node of sceneNodes(scene)) {
    const name = node.getName()
    if (name !== '' && !positions.has(name)) {
      positions.set(name, node.getWorldTranslation().map(micrometers))
    }
  }
  return Object.fromEntries(positions)
}

// Every triangle-list primitive of the scene as world-space vertices and faces. A mesh used by
// two nodes appears twice, once per node. A node with a mirroring matrix gets its faces turned
// back, so they still face outward.
function worldGeometry(doc: Document): { vertices: number[][]; faces: number[][] } {
  const vertices: number[][] = []
  const faces: number[][] = []
  for (const node of sceneNodes(sceneOf(doc))) {
    const mesh = node.getMesh()
    if (!mesh) continue
    const m = node.getWorldMatrix()
    const at = (index: number): number => m[index] ?? 0
    const determinant =
      at(0) * (at(5) * at(10) - at(9) * at(6)) -
      at(4) * (at(1) * at(10) - at(9) * at(2)) +
      at(8) * (at(1) * at(6) - at(5) * at(2))
    const mirrored = determinant < 0
    for (const primitive of mesh.listPrimitives()) {
      const position = primitive.getAttribute('POSITION')
      if (primitive.getMode() !== TRIANGLES || !position) continue
      const first = vertices.length
      const local = [0, 0, 0]
      for (let i = 0; i < position.getCount(); i++) {
        position.getElement(i, local)
        const [x = 0, y = 0, z = 0] = local
        vertices.push([
          micrometers(at(0) * x + at(4) * y + at(8) * z + at(12)),
          micrometers(at(1) * x + at(5) * y + at(9) * z + at(13)),
          micrometers(at(2) * x + at(6) * y + at(10) * z + at(14)),
        ])
      }
      const indices = primitive.getIndices()
      const count = indices ? indices.getCount() : position.getCount()
      const pick = (i: number): number => first + (indices ? indices.getScalar(i) : i)
      for (let i = 0; i + 2 < count; i += 3) {
        faces.push(
          mirrored ? [pick(i), pick(i + 2), pick(i + 1)] : [pick(i), pick(i + 1), pick(i + 2)],
        )
      }
    }
  }
  return { vertices, faces }
}

// Runs `pass(ratio)`, which simplifies the proxy's mesh to that share of its triangles and returns
// how many it has left, until the count is within PROXY_MAX_TRIANGLES. A pass that lands above it
// is followed by one aimed again at PROXY_TRIANGLES from where it stopped. Past PROXY_PASSES
// passes it throws, rather than hand `score` a proxy over the budget. Returns the final count.
export async function fitProxyBudget(
  count: number,
  pass: (ratio: number) => Promise<number>,
): Promise<number> {
  let left = count
  for (let attempt = 0; attempt < PROXY_PASSES && left > PROXY_TRIANGLES; attempt++) {
    left = await pass(PROXY_TRIANGLES / left)
    if (left <= PROXY_MAX_TRIANGLES) return left
  }
  if (left > PROXY_MAX_TRIANGLES) {
    throw new Error(
      `could not decimate the proxy to ${PROXY_MAX_TRIANGLES.toLocaleString('en-US')} triangles or fewer: ${left.toLocaleString('en-US')} left after ${PROXY_PASSES} passes`,
    )
  }
  return left
}

// Cuts the proxy's geometry from a copy of the document, so the real one keeps everything it has.
// On the copy:
// - Strips and fans become triangle lists, so they reach the proxy.
// - Every attribute but POSITION goes, and then coincident positions are welded. The simplifier
//   keeps a vertex split wherever normals or UVs differ, so a flat-shaded or seam-ridden mesh
//   (each triangle with vertices of its own) would otherwise stay far above the budget. The proxy
//   is positions only, so the splits mean nothing to it.
// - Then `simplifier` takes it to PROXY_TRIANGLES through `fitProxyBudget`.
async function decimatedGeometry(doc: Document, simplifier: ProxySimplifier) {
  const copy = cloneDocument(doc)
  for (const mesh of copy.getRoot().listMeshes()) {
    for (const primitive of mesh.listPrimitives()) {
      const mode = primitive.getMode()
      if (mode === TRIANGLE_STRIP || mode === TRIANGLE_FAN) convertPrimitiveToTriangles(primitive)
      for (const semantic of primitive.listSemantics()) {
        if (semantic !== 'POSITION') primitive.setAttribute(semantic, null)
      }
      for (const target of primitive.listTargets()) primitive.removeTarget(target)
    }
  }
  await copy.transform(weld())
  const scene = sceneOf(copy)
  await fitProxyBudget(countTriangles(scene), async (ratio) => {
    await simplifier(copy, ratio)
    return countTriangles(scene)
  })
  return worldGeometry(copy)
}

// The parts of the contract that depend on the file's node structure, by name. `nodes` and
// `anchors` are the required ones the scene has, `meshNodes` the required nodes that carry a mesh,
// and `emptyAnchors` the anchors with no mesh on them or below them.
export interface ContractStructure {
  nodes: string[]
  meshNodes: string[]
  anchors: string[]
  emptyAnchors: string[]
}

const hasMeshAtOrBelow = (node: Node): boolean =>
  node.getMesh() !== null || node.listChildren().some(hasMeshAtOrBelow)

export function contractStructure(scene: Scene, kind: AssetKind): ContractStructure {
  const { requiredNodes, requiredAnchors } = CONTRACTS[kind]
  const all = sceneNodes(scene)
  const named = (name: string): Node[] => all.filter((node) => node.getName() === name)
  const anchors = requiredAnchors.filter((name) => named(name).length > 0)
  return {
    nodes: requiredNodes.filter((name) => named(name).length > 0),
    meshNodes: requiredNodes.filter((name) => named(name).some((node) => node.getMesh() !== null)),
    anchors,
    emptyAnchors: anchors.filter((name) => named(name).every((node) => !hasMeshAtOrBelow(node))),
  }
}

// What an export lost: a required node that is gone, a required mesh node without its mesh, an
// anchor that is gone, an anchor that got a mesh. A defect the input already had is not listed,
// because the export did not cause it and `validate` reports it.
export function structureProblems(before: ContractStructure, after: ContractStructure): string[] {
  const lost = (was: string[], now: string[]): string[] => was.filter((name) => !now.includes(name))
  return [
    ...lost(before.nodes, after.nodes).map((name) => `${name} is gone`),
    ...lost(before.meshNodes, after.meshNodes)
      .filter((name) => after.nodes.includes(name))
      .map((name) => `${name} lost its mesh`),
    ...lost(before.anchors, after.anchors).map((name) => `${name} is gone`),
    ...lost(before.emptyAnchors, after.emptyAnchors)
      .filter((name) => after.anchors.includes(name))
      .map((name) => `${name} is no longer an empty leaf`),
  ]
}

// Column-major 4x4 product `a * b`, as glTF stores matrices.
function multiply(a: readonly number[], b: readonly number[]): mat4 {
  const out = new Array<number>(16).fill(0)
  for (let column = 0; column < 4; column++) {
    for (let row = 0; row < 4; row++) {
      let sum = 0
      for (let k = 0; k < 4; k++) sum += (a[k * 4 + row] ?? 0) * (b[column * 4 + k] ?? 0)
      out[column * 4 + row] = sum
    }
  }
  return out as mat4
}

// A node that draws a mesh and has children, as it is before quantize.
interface MeshParent {
  node: Node
  mesh: Mesh
  children: Node[]
}

function meshParents(doc: Document): MeshParent[] {
  return doc
    .getRoot()
    .listNodes()
    .flatMap((node) => {
      const mesh = node.getMesh()
      return mesh && node.listChildren().length > 0
        ? [{ node, mesh, children: [...node.listChildren()] }]
        : []
    })
}

// A node with children and a translation, rotation or scale animation can't be restored: its
// static matrix would carry quantize's correction, and the animation overwrites that matrix, so
// playing it would move or distort the mesh. Export refuses it, naming the node.
function rejectAnimatedMeshParents(parents: MeshParent[]): void {
  const transformPaths = ['translation', 'rotation', 'scale']
  for (const { node } of parents) {
    const animated = node
      .listParents()
      .some(
        (parent) =>
          parent instanceof AnimationChannel &&
          transformPaths.includes(parent.getTargetPath() ?? ''),
      )
    if (animated) {
      throw new Error(
        `${node.getName() || '(unnamed node)'} has children and an animated translation, rotation or scale, which the export cannot keep: quantizing its mesh changes the node's transform, and the animation would overwrite that change`,
      )
    }
  }
}

// quantize() scales a mesh through the matrix of the node that draws it. For a node with children
// it moves the mesh to a new unnamed child instead, so the children are not scaled, which leaves
// the named node (`trunk_lid` with an anchor under it) without its mesh, and a module swap hides
// that node. This puts the mesh back and folds the correction into the node's matrix, and its
// inverse into each original child's, so every child stays where it was.
function restoreMeshParents(parents: MeshParent[]): void {
  for (const { node, mesh, children } of parents) {
    if (node.getMesh() !== null) continue
    const carrier = node.listChildren().find((c) => !children.includes(c) && c.getMesh() === mesh)
    if (!carrier) continue // the structure check reports the node
    const m = carrier.getMatrix()
    const scale = m[0]
    // quantize's correction is a uniform scale and a translation; the inverse below assumes it.
    const uniform = m[5] === scale && m[10] === scale && scale > 0
    const linear = [1, 2, 4, 6, 8, 9].every((index) => m[index] === 0)
    if (!(uniform && linear))
      throw new Error(`quantize gave ${node.getName()} an unexpected matrix`)
    // biome-ignore format: keeps the matrix as a 4 x 4 grid
    const inverse: mat4 = [
      1 / scale, 0, 0, 0,
      0, 1 / scale, 0, 0,
      0, 0, 1 / scale, 0,
      -m[12] / scale, -m[13] / scale, -m[14] / scale, 1,
    ]
    node.setMesh(mesh).setMatrix(multiply(node.getMatrix(), m))
    carrier.dispose()
    for (const child of children) child.setMatrix(multiply(inverse, child.getMatrix()))
  }
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

// Runs glTF-Transform's functions one by one (never `optimize`: it drops anchors and merges the
// required materials) and writes a meshopt-compressed GLB, plus the proxy built from the document
// as it stands right before quantize and meshopt rewrite its accessors and node matrices.
//
// - `weld`, then `dedup({ keepUniqueNames: true })`: the five required materials differ only by
//   name, and the default `dedup` would merge them.
// - `prune({ keepLeaves: true })`: the anchors are empty leaf nodes, and the default deletes them.
//   Solid-color textures are kept too, because export doesn't edit textures.
// - No `flatten` or `join`: both delete empty leaves unless told not to, and required names must
//   stay unique.
// - `quantize` moves the mesh of a node that has children onto a new unnamed child. A required
//   node keeps its own mesh, so the mesh is put back and the children's matrices are corrected.
// - The result is checked against the contract's node structure (`structureProblems`), and a loss
//   fails the export.
// - Textures stay as they come (WebP, or PNG where WebP is unsupported). KTX2 waits for Phase 1.
export async function exportGlb(
  input: Uint8Array,
  opts: ExportOptions,
): Promise<{ glb: Uint8Array; proxy: ExportProxy }> {
  await Promise.all([MeshoptDecoder.ready, MeshoptEncoder.ready])
  const doc = await io.readBinary(input)
  const before = contractStructure(sceneOf(doc), opts.kind)
  await doc.transform(
    weld(),
    dedup({ keepUniqueNames: true }),
    prune({ keepLeaves: true, keepSolidTextures: true }),
  )

  const parents = meshParents(doc)
  rejectAnimatedMeshParents(parents)

  const asset = doc.getRoot().getAsset()
  asset.extras = {
    ...(isRecord(asset.extras) ? asset.extras : {}),
    aiGenerated: true,
    ...(opts.markers === undefined ? {} : { sourceAsset: opts.markers }),
  }

  const scene = sceneOf(doc)
  const triangles = countTriangles(scene)
  const bounds = getBounds(scene)
  const nodePositions = namedPositions(scene)
  const { vertices, faces } = await decimatedGeometry(
    doc,
    opts.proxySimplifier ?? simplifyWithMeshopt,
  )

  await doc.transform(reorder({ encoder: MeshoptEncoder }), quantize())
  restoreMeshParents(parents)

  // A file that no longer meets the contract's structure is not worth writing: the stage after
  // this one would only find it out later, without saying which step broke it.
  const problems = structureProblems(before, contractStructure(sceneOf(doc), opts.kind))
  if (problems.length > 0) {
    throw new Error(`the export would break the asset's structure: ${problems.join('; ')}`)
  }
  doc
    .createExtension(EXTMeshoptCompression)
    .setRequired(true)
    .setEncoderOptions({ method: EXTMeshoptCompression.EncoderMethod.QUANTIZE })
  const glb = await io.writeBinary(doc)

  return {
    glb,
    proxy: {
      sha256: createHash('sha256').update(glb).digest('hex'),
      bbox_min: bounds.min.map(micrometers),
      bbox_max: bounds.max.map(micrometers),
      triangles,
      node_positions: nodePositions,
      vertices,
      faces,
    },
  }
}

export interface ExportGlbResult {
  exitCode: 0 | 1 | 2
  stdout: string[]
  stderr: string[]
}

const usageError = (message: string): ExportGlbResult => ({
  exitCode: 2,
  stdout: [],
  stderr: [message, USAGE],
})

const isKind = (value: string): value is AssetKind =>
  (ASSET_KINDS as readonly string[]).includes(value)

const missing = (error: unknown): boolean =>
  error instanceof Error && 'code' in error && error.code === 'ENOENT'

const GLB_EXTENSION = '.glb'

// `--markers` names a JSON file holding one object: the generator markers to carry into the GLB.
async function readMarkers(file: string): Promise<Record<string, unknown> | string> {
  let parsed: unknown
  try {
    parsed = JSON.parse(await readFile(file, 'utf8'))
  } catch (error) {
    return `cannot read the markers file ${file}: ${error instanceof Error ? error.message : String(error)}`
  }
  return isRecord(parsed) ? parsed : `the markers file ${file} must hold a JSON object`
}

// Exports one GLB and writes `<out minus .glb>.proxy.json` next to it. Exit codes: 0 done, 1 the
// input could not be exported, 2 bad usage or an unreadable input or markers file. `testing` only
// exists for tests (it swaps the proxy's simplifier); the command line never passes it.
export async function runExportGlb(
  args: string[],
  testing: Pick<ExportOptions, 'proxySimplifier'> = {},
): Promise<ExportGlbResult> {
  let parsed: ReturnType<
    typeof parseArgs<{
      options: { kind: { type: 'string' }; markers: { type: 'string' } }
      allowPositionals: true
    }>
  >
  try {
    parsed = parseArgs({
      args,
      allowPositionals: true,
      options: { kind: { type: 'string' }, markers: { type: 'string' } },
    })
  } catch (error) {
    return usageError(error instanceof Error ? error.message : String(error))
  }
  const { values, positionals } = parsed
  const [inFile, outFile, ...extra] = positionals
  if (!inFile || !outFile || extra.length > 0) {
    return usageError('expected an input GLB and an output GLB')
  }
  if (!outFile.endsWith(GLB_EXTENSION)) {
    return usageError(`the output must end in ${GLB_EXTENSION}: ${outFile}`)
  }
  if (values.kind === undefined) return usageError('--kind is required')
  if (!isKind(values.kind)) {
    return usageError(
      `unknown kind ${JSON.stringify(values.kind)}; known: ${ASSET_KINDS.join(', ')}`,
    )
  }

  let markers: Record<string, unknown> | undefined
  if (values.markers !== undefined) {
    const read = await readMarkers(values.markers)
    if (typeof read === 'string') return usageError(read)
    markers = read
  }

  let input: Uint8Array
  try {
    input = await readFile(inFile)
  } catch (error) {
    return usageError(
      missing(error) ? `file not found: ${inFile}` : `cannot read ${inFile}: ${String(error)}`,
    )
  }

  const proxyFile = `${outFile.slice(0, -GLB_EXTENSION.length)}.proxy.json`
  try {
    const { glb, proxy } = await exportGlb(input, {
      kind: values.kind,
      ...(markers === undefined ? {} : { markers }),
      ...testing,
    })
    await mkdir(dirname(outFile), { recursive: true })
    await writeFile(outFile, glb)
    await writeFile(proxyFile, JSON.stringify(proxy))
    return {
      exitCode: 0,
      stdout: [
        `wrote ${outFile} (${glb.byteLength} bytes, ${proxy.triangles} triangles) and ${proxyFile}`,
      ],
      stderr: [],
    }
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error)
    return { exitCode: 1, stdout: [], stderr: [`could not export ${inFile}: ${reason}`] }
  }
}

if (import.meta.main) {
  const { exitCode, stdout, stderr } = await runExportGlb(process.argv.slice(2))
  for (const line of stdout) console.log(line)
  for (const line of stderr) console.error(line)
  process.exitCode = exitCode
}
