// The id Astro stores a data entry under. Astro's default is derived from the file path, so a part
// at data/parts/e46/fixture-wheel.yaml would be "e46/fixture-wheel", while `requires` and
// `conflicts` name the bare YAML id, "fixture-wheel". Every collection uses this instead.
//
// A file without a usable id falls back to its stem. The schema then reports the missing id, which
// is a better error than one thrown from here.
export function entryId({ entry, data }: { entry: string; data: Record<string, unknown> }): string {
  if (typeof data.id === 'string' && data.id !== '') return data.id
  const name = entry.split('/').pop() ?? entry
  return name.replace(/\.[^.]*$/, '')
}
