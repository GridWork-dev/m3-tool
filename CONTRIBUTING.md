# Contributing

m3-tool is a free, independent reference site for BMW M3 owners and shoppers. Contributions are welcome. This page is the short version: [AGENTS.md](AGENTS.md) has the full commands, layout and rules, and agents read it first.

## Set up

Install the tools first, because the pre-push hook needs gitleaks on your PATH and `mise install` provides it.

```sh
mise install                    # node, pnpm, python, uv and gitleaks, at the pinned versions
pnpm install                    # installs the dependencies and the pre-push hook
uv sync --project pipeline      # the Python environment for the asset pipeline
pnpm exec playwright install chromium   # once, for pnpm e2e
```

Then check that your setup works with `pnpm check`.

## Make a change

1. Branch from `main` (`git worktree add ../m3-tool.worktrees/<slug> -b <branch> origin/main` keeps your other work clean). `main` is protected, so every change is a pull request.
2. Run `pnpm check` and `pnpm e2e` (after `pnpm build`) until both are green.
3. Commit with [Conventional Commits](https://www.conventionalcommits.org/) (`feat(data): ...`, `fix(pipeline): ...`, `docs: ...`). Stage files by path.
4. Open a PR from the template. Say `Closes #<issue>`. Attach before-and-after screenshots for UI or 3D changes.
5. CI runs `check`, `e2e` and `gitleaks`, and they must pass. Each PR also gets a preview deploy. A reviewer reads it and a second model gives a second opinion before it merges.

## The rules in short

- **No store links.** No affiliate, ad or sponsored links. A price's `url` is stored, never shown as a link.
- **No BMW marks.** No roundel, M logo or badges in the UI, models or textures.
- **Cite and date every data value.** Use sources you opened, with the tier and the date you read them. A `verified: true` entry needs one Tier 1 source or two independent Tier 2 sources. Forum posts alone verify nothing. See the [data standard](docs/standards/data.md).
- **No reference photos in the repo.** See the [legal standard](docs/standards/legal.md).
- **Contracts change in their own PR.** `src/data/schemas.ts`, `src/lib/asset-contract.ts` and `docs/standards/3d-assets.md` carry the `contract` label.
- **No secrets, ever.** They live in `~/.config/secrets.env` and GitHub Actions secrets, named with the `M3_` prefix. Don't commit a value, an account ID or a `.env` file.
- **Paid API calls need a cap and a ledger row first.** See [docs/spend-ledger.md](docs/spend-ledger.md).
- **Run TypeScript through `pnpm typecheck`.** Never a bare `tsc`.

## Licenses

By contributing you agree that your code is MIT-licensed (`LICENSE`) and your data is CC BY-SA 4.0 (`DATA_LICENSE`).

## Standards

[Code](docs/standards/code.md), [testing](docs/standards/testing.md), [data](docs/standards/data.md), [3D assets](docs/standards/3d-assets.md) and [legal](docs/standards/legal.md). The index is [docs/README.md](docs/README.md).
