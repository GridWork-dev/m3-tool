export const isUnverified = (listed: readonly string[] | undefined, path: string): boolean =>
  listed?.some((p) => path === p || path.startsWith(`${p}.`)) ?? false
