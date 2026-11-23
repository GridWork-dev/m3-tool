// The schema of `src/assets/manifest.json`: which published GLB each logical asset id points to.
// The publish stage writes it, `pnpm check:data` validates it, and the site reads it.
import { z } from 'astro/zod'
import { DateLike, HttpsUrl, Id, Text } from '../data/schemas.ts'
import { ASSET_KINDS } from './asset-contract.ts'

export const AssetManifestEntry = z.strictObject({
  kind: z.enum(ASSET_KINDS),
  // Content-hashed, so a URL never changes what it serves.
  url: HttpsUrl,
  sha256: z.string().regex(/^[a-f0-9]{64}$/, 'must be 64 lowercase hex characters'),
  bytes: z.int().positive(),
  triangles: z.int().min(0),
  license: Text,
  // Where the references for the model came from: photo pages, product pages, tool names.
  sources: z.array(Text),
  publishedAt: DateLike,
})
export type AssetManifestEntry = z.infer<typeof AssetManifestEntry>

export const AssetManifest = z.strictObject({
  version: z.literal(1),
  assets: z.record(Id, AssetManifestEntry),
})
export type AssetManifest = z.infer<typeof AssetManifest>
