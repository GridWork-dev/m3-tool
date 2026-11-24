import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { dirname } from 'node:path'
import { parseArgs } from 'node:util'
import {
  type Document,
  getBounds,
  Logger,
  type Node,
  NodeIO,
  type Scene,
} from '@gltf-transform/core'
import { ALL_EXTENSIONS, EXTMeshoptCompression } from '@gltf-transform/extensions'
import {
  cloneDocument,
  dedup,
  getGLPrimitiveCount,
  prune,
  quantize,
  reorder,
  simplify,
  weld,
} from '@gltf-transform/functions'
import { MeshoptDecoder, MeshoptEncoder, MeshoptSimplifier } from 'meshoptimizer'
import { ASSET_KINDS, type AssetKind } from '../src/lib/asset-contract.ts'

const USAGE = `usage: node tools/export-glb.ts <in.glb> <out.glb> --kind <${ASSET_KINDS.join('|')}> [--markers <markers.json>]`

// The proxy keeps about this many triangles, for the scorer to render and compare.
const PROXY_TRIANGLES = 30_000
// glTF primitive mode of a triangle list.
const TRIANGLES = 4
// Proxy numbers are meters, written to the micrometer, so the JSON stays small.
const MICROMETER = 1e6

export interface ExportOptions {
  // The kind the file is meant to be. Export runs the same steps for every kind, and
  // `validate-asset` applies each kind's contract afterwards.
  kind: AssetKind
  // Generator markers from the raw file. They are copied to `asset.extras.sourceAsset`. Absent
  // means there is nothing to carry, and the key is left out.
  markers?: Record<string, unknown>
}

// What `score` loads instead of reading the GLB. `bbox_min`, `bbox_max`, `triangles` and
// `node_positions` describe the full mesh in the contract frame (glTF world space). `vertices` and
// `faces` are the same geometry in that frame, decimated to about PROXY_TRIANGLES, so they must
// not be used to measure anything. `sha256` is the digest of the exported GLB's bytes.
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

// Decimates a copy of the document, so the real one keeps its full geometry. The error limit is
// off (1 is the whole mesh radius): the target alone decides, and a curved car would otherwise
// stop far above it.
async function decimatedGeometry(doc: Document, triangles: number) {
  const copy = cloneDocument(doc)
  if (triangles > PROXY_TRIANGLES) {
    await MeshoptSimplifier.ready
    await copy.transform(
      simplify({ simplifier: MeshoptSimplifier, ratio: PROXY_TRIANGLES / triangles, error: 1 }),
    )
  }
  return worldGeometry(copy)
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
// - Textures stay as they come (WebP, or PNG where WebP is unsupported). KTX2 waits for Phase 1.
export async function exportGlb(
  input: Uint8Array,
  opts: ExportOptions,
): Promise<{ glb: Uint8Array; proxy: ExportProxy }> {
  await Promise.all([MeshoptDecoder.ready, MeshoptEncoder.ready])
  const doc = await io.readBinary(input)
  await doc.transform(
    weld(),
    dedup({ keepUniqueNames: true }),
    prune({ keepLeaves: true, keepSolidTextures: true }),
  )

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
  const { vertices, faces } = await decimatedGeometry(doc, triangles)

  await doc.transform(reorder({ encoder: MeshoptEncoder }), quantize())
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
// input could not be exported, 2 bad usage or an unreadable input or markers file.
export async function runExportGlb(args: string[]): Promise<ExportGlbResult> {
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
