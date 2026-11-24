// Screenshot check for the throwaway viewer (Phase 0.6 spike). It is a throwaway check, not a
// test under tests/: it uses Playwright's API and writes its shots to the work dir.
//
//   node pipeline/viewer/shoot.ts --fixture [--webgl] [--work-dir <dir>]
//   node pipeline/viewer/shoot.ts --car <glb> [--interior <glb>] [--wheel <glb>] [--webgl]
//
// It starts the viewer's server, opens headed Chromium with WebGPU on, and checks that paint,
// glass, wheels and interior each change the picture on their own: for each one it resets the
// viewer, takes a baseline from the camera that sees the part, flips only that control, takes
// another shot, and compares. It also checks `state()` after every step. Paths given to --car,
// --interior and --wheel are absolute, or relative to the work dir, and must be inside it.
// Shots go to <work dir>/spike/fixture/shots/ (--fixture) or <work dir>/spike/shots/, with
// `-webgl` after `shots` when --webgl forces the WebGL2 backend, so the two runs keep their own.
// Exit 0 when every check passes, 1 when one fails, 2 when it could not run.
import { mkdir, readFile, realpath, writeFile } from 'node:fs/promises'
import { isAbsolute, join, relative, resolve, sep } from 'node:path'
import { parseArgs } from 'node:util'
import type { Document } from '@gltf-transform/core'
import { type Browser, chromium, type Page } from '@playwright/test'
import { parse as parseYaml } from 'yaml'
import { makeBaseCar, makeInterior, makeProduct, toGlb } from '../../tests/unit/assets/fixtures.ts'
import { REPO_ROOT, resolveWorkDir, startServer } from './serve.ts'

const GEN = 'e46'
// A pixel counts as changed when a channel moves by more than this (out of 255).
const CHANNEL_TOLERANCE = 16
// A flipped control must change at least this share of the canvas, and two shots of one state
// must differ by less than the second number.
const MIN_CHANGED = 0.002
const MAX_NOISE = 0.0005
const VIEWPORT = { width: 1280, height: 800 }

interface ViewerState {
  camera: 'orbit' | 'driver'
  paint: string
  glassVisible: boolean
  glassOpacity: number
  wheelsVisible: boolean
  interiorVisible: boolean
  interiorPosition: [number, number, number]
  eye: [number, number, number]
  backend: 'webgpu' | 'webgl2'
}

interface ViewerApi {
  ready: Promise<void>
  state: () => ViewerState
  reset: () => void
  settle: (count?: number) => Promise<void>
  // The direction the driver camera looks, as a unit vector in the car frame.
  driverForward: () => [number, number, number]
}

type ViewerWindow = { __viewer: ViewerApi }

// ---------------------------------------------------------------------------------------------
// Fixture: a car, a wheel and an interior built from tests/unit/assets/fixtures.ts, tuned so each
// part is visible from the camera that is meant to see it.
// ---------------------------------------------------------------------------------------------

type Rgba = [number, number, number, number]

// glTF colors are linear, and a hex color is sRGB.
function linear(hex: string, alpha = 1): Rgba {
  const channel = (offset: number): number => {
    const value = Number.parseInt(hex.slice(offset, offset + 2), 16) / 255
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
  }
  return [channel(1), channel(3), channel(5), alpha]
}

function style(doc: Document, name: string, hex: string, metallic: number, roughness: number) {
  const material = doc
    .getRoot()
    .listMaterials()
    .find((candidate) => candidate.getName() === name)
  if (!material) throw new Error(`fixture has no material ${name}`)
  material.setBaseColorFactor(linear(hex)).setMetallicFactor(metallic).setRoughnessFactor(roughness)
  return material
}

function fixtureCar(): Document {
  const doc = makeBaseCar()
  style(doc, 'paint', '#b01c1c', 0.4, 0.35)
  style(doc, 'trim', '#151515', 0, 0.7)
  const glass = style(doc, 'glass', '#9cc4e4', 0, 0.1)
  glass.setAlphaMode('BLEND')
  // The base car's own glass is a 0.1 m cube inside the body, which nothing can see. A glass slab
  // above the roof, made from the same primitive and stretched, is outside the body, so the glass
  // controls have something to show. It sits at 1.75 m, the roof's top being at 1.49 m.
  const cube = doc
    .getRoot()
    .listMeshes()
    .flatMap((mesh) => mesh.listPrimitives())
    .find((primitive) => primitive.getMaterial() === glass)
  if (!cube) throw new Error('fixture car has no glass primitive to copy')
  // The cube's center is 0.72 m up, and a node scales about the origin, so shift the node to
  // land the slab's center at y 1.75.
  const slab = doc
    .createNode('glass_slab')
    .setMesh(doc.createMesh('glass_slab').addPrimitive(cube.clone()))
    .setScale([16, 0.5, 20])
    .setTranslation([0, 1.75 - 0.72 * 0.5, 0])
  doc.getRoot().listScenes()[0]?.listChildren()[0]?.addChild(slab)
  return doc
}

function fixtureWheel(): Document {
  const doc = makeProduct()
  style(doc, 'product', '#c9ccd2', 0.9, 0.3)
  // makeProduct is a 0.3 m cube standing on its pivot. Stretch it to a 0.6 x 0.66 x 0.66 m slab
  // and center it on the pivot, so a wheel anchor at 0.32 m up puts it on the ground and its
  // outer face 0.16 m outside the body.
  const root = doc.getRoot().listScenes()[0]?.listChildren()[0]
  if (!root) throw new Error('fixture wheel has no root node')
  root.setScale([2, 2.2, 2.2]).setTranslation([0, -0.33, 0])
  return doc
}

function fixtureInterior(): Document {
  const doc = makeInterior()
  style(doc, 'fabric', '#c8a46a', 0, 0.8)
  return doc
}

async function writeFixture(
  dir: string,
): Promise<{ car: string; interior: string; wheel: string }> {
  await mkdir(dir, { recursive: true })
  const files = {
    car: await toGlb(fixtureCar(), { meshopt: true }),
    interior: await toGlb(fixtureInterior(), { meshopt: true }),
    wheel: await toGlb(fixtureWheel(), { meshopt: true }),
  }
  for (const [name, bytes] of Object.entries(files))
    await writeFile(join(dir, `${name}.glb`), bytes)
  return { car: 'car.glb', interior: 'interior.glb', wheel: 'wheel.glb' }
}

// ---------------------------------------------------------------------------------------------
// Checks
// ---------------------------------------------------------------------------------------------

interface CheckResult {
  name: string
  ok: boolean
  detail: string
}

const results: CheckResult[] = []

function record(name: string, ok: boolean, detail: string): boolean {
  results.push({ name, ok, detail })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}: ${detail}`)
  return ok
}

const viewerState = (page: Page): Promise<ViewerState> =>
  page.evaluate(() => (window as unknown as ViewerWindow).__viewer.state())
const viewerReset = (page: Page): Promise<void> =>
  page.evaluate(() => (window as unknown as ViewerWindow).__viewer.reset())
const viewerSettle = (page: Page): Promise<void> =>
  page.evaluate(() => (window as unknown as ViewerWindow).__viewer.settle(5))
const viewerForward = (page: Page): Promise<[number, number, number]> =>
  page.evaluate(() => (window as unknown as ViewerWindow).__viewer.driverForward())

const near = (a: readonly number[], b: readonly number[], tolerance: number): boolean =>
  a.length === b.length &&
  a.every((value, i) => Math.abs(value - (b[i] ?? Number.NaN)) <= tolerance)

// The state keys whose value differs between two states.
function changedKeys(a: ViewerState, b: ViewerState): string[] {
  const keys = Object.keys(a) as (keyof ViewerState)[]
  return keys.filter((key) => JSON.stringify(a[key]) !== JSON.stringify(b[key]))
}

const sameList = (a: string[], b: string[]): boolean =>
  a.length === b.length && a.every((value, index) => value === b[index])

// Loads the viewer and waits until it has drawn its first frames, or throws what stopped it.
async function openViewer(page: Page, url: string, timeout = 30_000): Promise<void> {
  await page.goto(url)
  await page.waitForFunction(() => '__viewer' in window, undefined, { timeout })
  await page.evaluate(() => (window as unknown as ViewerWindow).__viewer.ready)
  await viewerSettle(page)
  await page.bringToFront()
}

async function shoot(page: Page, file: string): Promise<Buffer> {
  await viewerSettle(page)
  return page.locator('#stage canvas').screenshot({ path: file })
}

// The share of pixels that differ between two PNGs, decoded by a scratch page's canvas.
async function changedShare(scratch: Page, a: Buffer, b: Buffer): Promise<number> {
  return scratch.evaluate(
    async ([left, right, tolerance]) => {
      const pixels = async (base64: string): Promise<ImageData> => {
        const blob = await (await fetch(`data:image/png;base64,${base64}`)).blob()
        const bitmap = await createImageBitmap(blob)
        const context = new OffscreenCanvas(bitmap.width, bitmap.height).getContext('2d')
        if (!context) throw new Error('no 2d context')
        context.drawImage(bitmap, 0, 0)
        return context.getImageData(0, 0, bitmap.width, bitmap.height)
      }
      const first = await pixels(left as string)
      const second = await pixels(right as string)
      if (first.width !== second.width || first.height !== second.height) return 1
      let changed = 0
      for (let i = 0; i < first.data.length; i += 4) {
        const moved = [0, 1, 2].some(
          (c) =>
            Math.abs((first.data[i + c] ?? 0) - (second.data[i + c] ?? 0)) > (tolerance as number),
        )
        if (moved) changed += 1
      }
      return changed / (first.width * first.height)
    },
    [a.toString('base64'), b.toString('base64'), CHANNEL_TOLERANCE],
  )
}

interface ToggleCase {
  name: string
  // The camera that sees the part.
  camera: 'orbit' | 'driver'
  // The state key the control moves. Controls that state() doesn't report, like the field of
  // view, leave it out, and then no key may change.
  key?: keyof ViewerState
  expected?: (before: ViewerState) => unknown
  flip: (page: Page, before: ViewerState) => Promise<void>
}

function toggleCases(has: { wheel: boolean; interior: boolean }): ToggleCase[] {
  const cases: ToggleCase[] = [
    {
      name: 'paint',
      camera: 'orbit',
      key: 'paint',
      expected: (before) => (before.paint === '#1f4fd8' ? '#d8a31f' : '#1f4fd8'),
      flip: (page, before) =>
        page.locator('#paint').fill(before.paint === '#1f4fd8' ? '#d8a31f' : '#1f4fd8'),
    },
    {
      name: 'glass',
      camera: 'orbit',
      key: 'glassVisible',
      expected: () => false,
      flip: (page) => page.locator('#glass-visible').uncheck(),
    },
    {
      name: 'glass-opacity',
      camera: 'orbit',
      key: 'glassOpacity',
      expected: () => 1,
      flip: (page) => page.locator('#glass-opacity').fill('1'),
    },
  ]
  if (has.wheel) {
    cases.push({
      name: 'wheels',
      camera: 'orbit',
      key: 'wheelsVisible',
      expected: () => false,
      flip: (page) => page.locator('#wheels-visible').uncheck(),
    })
  }
  if (has.interior) {
    // The interior case goes first among the driver ones: its baseline is the driver reference.
    cases.push(
      {
        name: 'interior',
        camera: 'driver',
        key: 'interiorVisible',
        expected: () => false,
        flip: (page) => page.locator('#interior-visible').uncheck(),
      },
      {
        name: 'driver-fov',
        camera: 'driver',
        flip: (page) => page.locator('#fov').fill('110'),
      },
      {
        name: 'driver-look',
        camera: 'driver',
        flip: async (page) => {
          const box = await page.locator('#stage canvas').boundingBox()
          if (!box) throw new Error('the canvas has no box')
          const x = box.x + box.width / 2
          const y = box.y + box.height / 2
          await page.mouse.move(x, y)
          await page.mouse.down()
          await page.mouse.move(x - 240, y - 60, { steps: 8 })
          await page.mouse.up()
        },
      },
    )
  }
  return cases
}

// The first reset-state shot from each camera. Every later baseline must match it, which is what
// proves that reset() put the part, the paint, the field of view and the look direction back.
type References = { orbit?: Buffer; driver?: Buffer }

const percent = (share: number, digits = 2): string => `${(share * 100).toFixed(digits)}%`

async function runToggle(
  page: Page,
  scratch: Page,
  shots: string,
  defaults: ViewerState,
  references: References,
  c: ToggleCase,
): Promise<void> {
  const name = `control ${c.name}`
  await viewerReset(page)
  await viewerSettle(page)
  const reset = await viewerState(page)
  const resetDiff = changedKeys(reset, defaults)
  record(
    `${name}: reset restores the defaults`,
    resetDiff.length === 0,
    resetDiff.join(', ') || 'state equals the defaults',
  )

  // The driver camera is itself a state key, so it is part of the baseline, not of the flip.
  const baseKeys: string[] = []
  if (c.camera === 'driver') {
    await page.locator('#camera-driver').check()
    baseKeys.push('camera')
  }
  const baseline = await shoot(page, join(shots, `${c.name}-baseline.png`))
  const before = await viewerState(page)
  const beforeDiff = changedKeys(before, defaults)
  record(
    `${name}: baseline differs from the defaults only by the camera`,
    sameList(beforeDiff, baseKeys),
    beforeDiff.join(', ') || 'no keys',
  )
  const reference = references[c.camera]
  if (reference) {
    const drift = await changedShare(scratch, reference, baseline)
    record(
      `${name}: baseline matches the reset-state ${c.camera} shot`,
      drift < MAX_NOISE,
      percent(drift, 3),
    )
  } else {
    references[c.camera] = baseline
  }

  await c.flip(page, before)
  const flipped = await shoot(page, join(shots, `${c.name}-flipped.png`))
  const after = await viewerState(page)
  const afterDiff = changedKeys(after, before)
  const { key } = c
  if (key === undefined) {
    record(
      `${name}: state() is unchanged`,
      afterDiff.length === 0,
      afterDiff.join(', ') || 'no keys',
    )
  } else {
    record(
      `${name}: only ${key} changed`,
      sameList(afterDiff, [key]),
      afterDiff.join(', ') || 'no keys',
    )
    const wanted = c.expected?.(before)
    record(
      `${name}: ${key} is ${JSON.stringify(wanted)}`,
      JSON.stringify(after[key]) === JSON.stringify(wanted),
      JSON.stringify(after[key]),
    )
  }

  const share = await changedShare(scratch, baseline, flipped)
  record(
    `${name}: the ${c.camera} shot changed`,
    share >= MIN_CHANGED,
    `${percent(share)} of pixels moved (needs ${percent(MIN_CHANGED, 1)})`,
  )
}

// ---------------------------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------------------------

// The eye point read straight from the YAML, in meters, apart from the server's own reader.
async function yamlEyeMeters(gen: string): Promise<number[]> {
  const text = await readFile(join(REPO_ROOT, 'data', 'generations', `${gen}.yaml`), 'utf8')
  const data = parseYaml(text) as { driverEyePoint: { xMm: number; yMm: number; zMm: number } }
  const eye = data.driverEyePoint
  return [eye.xMm / 1000, eye.yMm / 1000, eye.zMm / 1000]
}

// A path under the work dir, as the viewer's ?car= wants it (relative, forward slashes).
async function underWorkDir(workDir: string, path: string): Promise<string> {
  const absolute = isAbsolute(path) ? path : resolve(workDir, path)
  let real: string
  try {
    real = await realpath(absolute)
  } catch {
    throw new Error(`${absolute} does not exist`)
  }
  const realWork = await realpath(workDir)
  if (!real.startsWith(realWork + sep))
    throw new Error(`${path} is not inside the work dir ${workDir}`)
  return relative(realWork, real).split(sep).join('/')
}

async function main(): Promise<number> {
  const { values } = parseArgs({
    options: {
      fixture: { type: 'boolean' },
      car: { type: 'string' },
      interior: { type: 'string' },
      wheel: { type: 'string' },
      webgl: { type: 'boolean' },
      'work-dir': { type: 'string' },
    },
    strict: true,
  })
  if (values.fixture === (values.car !== undefined)) {
    throw new Error('give exactly one of --fixture or --car <glb>')
  }
  if (values.fixture && (values.interior !== undefined || values.wheel !== undefined)) {
    throw new Error('--fixture builds its own interior and wheel; drop --interior and --wheel')
  }
  const workDir = resolveWorkDir(values['work-dir'])
  await mkdir(workDir, { recursive: true })

  let assets: { car: string; interior?: string; wheel?: string }
  let shots: string
  if (values.fixture) {
    const dir = join(workDir, 'spike', 'fixture')
    const written = await writeFixture(dir)
    assets = {
      car: `spike/fixture/${written.car}`,
      interior: `spike/fixture/${written.interior}`,
      wheel: `spike/fixture/${written.wheel}`,
    }
    shots = join(dir, values.webgl ? 'shots-webgl' : 'shots')
  } else {
    assets = { car: await underWorkDir(workDir, values.car as string) }
    if (values.interior !== undefined)
      assets.interior = await underWorkDir(workDir, values.interior)
    if (values.wheel !== undefined) assets.wheel = await underWorkDir(workDir, values.wheel)
    shots = join(workDir, 'spike', values.webgl ? 'shots-webgl' : 'shots')
  }
  await mkdir(shots, { recursive: true })

  const server = await startServer({ workDir, port: 0 })
  let browser: Browser | undefined
  try {
    browser = await chromium.launch({ headless: false, args: ['--enable-unsafe-webgpu'] })
    const context = await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: 1 })
    const page = await context.newPage()
    const scratch = await context.newPage()
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    page.on('console', (message) => {
      if (message.type() === 'error') pageErrors.push(`console.error: ${message.text()}`)
    })

    const query = new URLSearchParams({ car: assets.car })
    if (assets.interior) query.set('interior', assets.interior)
    if (assets.wheel) query.set('wheel', assets.wheel)
    if (values.webgl) query.set('backend', 'webgl')
    await openViewer(page, `${server.url}/viewer/?${query}`)

    const defaults = await viewerState(page)
    record(
      'viewer started',
      true,
      `backend ${defaults.backend}${values.webgl ? ' (forced WebGL2)' : ''}`,
    )
    if (values.webgl)
      record('forced WebGL2 is honored', defaults.backend === 'webgl2', defaults.backend)

    const eye = await yamlEyeMeters(GEN)
    record(
      `state().eye is the ${GEN} driverEyePoint in meters`,
      eye.length === 3 && eye.every((v, i) => Math.abs(v - (defaults.eye[i] ?? Number.NaN)) < 1e-9),
      `${JSON.stringify(defaults.eye)} vs YAML ${JSON.stringify(eye)}`,
    )
    // The nose is toward -Z, so a driver at default yaw looks along -Z. A flipped look direction
    // would still put the eye at the right point, so this is checked on its own.
    const forward = await viewerForward(page)
    record(
      'the driver camera looks toward -Z at default yaw',
      near(forward, [0, 0, -1], 1e-6),
      JSON.stringify(forward),
    )
    if (assets.interior) {
      record(
        'state().interiorPosition is the car origin',
        JSON.stringify(defaults.interiorPosition) === '[0,0,0]',
        JSON.stringify(defaults.interiorPosition),
      )
    }

    // Two shots of one state must match, or "the shot changed" would prove nothing.
    await viewerReset(page)
    const first = await shoot(page, join(shots, 'control-a.png'))
    const second = await shoot(page, join(shots, 'control-b.png'))
    const noise = await changedShare(scratch, first, second)
    record(
      'noise: two shots of one state match',
      noise < MAX_NOISE,
      `${percent(noise, 3)} of pixels moved (allows ${percent(MAX_NOISE)})`,
    )

    const references: References = { orbit: first }
    const cases = toggleCases({ wheel: Boolean(assets.wheel), interior: Boolean(assets.interior) })
    for (const c of cases) await runToggle(page, scratch, shots, defaults, references, c)
    if (references.driver) {
      // The look direction has no state key, so check it came back by the picture itself.
      await viewerReset(page)
      await page.locator('#camera-driver').check()
      const again = await shoot(page, join(shots, 'driver-after-reset.png'))
      const drift = await changedShare(scratch, references.driver, again)
      record('reset puts the driver look direction back', drift < MAX_NOISE, percent(drift, 3))
      const resetForward = await viewerForward(page)
      record(
        'reset points the driver camera toward -Z',
        near(resetForward, [0, 0, -1], 1e-6),
        JSON.stringify(resetForward),
      )
    }

    // /viewer without the slash must land on /viewer/ with the query, or the page's relative
    // ./viewer.js resolves to /viewer.js and the page never starts.
    const slashless = await fetch(`${server.url}/viewer?${query}`, { redirect: 'manual' })
    record(
      '/viewer redirects to /viewer/ and keeps the query',
      slashless.status === 302 && slashless.headers.get('location') === `/viewer/?${query}`,
      `${slashless.status} ${slashless.headers.get('location')}`,
    )
    let slashlessResult: string
    try {
      await openViewer(page, `${server.url}/viewer?${query}`, 10_000)
      const status = (await page.locator('#status').textContent()) ?? ''
      slashlessResult =
        !status.startsWith('loading') && status.includes('renderer:')
          ? 'loaded'
          : `status is "${status.split('\n')[0]}"`
    } catch (error) {
      slashlessResult = `did not start: ${error instanceof Error ? error.message.split('\n')[0] : error}`
    }
    record(
      '/viewer without the slash loads the viewer',
      slashlessResult === 'loaded' && page.url() === `${server.url}/viewer/?${query}`,
      `${slashlessResult}; ended at ${page.url()}`,
    )

    // ?eye= replaces the data's eye point, and the page prints the value it uses. state().eye is
    // the driver camera's own world position, and z is not 0, so a flipped sign shows.
    const override = [-0.37, 1.1, 0.25]
    query.set('eye', override.join(','))
    await openViewer(page, `${server.url}/viewer/?${query}`)
    const overridden = await viewerState(page)
    const printed = (await page.locator('#readout').textContent()) ?? ''
    record(
      '?eye= moves the driver camera to exactly that point and the page prints it',
      JSON.stringify(overridden.eye) === JSON.stringify(override) &&
        printed.includes('-0.370, 1.100, 0.250') &&
        printed.includes('?eye= override'),
      `${JSON.stringify(overridden.eye)}; ${printed.split('\n')[0]}`,
    )
    if (references.driver) {
      // The picture must follow the camera: 0.25 m further back changes the driver's view.
      await page.locator('#camera-driver').check()
      const moved = await shoot(page, join(shots, 'driver-eye-override.png'))
      const share = await changedShare(scratch, references.driver, moved)
      record(
        '?eye= changes the driver shot',
        share >= MIN_CHANGED,
        `${percent(share)} of pixels moved (needs ${percent(MIN_CHANGED, 1)})`,
      )
    }

    record('no page errors', pageErrors.length === 0, pageErrors.join(' | ') || 'none')
    const failed = results.filter((r) => !r.ok)
    await writeFile(
      join(shots, 'result.json'),
      `${JSON.stringify({ backend: defaults.backend, assets, ok: failed.length === 0, results }, null, 2)}\n`,
    )
    console.log(
      `\nbackend ${defaults.backend}; ${results.length - failed.length}/${results.length} checks passed; shots in ${shots}`,
    )
    return failed.length === 0 ? 0 : 1
  } finally {
    await browser?.close()
    await server.close()
  }
}

main().then(
  (code) => process.exit(code),
  (error: unknown) => {
    console.error(error instanceof Error ? error.message : error)
    process.exit(2)
  },
)
