import react from '@astrojs/react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'astro/config'

export default defineConfig({
  site: process.env.SITE_URL ?? 'https://m3-tool.broken-wood-97a9.workers.dev',
  integrations: [react()],
  vite: { plugins: [tailwindcss()] },
})
