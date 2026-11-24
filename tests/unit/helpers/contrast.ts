// WCAG 2.x contrast ratio for two sRGB hex colours (#rgb or #rrggbb), as used by the token tests.
// https://www.w3.org/TR/WCAG21/#dfn-contrast-ratio

const channel = (hex: string, index: number): number => {
  const value = Number.parseInt(hex.slice(index * 2, index * 2 + 2), 16) / 255
  return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
}

const expand = (colour: string): string => {
  const hex = colour.trim().replace(/^#/, '')
  if (/^[0-9a-fA-F]{3}$/.test(hex)) return [...hex].map((c) => c + c).join('')
  if (/^[0-9a-fA-F]{6}$/.test(hex)) return hex
  throw new Error(`contrast: not a #rgb or #rrggbb colour: ${colour}`)
}

const luminance = (colour: string): number => {
  const hex = expand(colour)
  return 0.2126 * channel(hex, 0) + 0.7152 * channel(hex, 1) + 0.0722 * channel(hex, 2)
}

export function contrastRatio(foreground: string, background: string): number {
  const a = luminance(foreground)
  const b = luminance(background)
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)
}
