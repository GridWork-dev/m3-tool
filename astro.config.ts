import react from '@astrojs/react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig, fontProviders } from 'astro/config'

export default defineConfig({
  site: process.env.SITE_URL ?? 'https://m3-tool.broken-wood-97a9.workers.dev',
  trailingSlash: 'always',
  integrations: [react()],
  vite: { plugins: [tailwindcss()] },
  // Self-hosted through Astro's Fonts API: the build fetches the Fontsource files and emits them as
  // /_astro/fonts/*.woff2, so no page makes a cross-origin request for a font. The build needs
  // network for that. If the CDN is down, rerun it; never vendor a copy to work around it.
  fonts: [
    {
      provider: fontProviders.fontsource(),
      name: 'Big Shoulders Display',
      cssVariable: '--font-display',
      weights: ['600 900'],
      styles: ['normal'],
      fallbacks: ['Arial Narrow', 'sans-serif'],
    },
    {
      provider: fontProviders.fontsource(),
      name: 'Geist',
      cssVariable: '--font-sans',
      weights: ['400 700'],
      styles: ['normal'],
      fallbacks: ['system-ui', 'sans-serif'],
    },
  ],
})
