# Infrastructure

Everything m3-tool runs on, with the command that recreates each piece. Secrets are listed by name only; values live in `~/.config/secrets.env` on the maintainer's laptop and in GitHub Actions secrets, never in this repo.

All commands below assume `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` are set for a token that can do the job (see "Tokens"). On the laptop, map them from `M3_CF_API_TOKEN` and `M3_CF_ACCOUNT_ID`.

## Resources

### Worker `m3-tool` (static site)

- **What:** the Astro build in `dist/`, served as Workers static assets. Config is `wrangler.jsonc`. Unknown paths return the built `404.html` with a 404 status.
- **Public:** yes, at `https://m3-tool.broken-wood-97a9.workers.dev`. Pages carry `noindex` until the public beta.
- **Recreate:** `pnpm build && pnpm run deploy`. Use `pnpm run deploy`, not `pnpm deploy`: `deploy` is a pnpm built-in, so the bare form doesn't run the script.
- **Deployed by:** `.github/workflows/deploy.yml` on every push to `main`.
- **Names:** `M3_CF_DEPLOY_TOKEN` and `M3_CF_ACCOUNT_ID` (GitHub Actions secrets).

### PR previews

- **What:** a non-production Worker version per pull request, aliased `pr-<n>`.
- **Public:** yes, at `https://pr-<n>-m3-tool.broken-wood-97a9.workers.dev`. The same workflow posts the URL as a single PR comment that starts with `<!-- m3-tool-preview -->` and updates it on every push.
- **Recreate:** `pnpm build && pnpm wrangler versions upload --preview-alias pr-<n>`.
- **Limits:** the job runs only for PRs from this repo, because forks get no secrets. It is not a required status check. `check`, `e2e` and `gitleaks` stay the merge gate.
- **Names:** the same two Actions secrets as the Worker.

### R2 bucket `m3-tool-models`

- **What:** the published, hashed GLB models. The models are CC BY-SA content.
- **Public:** yes, through the r2.dev URL `https://pub-a5bb7bb30511434e9ee59189ba57d62f.r2.dev`. CORS allows `GET` and `HEAD` from any origin, with a 24-hour preflight cache (`infra/r2-models-cors.json`).
- **Recreate:**
  ```bash
  pnpm wrangler r2 bucket create m3-tool-models
  pnpm wrangler r2 bucket dev-url enable m3-tool-models
  pnpm wrangler r2 bucket cors set m3-tool-models --file infra/r2-models-cors.json
  ```
  A recreated bucket gets a new r2.dev URL. Update the places that reference it.
- **Names:** `M3_R2_ACCOUNT_ID`, `M3_R2_ACCESS_KEY_ID` and `M3_R2_SECRET_ACCESS_KEY` (laptop env), used by the pipeline's S3 uploads.

### R2 bucket `m3-tool-refs`

- **What:** the pipeline's reference photos and their manifest, plus intermediate files. None of it is published, and none of it goes in the repo.
- **Public:** no. The r2.dev URL is disabled, and there is no custom domain.
- **Recreate:** `pnpm wrangler r2 bucket create m3-tool-refs`. Leave the dev URL off. Check it with `pnpm wrangler r2 bucket dev-url get m3-tool-refs`.
- **Names:** the same three `M3_R2_*` laptop variables.

## Tokens and secrets

Every token is minted through the Cloudflare API with the account's key-management token. Nothing is created in the dashboard. Token values are never printed, logged or committed.

| Token | Scope | Where it lives |
| --- | --- | --- |
| `m3-tool-bootstrap` | Workers Scripts Write, R2 Storage Write, Account Settings Read | Laptop only, as `M3_CF_API_TOKEN` with `M3_CF_ACCOUNT_ID`. Expires 2026-12-07. |
| `m3-tool-deploy` | Individual Workers Editor on the `m3-tool` Worker, plus Account Settings Read | GitHub Actions secret `M3_CF_DEPLOY_TOKEN`, used by `deploy.yml`. |
| `m3-tool-r2` | Bucket Item Write on `m3-tool-models` and `m3-tool-refs` only | Laptop only. Its S3 credentials are `M3_R2_ACCOUNT_ID`, `M3_R2_ACCESS_KEY_ID` and `M3_R2_SECRET_ACCESS_KEY`. |

The S3 access key ID is the token's id, and the secret is the SHA-256 hex of the token value. Confirm a working key by listing `m3-tool-refs` over `https://$M3_R2_ACCOUNT_ID.r2.cloudflarestorage.com`.

GitHub Actions secrets:

- `M3_CF_DEPLOY_TOKEN`: the `m3-tool-deploy` token.
- `M3_CF_ACCOUNT_ID`: the GridWork Cloudflare account id.

## Notes

- **Bootstrap token expiry.** `m3-tool-bootstrap` expires on 2026-12-07. Nothing in CI depends on it. After that date, `main` deploys keep running from GitHub Actions, because `m3-tool-deploy` exists only there and the laptop has no copy. If the laptop ever needs to deploy again, mint a new short-lived token through the API.
- **Analytics.** Cloudflare Web Analytics waits for the beta domain (Phase 1). The workers.dev URL isn't a good fit, and the site is `noindex` until then.
- **workers.dev subdomain.** `broken-wood-97a9` belongs to the whole account, so other Workers share it. Don't change it from this repo.
