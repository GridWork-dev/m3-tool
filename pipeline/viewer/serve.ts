// The throwaway viewer's local server (Phase 0.6 spike). Not part of the site.
//
//   node pipeline/viewer/serve.ts [--work-dir <dir>] [--port 4350]
//
// It binds 127.0.0.1 only and answers GET only. Three routes:
//   /viewer/*            files from pipeline/viewer/
//   /work/*              files from the work dir (the GLBs the pipeline wrote)
//   /api/eye?gen=<id>    the generation's driver's-eye point as { x, y, z } in meters
// A path that leaves its root, by `..`, an encoded `..`, a backslash or a symlink, is refused.
import { existsSync, realpathSync } from 'node:fs'
import { readFile, realpath, stat } from 'node:fs/promises'
import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http'
import type { AddressInfo } from 'node:net'
import { homedir } from 'node:os'
import { basename, dirname, extname, isAbsolute, join, relative, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import { parseArgs } from 'node:util'
import { parse as parseYaml } from 'yaml'

const VIEWER_DIR = fileURLToPath(new URL('.', import.meta.url))
export const REPO_ROOT = resolve(VIEWER_DIR, '..', '..')
const DEFAULT_WORK_DIR = '~/.cache/m3-tool'
const DEFAULT_PORT = 4350
const ID = /^[a-z0-9]+(-[a-z0-9]+)*$/

// Only these types are served. A `.ts` file next to the page is never sent.
const TYPES: Record<string, string> = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.glb': 'model/gltf-binary',
  '.gltf': 'model/gltf+json',
  '.bin': 'application/octet-stream',
  '.png': 'image/png',
  '.webp': 'image/webp',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.ktx2': 'image/ktx2',
}

class HttpError extends Error {
  readonly status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

// The real path of `path`, or, when it doesn't exist yet, of its nearest existing parent with the
// missing part put back. A work dir that isn't created yet must still be checked for a symlinked
// parent that leads into the repo.
function realpathLoose(path: string): string {
  let existing = path
  const missing: string[] = []
  while (!existsSync(existing)) {
    const parent = dirname(existing)
    if (parent === existing) break
    missing.unshift(basename(existing))
    existing = parent
  }
  return join(realpathSync(existing), ...missing)
}

// The work dir the pipeline uses: `--work-dir`, else env M3_WORK_DIR, else ~/.cache/m3-tool. It
// is made absolute and, like the pipeline, refused when it sits inside the repo, because renders
// and generator output never go there.
export function resolveWorkDir(flag: string | undefined): string {
  const raw = flag || process.env.M3_WORK_DIR || DEFAULT_WORK_DIR
  const expanded = raw === '~' || raw.startsWith('~/') ? join(homedir(), raw.slice(1)) : raw
  const dir = resolve(expanded)
  // Compare real locations, so a symlink or a relative path can't slip into the repo.
  const real = realpathLoose(dir)
  const inside = relative(realpathSync(REPO_ROOT), real)
  if (inside === '' || (!inside.startsWith('..') && !isAbsolute(inside))) {
    throw new Error(`work dir ${dir} is inside the repo (${REPO_ROOT}); pick a path outside it`)
  }
  return dir
}

// Turns the URL part after a route prefix into a file under `root`, or throws a 400/403/404.
async function fileUnder(root: string, urlPath: string): Promise<string> {
  let decoded: string
  try {
    decoded = decodeURIComponent(urlPath)
  } catch {
    throw new HttpError(400, 'bad percent-encoding')
  }
  if (decoded.includes('\0') || decoded.includes('\\')) throw new HttpError(400, 'bad path')
  const parts = decoded.split('/').filter((part) => part !== '')
  if (parts.some((part) => part === '..' || part === '.')) throw new HttpError(403, 'path refused')
  const candidate = join(root, ...parts)
  let real: string
  try {
    real = await realpath(candidate)
  } catch {
    throw new HttpError(404, 'not found')
  }
  const realRoot = await realpath(root)
  if (real !== realRoot && !real.startsWith(realRoot + sep)) {
    throw new HttpError(403, 'path refused')
  }
  const info = await stat(real)
  if (!info.isFile()) throw new HttpError(404, 'not found')
  return real
}

async function sendFile(res: ServerResponse, file: string): Promise<void> {
  const type = TYPES[extname(file).toLowerCase()]
  if (type === undefined) throw new HttpError(404, 'not found')
  const body = await readFile(file)
  res.writeHead(200, {
    'Content-Type': type,
    'Content-Length': body.length,
    'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff',
  })
  res.end(body)
}

function sendJson(res: ServerResponse, status: number, value: unknown): void {
  const body = Buffer.from(JSON.stringify(value))
  res.writeHead(status, {
    'Content-Type': TYPES['.json'] ?? 'application/json',
    'Content-Length': body.length,
    'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff',
  })
  res.end(body)
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

// `driverEyePoint` of data/generations/<gen>.yaml, millimeters in, meters out. The data owns the
// value, so this reads the file on every request instead of caching it.
export async function readEyePoint(
  repoRoot: string,
  gen: string,
): Promise<{ x: number; y: number; z: number }> {
  if (!ID.test(gen)) throw new HttpError(400, 'gen must be a kebab-case id')
  const file = join(repoRoot, 'data', 'generations', `${gen}.yaml`)
  let text: string
  try {
    text = await readFile(file, 'utf8')
  } catch {
    throw new HttpError(404, `no generation ${gen}`)
  }
  const data: unknown = parseYaml(text)
  const eye = isRecord(data) ? data.driverEyePoint : undefined
  if (!isRecord(eye)) throw new HttpError(500, `${gen}.yaml has no driverEyePoint`)
  const mm = (key: 'xMm' | 'yMm' | 'zMm'): number => {
    const value = eye[key]
    if (typeof value !== 'number' || !Number.isFinite(value)) {
      throw new HttpError(500, `${gen}.yaml driverEyePoint.${key} is not a number`)
    }
    return value
  }
  return { x: mm('xMm') / 1000, y: mm('yMm') / 1000, z: mm('zMm') / 1000 }
}

export interface RunningServer {
  server: Server
  port: number
  url: string
  close: () => Promise<void>
}

export interface ServerOptions {
  workDir: string
  // 0 picks a free port.
  port: number
  repoRoot?: string
}

export function startServer(options: ServerOptions): Promise<RunningServer> {
  const repoRoot = options.repoRoot ?? REPO_ROOT
  const workDir = resolve(options.workDir)
  let port = options.port

  async function route(req: IncomingMessage, res: ServerResponse): Promise<void> {
    if (req.method !== 'GET') {
      res.setHeader('Allow', 'GET')
      throw new HttpError(405, 'GET only')
    }
    // A Host that isn't this server blocks DNS rebinding from a page on another origin.
    const host = req.headers.host ?? ''
    if (host !== `127.0.0.1:${port}` && host !== `localhost:${port}`) {
      throw new HttpError(403, 'bad Host header')
    }
    const target = req.url ?? ''
    // Prefixing the origin keeps `//evil/x` a path instead of a network-path reference.
    if (!target.startsWith('/')) throw new HttpError(400, 'bad request target')
    const url = new URL(`http://127.0.0.1${target}`)
    const path = url.pathname

    if (path === '/') {
      res.writeHead(302, { Location: '/viewer/' })
      res.end()
      return
    }
    // The page loads ./viewer.js, which only resolves under /viewer/. Without the slash it would
    // ask for /viewer.js and get a 404, so send the browser on, keeping ?car=... and the rest.
    if (path === '/viewer') {
      res.writeHead(302, { Location: `/viewer/${url.search}` })
      res.end()
      return
    }
    if (path === '/viewer/') {
      return sendFile(res, await fileUnder(VIEWER_DIR, 'index.html'))
    }
    if (path.startsWith('/viewer/')) {
      return sendFile(res, await fileUnder(VIEWER_DIR, path.slice('/viewer/'.length)))
    }
    if (path.startsWith('/work/')) {
      return sendFile(res, await fileUnder(workDir, path.slice('/work/'.length)))
    }
    if (path === '/api/eye') {
      const gen = url.searchParams.get('gen') ?? ''
      return sendJson(res, 200, await readEyePoint(repoRoot, gen))
    }
    throw new HttpError(404, 'not found')
  }

  const server = createServer((req, res) => {
    route(req, res).catch((error: unknown) => {
      const status = error instanceof HttpError ? error.status : 500
      const message = error instanceof Error ? error.message : String(error)
      if (!(error instanceof HttpError)) console.error(error)
      if (res.headersSent) {
        res.destroy()
        return
      }
      sendJson(res, status, { error: message })
    })
  })

  return new Promise((resolveStart, rejectStart) => {
    server.once('error', rejectStart)
    server.listen(options.port, '127.0.0.1', () => {
      port = (server.address() as AddressInfo).port
      resolveStart({
        server,
        port,
        url: `http://127.0.0.1:${port}`,
        close: () =>
          new Promise<void>((done, fail) => {
            server.close((error) => (error ? fail(error) : done()))
            server.closeAllConnections()
          }),
      })
    })
  })
}

async function main(): Promise<void> {
  const { values } = parseArgs({
    options: { 'work-dir': { type: 'string' }, port: { type: 'string' } },
    strict: true,
  })
  const port = values.port === undefined ? DEFAULT_PORT : Number(values.port)
  if (!Number.isInteger(port) || port < 0 || port > 65535) {
    throw new Error(`--port must be 0 to 65535, got ${values.port}`)
  }
  const workDir = resolveWorkDir(values['work-dir'])
  const running = await startServer({ workDir, port })
  console.log(`viewer  ${running.url}/viewer/?car=<path under the work dir>`)
  console.log(`work    ${workDir}`)
}

if (import.meta.main) {
  main().catch((error: unknown) => {
    console.error(error instanceof Error ? error.message : error)
    process.exit(1)
  })
}
