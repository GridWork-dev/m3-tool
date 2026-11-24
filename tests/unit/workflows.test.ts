// Static checks on the CI and deploy workflows and on Renovate's config (ADR 0011). A workflow
// change can't be fully run before it merges, so these pin the properties that matter: the build
// job never sees a secret, only the two wrangler steps do, every action is pinned to a commit, and
// the wrangler version in the workflow is the one in package.json.
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, test } from 'vitest'
import { parse } from 'yaml'

const root = fileURLToPath(new URL('../../', import.meta.url))
const read = (path: string): string => readFileSync(`${root}${path}`, 'utf8')

interface Step {
  name?: string
  uses?: string
  run?: string
  if?: string
  env?: Record<string, string>
  with?: Record<string, unknown>
}
interface Job {
  needs?: string | string[]
  if?: string
  permissions?: Record<string, string>
  env?: Record<string, string>
  steps: Step[]
}
interface Workflow {
  permissions?: Record<string, string>
  env?: Record<string, string>
  jobs: Record<string, Job>
}

const workflow = (file: string): Workflow => parse(read(`.github/workflows/${file}`)) as Workflow
const FILES = ['ci.yml', 'deploy.yml']
const deploy = workflow('deploy.yml')
const build = deploy.jobs.build as Job
const ship = deploy.jobs.deploy as Job
const stepsOf = (job: Job | undefined): Step[] => job?.steps ?? []
const text = (value: unknown): string => JSON.stringify(value ?? null)
const wranglerVersion = (): string => {
  const pkg = JSON.parse(read('package.json')) as { devDependencies: Record<string, string> }
  return pkg.devDependencies.wrangler ?? ''
}

describe('every action is pinned to a commit', () => {
  test.each(FILES)('%s: each `uses:` is a full SHA followed by a # vX.Y.Z comment', (file) => {
    const uses = read(`.github/workflows/${file}`)
      .split('\n')
      .filter((line) => /^\s*(-\s+)?uses:/.test(line))
    expect(uses.length).toBeGreaterThan(0)
    for (const line of uses) {
      expect(line, line).toMatch(/uses:\s+[\w./-]+@[0-9a-f]{40}\s+#\s+v\d+\.\d+\.\d+\s*$/)
    }
  })

  test.each(FILES)('%s: every checkout sets persist-credentials: false', (file) => {
    const checkouts = Object.values(workflow(file).jobs)
      .flatMap(stepsOf)
      .filter((step) => step.uses?.startsWith('actions/checkout@'))
    expect(checkouts.length).toBeGreaterThan(0)
    for (const step of checkouts) expect(step.with?.['persist-credentials'], text(step)).toBe(false)
  })

  test('the two workflows use the same commit for the same action', () => {
    const pins = new Map<string, Set<string>>()
    for (const file of FILES) {
      for (const [, action, sha] of read(`.github/workflows/${file}`).matchAll(
        /uses:\s+([\w./-]+)@([0-9a-f]{40})/g,
      )) {
        pins.set(action as string, (pins.get(action as string) ?? new Set()).add(sha as string))
      }
    }
    for (const [action, shas] of pins) expect(shas.size, action).toBe(1)
  })
})

describe('deploy.yml is a build job without secrets and a deploy job that runs no project code', () => {
  test('there are two jobs, and deploy needs build', () => {
    expect(Object.keys(deploy.jobs)).toEqual(['build', 'deploy'])
    expect([ship.needs].flat()).toEqual(['build'])
  })

  test('the build job is read-only and holds no secret, at any level', () => {
    expect(build.permissions).toEqual({ contents: 'read' })
    expect(deploy.permissions).toEqual({ contents: 'read' })
    expect(text(build)).not.toMatch(/secrets\.|CLOUDFLARE_|M3_CF_/)
    expect(text(deploy.env)).not.toMatch(/secrets\.|CLOUDFLARE_|M3_CF_/)
    expect(build.env).toBeUndefined()
  })

  test('the build job runs checkout, mise, install, check:data, build, check:links, upload, in that order', () => {
    const steps = stepsOf(build)
    const at = (predicate: (step: Step) => boolean) => steps.findIndex(predicate)
    const order = [
      at((s) => s.uses?.startsWith('actions/checkout@') === true),
      at((s) => s.uses?.startsWith('jdx/mise-action@') === true),
      at((s) => s.run === 'pnpm install --frozen-lockfile'),
      at((s) => s.run === 'pnpm check:data'),
      at((s) => s.run === 'pnpm build'),
      at((s) => s.run === 'pnpm check:links'),
      at((s) => s.uses?.startsWith('actions/upload-artifact@') === true),
    ]
    expect(
      order.every((index) => index >= 0),
      `missing a step: ${order}`,
    ).toBe(true)
    expect([...order].sort((a, b) => a - b)).toEqual(order)
  })

  test('the build job uploads dist and wrangler.jsonc, and fails if either is missing', () => {
    const upload = stepsOf(build).find((s) => s.uses?.startsWith('actions/upload-artifact@'))
    const paths = String(upload?.with?.path ?? '')
      .split('\n')
      .map((p) => p.trim())
      .filter(Boolean)
    expect(paths).toEqual(['dist/', 'wrangler.jsonc'])
    expect(upload?.with?.['if-no-files-found']).toBe('error')
    expect(upload?.with?.['include-hidden-files']).toBe(true)
  })

  test('the deploy job does not check out the repo or run project code', () => {
    const steps = stepsOf(ship)
    expect(steps.some((s) => s.uses?.startsWith('actions/checkout@'))).toBe(false)
    expect(steps.some((s) => s.uses?.startsWith('jdx/mise-action@'))).toBe(false)
    expect(steps.some((s) => /\bpnpm\b/.test(s.run ?? ''))).toBe(false)
  })

  test('the deploy job downloads the artifact the build job uploaded, before anything else', () => {
    const upload = stepsOf(build).find((s) => s.uses?.startsWith('actions/upload-artifact@'))
    const [first] = stepsOf(ship)
    expect(first?.uses).toMatch(/^actions\/download-artifact@/)
    expect(first?.with?.name).toBe(upload?.with?.name)
  })

  test("Node comes from setup-node, at the repo's pinned version, which is Node 26", () => {
    const miseNode = /^node\s*=\s*"([^"]+)"/m.exec(read('mise.toml'))?.[1]
    const setup = stepsOf(ship).find((s) => s.uses?.startsWith('actions/setup-node@'))
    expect(miseNode).toMatch(/^26\./)
    expect(String(setup?.with?.['node-version'])).toBe(miseNode)
  })

  test("wrangler runs through npx at the version in package.json, not through the repo's install", () => {
    const wrangler = stepsOf(ship).filter((s) => /\bwrangler\b/.test(s.run ?? ''))
    expect(wrangler.length).toBeGreaterThanOrEqual(2) // production deploy, preview upload
    for (const step of wrangler) {
      expect(step.run, text(step)).toContain(`npx --yes wrangler@${wranglerVersion()} `)
    }
    expect(wranglerVersion()).toMatch(/^\d+\.\d+\.\d+$/) // pinned exactly
  })

  test('the Cloudflare secrets are on the wrangler steps only', () => {
    expect(ship.env).toBeUndefined()
    const withSecrets = stepsOf(ship).filter((s) => /secrets\.M3_CF_/.test(text(s.env)))
    expect(withSecrets.length).toBe(2)
    for (const step of withSecrets) expect(step.run, text(step)).toMatch(/\bwrangler@/)
    for (const step of stepsOf(ship).filter((s) => !withSecrets.includes(s))) {
      expect(text(step.env), text(step)).not.toMatch(/CLOUDFLARE_|M3_CF_/)
    }
  })

  test('the only secrets the workflow names are the two Cloudflare ones and the GitHub token', () => {
    const names = [...read('.github/workflows/deploy.yml').matchAll(/secrets\.(\w+)/g)].map(
      (m) => m[1],
    )
    expect(new Set(names)).toEqual(
      new Set(['M3_CF_DEPLOY_TOKEN', 'M3_CF_ACCOUNT_ID', 'GITHUB_TOKEN']),
    )
  })

  test('the deploy job needs write access to PRs for the preview comment, and nothing else extra', () => {
    expect(ship.permissions).toEqual({ contents: 'read', 'pull-requests': 'write' })
  })

  test('the preview comment keeps its marker and updates one comment', () => {
    const comment = stepsOf(ship).find((s) => (s.run ?? '').includes('<!-- m3-tool-preview -->'))
    expect(comment?.if).toBe("github.event_name == 'pull_request'")
    expect(comment?.run).toContain('--method PATCH')
    expect(comment?.run).toContain('--method POST')
  })

  test('production deploys on a push to main, and the preview upload is for pull requests', () => {
    const production = stepsOf(ship).find((s) => /wrangler@\S+ deploy\b/.test(s.run ?? ''))
    const preview = stepsOf(ship).find((s) => /versions upload/.test(s.run ?? ''))
    expect(production?.if).toBe("github.event_name == 'push'")
    expect(preview?.if).toBe("github.event_name == 'pull_request'")
    expect(preview?.run).toContain('--preview-alias')
  })
})

describe('who gets a deploy', () => {
  const condition = (job: Job): string => job.if ?? ''

  test('forks never deploy: they get no secrets', () => {
    expect(condition(ship)).toContain(
      'github.event.pull_request.head.repo.full_name == github.repository',
    )
  })

  test('a bot actor, or a bot-authored PR, gets no deploy, but a push to main always does', () => {
    expect(condition(ship)).toContain("endsWith(github.actor, '[bot]')")
    expect(condition(ship)).toContain("endsWith(github.event.pull_request.user.login, '[bot]')")
    expect(condition(ship).startsWith("github.event_name == 'push' ||")).toBe(true)
  })

  test('the build job has the same condition, so a skipped deploy does not leave a useless build', () => {
    expect(condition(build)).toBe(condition(ship))
  })
})

describe('a smoke test follows the production deploy', () => {
  const production = stepsOf(ship).findIndex((s) => /wrangler@\S+ deploy\b/.test(s.run ?? ''))
  const smoke = stepsOf(ship).find((s) => /curl/.test(s.run ?? ''))

  test('it runs after the production deploy, on a push only, and with no secret', () => {
    expect(smoke).toBeDefined()
    expect(stepsOf(ship).indexOf(smoke as Step)).toBeGreaterThan(production)
    expect(smoke?.if).toBe("github.event_name == 'push'")
    expect(text(smoke?.env)).not.toMatch(/secrets\.|CLOUDFLARE_/)
  })

  test('it asks the production URL for the notice, and for a 404 on /__nope', () => {
    const run = smoke?.run ?? ''
    expect(run).toContain('https://m3-tool.broken-wood-97a9.workers.dev')
    expect(run).toContain('__nope')
    expect(run).toMatch(/404/)
    expect(run).toContain(noticeCore())
  })

  test('the sentence it looks for is the one the e2e test and the footer carry', () => {
    expect(read('src/components/SiteFooter.astro').replace(/\s+/g, ' ')).toContain(noticeCore())
  })

  test('it retries, so a deploy that is a moment from live is not a failure', () => {
    expect(smoke?.run).toMatch(/for .* in|until|while|retry/i)
  })

  test('it fails the job when the check fails', () => {
    expect(smoke?.run).toMatch(/exit 1/)
  })

  function noticeCore(): string {
    const match = /const NOTICE = '([^']+)'/.exec(read('tests/e2e/smoke.spec.ts'))
    return match?.[1] ?? ''
  }
})

describe('Renovate', () => {
  interface Rule {
    matchUpdateTypes?: string[]
    matchPackageNames?: string[]
    matchManagers?: string[]
    automerge?: boolean
    groupName?: string
  }
  const config = JSON.parse(read('renovate.json')) as {
    extends: string[]
    minimumReleaseAge?: string
    packageRules: Rule[]
    lockFileMaintenance?: { enabled: boolean }
  }
  const index = (predicate: (rule: Rule) => boolean) => config.packageRules.findIndex(predicate)

  test('an update waits three days after its release', () => {
    expect(config.minimumReleaseAge).toBe('3 days')
  })

  test('what was there stays: the presets, minor and patch automerge, lockfile maintenance', () => {
    expect(config.extends).toEqual(['config:recommended', 'schedule:weekly', 'group:allNonMajor'])
    const merge = config.packageRules[index((r) => r.matchUpdateTypes?.includes('minor') === true)]
    expect(merge).toEqual({ matchUpdateTypes: ['minor', 'patch'], automerge: true })
    expect(config.lockFileMaintenance).toEqual({ enabled: true })
  })

  test('wrangler is never automerged, and is not grouped with what is', () => {
    const rule =
      config.packageRules[index((r) => r.matchPackageNames?.includes('wrangler') === true)]
    expect(rule?.automerge).toBe(false)
    expect(rule?.groupName).toBeTruthy()
  })

  test('GitHub Actions updates are never automerged, and are not grouped with what is', () => {
    const rule =
      config.packageRules[index((r) => r.matchManagers?.includes('github-actions') === true)]
    expect(rule?.automerge).toBe(false)
    expect(rule?.groupName).toBeTruthy()
  })

  test('the two no-automerge rules come after the automerge rule, because the last match wins', () => {
    const merge = index((r) => r.matchUpdateTypes?.includes('minor') === true)
    expect(index((r) => r.matchPackageNames?.includes('wrangler') === true)).toBeGreaterThan(merge)
    expect(index((r) => r.matchManagers?.includes('github-actions') === true)).toBeGreaterThan(
      merge,
    )
  })
})
