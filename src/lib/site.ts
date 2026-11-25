export const SITE_NAME = 'm3-tool'

// The document title: the page name first, then the site name. A missing or blank title gives the
// site name alone.
export function pageTitle(title?: string | undefined): string {
  const name = title?.trim()
  return name ? `${name} · ${SITE_NAME}` : SITE_NAME
}
