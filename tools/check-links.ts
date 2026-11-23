import { readdir, readFile } from 'node:fs/promises'
import { join, relative } from 'node:path'
import { findHrefs, isAllowedHref } from '../src/lib/link-policy.ts'

export type LinkViolation = { file: string; href: string }

export async function checkLinks(distDir: string): Promise<LinkViolation[]> {
  const entries = await readdir(distDir, { recursive: true, withFileTypes: true })
  const files = entries
    .filter((entry) => entry.isFile() && entry.name.endsWith('.html'))
    .map((entry) => join(entry.parentPath, entry.name))
    .sort()
  const violations: LinkViolation[] = []
  for (const path of files) {
    const html = await readFile(path, 'utf8')
    for (const href of findHrefs(html)) {
      if (!isAllowedHref(href)) violations.push({ file: relative(distDir, path), href })
    }
  }
  return violations
}

if (import.meta.main) {
  const distDir = process.argv[2]
  if (!distDir) {
    console.error('usage: node tools/check-links.ts <distDir>')
    process.exit(2)
  }
  const violations = await checkLinks(distDir)
  for (const { file, href } of violations) console.log(`${file}: ${href}`)
  process.exitCode = violations.length > 0 ? 1 : 0
}
