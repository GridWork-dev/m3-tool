export function valueAt(root: unknown, path: string): unknown {
  let value = root
  for (const key of path.split('.')) {
    if (Array.isArray(value)) {
      if (path.startsWith('years.') && /^(0|1)$/.test(key)) value = value[Number(key)]
      else {
        const matches = value.filter(
          (v) => v && typeof v === 'object' && ('id' in v ? v.id : v.code) === key,
        )
        value = matches.length === 1 ? matches[0] : undefined
      }
    } else if (value && typeof value === 'object' && Object.hasOwn(value, key))
      value = (value as Record<string, unknown>)[key]
    else return undefined
  }
  return value
}
