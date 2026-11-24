// Static checks on the workflows and on Renovate's config (ADR 0011). A workflow change can't be
// fully run before it merges, so these pin the properties that matter: the build job never sees a
// secret, the deploy job takes nothing but static files from the build job, only the two wrangler
// steps hold the token, every action is pinned to a commit, and wrangler comes from a lockfile.
import { readdirSync, readFileSync } from 'node:fs'
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
  id?: string
  shell?: string
  'working-directory'?: string
  'timeout-minutes'?: number
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

// Every workflow in the repo, so a new one is held to the same rules without a test edit.
const FILES = readdirSync(`${root}.github/workflows`).filter((file) => /\.ya?ml$/.test(file))
const workflow = (file: string): Workflow => parse(read(`.github/workflows/${file}`)) as Workflow
const deploy = workflow('deploy.yml')
const build = deploy.jobs.build as Job
const ship = deploy.jobs.deploy as Job
const stepsOf = (job: Job | undefined): Step[] => job?.steps ?? []
const text = (value: unknown): string => JSON.stringify(value ?? null)
const named = (job: Job, name: string): Step => {
  const step = stepsOf(job).find((candidate) => candidate.name === name)
  if (!step) throw new Error(`no step named ${name}`)
  return step
}
// An Actions expression, written so it isn't mistaken for a template placeholder.
const expr = (inner: string): string => `\${{ ${inner} }}`
const WRANGLER = './infra/deploy/node_modules/.bin/wrangler'
const SECRET_NAMES = /secrets\.M3_CF_|CLOUDFLARE_|M3_CF_/

describe('the workflow files', () => {
  test('are the two the repo has, so the tests below cover each of them', () => {
    expect(FILES).toEqual(expect.arrayContaining(['ci.yml', 'deploy.yml']))
  })
})

describe('every action is pinned to a commit', () => {
  test.each(FILES)('%s: each `uses:` is a full SHA followed by a # vX.Y.Z comment', (file) => {
    const uses = read(`.github/workflows/${file}`)
      .split('\n')
      .filter((line) => /^\s*(-\s+)?uses:/.test(line))
    for (const line of uses) {
      expect(line, line).toMatch(/uses:\s+[\w./-]+@[0-9a-f]{40}\s+#\s+v\d+\.\d+\.\d+\s*$/)
    }
  })

  test.each(FILES)('%s: every checkout sets persist-credentials: false', (file) => {
    const checkouts = Object.values(workflow(file).jobs)
      .flatMap(stepsOf)
      .filter((step) => step.uses?.startsWith('actions/checkout@'))
    for (const step of checkouts) expect(step.with?.['persist-credentials'], text(step)).toBe(false)
  })

  test.each(FILES)('%s: no local action is used, because it would be project code', (file) => {
    const uses = Object.values(workflow(file).jobs)
      .flatMap(stepsOf)
      .map((step) => step.uses ?? '')
    expect(uses.filter((value) => value.startsWith('.'))).toEqual([])
  })

  test('the workflows use the same commit for the same action', () => {
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

describe('no script interpolates a GitHub expression', () => {
  // `${{ ... }}` inside a `run:` is pasted into the shell before it runs, so a value an attacker
  // controls (a branch name, a PR title) becomes code. Values reach scripts through `env:`.
  test.each(FILES)('%s: no `run:` script contains an expression', (file) => {
    const runs = Object.values(workflow(file).jobs)
      .flatMap(stepsOf)
      .map((step) => step.run ?? '')
    for (const run of runs) expect(run, run).not.toContain('${{')
  })

  test.each(FILES)('%s: nothing runs npx, which resolves packages at run time', (file) => {
    expect(read(`.github/workflows/${file}`)).not.toMatch(/\bnpx\b/)
  })
})

describe('deploy.yml: a build job without secrets, and a deploy job that takes only static files from it', () => {
  test('there are two jobs, and deploy needs build', () => {
    expect(Object.keys(deploy.jobs)).toEqual(['build', 'deploy'])
    expect([ship.needs].flat()).toEqual(['build'])
  })

  test('the build job is read-only and holds no secret, at any level', () => {
    expect(build.permissions).toEqual({ contents: 'read' })
    expect(deploy.permissions).toEqual({ contents: 'read' })
    expect(text(build)).not.toMatch(/\bsecrets\b|CLOUDFLARE_|M3_CF_/)
    expect(text(deploy.env)).not.toMatch(/\bsecrets\b|CLOUDFLARE_|M3_CF_/)
    expect(build.env).toBeUndefined()
  })

  test('the build job runs checkout, mise, install, check:data, build, check:links, the version marker, upload, in that order', () => {
    const steps = stepsOf(build)
    const at = (predicate: (step: Step) => boolean) => steps.findIndex(predicate)
    const order = [
      at((s) => s.uses?.startsWith('actions/checkout@') === true),
      at((s) => s.uses?.startsWith('jdx/mise-action@') === true),
      at((s) => s.run === 'pnpm install --frozen-lockfile'),
      at((s) => s.run === 'pnpm check:data'),
      at((s) => s.run === 'pnpm build'),
      at((s) => s.run === 'pnpm check:links'),
      at((s) => /dist\/version\.txt/.test(s.run ?? '')),
      at((s) => s.uses?.startsWith('actions/upload-artifact@') === true),
    ]
    expect(
      order.every((index) => index >= 0),
      `missing a step: ${order}`,
    ).toBe(true)
    expect([...order].sort((a, b) => a - b)).toEqual(order)
  })

  test('the build job records the commit in dist/version.txt, taking it from env, not from the script', () => {
    const marker = stepsOf(build).find((s) => /dist\/version\.txt/.test(s.run ?? ''))
    expect(marker?.env).toEqual({ GIT_SHA: expr('github.sha') })
    expect(marker?.run).toMatch(/"\$GIT_SHA"\s*>\s*dist\/version\.txt/)
  })

  test('the artifact is dist/ and nothing else: no config crosses from the build job to the deploy job', () => {
    const upload = stepsOf(build).find((s) => s.uses?.startsWith('actions/upload-artifact@'))
    const paths = String(upload?.with?.path ?? '')
      .split('\n')
      .map((p) => p.trim())
      .filter(Boolean)
    expect(paths).toEqual(['dist/'])
    expect(upload?.with?.['if-no-files-found']).toBe('error')
    expect(upload?.with?.['include-hidden-files']).toBe(true)
    expect(upload?.with?.overwrite).toBe(true) // so "re-run all jobs" can upload again
  })

  test('the deploy job has exactly these steps, and no others', () => {
    expect(stepsOf(ship).map((step) => step.name)).toEqual([
      'Check out wrangler.jsonc and the wrangler lockfile only',
      'Download the built site',
      'Set up Node',
      'Check wrangler.jsonc',
      'Install wrangler from its lockfile',
      'Deploy to production',
      'Smoke test production',
      'Upload preview version',
      'Comment preview URL on the PR',
    ])
  })

  test('the deploy job uses only these actions: sparse checkout, artifact download, setup-node', () => {
    const uses = stepsOf(ship)
      .map((step) => step.uses)
      .filter(Boolean)
      .map((value) => String(value).split('@')[0])
    expect(uses).toEqual(['actions/checkout', 'actions/download-artifact', 'actions/setup-node'])
  })

  test('every command the deploy job runs is one of these, and nothing else', () => {
    const allowed: Record<string, RegExp> = {
      'Check wrangler.jsonc': /^node infra\/deploy\/check-config\.ts wrangler\.jsonc$/,
      'Install wrangler from its lockfile': /^npm ci --ignore-scripts --no-audit --no-fund$/,
      'Deploy to production': /^\.\/infra\/deploy\/node_modules\/\.bin\/wrangler deploy /,
      'Smoke test production': /^bash infra\/deploy\/smoke\.sh$/,
      'Upload preview version':
        /^\.\/infra\/deploy\/node_modules\/\.bin\/wrangler versions upload /,
      'Comment preview URL on the PR': /^marker='<!-- m3-tool-preview -->'/,
    }
    for (const step of stepsOf(ship).filter((s) => s.run !== undefined)) {
      const pattern = allowed[step.name ?? '']
      expect(pattern, `unexpected step: ${step.name}`).toBeDefined()
      expect(step.run?.trim(), step.name).toMatch(pattern as RegExp)
    }
  })

  test('the deploy job takes wrangler.jsonc and the wrangler lockfile from git, at the commit that triggered it', () => {
    const [checkout] = stepsOf(ship)
    expect(checkout?.uses).toMatch(/^actions\/checkout@/)
    expect(checkout?.with?.ref).toBe(expr('github.sha'))
    expect(checkout?.with?.['persist-credentials']).toBe(false)
    expect(checkout?.with?.['sparse-checkout-cone-mode']).toBe(false)
    const patterns = String(checkout?.with?.['sparse-checkout'] ?? '')
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
    expect(patterns).toEqual(['/wrangler.jsonc', '/infra/deploy/'])
    expect(stepsOf(ship).filter((s) => s.uses?.startsWith('actions/checkout@'))).toHaveLength(1)
  })

  test('the checkout comes first, because it empties the workspace', () => {
    expect(stepsOf(ship)[0]?.uses).toMatch(/^actions\/checkout@/)
  })

  test('the built site is downloaded into site/, away from the checkout, and nothing else is read from it', () => {
    const upload = stepsOf(build).find((s) => s.uses?.startsWith('actions/upload-artifact@'))
    const download = named(ship, 'Download the built site')
    expect(download.uses).toMatch(/^actions\/download-artifact@/)
    expect(download.with?.name).toBe(upload?.with?.name)
    expect(download.with?.path).toBe('site')
  })

  test("Node comes from setup-node, at the repo's pinned version, which is Node 26", () => {
    const miseNode = /^node\s*=\s*"([^"]+)"/m.exec(read('mise.toml'))?.[1]
    expect(miseNode).toMatch(/^26\./)
    expect(String(named(ship, 'Set up Node').with?.['node-version'])).toBe(miseNode)
  })

  test('wrangler.jsonc is checked, and wrangler installed, before any step that holds the token', () => {
    const steps = stepsOf(ship)
    const firstSecret = steps.findIndex((s) => SECRET_NAMES.test(text(s.env)))
    const check = steps.indexOf(named(ship, 'Check wrangler.jsonc'))
    const install = steps.indexOf(named(ship, 'Install wrangler from its lockfile'))
    expect(firstSecret).toBeGreaterThan(0)
    expect(check).toBeGreaterThan(steps.indexOf(named(ship, 'Download the built site')))
    expect(check).toBeLessThan(firstSecret)
    expect(install).toBeLessThan(firstSecret)
    for (const step of steps.slice(0, firstSecret)) expect(text(step.env)).not.toMatch(SECRET_NAMES)
  })

  test('wrangler is installed from the lockfile with install scripts off, in a step with no secret', () => {
    const install = named(ship, 'Install wrangler from its lockfile')
    expect(install['working-directory']).toBe('infra/deploy')
    expect(install.run).toBe('npm ci --ignore-scripts --no-audit --no-fund')
    expect(install.env).toBeUndefined()
  })

  test('both wrangler steps run the locked binary, with the config and the assets named', () => {
    for (const name of ['Deploy to production', 'Upload preview version']) {
      const step = named(ship, name)
      expect(step.run, name).toContain(WRANGLER)
      expect(step.run, name).toContain('--config wrangler.jsonc')
      expect(step.run, name).toContain('--assets site')
    }
  })

  test('the Cloudflare secrets are on the two wrangler steps only', () => {
    expect(ship.env).toBeUndefined()
    const withSecrets = stepsOf(ship).filter((s) => /secrets\.M3_CF_/.test(text(s.env)))
    expect(withSecrets.map((s) => s.name)).toEqual([
      'Deploy to production',
      'Upload preview version',
    ])
    for (const step of withSecrets) expect(step.run, text(step)).toContain(WRANGLER)
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

  test('the GitHub token is used by the comment step only', () => {
    const withToken = stepsOf(ship).filter((s) => /secrets\.GITHUB_TOKEN/.test(text(s.env)))
    expect(withToken.map((s) => s.name)).toEqual(['Comment preview URL on the PR'])
  })

  test('the deploy job needs write access to PRs for the preview comment, and nothing else extra', () => {
    expect(ship.permissions).toEqual({ contents: 'read', 'pull-requests': 'write' })
  })

  test('the preview comment keeps its marker and updates one comment', () => {
    const comment = named(ship, 'Comment preview URL on the PR')
    expect(comment.run).toContain('<!-- m3-tool-preview -->')
    expect(comment.if).toBe("github.event_name == 'pull_request'")
    expect(comment.run).toContain('--method PATCH')
    expect(comment.run).toContain('--method POST')
  })

  test('production deploys on a push to main, and the preview upload is for pull requests', () => {
    const production = named(ship, 'Deploy to production')
    const preview = named(ship, 'Upload preview version')
    expect(production.if).toBe("github.event_name == 'push'")
    expect(preview.if).toBe("github.event_name == 'pull_request'")
    expect(production.run).toMatch(/wrangler deploy /)
    expect(preview.run).toContain('--preview-alias')
  })
})

describe('who gets a deploy', () => {
  // The condition uses `==`, `&&`, `||`, `!` and `endsWith`, so it can be evaluated here. A missing
  // property is null, as in GitHub's expressions, and endsWith ignores case.
  function evaluate(expression: string, github: Record<string, unknown>): boolean {
    const get = (path: string): unknown =>
      path
        .split('.')
        .reduce<unknown>(
          (value, key) =>
            value !== null && typeof value === 'object'
              ? ((value as Record<string, unknown>)[key] ?? null)
              : null,
          github,
        )
    const endsWith = (value: unknown, suffix: string): boolean =>
      String(value ?? '')
        .toLowerCase()
        .endsWith(suffix.toLowerCase())
    const js = expression.replace(/github\.([\w.]+)/g, "get('$1')").replace(/==/g, '===')
    return Boolean(new Function('get', 'endsWith', `return (${js})`)(get, endsWith))
  }

  const REPO = 'GridWork-dev/m3-tool'
  const pullRequest = (actor: string, author: string, headRepo: string | null = REPO) => ({
    event_name: 'pull_request',
    actor,
    repository: REPO,
    event: {
      pull_request: {
        user: { login: author },
        head: { repo: headRepo && { full_name: headRepo } },
      },
    },
  })
  const push = (actor: string) => ({ event_name: 'push', actor, repository: REPO, event: {} })

  const cases: [string, Record<string, unknown>, boolean][] = [
    ['a push to main by a person', push('octocat'), true],
    ['a push to main by a bot (an automerge)', push('renovate[bot]'), true],
    ['a PR from this repo, by a person', pullRequest('octocat', 'octocat'), true],
    ['a PR from this repo, pushed by a bot', pullRequest('renovate[bot]', 'renovate[bot]'), false],
    [
      'a PR from this repo, opened by a bot, touched by a person',
      pullRequest('octocat', 'renovate[bot]'),
      false,
    ],
    [
      'a PR from this repo, by a person, touched by a bot',
      pullRequest('dependabot[bot]', 'octocat'),
      false,
    ],
    ['a bot with an upper-case suffix', pullRequest('Renovate[BOT]', 'octocat'), false],
    ['a PR from a fork', pullRequest('octocat', 'octocat', 'someone/m3-tool'), false],
    [
      'a PR from a fork with the same repository name',
      pullRequest('octocat', 'octocat', 'someone/other'),
      false,
    ],
    ['a PR from a deleted fork', pullRequest('octocat', 'octocat', null), false],
  ]

  test.each(cases)('the deploy job: %s', (_label, github, expected) => {
    expect(evaluate(ship.if ?? '', github)).toBe(expected)
  })

  test.each(cases)(
    'the build job, which has the same condition: %s',
    (_label, github, expected) => {
      expect(evaluate(build.if ?? '', github)).toBe(expected)
    },
  )

  test('the two conditions are the same text, so a skipped deploy leaves no unused build', () => {
    expect(ship.if).toBe(build.if)
  })

  test('the evaluator itself reads a dropped negation as a different rule', () => {
    const dropped = (ship.if ?? '').replace('!endsWith(github.actor', 'endsWith(github.actor')
    expect(dropped).not.toBe(ship.if)
    expect(evaluate(dropped, pullRequest('renovate[bot]', 'octocat'))).toBe(true) // the bug it would hide
  })
})

describe('a smoke test follows the production deploy', () => {
  const smoke = named(ship, 'Smoke test production')

  test('it runs after the production deploy, on a push only, taking the commit from env', () => {
    const steps = stepsOf(ship)
    expect(steps.indexOf(smoke)).toBeGreaterThan(steps.indexOf(named(ship, 'Deploy to production')))
    expect(smoke.if).toBe("github.event_name == 'push'")
    expect(smoke.env).toEqual({ EXPECTED_SHA: expr('github.sha') })
    expect(smoke.run).toBe('bash infra/deploy/smoke.sh')
  })

  test("the step has a backstop of four minutes, over the script's own 180 second budget", () => {
    expect(smoke['timeout-minutes']).toBe(4)
  })

  test('the build job writes the marker the smoke test polls for', () => {
    expect(read('infra/deploy/smoke.sh')).toContain('/version.txt')
    expect(stepsOf(build).some((s) => /dist\/version\.txt/.test(s.run ?? ''))).toBe(true)
  })
})

describe('wrangler comes from a lockfile that Renovate keeps in step with the root', () => {
  const rootPackage = JSON.parse(read('package.json')) as {
    devDependencies: Record<string, string>
  }
  const deployPackage = JSON.parse(read('infra/deploy/package.json')) as {
    dependencies: Record<string, string>
    devDependencies?: Record<string, string>
    scripts?: Record<string, string>
  }
  const lock = JSON.parse(read('infra/deploy/package-lock.json')) as {
    lockfileVersion: number
    packages: Record<string, { version?: string; integrity?: string; resolved?: string }>
  }

  test('infra/deploy pins wrangler to the exact version the root package.json has', () => {
    expect(rootPackage.devDependencies.wrangler).toMatch(/^\d+\.\d+\.\d+$/)
    expect(deployPackage.dependencies.wrangler).toBe(rootPackage.devDependencies.wrangler)
  })

  test('the lockfile has that version, with an integrity hash on every package', () => {
    expect(lock.packages['node_modules/wrangler']?.version).toBe(
      rootPackage.devDependencies.wrangler,
    )
    const without = Object.entries(lock.packages).filter(
      ([path, entry]) => path !== '' && !entry.integrity,
    )
    expect(without.map(([path]) => path)).toEqual([])
  })

  test('infra/deploy depends on wrangler and nothing else, and defines no script', () => {
    expect(Object.keys(deployPackage.dependencies)).toEqual(['wrangler'])
    expect(deployPackage.devDependencies).toBeUndefined()
    expect(deployPackage.scripts).toBeUndefined()
  })

  test('pnpm does not pick infra/deploy up as a workspace package', () => {
    const workspace = parse(read('pnpm-workspace.yaml')) as { packages?: string[] }
    // With no `packages` list, pnpm treats the repo as one project. If one is added, it must not
    // reach infra/deploy, whose lockfile is npm's.
    const reaches = (workspace.packages ?? []).filter((pattern) =>
      ['infra/deploy', 'infra/*', 'infra/**', '**', '*/*', '*/**'].includes(
        pattern.replace(/\/$/, ''),
      ),
    )
    expect(reaches).toEqual([])
  })

  test('the deploy workflow no longer names a wrangler version: infra/deploy is the one place', () => {
    expect(read('.github/workflows/deploy.yml')).not.toMatch(/wrangler@\d/)
  })
})

describe('Renovate', () => {
  interface Rule {
    matchUpdateTypes?: string[]
    matchPackageNames?: string[]
    matchManagers?: string[]
    matchFileNames?: string[]
    automerge?: boolean
    groupName?: string
  }
  const config = JSON.parse(read('renovate.json')) as {
    extends: string[]
    minimumReleaseAge?: string
    packageRules: Rule[]
    lockFileMaintenance?: { enabled: boolean }
    ignorePaths?: string[]
    enabledManagers?: string[]
  }
  const index = (predicate: (rule: Rule) => boolean) => config.packageRules.findIndex(predicate)
  const rule = (predicate: (rule: Rule) => boolean): Rule | undefined =>
    config.packageRules[index(predicate)]
  const isAutomerge = (r: Rule) => r.matchUpdateTypes?.includes('minor') === true
  const isWrangler = (r: Rule) => r.matchPackageNames?.includes('wrangler') === true
  const isActions = (r: Rule) => r.matchManagers?.includes('github-actions') === true
  const isDeployFolder = (r: Rule) => r.matchFileNames?.includes('infra/deploy/**') === true

  test('an update waits three days after its release', () => {
    expect(config.minimumReleaseAge).toBe('3 days')
  })

  test('what was there stays: the presets, minor and patch automerge, lockfile maintenance', () => {
    expect(config.extends).toEqual(['config:recommended', 'schedule:weekly', 'group:allNonMajor'])
    expect(rule(isAutomerge)).toEqual({ matchUpdateTypes: ['minor', 'patch'], automerge: true })
    expect(config.lockFileMaintenance).toEqual({ enabled: true })
  })

  test('wrangler is never automerged, wherever it is declared, and is not grouped with what is', () => {
    const wrangler = rule(isWrangler)
    expect(wrangler?.automerge).toBe(false)
    expect(wrangler?.groupName).toBeTruthy()
    expect(wrangler?.matchFileNames).toBeUndefined() // so it covers the root and infra/deploy alike
  })

  test('GitHub Actions updates are never automerged, and are not grouped with what is', () => {
    const actions = rule(isActions)
    expect(actions?.automerge).toBe(false)
    expect(actions?.groupName).toBeTruthy()
  })

  test('nothing in infra/deploy is automerged: it holds the wrangler that runs with the token', () => {
    expect(rule(isDeployFolder)?.automerge).toBe(false)
  })

  test('the no-automerge rules come after the automerge rule, because the last match wins', () => {
    const merge = index(isAutomerge)
    expect(index(isWrangler)).toBeGreaterThan(merge)
    expect(index(isActions)).toBeGreaterThan(merge)
    expect(index(isDeployFolder)).toBeGreaterThan(merge)
  })

  test('Renovate is not told to skip infra/deploy or to leave out the npm manager', () => {
    expect((config.ignorePaths ?? []).filter((path) => path.includes('infra'))).toEqual([])
    expect(config.enabledManagers === undefined || config.enabledManagers.includes('npm')).toBe(
      true,
    )
  })
})
