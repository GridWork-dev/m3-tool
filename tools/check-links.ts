import type { Dirent } from 'node:fs'
import { readdir, readFile } from 'node:fs/promises'
import { join, relative } from 'node:path'
import { findLinks, isLinkAllowed } from '../src/lib/link-policy.ts'

// `source` names the element and attribute (`base href`, `form action`), and is left out for an
// ordinary anchor.
export type LinkViolation = { file: string; href: string; source?: string }

// Returns one violation per disallowed href. Throws, rather than returning [], when there is
// nothing to scan (no such directory, or no .html files in it) so an empty build can't pass.
export async function checkLinks(distDir: string): Promise<LinkViolation[]> {
  let entries: Dirent[]
  try {
    entries = await readdir(distDir, { recursive: true, withFileTypes: true })
  } catch (error) {
    if (
      error instanceof Error &&
      'code' in error &&
      ['ENOENT', 'ENOTDIR'].includes(String(error.code))
    ) {
      throw new Error(`dist directory not found: ${distDir}`)
    }
    throw error
  }
  const files = entries
    .filter((entry) => entry.isFile() && entry.name.endsWith('.html'))
    .map((entry) => join(entry.parentPath, entry.name))
    .sort()
  if (files.length === 0) throw new Error(`no .html files found in ${distDir}, nothing was checked`)
  const violations: LinkViolation[] = []
  for (const path of files) {
    const html = await readFile(path, 'utf8')
    for (const link of findLinks(html)) {
      if (isLinkAllowed(link)) continue
      const file = relative(distDir, path)
      violations.push(
        link.element === 'a'
          ? { file, href: link.value }
          : { file, href: link.value, source: `${link.element} ${link.attribute}` },
      )
    }
  }
  return violations
}

// Exit codes: 0 clean, 1 violations found, 2 the check could not run.
if (import.meta.main) {
  const distDir = process.argv[2]
  if (!distDir) {
    console.error('usage: node tools/check-links.ts <distDir>')
    process.exit(2)
  }
  try {
    const violations = await checkLinks(distDir)
    for (const { file, href, source } of violations) {
      console.log(source === undefined ? `${file}: ${href}` : `${file}: ${href} [${source}]`)
    }
    process.exitCode = violations.length > 0 ? 1 : 0
  } catch (error) {
    console.error(`check-links: ${error instanceof Error ? error.message : String(error)}`)
    process.exit(2)
  }
}
