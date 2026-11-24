# 0011. Deploy pipeline hardening

- **Status:** Accepted 2026-11-23
- **Date:** 2026-11-23
- **Amends:** the deploy bullets of [0001](0001-static-site-on-workers.md)

## Context

ADR 0001 had one deploy job: check out, install, build, then run `wrangler` with the Cloudflare secrets set on the last steps. Those steps shared a runner, a workspace and a `node_modules` with the install that ran every dependency's code, and `pnpm wrangler` was the repo's own copy. wrangler also takes its orders from `wrangler.jsonc`: `build.command` runs in a shell with the token in its environment, and `main` ships code. Renovate PRs, which carry dependency bumps nobody has read, got the same job and secrets. Actions were pinned by moving tags. The Codex final review ranked this a P1, and a first split that passed `wrangler.jsonc` from the build job to the deploy job was found to leave the same hole.

## Decision

- **Two jobs.** `build` checks out the repo (`persist-credentials: false`), installs with `--frozen-lockfile`, runs `check:data`, builds, runs `check:links`, writes `dist/version.txt` (the commit), and uploads `dist/` and nothing else. It is read-only and has no secrets.
- **`deploy` runs on a fresh runner and takes nothing from the build job but the static site.** It takes `wrangler.jsonc` and `infra/deploy/` from git by sparse checkout at the triggering commit, and downloads the site into `site/`. The deploy job runs no build-job output except the static files it publishes.
- **The config is checked before any secret exists.** `infra/deploy/check-config.ts` (plain Node, no packages) accepts only `name`, `compatibility_date`, `assets` (`directory`, `not_found_handling`, `html_handling`), `workers_dev`, `preview_urls` and `$schema`. `build`, `main`, bindings or anything else fails the job.
- **wrangler comes from a lockfile.** `infra/deploy/package.json` pins the root's wrangler version, `npm ci --ignore-scripts` installs it in a step with no secret, and the two secret steps run that binary with `--config wrangler.jsonc --assets site`. A test keeps the two pins equal.
- **No deploy for forks or bots.** A PR from a fork gets no secrets. A PR whose actor or author ends in `[bot]` gets neither job. A push to `main` always deploys, even one a bot pushed (a Renovate automerge), so production doesn't go stale; the three-day wait and the lockfile are the gate there.
- **A smoke test follows the production deploy.** It polls `/version.txt` for up to about two minutes until it is the commit, then expects a 200 with the not-affiliated notice on `/` and a 404 on `/__nope`.
- **Every action is pinned to a full commit SHA** with a `# vX.Y.Z` comment, every checkout sets `persist-credentials: false`, and the repo setting that requires pinned actions is on.
- **Renovate waits three days after a release.** It never automerges `wrangler`, the github-actions manager or `infra/deploy`, and groups wrangler and Actions separately.

## Alternatives considered

- **One job, secrets scoped to the last steps:** what 0001 did. One runner and one workspace, so the scope hides nothing from code that ran earlier.
- **Passing `wrangler.jsonc` through the artifact:** rejected. The build job could write a `build` command into it.
- **`npx wrangler@<version>` at deploy time:** rejected. Its dependencies float outside any lockfile, and install scripts run with the token present.
- **A separate preview Worker with its own token, and the production token in a `production` environment limited to `main`:** not now. It costs a second Worker, hostname and token. It is the planned follow-up.
- **Tag pins (`@v7`):** rejected. A tag moves. **Workers Builds:** still rejected, for the reasons in 0001.

## Consequences

- **`dist/` is trusted by design.** A compromised build can still ship a malicious static site: any page, `_headers` or `_redirects`, and it can skip `check:data` and `check:links`, which run in the same job. The split protects the token and the Worker's config, not the site's content.
- **Accepted risk: the preview token is the production token,** and a same-repo PR runs its own copy of `deploy.yml` with the secrets before anyone reviews it. That is tolerable for a single-maintainer repo, and it is why forks and bots are skipped. The follow-up above would isolate it.
- `version.txt` shows the deploy took effect. A compromised build could forge it, so it is not an integrity check.
- A failed smoke test turns the run red after the deploy has happened. Fix forward, or redeploy the last good commit.
- A Renovate wrangler PR changes both package files in one group; a bump that misses one fails the workflow test. Wrangler, Actions and `infra/deploy` PRs need a manual merge.
- A pull request runs its own `deploy.yml`, so CI proves the build job, the config check, the locked install and the preview upload and comment. The production deploy, the smoke test, the push-event condition and the bot skip run only from `main` or a bot's PR, so the first deploy after this merges is their proof.
