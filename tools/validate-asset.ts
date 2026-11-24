import { readFile } from 'node:fs/promises'
import { parseArgs } from 'node:util'
import { ASSET_KINDS, type AssetKind } from '../src/lib/asset-contract.ts'
import { validateGlb } from '../src/lib/asset-validate.ts'

const USAGE = `usage: node tools/validate-asset.ts <file.glb> --kind <${ASSET_KINDS.join('|')}> [--json]`

export interface ValidateAssetResult {
  exitCode: 0 | 1 | 2
  stdout: string[]
  stderr: string[]
}

const usageError = (message: string): ValidateAssetResult => ({
  exitCode: 2,
  stdout: [],
  stderr: [message, USAGE],
})

const isKind = (value: string): value is AssetKind =>
  (ASSET_KINDS as readonly string[]).includes(value)

// Checks one GLB against the asset contract. Prints one `<SEVERITY> <code>: <message>` line per
// issue, or `{ ok, issues, stats }` as JSON with --json. `stats` is `{ triangles, bytes }`, with a
// null triangle count when the file could not be read.
export async function runValidateAsset(args: string[]): Promise<ValidateAssetResult> {
  let parsed: ReturnType<
    typeof parseArgs<{
      options: { kind: { type: 'string' }; json: { type: 'boolean' } }
      allowPositionals: true
    }>
  >
  try {
    parsed = parseArgs({
      args,
      allowPositionals: true,
      options: { kind: { type: 'string' }, json: { type: 'boolean' } },
    })
  } catch (error) {
    return usageError(error instanceof Error ? error.message : String(error))
  }
  const { values, positionals } = parsed
  const [file, ...extra] = positionals
  if (!file || extra.length > 0) return usageError('expected exactly one GLB file')
  if (values.kind === undefined) return usageError('--kind is required')
  if (!isKind(values.kind)) {
    return usageError(
      `unknown kind ${JSON.stringify(values.kind)}; known: ${ASSET_KINDS.join(', ')}`,
    )
  }

  let bytes: Uint8Array
  try {
    bytes = await readFile(file)
  } catch (error) {
    const missing = error instanceof Error && 'code' in error && error.code === 'ENOENT'
    return usageError(missing ? `file not found: ${file}` : `cannot read ${file}: ${String(error)}`)
  }

  const { ok, issues, stats } = await validateGlb(bytes, values.kind)
  const stdout = values.json
    ? [JSON.stringify({ ok, issues, stats })]
    : issues.length === 0
      ? ['ok']
      : issues.map((issue) => `${issue.severity.toUpperCase()} ${issue.code}: ${issue.message}`)
  return { exitCode: ok ? 0 : 1, stdout, stderr: [] }
}

// Exit codes: 0 the asset passes, 1 it has an error, 2 bad usage.
if (import.meta.main) {
  const { exitCode, stdout, stderr } = await runValidateAsset(process.argv.slice(2))
  for (const line of stdout) console.log(line)
  for (const line of stderr) console.error(line)
  process.exitCode = exitCode
}
